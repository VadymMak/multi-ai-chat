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

    ai_response = ask_model(
        messages=[
            {"role": "system", "content": "You are an expert code generator. Return only code."},
            {"role": "user", "content": prompt}
        ],
        model_key="gpt-4o",
        temperature=0.2,
        max_tokens=4000,
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
        from sqlalchemy import text
        
        project_id = plan.get("project_id")
        print(f"🔍 [EXECUTE] Looking for file in DB: {file_path} (project={project_id})")
        
        # Try exact match first
        result = db.execute(
            text("SELECT content FROM file_embeddings WHERE project_id = :pid AND file_path = :fpath LIMIT 1"),
            {"pid": project_id, "fpath": file_path}
        ).fetchone()
        
        # If not found, try partial match
        if not result:
            result = db.execute(
                text("SELECT content FROM file_embeddings WHERE project_id = :pid AND file_path LIKE :pattern LIMIT 1"),
                {"pid": project_id, "pattern": f"%{file_name}"}
            ).fetchone()
        
        if result:
            file_content = result[0]
            print(f"📄 [EXECUTE] Got file content from DB: {file_path} ({len(file_content)} chars)")
        else:
            print(f"⚠️ [EXECUTE] File not found in DB: {file_path}")
    
    # ✅ If still no content, raise error
    if not file_content:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot edit file: content not provided and file not found in index: {file_path}"
        )
    
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
    
    # Build prompt for edit
    prompt = f"""You are an expert code editor. Modify this file according to the instruction.

TASK: {plan["task"]}
STEP: {step["description"]}
FILE TO EDIT: {step["file_path"]}

CURRENT FILE CONTENT:
```
{file_content}
```

{"RELATED FILES (already created):" if previous_files else ""}
{chr(10).join([f"--- {f['path']} ---{chr(10)}{f['content']}" for f in previous_files])}

RULES:
1. Return the COMPLETE modified file (not just changes)
2. Keep existing functionality intact
3. Add imports if needed
4. Follow existing code style

Return ONLY the complete modified file content:"""

    ai_response = ask_model(
        messages=[
            {"role": "system", "content": "You are an expert code editor. Return only the complete modified file."},
            {"role": "user", "content": prompt}
        ],
        model_key="gpt-4o",
        temperature=0.2,
        max_tokens=8000,
        api_key=user_api_key
    )
    
    new_content = ai_response.strip()
    
    # Remove markdown if present
    if new_content.startswith("```"):
        lines = new_content.split("\n")
        new_content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    
    return {
        "action": "edit",
        "file_path": step["file_path"],
        "original_content": file_content,
        "new_content": new_content,
        "message": f"Modified {step['file_path']}"
    }