"""
VS Code Extension API endpoints.
Full Smart Context using EXISTING services:
- build_smart_context() from smart_context.py
- MemoryManager from manager.py
- store_message_with_embedding() from vector_service.py
"""
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
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

router = APIRouter(prefix="/vscode", tags=["vscode"])


# Request/Response Models
class VSCodeChatRequest(BaseModel):
    message: str
    project_id: Optional[int] = None
    role_id: Optional[int] = None
    chat_session_id: Optional[str] = None
    filePath: Optional[str] = None
    fileContent: Optional[str] = None
    selectedText: Optional[str] = None


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


class CreateFileRequest(BaseModel):
    project_id: int
    instruction: str
    file_path: Optional[str] = None
    current_content: Optional[str] = None


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


async def edit_file_with_ai(
    request: EditFileRequest, 
    current_user: User, 
    db: Session
):
    """
    Edit file using AI with Smart Context.
    Returns diff between original and new content.
    """
    try:
        print(f"\n🔧 [EDIT] file={request.file_path}")
        print(f"📝 [EDIT] instruction: {request.instruction[:100]}...")
        
        # Get user's API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Initialize memory
        memory = MemoryManager(db)
        
        # Build Smart Context
        context = await build_smart_context(  # ← async!
            project_id=request.project_id,
            role_id=1,  # default role
            query=request.instruction,
            session_id=str(uuid4()),  # временный session
            db=db,
            memory=memory  # уже есть выше!
        )

        original_lines = request.current_content.count('\n') + 1
        original_chars = len(request.current_content)
        
        # Build prompt
        prompt = f"""You are an expert code editor. Edit the file according to the instruction.

CURRENT FILE ({request.file_path}):
- Total lines: {original_lines}
- Total characters: {original_chars}
```
{request.current_content}
```

INSTRUCTION:
{request.instruction}

PROJECT CONTEXT:
{context}

CRITICAL RULES - READ CAREFULLY:

⚠️ MOST IMPORTANT RULE ⚠️
You MUST return the COMPLETE file. This means EVERY SINGLE LINE from the original file must be present in your response.

FORBIDDEN - These will cause IMMEDIATE REJECTION:
❌ "... rest of code ..."
❌ "... (rest of the code)"
❌ "# ... (previous code)"
❌ "# ... rest of"
❌ "# (code omitted)"
❌ "# ... additional code"
❌ "# remaining code unchanged"
❌ ANY placeholder or ellipsis indicating skipped code

REQUIRED:
1. Start with ALL imports from the original file
2. Include EVERY function, EVERY class, EVERY line
3. Add your requested changes to the appropriate locations
4. Keep everything else EXACTLY as it was
5. Do not include markdown code blocks (no ```python)
6. The output must be approximately {original_lines} lines
7. The output must be approximately {original_chars} characters

VERIFICATION:
- Original file: {original_lines} lines, {original_chars} characters
- Your output must be similar in length (minimum {int(original_chars * 0.7)} chars)
- If you can't fit everything, respond with "FILE TOO LARGE" instead

BAD EXAMPLE (will be rejected):
```
import something

def my_function():
    # Add error handling
    try:
        ...
    except:
        ...

# ... rest of code ...  ← FORBIDDEN!
```

GOOD EXAMPLE:
```
import something
import another_thing

def my_function():
    # Add error handling
    try:
        result = do_something()
        return result
    except Exception as e:
        logger.error(f"Error: {{e}}")
        raise

def another_function():
    # This function was in original - keeping it!
    pass

# ALL other functions from original file here...
```

Now generate the COMPLETE edited file with ALL {original_lines} lines:"""
        
        # ДОБАВИТЬ ПЕРЕД ask_model():
        # Динамически вычисляем нужный лимит токенов
        estimated_tokens = original_chars // 4
        max_tokens_needed = int(estimated_tokens * 1.5)
        max_tokens_needed = min(max_tokens_needed, 16000)
        max_tokens_needed = max(max_tokens_needed, 4000)

        print(f"🎯 [EDIT] Using max_tokens={max_tokens_needed} for file with {original_chars} chars")

        # Call AI
        ai_response = ask_model(
            messages=[
                {"role": "system", "content": "You are an expert code editor."},
                {"role": "user", "content": prompt}
            ],
            model_key="gpt-4o",
            temperature=0.2,
            max_tokens=max_tokens_needed,  # ← ВОТ ИЗМЕНЕНИЕ!
            api_key=user_api_key
        )
        
        new_content = ai_response.strip()

        # ========== ВАЛИДАЦИЯ ПОЛНОТЫ ФАЙЛА ==========
        original_length = len(request.current_content)
        new_length = len(new_content)
        original_lines = request.current_content.count('\n') + 1
        new_lines = new_content.count('\n') + 1

        print(f"📊 [EDIT] Original: {original_length} chars, {original_lines} lines")
        print(f"📊 [EDIT] Generated: {new_length} chars, {new_lines} lines")

        # Проверка 1: Новый файл не должен быть намного короче
        if new_length < original_length * 0.7:
            error_msg = (
                f"AI generated incomplete file!\n"
                f"Original: {original_length} chars ({original_lines} lines)\n"
                f"Generated: {new_length} chars ({new_lines} lines)\n"
                f"Difference: {original_length - new_length} chars missing\n"
                f"This is only {(new_length / original_length * 100):.1f}% of the original file.\n\n"
                f"Please try with a more specific instruction or break down the task."
            )
            print(f"❌ [EDIT] {error_msg}")
            raise HTTPException(
                status_code=400,
                detail=error_msg
            )

        # Проверка 2: Файл не должен содержать placeholders
        placeholder_patterns = [
            "... rest of code ...",
            "... (rest of the code)",
            "# ... (previous code)",
            "# ... rest of",
            "# (code omitted)",
            "# ... additional code",
        ]

        for pattern in placeholder_patterns:
            if pattern.lower() in new_content.lower():
                error_msg = (
                    f"AI generated file with placeholder text: '{pattern}'\n"
                    f"This indicates an incomplete generation.\n"
                    f"Please try again with a more specific instruction."
                )
                print(f"❌ [EDIT] {error_msg}")
                raise HTTPException(
                    status_code=400,
                    detail=error_msg
                )

        print(f"✅ [EDIT] Validation passed: File is complete")

        # Generate diff
        diff = ''.join(difflib.unified_diff(
            request.current_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{request.file_path}",
            tofile=f"b/{request.file_path}",
            lineterm=''
        ))
        
        print(f"✅ [EDIT] Generated {len(new_content)} chars, diff {len(diff)} chars")
        
        # Return response-like dict (not model instance)
        return type('obj', (object,), {
            'original_content': request.current_content,
            'new_content': new_content,
            'diff': diff,
            'tokens_used': {'total': len(prompt.split()) + len(new_content.split())}
        })()
        
    except Exception as e:
        print(f"❌ [EDIT] Failed: {e}")
        raise


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
        
        # Get user's API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Initialize memory
        memory = MemoryManager(db)
        
        # Build Smart Context
        context = await build_smart_context(  # ← async!
            project_id=request.project_id,
            role_id=1,  # default role
            query=request.instruction,
            session_id=str(uuid4()),  # временный session
            db=db,
            memory=memory  # уже есть выше!
        )
        
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

        # ✅ СТАЛО:
        # Для CREATE mode используем стандартный лимит
        # (у нас нет исходного файла для оценки размера)
        max_tokens_needed = 4000  # Стандартный лимит для новых файлов

        print(f"🎯 [CREATE] Using max_tokens={max_tokens_needed} for new file")

        ai_response = ask_model(
            messages=[
                {"role": "system", "content": "You are an expert code editor."},
                {"role": "user", "content": prompt}
            ],
            model_key="gpt-4o",
            temperature=0.2,
            max_tokens=max_tokens_needed,  # ← динамический лимит!
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
        
        # Return response-like dict
        return type('obj', (object,), {
            'file_path': suggested_path,
            'new_content': content,
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
        if intent == "EDIT" and has_file_open and project_id:
            print(f"🎯 [Intent] EDIT mode activated!")
            
            # Call edit-file endpoint logic
            try:
                edit_request = EditFileRequest(
                    project_id=project_id,
                    file_path=request.filePath,
                    instruction=request.message,
                    current_content=request.fileContent
                )
                
                edit_response = await edit_file_with_ai(edit_request, current_user, db)
                
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
                
            except Exception as e:
                print(f"❌ [EDIT mode] Failed: {e}")
                # Fall through to normal chat mode
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
                    current_content=None
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
        
        # Build smart context
        try:
            context = await build_smart_context(  # ← async!
                project_id=project_id,
                role_id=role_id,
                query=request.message,
                session_id=chat_session_id,  # уже есть выше!
                db=db,
                memory=memory  # уже есть выше!
            )
        except Exception as e:
            print(f"⚠️ [VSCode] Failed to build smart context: {e}, using minimal context")
            context = f"User message: {request.message}"
        
        # Add current file context if available
        if request.filePath and request.fileContent:
            context += f"\n\n=== Current File: {request.filePath} ===\n{request.fileContent[:2000]}"
        
        if request.selectedText:
            context += f"\n\n=== Selected Text ===\n{request.selectedText}"
        
        # Call AI
        try:
            ai_response = ask_model(
                messages=[
                    {"role": "system", "content": "You are a helpful coding assistant integrated into VS Code."},
                    {"role": "user", "content": context}
                ],
                model_key="gpt-4o",
                temperature=0.7,
                max_tokens=2000,
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