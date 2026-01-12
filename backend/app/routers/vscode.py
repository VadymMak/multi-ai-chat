"""
VS Code Extension API endpoints.
Full Smart Context using EXISTING services:
- build_smart_context() from smart_context.py
- MemoryManager from manager.py
- store_message_with_embedding() from vector_service.py
"""
from typing import Optional, List, Dict, Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Query  # VS Code API Router initialized
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from uuid import uuid4
import json
import re
import difflib

from app.deps import get_current_active_user, get_db
from app.memory.models import User, Role, Project
from app.memory.manager import MemoryManager
from app.providers.factory import ask_model
from app.utils.api_key_resolver import get_openai_key
from app.services.smart_context import build_smart_context
from app.services.vector_service import store_message_with_embedding
from app.services.version_service import VersionService
from app.services.auto_learning import AutoLearningService

router = APIRouter(prefix="/vscode", tags=["vscode"])

# ============================================================
# FILE SIZE LIMITS
# ============================================================
MAX_FILE_SIZE_FOR_FULL_EDIT = 20000  # 20K chars - full file edit
MAX_FILE_SIZE_FOR_CHUNK_EDIT = 50000  # 50K chars - chunk mode
MAX_FILE_SIZE_ABSOLUTE = 100000  # 100K chars - reject

def normalize_code(text: str) -> str:
    """
    Normalize code for better SEARCH/REPLACE matching.
    Removes trailing whitespace and empty lines at start/end.
    """
    if not text:
        return text
    
    # Split into lines
    lines = text.split('\n')
    
    # Remove trailing whitespace from each line
    lines = [line.rstrip() for line in lines]
    
    # Remove empty lines at start
    while lines and not lines[0].strip():
        lines.pop(0)
    
    # Remove empty lines at end
    while lines and not lines[-1].strip():
        lines.pop()
    
    return '\n'.join(lines)


def find_block_position(content: str, search_text: str) -> int:
    """
    Find the starting position of search_text in content.
    Returns -1 if not found.
    Used for sorting blocks by position (bottom-up application).
    """
    # Try exact match first
    pos = content.find(search_text)
    if pos != -1:
        return pos
    
    # Try normalized match
    search_normalized = normalize_code(search_text)
    content_normalized = normalize_code(content)
    
    if search_normalized in content_normalized:
        # Find approximate position by searching for unique line
        search_lines = search_text.strip().split('\n')
        content_lines = content.split('\n')
        
        # Find longest line as anchor
        unique_line = max((sl.strip() for sl in search_lines if sl.strip()), key=len, default='')
        
        if unique_line:
            for idx, cl in enumerate(content_lines):
                if unique_line in cl or cl.strip() == unique_line:
                    # Return character position of this line
                    return sum(len(content_lines[i]) + 1 for i in range(idx))
    
    return -1

def find_fuzzy_match(content: str, search: str, threshold: float = 0.8) -> Optional[Dict[str, Any]]:
    """
    Find similar block using difflib SequenceMatcher.
    Used as last resort when exact and normalized matches fail.
    
    From Aider approach - proven to reduce edit failures.
    
    Args:
        content: Full file content
        search: Search block to find
        threshold: Minimum similarity ratio (0.8 = 80%)
    
    Returns:
        Dict with start, end, ratio, content if found, None otherwise
    """
    from difflib import SequenceMatcher
    
    lines = content.split('\n')
    search_lines = search.strip().split('\n')
    search_len = len(search_lines)
    
    if search_len == 0:
        return None
    
    best_match = None
    best_ratio = 0.0
    
    # Sliding window over content
    for i in range(len(lines) - search_len + 1):
        window = '\n'.join(lines[i:i + search_len])
        
        # Calculate similarity ratio
        ratio = SequenceMatcher(None, search.strip(), window.strip()).ratio()
        
        if ratio > best_ratio and ratio >= threshold:
            best_ratio = ratio
            best_match = {
                'start': i,
                'end': i + search_len,
                'ratio': ratio,
                'content': window
            }
    
    if best_match:
        print(f"🎯 [Fuzzy] Best match: {best_match['ratio']:.2%} at lines {best_match['start']}-{best_match['end']}")
    
    return best_match


# ✅ Context Mode Type
ContextModeType = Literal['selection', 'file', 'project']


# Request/Response Models
class VSCodeChatRequest(BaseModel):
    message: str
    project_id: Optional[int] = None
    role_id: Optional[int] = None
    chat_session_id: Optional[str] = None
    filePath: Optional[str] = None
    fileContent: Optional[str] = None
    selectedText: Optional[str] = None
    mode: Optional[str] = None
    # ✅ NEW: Context mode from frontend
    context_mode: Optional[ContextModeType] = 'file'
    use_smart_context: Optional[bool] = False


class VSCodeChatResponse(BaseModel):
    message: str
    chat_session_id: Optional[str] = None
    response_type: str = "chat"  
    original_content: Optional[str] = None  
    new_content: Optional[str] = None  
    diff: Optional[str] = None  
    file_path: Optional[str] = None  
    tokens_used: Optional[Dict[str, int]] = None  


class EditFileRequest(BaseModel):
    project_id: int
    file_path: str
    instruction: str
    current_content: str
    context_mode: Optional[ContextModeType] = 'file'
    use_smart_context: Optional[bool] = False
    # NEW: Retry support
    last_error: Optional[Dict[str, Any]] = None
    attempt: Optional[int] = 1


class CreateFileRequest(BaseModel):
    project_id: int
    instruction: str
    file_path: Optional[str] = None
    current_content: Optional[str] = None
    # ✅ NEW: Context mode
    context_mode: Optional[ContextModeType] = 'file'
    use_smart_context: Optional[bool] = False


async def classify_user_intent(
    message: str,
    has_file_open: bool,
    user_api_key: str
) -> str:
    """
    Classify user intent using GPT-4o-mini.
    
    Returns: "EDIT", "CREATE", or "CHAT"
    Cost: ~$0.0001 (very cheap!)
    """
    
    prompt = f"""Classify this user message into ONE category:

Message: "{message}"
File is currently open: {has_file_open}

Categories:
- EDIT: User wants to modify/change/fix/refactor/add to existing code in the open file
  Examples: "add error handling", "fix this bug", "refactor to async", "optimize this"
  
- CREATE: User wants to create/build/make a new file/component/class
  Examples: "create a UserService", "make a login component", "build an API client"
  
- CHAT: User wants explanation/discussion/help/information
  Examples: "explain this code", "what does this do", "why use async", "how does this work"

Rules:
- If file is open AND message asks to change it → EDIT
- If message asks to create something new → CREATE  
- Otherwise → CHAT

Respond with ONLY one word: EDIT, CREATE, or CHAT"""

    try:
        classification = ask_model(
            messages=[{"role": "user", "content": prompt}],
            model_key="gpt-4o-mini",
            temperature=0.1,
            max_tokens=10,
            api_key=user_api_key
        )
        
        result = classification.strip().upper()
        
        # Validate result
        if result in ["EDIT", "CREATE", "CHAT"]:
            print(f"🎯 [Intent] '{message[:50]}...' → {result}")
            return result
        else:
            print(f"⚠️ [Intent] Invalid classification '{result}', defaulting to CHAT")
            return "CHAT"
            
    except Exception as e:
        print(f"⚠️ [Intent] Classification failed: {e}, defaulting to CHAT")
        return "CHAT"


