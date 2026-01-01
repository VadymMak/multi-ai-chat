"""
Version Service - Our own Git for tracking file changes
Handles: create version, get history, rollback, diff
"""

import difflib
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.memory.models import FileVersion


class VersionService:
    """Service for managing file versions"""
    
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
    ) -> FileVersion:
        """
        Create new version of a file
        
        Args:
            file_id: ID from file_embeddings
            content: Full file content
            change_type: 'create', 'edit', 'delete', 'rollback'
            change_source: 'user', 'ai_edit', 'ai_create', 'ai_fix'
            change_message: Description of change
            user_id: User who made change (if user)
            ai_model: AI model used (if AI)
            plan_id: Agentic plan ID (if from plan)
            step_num: Step number in plan
            previous_content: Previous content for diff generation
        """
        
        # Get next version number
        last_version = self.db.query(FileVersion).filter(
            FileVersion.file_id == file_id
        ).order_by(desc(FileVersion.version_number)).first()
        
        version_number = (last_version.version_number + 1) if last_version else 1
        
        # Generate diff if previous content provided
        diff = None
        if previous_content is not None:
            diff = self._generate_diff(previous_content, content)
        
        # Create version
        version = FileVersion(
            file_id=file_id,
            version_number=version_number,
            content=content,
            diff_from_previous=diff,
            change_type=change_type,
            change_source=change_source,
            change_message=change_message,
            user_id=user_id,
            ai_model=ai_model,
            plan_id=plan_id,
            step_num=step_num
        )
        
        self.db.add(version)
        self.db.commit()
        self.db.refresh(version)
        
        return version
    
    def get_versions(
        self,
        file_id: int,
        limit: int = 50
    ) -> List[FileVersion]:
        """Get version history for a file (newest first)"""
        
        return self.db.query(FileVersion).filter(
            FileVersion.file_id == file_id
        ).order_by(desc(FileVersion.version_number)).limit(limit).all()
    
    def get_version(
        self,
        file_id: int,
        version_number: int
    ) -> Optional[FileVersion]:
        """Get specific version of a file"""
        
        return self.db.query(FileVersion).filter(
            FileVersion.file_id == file_id,
            FileVersion.version_number == version_number
        ).first()
    
    def get_latest_version(self, file_id: int) -> Optional[FileVersion]:
        """Get latest version of a file"""
        
        return self.db.query(FileVersion).filter(
            FileVersion.file_id == file_id
        ).order_by(desc(FileVersion.version_number)).first()
    
    def rollback(
        self,
        file_id: int,
        to_version: int,
        user_id: Optional[int] = None
    ) -> FileVersion:
        """
        Rollback file to a previous version
        Creates NEW version with old content (preserves history)
        """
        
        # Get target version
        target = self.get_version(file_id, to_version)
        if not target:
            raise ValueError(f"Version {to_version} not found for file {file_id}")
        
        # Get current content for diff
        latest = self.get_latest_version(file_id)
        previous_content = latest.content if latest else None
        
        # Create new version with rollback content
        return self.create_version(
            file_id=file_id,
            content=target.content,
            change_type="rollback",
            change_source="user",
            change_message=f"Rollback to version {to_version}",
            user_id=user_id,
            previous_content=previous_content
        )
    
    def get_diff_between(
        self,
        file_id: int,
        from_version: int,
        to_version: int
    ) -> str:
        """Get diff between two versions"""
        
        v_from = self.get_version(file_id, from_version)
        v_to = self.get_version(file_id, to_version)
        
        if not v_from or not v_to:
            raise ValueError("One or both versions not found")
        
        return self._generate_diff(v_from.content, v_to.content)
    
    def _generate_diff(self, old: str, new: str) -> str:
        """Generate unified diff between two contents"""
        
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile='before',
            tofile='after',
            lineterm=''
        )
        
        return ''.join(diff)
    
    def to_dict(self, version: FileVersion) -> Dict[str, Any]:
        """Convert version to dictionary for API response"""
        
        return {
            "id": version.id,
            "file_id": version.file_id,
            "version_number": version.version_number,
            "change_type": version.change_type,
            "change_source": version.change_source,
            "change_message": version.change_message,
            "user_id": version.user_id,
            "ai_model": version.ai_model,
            "plan_id": version.plan_id,
            "step_num": version.step_num,
            "created_at": version.created_at.isoformat() if version.created_at else None,
            "has_diff": version.diff_from_previous is not None
        }