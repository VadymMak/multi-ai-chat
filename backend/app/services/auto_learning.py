"""
Auto-Learning Service for Smart Cline.
Captures errors, learns patterns, provides warnings to AI.

File: backend/app/services/auto_learning.py
"""
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone
import json
import re


class AutoLearningService:
    """
    Service for capturing and learning from code errors.
    
    Features:
    - Report errors from VS Code Extension
    - Find similar errors using pattern matching
    - Generate warnings for AI prompts
    - Track error resolutions
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    # ==================== ERROR REPORTING ====================
    
    def report_error(
        self,
        project_id: int,
        error_pattern: str,
        error_type: str,
        file_path: Optional[str] = None,
        error_code: Optional[str] = None,
        line_number: Optional[int] = None,
        code_snippet: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Report a new error or increment existing error count.
        Called by VS Code Extension when TypeScript/ESLint error detected.
        
        Returns:
            Dict with error_id, is_new, occurrence_count
        """
        
        # Normalize error pattern (remove specific paths/names for matching)
        normalized_pattern = self._normalize_error_pattern(error_pattern)
        
        # Check if similar error exists
        existing = self.db.execute(text("""
            SELECT id, occurrence_count 
            FROM learned_errors
            WHERE project_id = :project_id
              AND error_type = :error_type
              AND (
                  error_pattern = :pattern
                  OR error_pattern = :normalized
              )
            LIMIT 1
        """), {
            "project_id": project_id,
            "error_type": error_type,
            "pattern": error_pattern,
            "normalized": normalized_pattern
        }).fetchone()
        
        if existing:
            # Increment count
            self.db.execute(text("""
                UPDATE learned_errors
                SET occurrence_count = occurrence_count + 1,
                    last_seen = :now,
                    updated_at = :now,
                    file_path = COALESCE(:file_path, file_path),
                    line_number = COALESCE(:line_number, line_number),
                    code_snippet = COALESCE(:code_snippet, code_snippet)
                WHERE id = :id
            """), {
                "id": existing[0],
                "now": datetime.now(timezone.utc),
                "file_path": file_path,
                "line_number": line_number,
                "code_snippet": code_snippet
            })
            self.db.commit()
            
            return {
                "error_id": existing[0],
                "is_new": False,
                "occurrence_count": existing[1] + 1
            }
        
        # Create new error entry
        result = self.db.execute(text("""
            INSERT INTO learned_errors
            (project_id, error_pattern, error_type, error_code, 
             file_path, line_number, code_snippet,
             occurrence_count, first_seen, last_seen, created_at, updated_at)
            VALUES 
            (:project_id, :pattern, :error_type, :error_code,
             :file_path, :line_number, :code_snippet,
             1, :now, :now, :now, :now)
            RETURNING id
        """), {
            "project_id": project_id,
            "pattern": error_pattern,
            "error_type": error_type,
            "error_code": error_code,
            "file_path": file_path,
            "line_number": line_number,
            "code_snippet": code_snippet,
            "now": datetime.now(timezone.utc)
        })
        
        error_id = result.fetchone()[0]
        self.db.commit()
        
        print(f"🎓 [AutoLearn] New error recorded: {error_type} - {error_pattern[:50]}...")
        
        return {
            "error_id": error_id,
            "is_new": True,
            "occurrence_count": 1
        }
    
    def report_fix(
        self,
        error_id: int,
        original_code: Optional[str] = None,
        fixed_code: Optional[str] = None,
        fix_method: str = "manual",
        solution_pattern: Optional[str] = None
    ) -> bool:
        """
        Report that an error was fixed.
        Used to learn solutions and update resolved_count.
        """
        
        try:
            # Update error resolved count
            self.db.execute(text("""
                UPDATE learned_errors
                SET resolved_count = resolved_count + 1,
                    solution_pattern = COALESCE(:solution, solution_pattern),
                    solution_example = COALESCE(:example, solution_example),
                    updated_at = :now
                WHERE id = :id
            """), {
                "id": error_id,
                "solution": solution_pattern,
                "example": fixed_code,
                "now": datetime.now(timezone.utc)
            })
            
            # Record resolution history
            if original_code or fixed_code:
                self.db.execute(text("""
                    INSERT INTO error_resolutions
                    (learned_error_id, original_code, fixed_code, fix_method, fix_successful)
                    VALUES (:error_id, :original, :fixed, :method, TRUE)
                """), {
                    "error_id": error_id,
                    "original": original_code,
                    "fixed": fixed_code,
                    "method": fix_method
                })
            
            self.db.commit()
            
            print(f"✅ [AutoLearn] Error {error_id} marked as fixed via {fix_method}")
            return True
            
        except Exception as e:
            print(f"❌ [AutoLearn] Failed to report fix: {e}")
            self.db.rollback()
            return False
    
    # ==================== WARNING GENERATION ====================
    
    def get_warnings_for_prompt(
        self,
        project_id: int,
        file_path: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get relevant warnings to include in AI prompt.
        Prioritizes by occurrence_count and recency.
        
        Returns list of warnings with pattern, solution, count.
        """
        
        # Build query based on file_path
        if file_path:
            # Get errors for specific file + project-wide common errors
            query = text("""
                SELECT DISTINCT ON (error_pattern)
                    id, error_pattern, error_type, error_code,
                    solution_pattern, occurrence_count, resolved_count
                FROM learned_errors
                WHERE project_id = :project_id
                  AND (file_path = :file_path OR occurrence_count >= 3)
                ORDER BY error_pattern, occurrence_count DESC
                LIMIT :limit
            """)
            params = {
                "project_id": project_id,
                "file_path": file_path,
                "limit": limit
            }
        else:
            # Get project-wide common errors
            query = text("""
                SELECT id, error_pattern, error_type, error_code,
                       solution_pattern, occurrence_count, resolved_count
                FROM learned_errors
                WHERE project_id = :project_id
                  AND occurrence_count >= 2
                ORDER BY occurrence_count DESC, last_seen DESC
                LIMIT :limit
            """)
            params = {"project_id": project_id, "limit": limit}
        
        results = self.db.execute(query, params).fetchall()
        
        warnings = []
        for row in results:
            warnings.append({
                "id": row[0],
                "error_pattern": row[1],
                "error_type": row[2],
                "error_code": row[3],
                "solution_pattern": row[4],
                "occurrence_count": row[5],
                "resolved_count": row[6],
                "success_rate": row[6] / row[5] if row[5] > 0 else 0
            })
        
        return warnings
    
    def format_warnings_for_prompt(
        self,
        project_id: int,
        file_path: Optional[str] = None
    ) -> str:
        """
        Format warnings as a string to inject into AI prompt.
        """
        
        warnings = self.get_warnings_for_prompt(project_id, file_path)
        
        if not warnings:
            return ""
        
        lines = ["\n⚠️ COMMON ERRORS IN THIS PROJECT (avoid these!):\n"]
        
        for w in warnings:
            # Error pattern
            lines.append(f"• [{w['error_type'].upper()}] {w['error_pattern']}")
            lines.append(f"  Seen {w['occurrence_count']}x in this project")
            
            # Solution if available
            if w['solution_pattern']:
                lines.append(f"  ✅ Fix: {w['solution_pattern']}")
            
            lines.append("")
        
        return "\n".join(lines)
    
    # ==================== BREAKING CHANGES ====================
    
    def detect_breaking_change(
        self,
        project_id: int,
        old_path: str,
        new_path: Optional[str],
        change_type: str = "rename"
    ) -> Dict[str, Any]:
        """
        Detect and record a potentially breaking change (file rename/delete).
        Finds all files that import the old path.
        
        Args:
            old_path: Original file path
            new_path: New file path (None if deleted)
            change_type: 'rename', 'remove', 'move'
        """
        
        # Find files that import the old path
        importers = self.db.execute(text("""
            SELECT source_file
            FROM file_dependencies
            WHERE project_id = :project_id
              AND (
                  target_file = :old_path
                  OR target_file LIKE :pattern
              )
        """), {
            "project_id": project_id,
            "old_path": old_path,
            "pattern": f"%{old_path.split('/')[-1].replace('.ts', '').replace('.tsx', '')}%"
        }).fetchall()
        
        broken_files = [row[0] for row in importers]
        
        if not broken_files:
            return {
                "recorded": False,
                "reason": "No files import this path"
            }
        
        # Record breaking change
        result = self.db.execute(text("""
            INSERT INTO learned_breaking_changes
            (project_id, change_type, old_path, new_path, 
             broken_files, broken_count, detected_at)
            VALUES 
            (:project_id, :change_type, :old_path, :new_path,
             :broken_files, :broken_count, :now)
            RETURNING id
        """), {
            "project_id": project_id,
            "change_type": change_type,
            "old_path": old_path,
            "new_path": new_path,
            "broken_files": broken_files,
            "broken_count": len(broken_files),
            "now": datetime.now(timezone.utc)
        })
        
        change_id = result.fetchone()[0]
        self.db.commit()
        
        print(f"⚠️ [AutoLearn] Breaking change detected: {old_path} → {new_path}")
        print(f"   Affects {len(broken_files)} files")
        
        return {
            "recorded": True,
            "change_id": change_id,
            "broken_files": broken_files,
            "broken_count": len(broken_files)
        }
    
    def get_unresolved_breaking_changes(
        self,
        project_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get list of unresolved breaking changes for a project.
        """
        
        results = self.db.execute(text("""
            SELECT id, change_type, old_path, new_path, 
                   broken_files, broken_count, detected_at
            FROM learned_breaking_changes
            WHERE project_id = :project_id
              AND is_resolved = FALSE
            ORDER BY detected_at DESC
        """), {"project_id": project_id}).fetchall()
        
        changes = []
        for row in results:
            changes.append({
                "id": row[0],
                "change_type": row[1],
                "old_path": row[2],
                "new_path": row[3],
                "broken_files": row[4],
                "broken_count": row[5],
                "detected_at": row[6].isoformat() if row[6] else None
            })
        
        return changes
    
    # ==================== STATISTICS ====================
    
    def get_project_stats(self, project_id: int) -> Dict[str, Any]:
        """
        Get learning statistics for a project.
        """
        
        # Error stats
        error_stats = self.db.execute(text("""
            SELECT 
                COUNT(*) as total_errors,
                SUM(occurrence_count) as total_occurrences,
                SUM(resolved_count) as total_resolved,
                COUNT(DISTINCT error_type) as error_types
            FROM learned_errors
            WHERE project_id = :project_id
        """), {"project_id": project_id}).fetchone()
        
        # Breaking changes stats
        breaking_stats = self.db.execute(text("""
            SELECT 
                COUNT(*) as total_changes,
                SUM(broken_count) as total_broken,
                SUM(CASE WHEN is_resolved THEN 1 ELSE 0 END) as resolved_changes
            FROM learned_breaking_changes
            WHERE project_id = :project_id
        """), {"project_id": project_id}).fetchone()
        
        # Top errors
        top_errors = self.db.execute(text("""
            SELECT error_pattern, error_type, occurrence_count
            FROM learned_errors
            WHERE project_id = :project_id
            ORDER BY occurrence_count DESC
            LIMIT 5
        """), {"project_id": project_id}).fetchall()
        
        return {
            "errors": {
                "unique_patterns": error_stats[0] or 0,
                "total_occurrences": error_stats[1] or 0,
                "total_resolved": error_stats[2] or 0,
                "error_types": error_stats[3] or 0,
                "resolution_rate": (error_stats[2] or 0) / (error_stats[1] or 1)
            },
            "breaking_changes": {
                "total": breaking_stats[0] or 0,
                "total_broken_files": breaking_stats[1] or 0,
                "resolved": breaking_stats[2] or 0
            },
            "top_errors": [
                {
                    "pattern": row[0][:50] + "..." if len(row[0]) > 50 else row[0],
                    "type": row[1],
                    "count": row[2]
                }
                for row in top_errors
            ]
        }
    
    # ==================== HELPERS ====================
    
    def _normalize_error_pattern(self, pattern: str) -> str:
        """
        Normalize error pattern for better matching.
        Removes specific identifiers to find similar errors.
        """
        
        # Remove specific module paths
        pattern = re.sub(r"'\.\/[^']+'" , "'./MODULE'", pattern)
        pattern = re.sub(r"'[^']+'" , "'X'", pattern)
        
        # Remove specific line numbers
        pattern = re.sub(r"line \d+", "line N", pattern)
        
        # Remove specific type names (keep structure)
        pattern = re.sub(r"type '([A-Z][a-zA-Z]+)'", "type 'T'", pattern)
        
        return pattern