async def build_context_for_mode(
    context_mode: ContextModeType,
    use_smart_context: bool,
    project_id: int,
    role_id: int,
    query: str,
    session_id: str,
    db: Session,
    memory: MemoryManager,
    file_content: Optional[str] = None,
    selected_text: Optional[str] = None,
    file_path: Optional[str] = None
) -> str:
    """
    ✅ NEW: Build context based on selected context mode.
    
    - selection: Only selected text
    - file: Full file content (default)
    - project: Use Smart Context (pgvector search)
    """
    
    print(f"🔍 [Context] Building context for mode: {context_mode}")
    
    context_parts = []
    
    # ========== SELECTION MODE ==========
    if context_mode == 'selection':
        if selected_text:
            context_parts.append(f"=== Selected Code ===\n{selected_text}")
            print(f"✂️ [Context] Selection mode: {len(selected_text)} chars")
        else:
            # Fallback to file if no selection
            print(f"⚠️ [Context] No selection, falling back to file mode")
            if file_content:
                context_parts.append(f"=== Current File: {file_path} ===\n{file_content}")
    
    # ========== FILE MODE (Default) ==========
    elif context_mode == 'file':
        if file_content:
            context_parts.append(f"=== Current File: {file_path} ===\n{file_content}")
            print(f"📄 [Context] File mode: {len(file_content)} chars")
        else:
            print(f"⚠️ [Context] No file content available")
    
    # ========== PROJECT MODE (Smart Context) ==========
    elif context_mode == 'project' or use_smart_context:
        print(f"📁 [Context] Project mode: Using Smart Context (pgvector)")
        
        try:
            # Use existing build_smart_context function
            smart_context = await build_smart_context(
                project_id=project_id,
                role_id=role_id,
                query=query,
                session_id=session_id,
                db=db,
                memory=memory
            )
            context_parts.append(smart_context)
            print(f"🧠 [Context] Smart Context built: {len(smart_context)} chars")
            
        except Exception as e:
            print(f"❌ [Context] Smart Context failed: {e}")
            # Fallback to file mode
            if file_content:
                context_parts.append(f"=== Current File: {file_path} ===\n{file_content}")
        
        # Still include current file for reference in project mode
        if file_content and context_mode == 'project':
            # Add current file but mark it clearly
            context_parts.append(f"\n=== ACTIVE FILE: {file_path} ===\n{file_content[:3000]}")
    
    # Combine all context parts
    final_context = "\n\n".join(context_parts) if context_parts else "No context available."
    
    print(f"📋 [Context] Final context: {len(final_context)} chars for mode '{context_mode}'")
    
    return final_context


async def handle_large_file_edit(
    request: EditFileRequest,
    current_user: User,
    db: Session
):
    """
    Handle editing of large files (>20K chars) using chunk-based approach.
    Finds relevant sections using semantic search and only sends those to AI.
    """
    print(f"📦 [LARGE FILE] Handling large file: {len(request.current_content)} chars")
    
    # ... (я дам полный код)


async def edit_file_with_ai(
    request: EditFileRequest, 
    current_user: User, 
    db: Session
):
    """
    Edit file using AI with Smart Context.
    Returns diff between original and new content.
    
    ✅ UPDATED: Includes retry logic with error context
    ✅ UPDATED: File size limits and chunk mode for large files
    """
    try:
        print(f"\n🔧 [EDIT] file={request.file_path}")
        print(f"📝 [EDIT] instruction: {request.instruction[:100]}...")
        print(f"🔍 [EDIT] context_mode: {request.context_mode}")
        print(f"🔄 [EDIT] attempt: {request.attempt or 1}")
        
        # ✅ NEW: File size validation
        file_size = len(request.current_content)
        print(f"📏 [EDIT] file_size: {file_size} chars")
        
        if file_size > MAX_FILE_SIZE_ABSOLUTE:
            print(f"❌ [EDIT] File too large: {file_size} > {MAX_FILE_SIZE_ABSOLUTE}")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": f"File too large ({file_size:,} chars). Maximum is {MAX_FILE_SIZE_ABSOLUTE:,} chars. Please select a specific section to edit.",
                    "error_type": "file_too_large",
                    "file_size": file_size,
                    "max_size": MAX_FILE_SIZE_ABSOLUTE
                }
            )
        
        if file_size > MAX_FILE_SIZE_FOR_FULL_EDIT:
            print(f"📦 [EDIT] Large file ({file_size} chars), using focused edit mode")
            # For now, continue with warning - chunk mode will be added in future
            # TODO: Implement handle_large_file_edit() for smarter chunk-based editing
        
        # Get user's API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Initialize memory
        memory = MemoryManager(db)
        
        # ✅ Get Auto-Learning warnings
        from app.services.auto_learning import AutoLearningService
        auto_learn = AutoLearningService(db)
        learned_warnings = auto_learn.format_warnings_for_prompt(
            project_id=request.project_id,
            file_path=request.file_path
        )
        if learned_warnings:
            print(f"🎓 [EDIT] Added {len(learned_warnings)} chars of learned warnings")
        
        # ✅ Build context based on mode
        context = await build_context_for_mode(
            context_mode=request.context_mode or 'file',
            use_smart_context=request.use_smart_context or False,
            project_id=request.project_id,
            role_id=1,
            query=request.instruction,
            session_id=str(uuid4()),
            db=db,
            memory=memory,
            file_content=request.current_content,
            selected_text=None,
            file_path=request.file_path
        )

        print(f"📋 [EDIT] Context length: {len(context)} chars")

        original_lines = request.current_content.count('\n') + 1
        original_chars = len(request.current_content)
        
        # ✅ NEW: Build retry context if this is a retry attempt
        retry_context = ""
        if request.last_error and request.attempt and request.attempt > 1:
            failed_block = request.last_error.get('failed_search_block', '')
            if failed_block and len(failed_block) > 500:
                failed_block = failed_block[:500] + "..."
            
            retry_context = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ RETRY ATTEMPT {request.attempt} - PREVIOUS ATTEMPT FAILED!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ERROR: {request.last_error.get('error', 'Unknown error')}
HINT: {request.last_error.get('hint', 'Check your SEARCH block matches exactly')}

{"FAILED SEARCH BLOCK (this text was NOT found in file):" if failed_block else ""}
{failed_block}

