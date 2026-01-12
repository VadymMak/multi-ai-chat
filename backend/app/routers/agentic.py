"""
Agentic Workflow Endpoints for VS Code Extension.
Enables multi-step task planning and execution.

File: backend/app/routers/agentic.py
"""
from typing import Optional, List, Dict, Any, Literal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from uuid import uuid4
from datetime import datetime
import json
import re

from app.deps import get_current_active_user, get_db
from app.memory.models import User, Project
from app.memory.manager import MemoryManager
from app.providers.factory import ask_model
from app.utils.api_key_resolver import get_openai_key
from app.services.smart_context import build_smart_context

router = APIRouter(prefix="/vscode", tags=["agentic"])


# ==================== MODELS ====================

class TaskStep(BaseModel):
    """A single step in the task plan"""
    step_num: int
    action: Literal['create', 'edit', 'delete', 'command']
    file_path: Optional[str] = None
    description: str
    dependencies: List[str] = []
    estimated_complexity: Literal['low', 'medium', 'high'] = 'medium'
    status: Literal['pending', 'in_progress', 'completed', 'failed', 'skipped'] = 'pending'
    result: Optional[Dict] = None
    error: Optional[str] = None


class PlanTaskRequest(BaseModel):
    """Request to plan a complex task"""
    project_id: int
    task: str
    file_path: Optional[str] = None
    file_content: Optional[str] = None


class PlanTaskResponse(BaseModel):
    """Response with task plan"""
    success: bool
    plan_id: str
    task: str
    steps: List[TaskStep]
    total_steps: int
    estimated_time: str
    tokens_used: int


class ExecuteStepRequest(BaseModel):
    """Request to execute a single step"""
    plan_id: str
    step_num: int
    file_content: Optional[str] = None  # Current content for edit steps


class ExecuteStepResponse(BaseModel):
    """Response from step execution"""
    success: bool
    step: TaskStep
    result: Optional[Dict] = None
    plan_completed: bool = False

# ==================== DEPENDENCY MODELS ====================

class FileDependencyItem(BaseModel):
    """Single file dependency"""
    source_file: str
    target_file: str
    dependency_type: str  # 'import', 'require', 'dynamic', 'from'
    imports_what: List[str]


class SaveDependenciesRequest(BaseModel):
    """Request to save file dependencies"""
    project_id: int
    dependencies: List[FileDependencyItem]


class SaveDependenciesResponse(BaseModel):
    """Response from saving dependencies"""
    success: bool
    saved: int
    errors: List[str] = []


# ==================== IN-MEMORY STORAGE ====================
# TODO: Move to database for production
task_plans: Dict[str, Dict] = {}


# ==================== HELPER FUNCTIONS ====================

def estimate_time(steps: List[Dict]) -> str:
    """Estimate execution time based on complexity"""
    complexity_time = {
        "low": 1,
        "medium": 3,
        "high": 5
    }
    
    total_minutes = sum(
        complexity_time.get(step.get("estimated_complexity", "medium"), 3)
        for step in steps
    )
    
    if total_minutes < 60:
        return f"{total_minutes} min"
    else:
        hours = total_minutes // 60
        minutes = total_minutes % 60
        return f"{hours}h {minutes}m"


# ==================== ENDPOINTS ====================

