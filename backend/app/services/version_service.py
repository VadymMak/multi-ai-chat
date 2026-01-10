"""
Version Service - Our own Git for tracking file changes
Handles: create version, get history, rollback, diff
"""

import difflib
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text


class VersionService:
    """Service for managing file versions - uses raw SQL"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_version(
        self,
        file_id: int,
        content: str,
        change_type: str,
        change_source: str,
        change_message: Optional[str] = None,
        user_id: Optional[int] = None,
        ai_model: Optional[str] = None,
        plan_id: Optional[str] = None,
        step_num: Optional[int] = None,
        previous_content: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create new version of a file
        """
        
        # Get next version number
        result = self.db.execute(text("""
            SELECT version_number FROM file_versions 
            WHERE file_id = :file_id 
            ORDER BY version_number DESC 
            LIMIT 1
        """), {"file_id": file_id}).fetchone()
        
        version_number = (result[0] + 1) if result else 1
        
        # Generate diff if previous content provided
        diff = None
        if previous_content is not None:
            diff = self._generate_diff(previous_content, content)
        
        # Insert new version
        self.db.execute(text("""
            INSERT INTO file_versions 
            (file_id, version_number, content, diff_from_previous, change_type, 
             change_source, change_message, user_id, ai_model, plan_id, step_num, created_at)
            VALUES 
            (:file_id, :version_number, :content, :diff, :change_type,
             :change_source, :change_message, :user_id, :ai_model, :plan_id, :step_num, NOW())
        """), {
            "file_id": file_id,
            "version_number": version_number,
            "content": content,
            "diff": diff,
            "change_type": change_type,
            "change_source": change_source,
            "change_message": change_message,
            "user_id": user_id,
            "ai_model": ai_model,
            "plan_id": plan_id,
            "step_num": step_num
        })
        self.db.commit()
        
        return {
            "file_id": file_id,
            "version_number": version_number,
            "change_type": change_type,
            "change_source": change_source
        }
    
    def get_versions(self, file_id: int, limit: int = 50) -> List[Dict]:
        """Get version history for a file (newest first)"""
        
        results = self.db.execute(text("""
            SELECT id, file_id, version_number, change_type, change_source, 
                   change_message, user_id, ai_model, plan_id, step_num, created_at,
                   (diff_from_previous IS NOT NULL) as has_diff
            FROM file_versions 
            WHERE file_id = :file_id 
            ORDER BY version_number DESC 
            LIMIT :limit
        """), {"file_id": file_id, "limit": limit}).fetchall()
        
        return [self._row_to_dict(r) for r in results]
    
    def get_version(self, file_id: int, version_number: int) -> Optional[Dict]:
        """Get specific version of a file"""
        
        result = self.db.execute(text("""
            SELECT id, file_id, version_number, content, diff_from_previous,
                   change_type, change_source, change_message, user_id, 
                   ai_model, plan_id, step_num, created_at
            FROM file_versions 
            WHERE file_id = :file_id AND version_number = :version_number
        """), {"file_id": file_id, "version_number": version_number}).fetchone()
        
        return self._row_to_dict_full(result) if result else None
    
    def get_latest_version(self, file_id: int) -> Optional[Dict]:
        """Get latest version of a file"""
        
        result = self.db.execute(text("""
            SELECT id, file_id, version_number, content, diff_from_previous,
                   change_type, change_source, change_message, user_id, 
                   ai_model, plan_id, step_num, created_at
            FROM file_versions 
            WHERE file_id = :file_id 
            ORDER BY version_number DESC 
            LIMIT 1
        """), {"file_id": file_id}).fetchone()
        
        return self._row_to_dict_full(result) if result else None
    
    def rollback(self, file_id: int, to_version: int, user_id: Optional[int] = None) -> Dict:
        """Rollback file to a previous version - creates NEW version"""
        
        target = self.get_version(file_id, to_version)
        if not target:
            raise ValueError(f"Version {to_version} not found for file {file_id}")
        
        latest = self.get_latest_version(file_id)
        previous_content = latest["content"] if latest else None
        
        return self.create_version(
            file_id=file_id,
            content=target["content"],
            change_type="rollback",
            change_source="user",
            change_message=f"Rollback to version {to_version}",
            user_id=user_id,
            previous_content=previous_content
        )
    
    def get_diff_between(self, file_id: int, from_version: int, to_version: int) -> str:
        """Get diff between two versions"""
        
        v_from = self.get_version(file_id, from_version)
        v_to = self.get_version(file_id, to_version)
        
        if not v_from or not v_to:
            raise ValueError("One or both versions not found")
        
        return self._generate_diff(v_from["content"], v_to["content"])
    
    def _generate_diff(self, old: str, new: str) -> str:
        """Generate unified diff"""
        
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        
        diff = difflib.unified_diff(old_lines, new_lines, fromfile='before', tofile='after', lineterm='')
        return ''.join(diff)
    
    def _row_to_dict(self, row) -> Dict[str, Any]:
        """Convert row to dict (without content)"""
        return {
            "id": row[0],
            "file_id": row[1],
            "version_number": row[2],
            "change_type": row[3],
            "change_source": row[4],
            "change_message": row[5],
            "user_id": row[6],
            "ai_model": row[7],
            "plan_id": row[8],
            "step_num": row[9],
            "created_at": row[10].isoformat() if row[10] else None,
            "has_diff": row[11]
        }
    
    def _row_to_dict_full(self, row) -> Dict[str, Any]:
        """Convert row to dict (with content)"""
        return {
            "id": row[0],
            "file_id": row[1],
            "version_number": row[2],
            "content": row[3],
            "diff_from_previous": row[4],
            "change_type": row[5],
            "change_source": row[6],
            "change_message": row[7],
            "user_id": row[8],
            "ai_model": row[9],
            "plan_id": row[10],
            "step_num": row[11],
            "created_at": row[12].isoformat() if row[12] else None,
            "has_diff": row[4] is not None
        }