CRITICAL FOR THIS RETRY:
1. The SEARCH block MUST be copied EXACTLY from the FILE CONTENT section above
2. Check whitespace - every space and tab matters
3. Check line endings - include complete lines only
4. Do NOT add or remove any characters
5. Try using a SMALLER, more unique section of code (3-5 lines)
6. Look for UNIQUE identifiers like function names or variable names

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            print(f"🔄 [EDIT] Retry attempt {request.attempt}, adding error context")
        
        # Build prompt with STRICT formatting rules
        prompt = f"""You are an expert code editor. Your ONLY job is to provide SEARCH/REPLACE instructions.

CURRENT FILE: {request.file_path}
Lines: {original_lines} | Characters: {original_chars}

=== FILE CONTENT ===
{request.current_content}

=== USER INSTRUCTION ===
{request.instruction}

=== PROJECT CONTEXT ===
{context}
{learned_warnings}
{retry_context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL FORMAT RULES - FOLLOW EXACTLY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ❌ DO NOT use markdown (no ```python or ```)
2. ❌ DO NOT add headers like "### SEARCH/REPLACE 1"
3. ❌ DO NOT add explanations before/after
4. ✅ USE ONLY this EXACT format:

SEARCH:
<<<
[exact code from file - copy character-for-character]
>>>

REPLACE:
<<<
[modified code with your changes]
>>>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SEARCH BLOCK RULES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Copy EXACT text from file (character-for-character)
2. Include 3-10 lines of context (not more!)
3. Keep ALL whitespace, indentation, quotes EXACTLY as in file
4. If code has multiple locations - provide ONE block for MAIN location only
5. Test mentally: Can I find this EXACT text in file above? If NO - try again!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLE (CORRECT):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SEARCH:
<<<
    def get_user_by_id(self, user_id):
        if user_id in self.cache:
            return self.cache[user_id]
>>>

REPLACE:
<<<
    def get_user_by_id(self, user_id):
        try:
            if user_id in self.cache:
                return self.cache[user_id]
        except Exception as e:
            raise Exception(f"Failed: {{e}}")
>>>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOW GENERATE YOUR SEARCH/REPLACE BLOCKS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Focus on: {request.instruction}
Provide 1-2 SEARCH/REPLACE blocks maximum.
Response must start with "SEARCH:" immediately.
"""
        
        # Dynamic max_tokens calculation
        estimated_tokens = original_chars // 4
        max_tokens_needed = int(estimated_tokens * 2.0)
        max_tokens_needed = min(max_tokens_needed, 16000)
        max_tokens_needed = max(max_tokens_needed, 6000)

        print(f"🎯 [EDIT] Using max_tokens={max_tokens_needed} for file with {original_chars} chars")

        # Call AI
        ai_response = ask_model(
            messages=[
                {"role": "system", "content": "You are an expert code editor that provides precise SEARCH/REPLACE instructions."},
                {"role": "user", "content": prompt}
            ],
            model_key="gpt-4o",
            temperature=0.2,
            max_tokens=max_tokens_needed,
            api_key=user_api_key
        )

        response_text = ai_response.strip()
        print(f"\n{'='*80}")
        print(f"🤖 [AI RESPONSE] Length: {len(response_text)} chars")
        print(f"🤖 [AI RESPONSE] First 500 chars:")
        print(response_text[:500])
        print(f"{'='*80}\n")

        # ✅ Parse SEARCH/REPLACE blocks
        
        # Step 1: Remove markdown if present
        cleaned_text = response_text
        cleaned_text = re.sub(r'```python\s*', '', cleaned_text)
        cleaned_text = re.sub(r'```typescript\s*', '', cleaned_text)
        cleaned_text = re.sub(r'```\s*', '', cleaned_text)
        
        print(f"🧹 [CLEAN] Removed markdown, length: {len(cleaned_text)}")
        
        # Step 2: Parse SEARCH/REPLACE blocks
        def parse_search_replace_blocks(text: str):
            """Parse SEARCH/REPLACE blocks reliably"""
            blocks = []
            
            # Split by SEARCH:
            parts = re.split(r'SEARCH:\s*', text, flags=re.IGNORECASE)
            
            for part in parts[1:]:
                # Find <<< >>> for search block
                search_match = re.search(r'<<<\n?([\s\S]*?)>>>', part)
                if not search_match:
                    continue
                    
                search_text = search_match.group(1)
                
                # Find REPLACE block after search
                after_search = part[search_match.end():]
                replace_match = re.search(r'REPLACE:\s*<<<\n?([\s\S]*?)>>>', after_search, re.IGNORECASE)
                
                if replace_match:
                    replace_text = replace_match.group(1)
                    blocks.append((search_text, replace_text))
                    print(f"   📦 Block: SEARCH={len(search_text)} chars, REPLACE={len(replace_text)} chars")
            
            return blocks

        matches = parse_search_replace_blocks(cleaned_text)

        if matches:
            print(f"✅ [PARSE] Found {len(matches)} blocks")
                
        # Step 3: Fallback parser (without <<< >>>)
        if not matches:
            print(f"⚠️ [PARSE] Standard format failed, trying fallback...")
            search_replace_pattern = r'SEARCH:\s*\n(.*?)\n\s*REPLACE:\s*\n(.*?)(?=\n\s*SEARCH:|\Z)'
            matches = re.findall(search_replace_pattern, cleaned_text, re.DOTALL)
            
            if matches:
                print(f"✅ [PARSE] Found {len(matches)} blocks with fallback format")

        if not matches:
            # AI didn't follow format
            print(f"⚠️ [EDIT] AI response didn't follow SEARCH/REPLACE format")
            print(f"   Response: {response_text[:200]}...")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "AI response didn't follow SEARCH/REPLACE format. Please try again with a more specific instruction.",
                    "error_type": "format_error",
                    "failed_search_block": None
                }
            )

        # ✅ NEW: Sort blocks by position (bottom-up) to avoid index shifting
        if len(matches) > 1:
            print(f"🔄 [EDIT] Sorting {len(matches)} blocks by position (bottom-up)...")
            
            # Find positions for each block
            blocks_with_positions = []
            for search_block, replace_block in matches:
                search_text = search_block.strip()
                pos = find_block_position(request.current_content, search_text)
                blocks_with_positions.append((pos, search_block, replace_block))
                print(f"   📍 Block at position {pos}: {search_text[:50]}...")
            
            # Sort by position DESCENDING (bottom-up)
            blocks_with_positions.sort(key=lambda x: x[0], reverse=True)
            
            # Rebuild matches in sorted order
            matches = [(search, replace) for pos, search, replace in blocks_with_positions]
            print(f"✅ [EDIT] Blocks sorted: positions = {[p for p, s, r in blocks_with_positions]}")

        # Apply all SEARCH/REPLACE operations
        new_content = request.current_content
        failed_search_block = None

        for i, (search_block, replace_block) in enumerate(matches):
            search_text = search_block.strip()
            replace_text = replace_block.strip()
            
            print(f"🔍 [EDIT] Processing replacement {i+1}/{len(matches)} (bottom-up order)")
            print(f"   Searching for: {len(search_text)} chars")
            print(f"   Preview: {search_text[:80]}...")
            
            # ✅ SPECIAL CASE: Empty search = prepend to file
            if not search_text.strip():
                print(f"✅ [EDIT] Empty SEARCH block = prepend to file")
                new_content = replace_text + "\n" + new_content
                print(f"✅ [EDIT] Prepended {len(replace_text)} chars to file")
                continue

            # ✅ Try normalized matching
            search_normalized = normalize_code(search_text)
            content_normalized = normalize_code(new_content)

            # Try exact match first
            if search_text in new_content:
                print(f"✅ [EDIT] Found exact match")
                new_content = new_content.replace(search_text, replace_text, 1)
                print(f"✅ [EDIT] Applied replacement {i+1}: {len(search_text)} → {len(replace_text)} chars")
                continue
            
            # Try normalized match
            if search_normalized in content_normalized:
                print(f"✅ [EDIT] Found normalized match in normalized content")
                
                # Strategy: Find by unique line from search block
                search_lines = search_text.strip().split('\n')
                content_lines = new_content.split('\n')
                
                # Find the most unique line in search block (longest non-empty line)
                unique_line = None
                for sl in search_lines:
                    sl_stripped = sl.strip()
                    if sl_stripped and (unique_line is None or len(sl_stripped) > len(unique_line)):
                        unique_line = sl_stripped
                
                if unique_line:
                    # Find this unique line in content
                    found_idx = None
                    for idx, cl in enumerate(content_lines):
                        if unique_line in cl or cl.strip() == unique_line:
                            found_idx = idx
                            break
                    
                    if found_idx is not None:
                        # Calculate start index (go back to find beginning of the block)
                        # Find which line in search_lines contains our unique_line
                        unique_line_offset = 0
                        for offset, sl in enumerate(search_lines):
                            if unique_line in sl.strip():
                                unique_line_offset = offset
                                break
                        
                        start_idx = found_idx - unique_line_offset
                        end_idx = start_idx + len(search_lines)
                        
                        # Make sure indices are valid
                        if start_idx >= 0 and end_idx <= len(content_lines):
                            # Replace the section
                            replace_lines = replace_text.strip().split('\n')
                            content_lines[start_idx:end_idx] = replace_lines
                            new_content = '\n'.join(content_lines)
                            print(f"✅ [EDIT] Applied replacement {i+1} (normalized via unique line): {len(search_text)} → {len(replace_text)} chars")
                            continue
                
                # Fallback: try simple normalized string replacement
                print(f"⚠️ [EDIT] Unique line strategy failed, trying string replacement")
                
                # Build a pattern that's more flexible
                search_pattern = search_text.strip()
                content_to_search = new_content
                
                # Try removing trailing semicolons and braces variations
                if search_pattern in content_to_search:
                    new_content = content_to_search.replace(search_pattern, replace_text.strip(), 1)
                    print(f"✅ [EDIT] Applied replacement {i+1} (direct pattern): {len(search_text)} → {len(replace_text)} chars")
                    continue

            # ✅ Strategy 3: Fuzzy match (last resort) - from Aider approach
            print(f"🔍 [EDIT] Trying fuzzy match (80% threshold)...")
            
            fuzzy_match = find_fuzzy_match(new_content, search_text, threshold=0.8)
            
            if fuzzy_match:
                print(f"✅ [EDIT] Fuzzy match found! Ratio: {fuzzy_match['ratio']:.2%}")
                print(f"   Lines {fuzzy_match['start']}-{fuzzy_match['end']}")
                
                # Apply fuzzy match replacement
                content_lines = new_content.split('\n')
                replace_lines = replace_text.strip().split('\n')
                content_lines[fuzzy_match['start']:fuzzy_match['end']] = replace_lines
                new_content = '\n'.join(content_lines)
                
                print(f"✅ [EDIT] Applied replacement {i+1} (fuzzy): {len(search_text)} → {len(replace_text)} chars")
                continue
            
            # ✅ Search failed - prepare for retry
            print(f"⚠️ [EDIT] Search block not found in file:")
            print(f"   Looking for (first 200 chars): {search_text[:200]}...")
            
            failed_search_block = search_text
            
            # Report to Auto-Learning
            try:
                auto_learn.report_error(
                    project_id=request.project_id,
                    error_pattern=f"SEARCH/REPLACE block not found in file",
                    error_type="ai_edit_failed",
                    file_path=request.file_path,
                    code_snippet=search_text[:500]
                )
                print(f"🎓 [EDIT] Reported failed edit to Auto-Learning")
            except Exception as learn_err:
                print(f"⚠️ [EDIT] Failed to report to Auto-Learning: {learn_err}")
            
            # ✅ UPDATED: Return structured error for retry (using JSONResponse to bypass Railway proxy)
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": f"Could not find the code block to replace (block {i+1}). The AI may have made a mistake.",
                    "error_type": "search_not_found",
                    "failed_search_block": search_text[:500],
                    "block_index": i + 1
                }
            )

        # Generate diff
        diff = ''.join(difflib.unified_diff(
            request.current_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{request.file_path}",
            tofile=f"b/{request.file_path}",
            lineterm=''
        ))

        print(f"✅ [EDIT] Generated changes: {len(matches)} replacements, {len(diff)} chars diff")

        # ✅ Create version for this edit
        try:
            file_record = db.execute(
                text("SELECT id FROM file_embeddings WHERE project_id = :pid AND file_path = :path"),
                {"pid": request.project_id, "path": request.file_path}
            ).fetchone()
            
            if file_record:
                version_service = VersionService(db)
                version_service.create_version(
                    file_id=file_record[0],
                    content=new_content,
                    change_type="edit",
                    change_source="ai_edit",
                    change_message=request.instruction[:200],
                    user_id=current_user.id,
                    ai_model="gpt-4o",
                    previous_content=request.current_content
                )
                print(f"📝 [VERSION] Created version for {request.file_path}")
        except Exception as e:
            print(f"⚠️ [VERSION] Failed to create version: {e}")

        # ✅ Return SUCCESS response
        return type('obj', (object,), {
            'success': True,
            'response_type': 'edit',
            'original_content': request.current_content,
            'new_content': new_content,
            'diff': diff,
            'file_path': request.file_path,
            'tokens_used': {'total': len(prompt.split()) + len(response_text.split())},
            'attempt': request.attempt or 1
        })()
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [EDIT] Failed: {e}")
        raise