@router.post("/plan-task", response_model=PlanTaskResponse)
async def plan_task(
    request: PlanTaskRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Break down a complex task into executable steps.
    
    Example:
        Task: "Add JWT authentication to this API"
        
        Returns:
        [
            { step: 1, action: "create", file: "auth/service.ts", description: "Create AuthService" },
            { step: 2, action: "create", file: "auth/middleware.ts", description: "Create auth middleware" },
            { step: 3, action: "edit", file: "models/User.ts", description: "Add password fields" },
            { step: 4, action: "edit", file: "routes/index.ts", description: "Add auth routes" },
            { step: 5, action: "command", command: "npm install jsonwebtoken bcrypt" }
        ]
    """
    
    try:
        print(f"\n📋 [PLAN] Task: {request.task[:100]}...")
        print(f"📋 [PLAN] Project: {request.project_id}")
        
        # Get user's API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Initialize memory for Smart Context
        memory = MemoryManager(db)
        
        # Build Smart Context to understand project structure
        try:
            context = await build_smart_context(
                project_id=request.project_id,
                role_id=1,
                query=request.task,
                session_id=str(uuid4()),
                db=db,
                memory=memory
            )
            print(f"📋 [PLAN] Smart Context: {len(context)} chars")
        except Exception as e:
            print(f"⚠️ [PLAN] Smart Context failed: {e}")
            context = "No project context available."
        
        # Add current file context if provided
        if request.file_path and request.file_content:
            context += f"\n\n=== Current File: {request.file_path} ===\n{request.file_content[:3000]}"

        # Query all file paths from file_embeddings
        file_paths_result = db.execute(
            text("""
                SELECT file_path 
                FROM file_embeddings 
                WHERE project_id = :pid
                ORDER BY file_path
            """),
            {"pid": request.project_id}
        ).fetchall()

        # Format as list for AI
        project_files_list = "\n".join([row[0] for row in file_paths_result]) if file_paths_result else "No files indexed"
        files_count = len(file_paths_result)

        print(f"📋 [PLAN] Found {files_count} files in project")
        # ============ END PHASE 0 FIX ============
        
        # Build planning prompt
        prompt = f"""You are an expert software architect. Break down this task into specific, executable steps.

        TASK:
        {request.task}

        === EXISTING PROJECT FILES ({files_count} files) ===
        {project_files_list}
        === END OF FILE LIST ===

        PROJECT CONTEXT (relevant files):
        {context}

        CRITICAL RULES:
        1. For "edit" action: Use ONLY file paths from the EXISTING PROJECT FILES list above!
        2. For "create" action: Follow existing folder structure from the file list
        3. Do NOT invent paths like "src/app.js" - use actual paths from the list!

        4. Each step must be ONE of these actions:
        - "create": Create a new file (path should follow existing structure)
        - "edit": Modify an existing file (MUST exist in the list above!)
        - "delete": Delete a file
        - "command": Run a terminal command (npm install, etc.)

        5. Order steps by dependencies (create base files first)
        6. Keep steps focused (one file per step for create/edit)
        7. Maximum 10 steps

        Return ONLY a JSON array with this EXACT format (no markdown, no explanation):
        [
        {{
            "step_num": 1,
            "action": "create",
            "file_path": "backend/app/services/auth_service.py",
            "description": "Create authentication service with login/logout methods",
            "dependencies": [],
            "estimated_complexity": "medium"
        }},
        {{
            "step_num": 2,
            "action": "edit",
            "file_path": "backend/app/routers/users.py",
            "description": "Add authentication endpoints",
            "dependencies": ["backend/app/services/auth_service.py"],
            "estimated_complexity": "low"
        }}
        ]

        Generate the plan now:"""

        # Call AI for planning
        ai_response = ask_model(
            messages=[
                {"role": "system", "content": "You are a software architect that creates precise task plans. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            model_key="gpt-4o",
            temperature=0.3,
            max_tokens=2000,
            api_key=user_api_key
        )
        
        response_text = ai_response.strip()
        print(f"📋 [PLAN] AI Response: {len(response_text)} chars")
        
        # Parse JSON response
        try:
            # Try direct parse
            steps = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown
            json_match = re.search(r'\[[\s\S]*\]', response_text)
            if json_match:
                steps = json.loads(json_match.group(0))
            else:
                raise HTTPException(
                    status_code=400,
                    detail="AI failed to generate valid plan. Please try rephrasing your task."
                )
        
        # Validate and enhance steps
        validated_steps = []
        for i, step in enumerate(steps):
            validated_step = TaskStep(
                step_num=step.get("step_num", i + 1),
                action=step.get("action", "edit"),
                file_path=step.get("file_path"),
                description=step.get("description", "No description"),
                dependencies=step.get("dependencies", []),
                estimated_complexity=step.get("estimated_complexity", "medium"),
                status="pending"
            )
            validated_steps.append(validated_step)
        
        # ============ PHASE 0.1: Auto-correct EDIT action for non-existent files ============
        existing_paths = set(row[0] for row in file_paths_result)
        
        for step in validated_steps:
            if step.action == "edit":
                file_path = step.file_path or ""
                if file_path and file_path not in existing_paths:
                    print(f"⚠️ [PLAN] Auto-correcting: {file_path} EDIT → CREATE (file not in project)")
                    step.action = "create"
                    step.description = f"[Auto-converted] {step.description}"
        # ============ END PHASE 0.1 ============
        
        # Generate plan ID and store
        plan_id = str(uuid4())[:8]
        
        task_plans[plan_id] = {
            "plan_id": plan_id,
            "project_id": request.project_id,
            "task": request.task,
            "steps": [s.dict() for s in validated_steps],
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "created_by": current_user.id
        }
        
        print(f"✅ [PLAN] Created plan {plan_id} with {len(validated_steps)} steps")
        
        return PlanTaskResponse(
            success=True,
            plan_id=plan_id,
            task=request.task,
            steps=validated_steps,
            total_steps=len(validated_steps),
            estimated_time=estimate_time([s.dict() for s in validated_steps]),
            tokens_used=len(prompt.split()) + len(response_text.split())
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [PLAN] Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute-step", response_model=ExecuteStepResponse)
async def execute_step(
    request: ExecuteStepRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Execute a single step from a task plan.
    
    For 'create' and 'edit' actions, returns the generated code.
    For 'command' actions, returns the command to run.
    """
    
    try:
        print(f"\n⚡ [EXECUTE] Plan: {request.plan_id}, Step: {request.step_num}")
        
        # Get plan
        plan = task_plans.get(request.plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        
        # Get step
        if request.step_num < 1 or request.step_num > len(plan["steps"]):
            raise HTTPException(status_code=400, detail="Invalid step number")
        
        step = plan["steps"][request.step_num - 1]
        
        # Check if already executed
        if step["status"] == "completed":
            return ExecuteStepResponse(
                success=True,
                step=TaskStep(**step),
                result=step.get("result"),
                plan_completed=all(s["status"] in ["completed", "skipped"] for s in plan["steps"])
            )
        
        # Mark as in progress
        step["status"] = "in_progress"
        
        # Get user's API key
        user_api_key = get_openai_key(current_user, db, required=True)
        
        # Initialize memory
        memory = MemoryManager(db)
        
        # Execute based on action type
        result = {}
        
        if step["action"] == "create":
            result = await _execute_create_step(
                step=step,
                plan=plan,
                file_content=None,
                user_api_key=user_api_key,
                db=db,
                memory=memory
            )
            
        elif step["action"] == "edit":
            # ✅ Don't check here - _execute_edit_step will try to get from DB
            result = await _execute_edit_step(
                step=step,
                plan=plan,
                file_content=request.file_content,  # May be None - will try DB
                user_api_key=user_api_key,
                db=db,
                memory=memory
            )

            print(f"📤 [EXECUTE] Edit step {request.step_num} result:")
            print(f"   action: {result.get('action')}")
            print(f"   file_path: {result.get('file_path')}")
            print(f"   new_content length: {len(result.get('new_content', '')) if result.get('new_content') else 0}")
            
        elif step["action"] == "delete":
            result = {
                "action": "delete",
                "file_path": step["file_path"],
                "message": f"Delete file: {step['file_path']}"
            }
            
        elif step["action"] == "command":
            result = {
                "action": "command",
                "command": step.get("command", step["description"]),
                "message": f"Run command: {step.get('command', step['description'])}"
            }
        
        # Mark as completed
        step["status"] = "completed"
        step["result"] = result
        
        # Check if all steps completed
        plan_completed = all(s["status"] in ["completed", "skipped"] for s in plan["steps"])
        if plan_completed:
            plan["status"] = "completed"
        
        print(f"✅ [EXECUTE] Step {request.step_num} completed")
        
        return ExecuteStepResponse(
            success=True,
            step=TaskStep(**step),
            result=result,
            plan_completed=plan_completed
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [EXECUTE] Failed: {e}")
        # Mark step as failed
        if plan and step:
            step["status"] = "failed"
            step["error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task-plan/{plan_id}")
async def get_task_plan(
    plan_id: str,
    current_user: User = Depends(get_current_active_user)
):
    """Get current status of a task plan"""
    
    plan = task_plans.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    steps = [TaskStep(**s) for s in plan["steps"]]
    completed = sum(1 for s in steps if s.status == "completed")
    
    return {
        "plan_id": plan_id,
        "task": plan["task"],
        "status": plan["status"],
        "steps": steps,
        "total_steps": len(steps),
        "completed_steps": completed,
        "created_at": plan["created_at"]
    }


@router.post("/skip-step")
async def skip_step(
    request: ExecuteStepRequest,
    current_user: User = Depends(get_current_active_user)
):
    """Skip a step in the plan"""
    
    plan = task_plans.get(request.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    if request.step_num < 1 or request.step_num > len(plan["steps"]):
        raise HTTPException(status_code=400, detail="Invalid step number")
    
    step = plan["steps"][request.step_num - 1]
    step["status"] = "skipped"
    
    plan_completed = all(s["status"] in ["completed", "skipped"] for s in plan["steps"])
    
    return {
        "success": True,
        "step_num": request.step_num,
        "status": "skipped",
        "plan_completed": plan_completed
    }


@router.post("/cancel-plan/{plan_id}")
async def cancel_plan(
    plan_id: str,
    current_user: User = Depends(get_current_active_user)
):
    """Cancel a task plan"""
    
    plan = task_plans.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    plan["status"] = "cancelled"
    
    return {"success": True, "plan_id": plan_id, "status": "cancelled"}


# ==================== DEPENDENCIES ENDPOINT ====================

@router.post("/save-dependencies", response_model=SaveDependenciesResponse)
async def save_dependencies(
    request: SaveDependenciesRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Save file dependencies to file_dependencies table.
    Called by VS Code Extension after indexing.
    
    FIXED: Now resolves relative paths (../store/chatStore) 
    to full paths (frontend/src/store/chatStore.ts)!
    """
    saved = 0
    skipped = 0
    errors = []
    
    print(f"\n🔗 [DEPS] Saving {len(request.dependencies)} dependencies for project {request.project_id}")
    
    # Clear old dependencies for this project first
    try:
        db.execute(
            text("DELETE FROM file_dependencies WHERE project_id = :pid"),
            {"pid": request.project_id}
        )
        db.commit()
        print(f"🔗 [DEPS] Cleared old dependencies")
    except Exception as e:
        errors.append(f"Failed to clear old deps: {str(e)}")
    
    # Insert new dependencies WITH RESOLUTION
    for dep in request.dependencies:
        try:
            source_file = dep.source_file
            target_file = dep.target_file
            
            # ============================================================
            # NEW: Resolve relative paths to full paths!
            # ============================================================
            resolved_target = _resolve_dependency_path(
                source_file=source_file,
                target_file=target_file,
                project_id=request.project_id,
                db=db
            )
            
            if not resolved_target:
                # Skip unresolved dependencies - they are useless
                skipped += 1
                print(f"⏭️ [DEPS] Skipped unresolved: {source_file} → {target_file}")
                continue
            
            # Skip self-references
            if resolved_target == source_file:
                skipped += 1
                continue
            
            # ============================================================
            
            db.execute(
                text("""
                    INSERT INTO file_dependencies 
                    (project_id, source_file, target_file, dependency_type, imports_what, created_at)
                    VALUES (:pid, :src, :tgt, :dtype, :what, NOW())
                    ON CONFLICT (project_id, source_file, target_file) 
                    DO UPDATE SET 
                        dependency_type = EXCLUDED.dependency_type,
                        imports_what = EXCLUDED.imports_what,
                        created_at = EXCLUDED.created_at
                """),
                {
                    "pid": request.project_id,
                    "src": source_file,
                    "tgt": resolved_target,  # ← NOW USING RESOLVED PATH!
                    "dtype": dep.dependency_type,
                    "what": json.dumps(dep.imports_what)
                }
            )
            saved += 1
            print(f"✅ [DEPS] {source_file} → {resolved_target}")
            
        except Exception as e:
            db.rollback()
            error_msg = f"{dep.source_file} -> {dep.target_file}: {str(e)}"
            errors.append(error_msg)
            print(f"❌ [DEPS] {error_msg}")
    
    db.commit()
    
    print(f"✅ [DEPS] Saved {saved}, skipped {skipped} (unresolved), {len(errors)} errors")
    
    return SaveDependenciesResponse(
        success=len(errors) == 0,
        saved=saved,
        errors=errors[:10]
    )

def _resolve_dependency_path(
    source_file: str,
    target_file: str,
    project_id: int,
    db: Session
) -> Optional[str]:
    """
    Resolve relative import path to full file path.
    
    Examples:
    - source: "frontend/src/pages/ChatPage.tsx"
      target: "../store/chatStore"
      result: "frontend/src/store/chatStore.ts"
      
    - source: "frontend/src/pages/ChatPage.tsx"
      target: "../hooks/useStreamText"
      result: "frontend/src/hooks/useStreamText.ts"
    """
    
    # Skip external packages (no dot prefix)
    if not target_file.startswith(".") and not target_file.startswith("@/"):
        return None
    
    # Normalize source path
    source_file = source_file.replace("\\", "/")
    
    # Handle @/ alias
    if target_file.startswith("@/"):
        if "/src/" in source_file:
            src_idx = source_file.find("/src/")
            base_path = source_file[:src_idx + 5]
            target_file = "./" + target_file[2:]
            source_file = base_path + "index.ts"
        else:
            target_file = "./" + target_file[2:]
    
    # Get source directory
    if "/" in source_file:
        source_dir_parts = source_file.split("/")[:-1]
    else:
        source_dir_parts = []
    
    # Resolve relative path
    import_parts = target_file.split("/")
    resolved_parts = source_dir_parts.copy()
    
    for part in import_parts:
        if part == ".":
            continue
        elif part == "..":
            if resolved_parts:
                resolved_parts.pop()
        else:
            resolved_parts.append(part)
    
    # Build base path without extension
    base_path = "/".join(resolved_parts)
    
    # Try different extensions
    extensions = [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js"]
    
    for ext in extensions:
        test_path = base_path + ext
        
        result = db.execute(text("""
            SELECT file_path FROM file_embeddings
            WHERE project_id = :project_id 
              AND file_path = :path
            LIMIT 1
        """), {
            "project_id": project_id,
            "path": test_path,
        }).fetchone()
        
        if result:
            return result[0]
    
    # Fallback: search by filename
    file_name = resolved_parts[-1] if resolved_parts else target_file.split("/")[-1]
    
    for ext in [".ts", ".tsx", ".js", ".jsx"]:
        result = db.execute(text("""
            SELECT file_path FROM file_embeddings
            WHERE project_id = :project_id 
              AND (
                  file_path LIKE :pattern1
                  OR file_path LIKE :pattern2
              )
            LIMIT 1
        """), {
            "project_id": project_id,
            "pattern1": f"%/{file_name}{ext}",
            "pattern2": f"%/{file_name}/index{ext}",
        }).fetchone()
        
        if result:
            return result[0]
    
    return None

# ==================== STEP EXECUTION HELPERS ====================

async def _execute_create_step(
    step: Dict,
    plan: Dict,
    file_content: Optional[str],
    user_api_key: str,
    db: Session,
    memory: MemoryManager
) -> Dict:
    """Execute a CREATE step - generate new file content"""
    
    # Build context from previous steps
    previous_files = []
    for prev_step in plan["steps"]:
        if prev_step["status"] == "completed" and prev_step.get("result"):
            result = prev_step["result"]
            if result.get("new_content"):
                previous_files.append({
                    "path": prev_step["file_path"],
                    "content": result["new_content"][:1000]  # Truncate
                })
    
    # Build Smart Context
    try:
        context = await build_smart_context(
            project_id=plan["project_id"],
            role_id=1,
            query=step["description"],
            session_id=str(uuid4()),
            db=db,
            memory=memory
        )
    except:
        context = ""
    
    # Build prompt
    prompt = f"""You are an expert code generator. Create a new file.

TASK: {plan["task"]}
STEP: {step["description"]}
FILE TO CREATE: {step["file_path"]}

PROJECT CONTEXT:
{context[:3000]}

{"PREVIOUSLY CREATED FILES:" if previous_files else ""}
{chr(10).join([f"--- {f['path']} ---{chr(10)}{f['content']}" for f in previous_files])}

RULES:
1. Return ONLY the file content (no markdown, no explanations)
2. Include all necessary imports
3. Follow project conventions
4. Make it production-ready

Generate the file content:"""

    # Smart token calculation for CREATE
    context_tokens = len(prompt) // 4
    min_output_tokens = 4000  # CREATE needs space for new file
    model_limit = 16384  # gpt-4o output limit
    smart_max_tokens = min(max(min_output_tokens, 4000), model_limit)
    
    print(f"📊 [CREATE] Context: ~{context_tokens} tokens, Max output: {smart_max_tokens}")

    ai_response = ask_model(
        messages=[
            {"role": "system", "content": "You are an expert code generator. Return only code."},
            {"role": "user", "content": prompt}
        ],
        model_key="gpt-4o",
        temperature=0.2,
        max_tokens=smart_max_tokens,
        api_key=user_api_key
    )
    
    content = ai_response.strip()
    
    # Remove markdown if present
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    
    return {
        "action": "create",
        "file_path": step["file_path"],
        "new_content": content,
        "message": f"Created {step['file_path']}"
    }


async def _execute_edit_step(
    step: Dict,
    plan: Dict,
    file_content: Optional[str],
    user_api_key: str,
    db: Session,
    memory: MemoryManager
) -> Dict:
    """Execute an EDIT step - modify existing file"""
    
    file_path = step.get("file_path", "")
    file_name = file_path.split('/')[-1] if file_path else ""
    project_id = plan.get("project_id")
    
    # ✅ FIRST: Check if file was created in previous steps of this plan
    if not file_content:
        for prev_step in plan["steps"]:
            if prev_step["status"] == "completed" and prev_step.get("result"):
                result = prev_step["result"]
                prev_file_path = prev_step.get("file_path", "")
                # Check if this is the file we need (exact or partial match)
                if result.get("new_content") and (
                    prev_file_path == file_path or 
                    prev_file_path.endswith(file_name)
                ):
                    file_content = result["new_content"]
                    print(f"📄 [EXECUTE] Got file content from previous step: {prev_file_path}")
                    break
    
    # ✅ SECOND: Try to get from database if still no content
    if not file_content and file_path:
        print(f"🔍 [EXECUTE] Looking for file in DB: {file_path} (project={project_id})")
        
        # Try exact match first
        result = db.execute(
            text("SELECT content, file_path FROM file_embeddings WHERE project_id = :pid AND file_path = :fpath LIMIT 1"),
            {"pid": project_id, "fpath": file_path}
        ).fetchone()
        
        if result:
            file_content = result[0]
            actual_path = result[1]
            print(f"📄 [EXECUTE] Found exact match: {actual_path} ({len(file_content)} chars)")
        else:
            # Try partial match with filename
            file_name_with_ext = file_path.split('/')[-1]
            print(f"🔍 [EXECUTE] Trying partial match for: {file_name_with_ext}")
            
            result = db.execute(
                text("""
                    SELECT content, file_path FROM file_embeddings 
                    WHERE project_id = :pid 
                    AND file_path LIKE :pattern 
                    LIMIT 1
                """),
                {"pid": project_id, "pattern": f"%/{file_name_with_ext}"}
            ).fetchone()
            
            if result:
                file_content = result[0]
                actual_path = result[1]
                # ✅ CRITICAL: Update step with correct full path!
                step["file_path"] = actual_path
                print(f"📄 [EXECUTE] Found via partial match: {actual_path} ({len(file_content)} chars)")
            else:
                print(f"⚠️ [EXECUTE] File not found in DB: {file_path}")
    
    # ✅ If still no content, raise error
    if not file_content:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot edit file: content not provided and file not found in index: {file_path}"
        )
    
    # ============ NEW: Get file dependencies from graph ============
    dependent_files_context = ""
    
    if file_path and project_id:
        try:
            # Strip extension for matching (api.ts -> api)
            file_name_no_ext = file_name.replace('.ts', '').replace('.tsx', '').replace('.js', '').replace('.jsx', '').replace('.py', '')
            
            # 1. Files that THIS file imports (dependencies)
            imports_result = db.execute(
                text("""
                    SELECT fd.target_file, fd.imports_what
                    FROM file_dependencies fd
                    WHERE fd.project_id = :pid AND fd.source_file = :fpath
                    LIMIT 5
                """),
                {"pid": project_id, "fpath": file_path}
            ).fetchall()
            
            # 2. Files that IMPORT this file (dependents)
            importers_result = db.execute(
                text("""
                    SELECT fd.source_file, fd.imports_what, fe.content
                    FROM file_dependencies fd
                    LEFT JOIN file_embeddings fe ON fe.project_id = fd.project_id 
                        AND fe.file_path = fd.source_file
                    WHERE fd.project_id = :pid 
                        AND (fd.target_file LIKE :pattern1 OR fd.target_file LIKE :pattern2)
                    LIMIT 5
                """),
                {
                    "pid": project_id, 
                    "pattern1": f"%/{file_name_no_ext}",
                    "pattern2": f"%{file_name_no_ext}%"
                }
            ).fetchall()
            
            # Build context string
            if imports_result:
                dependent_files_context += "\n\n=== THIS FILE IMPORTS ===\n"
                for row in imports_result:
                    target, imports_what = row
                    dependent_files_context += f"• {target}: {imports_what}\n"
            
            if importers_result:
                dependent_files_context += "\n=== FILES THAT IMPORT THIS FILE (don't break their imports!) ===\n"
                for row in importers_result:
                    source, imports_what, content = row
                    dependent_files_context += f"\n--- {source} (uses: {imports_what}) ---\n"
                    if content:
                        # Show only first 300 chars to save tokens
                        dependent_files_context += f"{content[:300]}...\n"
            
            imports_count = len(imports_result) if imports_result else 0
            importers_count = len(importers_result) if importers_result else 0
            
            if imports_count > 0 or importers_count > 0:
                print(f"🔗 [EXECUTE] Dependencies: {imports_count} imports, {importers_count} importers")
        
        except Exception as e:
            print(f"⚠️ [EXECUTE] Failed to get dependencies: {e}")
    # ============ END NEW ============
    
    # Build context from previous steps (for AI prompt)
    previous_files = []
    for prev_step in plan["steps"]:
        if prev_step["status"] == "completed" and prev_step.get("result"):
            result = prev_step["result"]
            if result.get("new_content"):
                previous_files.append({
                    "path": prev_step["file_path"],
                    "content": result["new_content"][:1000]
                })
    
    # Detect language for syntax hints
    language = "typescript"
    if file_path.endswith(".py"):
        language = "python"
    elif file_path.endswith(".js"):
        language = "javascript"
    elif file_path.endswith(".tsx"):
        language = "tsx"
    elif file_path.endswith(".jsx"):
        language = "jsx"
    
    # Calculate file stats for AI awareness
    file_lines = len(file_content.split('\n'))
    file_chars = len(file_content)
    
    # Build prompt for edit - IMPROVED VERSION
    prompt = f"""You are an expert code editor. Modify this file according to the instruction.

TASK: {plan["task"]}
STEP: {step["description"]}
FILE TO EDIT: {step["file_path"]} ({file_lines} lines, {file_chars} chars)

CURRENT FILE CONTENT:
```{language}
{file_content}
```
{dependent_files_context}
{"RELATED FILES (already created):" if previous_files else ""}
{chr(10).join([f"--- {f['path']} ---{chr(10)}{f['content']}" for f in previous_files])}

═══════════════════════════════════════════════════════════════
CRITICAL RULES - YOU MUST FOLLOW ALL OF THESE:
═══════════════════════════════════════════════════════════════

1. RETURN THE COMPLETE FILE - every single line from start to end
2. Do NOT truncate or skip ANY code - no "// ..." or "// rest of code"
3. Do NOT use placeholders like "// existing code here" or "// остальной код"
4. VERIFY all brackets match: count {{ and }} - they MUST be equal
5. VERIFY all parentheses match: count ( and ) - they MUST be equal
6. Keep ALL existing imports - do not remove any
7. Keep ALL existing exports - do not remove or rename any
8. Keep ALL existing functions/components that are not being modified
9. Only modify what the task specifically requires
10. Preserve the exact code style (indentation, quotes, semicolons)

QUALITY CHECK before returning:
- Is every line from the original file present (unless intentionally removed)?
- Are all brackets/braces balanced?
- Did I keep all imports?
- Did I keep all exports?
- Is the component/function complete?

Return ONLY the complete modified file content (no markdown fences):"""

    # System prompt - IMPROVED VERSION
    system_prompt = """You are an expert code editor. You MUST return the COMPLETE file.

ABSOLUTE REQUIREMENTS:
1. Return the ENTIRE file - not just the changed parts
2. NEVER truncate code or use "..." or "// rest of code"
3. NEVER leave placeholders or incomplete code
4. All brackets, braces, and parentheses MUST be balanced
5. Preserve ALL existing functionality that wasn't asked to change

If you cannot complete the task properly, return the ORIGINAL file unchanged rather than returning broken code."""

    # Smart token calculation for EDIT
    file_tokens = len(file_content) // 4
    context_tokens = len(prompt) // 4
    buffer_tokens = 500  # Extra space for additions
    
    # Output needs at least file size + buffer
    min_output_tokens = file_tokens + buffer_tokens
    model_limit = 16384  # gpt-4o output limit
    
    # Smart max_tokens: at least 4096, enough for file, but not more than model allows
    smart_max_tokens = min(max(min_output_tokens, 4096), model_limit)
    
    print(f"📊 [EDIT] File: ~{file_tokens} tokens, Context: ~{context_tokens} tokens, Max output: {smart_max_tokens}")

    ai_response = ask_model(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        model_key="gpt-4o",
        temperature=0.2,
        max_tokens=smart_max_tokens,
        api_key=user_api_key
    )
    
    new_content = ai_response.strip()
    
    # Remove markdown if present
    if new_content.startswith("```"):
        lines = new_content.split("\n")
        # Find closing ``` and remove both markers
        if lines[-1].strip() == "```":
            new_content = "\n".join(lines[1:-1])
        else:
            # Maybe no closing, just remove first line
            new_content = "\n".join(lines[1:])
    
    # Basic validation warning (will be expanded in Step 1.7.2)
    original_lines = len(file_content.split('\n'))
    new_lines = len(new_content.split('\n'))
    if new_lines < original_lines * 0.5:
        print(f"⚠️ [EDIT] WARNING: Output significantly shorter! Original: {original_lines} lines, New: {new_lines} lines")
    
    # ✅ Log what we're returning
    print(f"📤 [EXECUTE] Returning edit result:")
    print(f"   file_path: {step['file_path']}")
    print(f"   new_content length: {len(new_content)}")
    
    return {
        "action": "edit",
        "file_path": step["file_path"],  # Now has correct path!
        "original_content": file_content,
        "new_content": new_content,
        "message": f"Modified {step['file_path']}"
    }