# ============================================================
# EDIT FILE ENDPOINT (called by extension directly)
# ============================================================
@router.post("/edit-file")
async def edit_file_endpoint(
    request: EditFileRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Direct endpoint for editing files.
    Called by VS Code extension's editFile command.
    """
    print(f"\n🔧 [ENDPOINT] /edit-file called for {request.file_path}")
    
    result = await edit_file_with_ai(request, current_user, db)
    
    # If result is JSONResponse (error), return it directly
    if isinstance(result, JSONResponse):
        return result
    
    # Otherwise return success response
    return {
        "success": True,
        "original_content": result.original_content,
        "new_content": result.new_content,
        "diff": result.diff,
        "file_path": result.file_path,
        "tokens_used": result.tokens_used,
        "attempt": result.attempt
    }


async def create_file_with_ai(
    request: CreateFileRequest, 
    current_user: User, 
    db: Session
):
    """
    Create new file using AI with Smart Context.
    Suggests filename if not provided.
    """
    try:
        print(f"\n📝 [CREATE] instruction: {request.instruction[:100]}...")
        print(f"🔍 [CREATE] context_mode: {request.context_mode}")
        
        # Get user's API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Initialize memory
        memory = MemoryManager(db)
        
        # ✅ Build context based on mode
        # For CREATE, we typically want project context to find patterns
        context = await build_context_for_mode(
            context_mode=request.context_mode or 'project',  # Default to project for CREATE
            use_smart_context=request.use_smart_context or True,  # Default to true for CREATE
            project_id=request.project_id,
            role_id=1,
            query=request.instruction,
            session_id=str(uuid4()),
            db=db,
            memory=memory,
            file_content=request.current_content,
            selected_text=None,
            file_path=request.file_path
        )
        
        print(f"📋 [CREATE] Context length: {len(context)} chars")
        
        # Analyze dependencies
        dependencies_prompt = f"""Analyze what existing files this new file will depend on.

INSTRUCTION:
{request.instruction}

PROJECT CONTEXT:
{context}

List 3-5 most relevant existing files that this new file will import from or depend on.
Return as JSON array: ["path/to/file1.ts", "path/to/file2.ts"]
"""

        try:
            deps_response = ask_model(
                messages=[{"role": "user", "content": dependencies_prompt}],
                model_key="gpt-4o-mini",
                temperature=0.1,
                max_tokens=200,
                api_key=user_api_key
            )
            
            # Parse dependencies
            json_match = re.search(r'\[.*?\]', deps_response, re.DOTALL)
            if json_match:
                dependencies = json.loads(json_match.group(0))
            else:
                dependencies = []
        except:
            dependencies = []
        
        print(f"📦 [CREATE] Dependencies: {dependencies}")
        
        # Build creation prompt
        if request.file_path:
            file_instruction = f"Create file: {request.file_path}"
        else:
            file_instruction = "Create a new file (suggest appropriate filename)"
        
        prompt = f"""You are an expert code generator. {file_instruction}

INSTRUCTION:
{request.instruction}

PROJECT CONTEXT:
{context}

DEPENDENCIES DETECTED:
{json.dumps(dependencies, indent=2) if dependencies else "None"}

RULES:
1. Return ONLY the file content (no markdown, no explanations)
2. Include all necessary imports based on project context
3. Follow project's code style
4. Add appropriate comments
5. Make it production-ready

{"If no filename provided, start with: FILENAME: path/to/file.ext" if not request.file_path else ""}

Generate the file:"""

        max_tokens_needed = 4000  # Standard for new files

        print(f"🎯 [CREATE] Using max_tokens={max_tokens_needed} for new file")

        ai_response = ask_model(
            messages=[
                {"role": "system", "content": "You are an expert code generator."},
                {"role": "user", "content": prompt}
            ],
            model_key="gpt-4o",
            temperature=0.2,
            max_tokens=max_tokens_needed,
            api_key=user_api_key
        )
        
        content = ai_response.strip()
        
        # Extract filename if AI suggested it
        suggested_path = request.file_path
        if not suggested_path and content.startswith("FILENAME:"):
            lines = content.split('\n')
            suggested_path = lines[0].replace("FILENAME:", "").strip()
            content = '\n'.join(lines[1:]).strip()
        
        if not suggested_path:
            suggested_path = "generated_file.txt"
        
        print(f"✅ [CREATE] Generated {suggested_path}, {len(content)} chars")

        # ✅ Create version for new file (will be version 1)
        try:
            # First check if file exists in file_embeddings
            file_record = db.execute(
                text("SELECT id FROM file_embeddings WHERE project_id = :pid AND file_path = :path"),
                {"pid": request.project_id, "path": suggested_path}
            ).fetchone()
            
            if file_record:
                version_service = VersionService(db)
                version_service.create_version(
                    file_id=file_record[0],
                    content=content,
                    change_type="create",
                    change_source="ai_create",
                    change_message=request.instruction[:200],
                    user_id=current_user.id,
                    ai_model="gpt-4o",
                    previous_content=None
                )
                print(f"📝 [VERSION] Created version 1 for {suggested_path}")
        except Exception as e:
            print(f"⚠️ [VERSION] Failed to create version: {e}")

        return type('obj', (object,), {
            'response_type': 'create',
            'file_path': suggested_path,
            'new_content': content,
            'original_content': None,
            'diff': None,
            'dependencies': dependencies,
            'tokens_used': {'total': len(prompt.split()) + len(content.split())}
        })()
        
    except Exception as e:
        print(f"❌ [CREATE] Failed: {e}")
        raise


@router.post("/chat", response_model=VSCodeChatResponse)
async def vscode_chat(
    request: VSCodeChatRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    VS Code Extension chat with FULL Smart Context.
    
    Now uses:
    - build_smart_context() for pgvector search + recent + summaries + files
    - MemoryManager for conversation storage
    - store_message_with_embedding() for future semantic search
    
    ✅ NEW: Supports context_mode parameter:
    - 'selection': Only selected text
    - 'file': Full file content (default)
    - 'project': Use Smart Context (pgvector search)
    """
    
    try:
        # Get user's OpenAI API key
        try:
            user_api_key = get_openai_key(current_user, db, required=True)
        except Exception as e:
            print(f"❌ [VSCode] Failed to get API key: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to get API key: {str(e)}")
        
        # Initialize MemoryManager
        try:
            memory = MemoryManager(db)
        except Exception as e:
            print(f"❌ [VSCode] Failed to initialize MemoryManager: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to initialize memory manager: {str(e)}")
        
        # ========== VALIDATE PROJECT & ROLE ==========
        project_id = request.project_id
        role_id = request.role_id or 1  # Default role
        
        # ✅ Get context mode from request
        context_mode = request.context_mode or 'file'
        use_smart_context = request.use_smart_context or (context_mode == 'project')
        
        print(f"\n🔌 [VSCode] /chat context_mode={context_mode} use_smart_context={use_smart_context}")
        
        if project_id:
            try:
                project = db.get(Project, project_id)
                if not project:
                    print(f"⚠️ [VSCode] Project {project_id} not found")
                    project_id = None
            except Exception as e:
                print(f"❌ [VSCode] Failed to fetch project: {e}")
                project_id = None
        
        # Validate role
        try:
            role = db.get(Role, role_id)
            if not role:
                role_id = 1
        except Exception as e:
            print(f"⚠️ [VSCode] Failed to fetch role: {e}, using default")
            role_id = 1
        
        project_id_str = str(project_id) if project_id else "0"
        
        # ========== GET/CREATE CHAT SESSION ==========
        try:
            if request.chat_session_id:
                chat_session_id = request.chat_session_id.strip()
            elif project_id:
                chat_session_id = memory.get_or_create_chat_session_id(role_id, project_id_str)
            else:
                chat_session_id = str(uuid4())
        except Exception as e:
            print(f"⚠️ [VSCode] Failed to get/create chat session: {e}, creating new")
            chat_session_id = str(uuid4())
        
        print(f"\n🔌 [VSCode] /chat project={project_id} role={role_id} session={chat_session_id[:8]}...")
        print(f"📥 User: {request.message[:100]}...")

        # ========== CLASSIFY USER INTENT ==========
        has_file_open = bool(request.filePath and request.fileContent)
        
        # ✅ Use mode from frontend if provided, otherwise classify
        if request.mode:
            intent = request.mode.upper()
            print(f"🎯 [Intent] Using frontend mode: {intent}")
        else:
            try:
                intent = await classify_user_intent(
                    message=request.message,
                    has_file_open=has_file_open,
                    user_api_key=user_api_key
                )
            except Exception as e:
                print(f"❌ [VSCode] Intent classification failed: {e}, defaulting to CHAT")
                intent = "CHAT"
        
        # ========== ROUTE TO EDIT MODE ==========
        print(f"\n{'='*80}")
        print(f"🔍 [DEBUG] EDIT mode check:")
        print(f"   intent: {intent}")
        print(f"   has_file_open: {has_file_open}")
        print(f"   filePath: {request.filePath}")
        print(f"   fileContent length: {len(request.fileContent) if request.fileContent else 0}")
        print(f"   project_id: {project_id}")
        print(f"   context_mode: {context_mode}")
        print(f"{'='*80}\n")

        if intent == "EDIT" and has_file_open and project_id:
            print(f"🎯 [Intent] EDIT mode activated!")
            
            # Call edit-file endpoint logic
            try:
                edit_request = EditFileRequest(
                    project_id=project_id,
                    file_path=request.filePath,
                    instruction=request.message,
                    current_content=request.fileContent,
                    # ✅ Pass context mode
                    context_mode=context_mode,
                    use_smart_context=use_smart_context
                )
                
                edit_response = await edit_file_with_ai(edit_request, current_user, db)
                
                # ✅ NEW: Check if edit_response is JSONResponse (error case)
                if isinstance(edit_response, JSONResponse):
                    # Return the error response directly
                    return edit_response
                
                # Store in memory for history
                if project_id:
                    try:
                        user_entry = memory.store_chat_message(
                            project_id_str, role_id, chat_session_id,
                            "user", request.message
                        )
                        store_message_with_embedding(db, user_entry.id, request.message)
                    except Exception as e:
                        print(f"⚠️ [Memory] Store failed: {e}")
                    
                    # Store AI response
                    try:
                        ai_msg = f"I've edited the file '{request.filePath}'. Please review the changes."
                        ai_entry = memory.store_chat_message(
                            project_id_str, role_id, chat_session_id,
                            "assistant", ai_msg
                        )
                        store_message_with_embedding(db, ai_entry.id, ai_msg)
                    except Exception as e:
                        print(f"⚠️ [Memory] AI store failed: {e}")

                # CRITICAL: Log the EXACT response before returning
                print(f"\n{'='*80}")
                print(f"🚀 [RESPONSE] BEFORE RETURN:")
                print(f"   response_type: {getattr(edit_response, 'response_type', 'MISSING')}")
                print(f"   original_content: {len(edit_response.original_content) if edit_response.original_content else 'None'}")
                print(f"   new_content: {len(edit_response.new_content) if edit_response.new_content else 'None'}")
                print(f"   diff: {len(edit_response.diff) if edit_response.diff else 'None'}")
                print(f"{'='*80}\n")
                
                # Return edit response
                return VSCodeChatResponse(
                    message=f"I've edited the file. Please review the changes in the diff view.",
                    chat_session_id=chat_session_id,
                    response_type="edit",
                    original_content=edit_response.original_content,
                    new_content=edit_response.new_content,
                    diff=edit_response.diff,
                    file_path=request.filePath,
                    tokens_used=edit_response.tokens_used
                )
                
            except HTTPException as he:
                # ✅ Convert HTTPException to JSONResponse for proper error structure
                print(f"\n{'='*80}")
                print(f"⚠️ [EDIT mode] HTTPException - converting to JSONResponse:")
                print(f"   Status: {he.status_code}")
                print(f"   Detail: {he.detail}")
                print(f"{'='*80}\n")
                
                # Return as JSONResponse to preserve structure through Railway proxy
                detail = he.detail if isinstance(he.detail, dict) else {"message": str(he.detail)}
                return JSONResponse(
                    status_code=he.status_code,
                    content={
                        "success": False,
                        **detail
                    }
                )
            except Exception as e:
                print(f"\n{'='*80}")
                print(f"❌ [EDIT mode] UNEXPECTED EXCEPTION:")
                print(f"   Error type: {type(e).__name__}")
                print(f"   Error message: {str(e)}")
                print(f"{'='*80}\n")
                
                import traceback
                print(f"❌ [EDIT mode] Full traceback:")
                traceback.print_exc()
                print(f"{'='*80}\n")
                
                # Fall through to normal chat mode only for unexpected errors
                intent = "CHAT"
        
        # ========== ROUTE TO CREATE MODE ==========
        elif intent == "CREATE" and project_id:
            print(f"🎯 [Intent] CREATE mode activated!")
            
            # Call create-file endpoint logic
            try:
                create_request = CreateFileRequest(
                    project_id=project_id,
                    instruction=request.message,
                    file_path=None,  # Let AI suggest
                    current_content=None,
                    # ✅ Pass context mode (default to project for CREATE)
                    context_mode='project' if context_mode == 'project' else context_mode,
                    use_smart_context=True  # Always use smart context for CREATE
                )
                
                create_response = await create_file_with_ai(create_request, current_user, db)
                
                # Store in memory
                if project_id:
                    try:
                        user_entry = memory.store_chat_message(
                            project_id_str, role_id, chat_session_id,
                            "user", request.message
                        )
                        store_message_with_embedding(db, user_entry.id, request.message)
                    except Exception as e:
                        print(f"⚠️ [Memory] Store failed: {e}")
                    
                    try:
                        ai_msg = f"I've created the file '{create_response.file_path}'. Please review the content."
                        ai_entry = memory.store_chat_message(
                            project_id_str, role_id, chat_session_id,
                            "assistant", ai_msg
                        )
                        store_message_with_embedding(db, ai_entry.id, ai_msg)
                    except Exception as e:
                        print(f"⚠️ [Memory] AI store failed: {e}")
                
                # Return create response
                return VSCodeChatResponse(
                    message=f"I've created the file. Please review the content.",
                    chat_session_id=chat_session_id,
                    response_type="create",
                    original_content=None,
                    new_content=create_response.new_content,
                    diff=None,
                    file_path=create_response.file_path,
                    tokens_used=create_response.tokens_used
                )
                
            except Exception as e:
                print(f"❌ [CREATE mode] Failed: {e}")
                # Fall through to normal chat mode
                intent = "CHAT"
        
        # ========== NORMAL CHAT MODE ==========
        print(f"💬 [Intent] CHAT mode - providing explanation/help")
        
        # ✅ Build context based on mode
        context = await build_context_for_mode(
            context_mode=context_mode,
            use_smart_context=use_smart_context,
            project_id=project_id,
            role_id=role_id,
            query=request.message,
            session_id=chat_session_id,
            db=db,
            memory=memory,
            file_content=request.fileContent,
            selected_text=request.selectedText,
            file_path=request.filePath
        )
        
        # Call AI
        try:
            ai_response = ask_model(
                messages=[
                    {"role": "system", "content": "You are a helpful coding assistant integrated into VS Code."},
                    {"role": "user", "content": f"{context}\n\nUser question: {request.message}"}
                ],
                model_key="gpt-4o",
                temperature=0.7,
                max_tokens=4000,
                api_key=user_api_key
            )
        except Exception as e:
            print(f"❌ [VSCode] AI call failed: {e}")
            raise HTTPException(status_code=500, detail=f"AI call failed: {str(e)}")
        
        # Store in memory
        if project_id:
            try:
                user_entry = memory.store_chat_message(
                    project_id_str, role_id, chat_session_id,
                    "user", request.message
                )
                store_message_with_embedding(db, user_entry.id, request.message)
            except Exception as e:
                print(f"⚠️ [Memory] User message store failed: {e}")
            
            try:
                ai_entry = memory.store_chat_message(
                    project_id_str, role_id, chat_session_id,
                    "assistant", ai_response
                )
                store_message_with_embedding(db, ai_entry.id, ai_response)
            except Exception as e:
                print(f"⚠️ [Memory] AI message store failed: {e}")
        
        return VSCodeChatResponse(
            message=ai_response,
            chat_session_id=chat_session_id,
            response_type="chat"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [VSCode] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    
    # ============================================================
# COPY CONTEXT FOR AI CHAT
# ============================================================

class CopyContextRequest(BaseModel):
    project_id: int
    file_path: str
    file_content: str
    imports: List[str] = [] 
    max_files: int = 10  
    max_tokens: int = 32000
    include_metadata: bool = True


class CopyContextResponse(BaseModel):
    success: bool
    context_markdown: str
    files_included: int
    estimated_tokens: int
    dependencies: List[Dict[str, Any]] = []

# ============================================================
# ЗАМЕНИ copy_context_for_ai в backend/app/routers/vscode.py
# ============================================================
# Версия B: Использует file_dependencies таблицу
# БЕЗ semantic search!
# ============================================================


def _normalize_file_path(file_path: str) -> str:
    """
    Normalize file path from VS Code format to database format.
    
    Input:  "e:\\projects\\ai-assistant\\backend\\app\\routers\\vscode.py"
    Output: "backend/app/routers/vscode.py"
    """
    # Replace backslashes with forward slashes
    normalized = file_path.replace("\\", "/")
    
    # Try to extract relative path
    markers = ["backend/", "frontend/", "src/", "app/"]
    
    for marker in markers:
        if marker in normalized:
            idx = normalized.find(marker)
            return normalized[idx:]
    
    # If no marker found, return as-is or last parts
    if "/" in normalized:
        parts = normalized.split("/")
        if len(parts) > 4:
            return "/".join(parts[-4:])
        return normalized
    
    return normalized


@router.post("/copy-context", response_model=CopyContextResponse)
async def copy_context_for_ai(
    request: CopyContextRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Build context for external AI chat (Claude, ChatGPT, etc.)
    
    VERSION B: Uses file_dependencies table for dependencies.
    NO semantic search - only actual imports from database!
    
    Returns formatted markdown with:
    1. Current file content
    2. Dependencies (from file_dependencies table)
    3. Project metadata
    """
    
    print(f"\n📋 [CopyContext] ========== START (v3 - file_dependencies) ==========")
    print(f"📋 [CopyContext] project_id={request.project_id}")
    print(f"📋 [CopyContext] file_path={request.file_path}")
    print(f"📋 [CopyContext] max_tokens={request.max_tokens}, max_files={request.max_files}")
    
    try:
        parts = []
        files_included = 0
        total_chars = 0
        max_chars = request.max_tokens * 4  # ~4 chars per token
        dependencies_found = []
        
        print(f"📋 [CopyContext] max_chars={max_chars}")
        
        # ========== 1. CURRENT FILE ==========
        file_name = request.file_path.split('/')[-1].split('\\')[-1]
        language = _detect_language(request.file_path)
        
        current_file_section = f"""## 📄 Current File: `{request.file_path}`
```{language}
{request.file_content}
```
"""
        parts.append(current_file_section)
        files_included += 1
        
        print(f"✅ [CopyContext] Added current file: {len(request.file_content)} chars")
        
        # ========== 2. GET DEPENDENCIES FROM file_dependencies TABLE ==========
        normalized_path = _normalize_file_path(request.file_path)
        print(f"🔗 [CopyContext] Normalized path: {normalized_path}")
        
        # Query file_dependencies with JOIN to get content
        deps_query = db.execute(text("""
            SELECT fd.target_file, fd.dependency_type, fd.imports_what,
                   fe.content, fe.language
            FROM file_dependencies fd
            LEFT JOIN file_embeddings fe 
                ON fe.project_id = fd.project_id AND fe.file_path = fd.target_file
            WHERE fd.project_id = :project_id 
              AND fd.source_file = :source_file
              AND fd.dependency_type = 'import'
            ORDER BY fd.target_file
            LIMIT :max_files
        """), {
            "project_id": request.project_id,
            "source_file": normalized_path,
            "max_files": request.max_files
        }).fetchall()
        
        deps_with_content = 0
        deps_without_content = 0
        
        print(f"🔗 [CopyContext] Found {len(deps_query)} dependencies in DB")
        
        if deps_query:
            parts.append("\n## 📦 Dependencies\n")
            
            for row in deps_query:
                target_file = row[0]
                dep_type = row[1]
                imports_what = row[2]
                content = row[3]
                dep_lang = row[4] or 'typescript'
                
                if not content:
                    deps_without_content += 1
                    print(f"⚠️ [CopyContext] No content for: {target_file}")
                    continue
                
                deps_with_content += 1
                
                if total_chars >= max_chars:
                    print(f"⏭️ [CopyContext] Char limit reached, stopping")
                    break
                
                # Truncate if needed
                remaining = max_chars - total_chars
                if len(content) > remaining:
                    content = content[:remaining] + "\n// ... (truncated)"
                    print(f"⚠️ [CopyContext] Truncated {target_file}")
                
                parts.append(f"""
### `{target_file}`
```{dep_lang}
{content}
```
""")
                total_chars += len(content)
                files_included += 1
                dependencies_found.append({
                    "file_path": target_file,
                    "language": dep_lang,
                    "chars": len(content),
                    "source": "file_dependencies"
                })
                
                print(f"✅ [CopyContext] Added: {target_file} ({len(content)} chars)")
        
        print(f"📊 [CopyContext] Dependencies: {deps_with_content} with content, {deps_without_content} without")
        
        # ========== 3. NO SEMANTIC SEARCH ==========
        # Semantic search is DISABLED - use file_dependencies only
        print(f"⏭️ [CopyContext] Semantic search DISABLED (using file_dependencies only)")
        
        # ========== 4. METADATA SECTION ==========
        if request.include_metadata:
            project = db.get(Project, request.project_id)
            project_name = project.name if project else "Unknown"
            
            # Get total dependencies count
            dep_count = db.execute(text("""
                SELECT COUNT(*) FROM file_dependencies
                WHERE project_id = :pid AND source_file = :source
            """), {"pid": request.project_id, "source": normalized_path}).scalar() or 0
            
            metadata_section = f"""
---

## 📊 Context Metadata

| Property | Value |
|----------|-------|
| Project | {project_name} |
| Current File | `{request.file_path}` |
| Files Included | {files_included} |
| Dependencies in DB | {dep_count} |
| Dependencies loaded | {deps_with_content} |
| Total Characters | {total_chars:,} |
| Estimated Tokens | ~{total_chars // 4:,} |

*Generated by Smart Cline v3 - Copy Context (file_dependencies)*
"""
            parts.append(metadata_section)
        
        # ========== BUILD FINAL MARKDOWN ==========
        header = f"""# 🧠 Code Context for AI

> Current file: `{request.file_path}`

---
"""
        
        final_markdown = header + "\n".join(parts)
        estimated_tokens = len(final_markdown) // 4
        
        print(f"\n✅ [CopyContext] ========== COMPLETE ==========")
        print(f"✅ [CopyContext] Files: {files_included}")
        print(f"✅ [CopyContext] Chars: {total_chars}")
        print(f"✅ [CopyContext] Tokens: ~{estimated_tokens}")
        print(f"✅ [CopyContext] Dependencies: {[d['file_path'] for d in dependencies_found]}")
        
        return CopyContextResponse(
            success=True,
            context_markdown=final_markdown,
            files_included=files_included,
            estimated_tokens=estimated_tokens,
            dependencies=dependencies_found
        )
        
    except Exception as e:
        print(f"❌ [CopyContext] Failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def _resolve_import(
    db: Session,
    project_id: int,
    current_file: str,
    import_path: str
) -> Optional[Dict[str, Any]]:
    """
    Resolve import path to actual file in database.
    Supports:
    - JS/TS: ../store/modelStore, @/components/Button
    - Python: app.deps, app.memory.models
    """
    
    # Handle Python dot notation: app.deps -> deps, app.memory.models -> models
    if '.' in import_path and not import_path.startswith('.'):
        # Python import: app.memory.models -> models
        filename = import_path.split('.')[-1]
        # Also try full path: app/memory/models.py
        python_path = import_path.replace('.', '/')
        
        print(f"🐍 [ResolveImport] Python import: {import_path} -> {filename} or {python_path}")
        
        # Try Python path patterns
        python_patterns = [
            f"%{python_path}.py",
            f"%{python_path}/__init__.py",
            f"%/{filename}.py",
        ]
        
        for pattern in python_patterns:
            result = db.execute(text("""
                SELECT file_path, content, language 
                FROM file_embeddings
                WHERE project_id = :pid 
                AND file_path LIKE :pattern
                LIMIT 1
            """), {"pid": project_id, "pattern": pattern}).fetchone()
            
            if result:
                print(f"✅ [ResolveImport] Found Python: {result[0]}")
                return {
                    "file_path": result[0],
                    "content": result[1],
                    "language": result[2] or "python"
                }
    
    # Handle JS/TS relative imports
    filename = import_path.split('/')[-1]
    
    print(f"🔍 [ResolveImport] Looking for: {filename} in project {project_id}")
    
    # Search by filename pattern in file_path
    search_patterns = [
        f"%/{filename}.ts",
        f"%/{filename}.tsx",
        f"%/{filename}.js",
        f"%/{filename}.jsx",
        f"%/{filename}/index.ts",
        f"%/{filename}/index.tsx",
    ]
    
    for pattern in search_patterns:
        result = db.execute(text("""
            SELECT file_path, content, language 
            FROM file_embeddings
            WHERE project_id = :pid 
            AND file_path LIKE :pattern
            LIMIT 1
        """), {"pid": project_id, "pattern": pattern}).fetchone()
        
        if result:
            print(f"✅ [ResolveImport] Found: {result[0]}")
            return {
                "file_path": result[0],
                "content": result[1],
                "language": result[2]
            }
    
    # Fallback: search by file_name column
    result = db.execute(text("""
        SELECT file_path, content, language 
        FROM file_embeddings
        WHERE project_id = :pid 
        AND file_name LIKE :pattern
        LIMIT 1
    """), {"pid": project_id, "pattern": f"{filename}.%"}).fetchone()
    
    if result:
        print(f"✅ [ResolveImport] Found via file_name: {result[0]}")
        return {
            "file_path": result[0],
            "content": result[1],
            "language": result[2]
        }
    
    print(f"❌ [ResolveImport] Not found: {filename}")
    return None


def _detect_language(file_path: str) -> str:
    """Detect language from file extension"""
    ext_map = {
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.py': 'python',
        '.css': 'css',
        '.scss': 'scss',
        '.html': 'html',
        '.json': 'json',
        '.md': 'markdown',
        '.sql': 'sql',
        '.sh': 'bash',
        '.yaml': 'yaml',
        '.yml': 'yaml',
    }
    
    for ext, lang in ext_map.items():
        if file_path.endswith(ext):
            return lang
    
    return 'text'