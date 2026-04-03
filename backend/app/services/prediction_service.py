"""
Prediction Service for multi-ai-chat brain.
Structural impact analysis based on the dependency graph.

File: backend/app/services/prediction_service.py
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone, timedelta
import hashlib
import json

from app.services.dependency_graph import build_dependency_graph, DependencyGraph


CACHE_TTL_MINUTES = 5


class PredictionService:
    """
    Service for structural prediction and impact analysis.

    Features:
    - Predict which files are affected by changes (direct + transitive)
    - Cross-reference changed files with historical errors
    - Generate human-readable summaries for AI prompt injection
    - Cache results for 5 minutes
    """

    def __init__(self, db: Session):
        self.db = db

    # ==================== IMPACT ANALYSIS ====================

    def predict_impact(self, project_id: int, changed_files: List[str]) -> Dict[str, Any]:
        """
        Given a list of files being changed, predict which other files
        might be affected using the dependency graph.

        Returns:
            {
                "directly_affected": [...],  # files that import changed files
                "transitively_affected": [...],  # files affected through chain
                "risk_score": 0-100,  # based on how many files affected + depth
                "suggestions": [...],  # "Consider also updating X because Y"
                "circular_warnings": [...]  # if changes touch circular deps
            }
        """
        # Check cache first
        cached = self._get_cached_impact(project_id, changed_files)
        if cached:
            print(f"⚡ [Prediction] Cache hit for project {project_id}, {len(changed_files)} files")
            return cached

        graph = self._load_graph(project_id)

        # Directly affected: files that import any of the changed files
        directly_affected: set = set()
        for changed in changed_files:
            for dependent in graph.reverse_graph.get(changed, []):
                if dependent not in changed_files:
                    directly_affected.add(dependent)

        # Transitively affected: BFS through reverse_graph beyond direct
        transitively_affected: set = set()
        visited = set(changed_files) | directly_affected
        queue = list(directly_affected)
        while queue:
            current = queue.pop(0)
            for dependent in graph.reverse_graph.get(current, []):
                if dependent not in visited and dependent not in changed_files:
                    transitively_affected.add(dependent)
                    visited.add(dependent)
                    queue.append(dependent)

        # risk_score: directly × 10 + transitively × 5, capped at 100
        risk_score = min(100, len(directly_affected) * 10 + len(transitively_affected) * 5)

        # Suggestions: top 5 directly affected
        suggestions = []
        for file in sorted(directly_affected)[:5]:
            suggestions.append(
                f"Consider reviewing {file} — it directly imports a changed file"
            )

        # Circular warnings: check if changed files are part of any cycle
        cycles = graph.detect_circular_dependencies()
        circular_warnings = []
        for cycle in cycles:
            if any(f in cycle for f in changed_files):
                circular_warnings.append(
                    f"Circular dependency detected: {' → '.join(cycle)}"
                )

        result = {
            "directly_affected": sorted(directly_affected),
            "transitively_affected": sorted(transitively_affected),
            "risk_score": risk_score,
            "suggestions": suggestions,
            "circular_warnings": circular_warnings,
        }

        print(
            f"⚡ [Prediction] Impact analysis: {len(directly_affected)} direct, "
            f"{len(transitively_affected)} transitive, risk={risk_score}"
        )

        # Save to cache
        self._save_cached_impact(project_id, changed_files, result)

        return result

    # ==================== ERROR RISK ====================

    def predict_error_prone_files(
        self, project_id: int, changed_files: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Cross-reference changed files with learned_errors table.
        If a file being changed has historically had many errors,
        flag it as high-risk.

        Returns list of:
            {
                "file_path": str,
                "historical_errors": int,
                "common_error_types": [...],
                "last_solution": str or None
            }
        """
        results = []

        for file_path in changed_files:
            row = self.db.execute(
                text("""
                    SELECT
                        COUNT(*)                                              AS error_patterns,
                        SUM(occurrence_count)                                 AS total_occurrences,
                        ARRAY_AGG(DISTINCT error_type)
                            FILTER (WHERE error_type IS NOT NULL)             AS error_types,
                        MAX(solution_pattern)
                            FILTER (WHERE solution_pattern IS NOT NULL)       AS last_solution
                    FROM learned_errors
                    WHERE project_id = :project_id
                      AND file_path   = :file_path
                """),
                {"project_id": project_id, "file_path": file_path},
            ).fetchone()

            if row and row[0] and row[0] > 0:
                results.append(
                    {
                        "file_path": file_path,
                        "historical_errors": int(row[1] or row[0]),
                        "common_error_types": list(row[2]) if row[2] else [],
                        "last_solution": row[3],
                    }
                )

        print(
            f"🔍 [Prediction] Error risk: {len(results)}/{len(changed_files)} "
            f"files have historical errors"
        )
        return results

    # ==================== CHANGE SUMMARY ====================

    def get_change_summary(self, project_id: int, changed_files: List[str]) -> str:
        """
        Generate a human-readable summary for AI prompt injection.
        Combines impact analysis + error history into concise text.

        Example output:
        "⚡ PREDICTION: Changing auth.ts affects 5 files (controller.ts, index.ts...).
         auth.ts has had 3 TypeScript errors historically (fix: check import paths).
         Risk: MEDIUM (score 45/100)"
        """
        impact = self.predict_impact(project_id, changed_files)
        error_risks = self.predict_error_prone_files(project_id, changed_files)

        risk_score = impact["risk_score"]
        if risk_score >= 67:
            risk_level = "HIGH"
        elif risk_score >= 34:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        total_affected = len(impact["directly_affected"]) + len(impact["transitively_affected"])

        lines = ["\n⚡ PREDICTION ANALYSIS:\n"]

        # Impact summary
        if total_affected > 0:
            preview_files = impact["directly_affected"][:3]
            preview_str = ", ".join(preview_files)
            if total_affected > 3:
                preview_str += f"... (+{total_affected - 3} more)"

            file_label = "file" if len(changed_files) == 1 else "files"
            lines.append(
                f"Changing {len(changed_files)} {file_label} "
                f"({', '.join(changed_files[:2])}) affects {total_affected} files "
                f"({preview_str})."
            )
        else:
            lines.append(
                f"Changing {len(changed_files)} file(s) has no detected downstream impact."
            )

        # Error history
        for risk in error_risks:
            error_types_str = (
                ", ".join(risk["common_error_types"]) if risk["common_error_types"] else "unknown"
            )
            solution_str = (
                f" Fix: {risk['last_solution']}" if risk["last_solution"] else ""
            )
            lines.append(
                f"{risk['file_path']} has had {risk['historical_errors']} historical error(s) "
                f"({error_types_str}).{solution_str}"
            )

        # Circular warnings
        for warning in impact["circular_warnings"]:
            lines.append(f"⚠️ {warning}")

        # Risk level
        lines.append(f"Risk: {risk_level} (score {risk_score}/100)")

        return "\n".join(lines)

    # ==================== STATISTICS ====================

    def get_prediction_stats(self, project_id: int) -> Dict[str, Any]:
        """
        Get prediction usage statistics for a project.
        """
        history_stats = self.db.execute(
            text("""
                SELECT
                    COUNT(*)                                AS total_predictions,
                    AVG(accuracy_score)                     AS avg_accuracy,
                    MAX(created_at)                         AS last_prediction_at
                FROM prediction_history
                WHERE project_id = :project_id
            """),
            {"project_id": project_id},
        ).fetchone()

        cache_stats = self.db.execute(
            text("""
                SELECT COUNT(*) AS cached_entries
                FROM prediction_cache
                WHERE project_id = :project_id
                  AND expires_at > NOW()
            """),
            {"project_id": project_id},
        ).fetchone()

        return {
            "total_predictions": int(history_stats[0] or 0),
            "avg_accuracy": float(history_stats[1]) if history_stats[1] else None,
            "last_prediction_at": (
                history_stats[2].isoformat() if history_stats[2] else None
            ),
            "active_cache_entries": int(cache_stats[0] or 0),
        }

    # ==================== HISTORY ====================

    def save_prediction_history(
        self, project_id: int, changed_files: List[str], predicted_impact: Dict[str, Any]
    ) -> int:
        """
        Save prediction to history log.
        Returns the history entry id.
        """
        result = self.db.execute(
            text("""
                INSERT INTO prediction_history
                    (project_id, changed_files, predicted_impact, created_at)
                VALUES
                    (:project_id, :changed_files, :predicted_impact, :now)
                RETURNING id
            """),
            {
                "project_id": project_id,
                "changed_files": changed_files,
                "predicted_impact": json.dumps(predicted_impact),
                "now": datetime.now(timezone.utc),
            },
        )
        entry_id = result.fetchone()[0]
        self.db.commit()
        return entry_id

    # ==================== CACHE HELPERS ====================

    def _make_cache_key(self, changed_files: List[str]) -> str:
        """Generate stable MD5 hash for a sorted list of changed files."""
        sorted_files = sorted(changed_files)
        return hashlib.md5(json.dumps(sorted_files).encode()).hexdigest()

    def _get_cached_impact(
        self, project_id: int, changed_files: List[str]
    ) -> Optional[Dict[str, Any]]:
        """Return cached impact result if still valid, else None."""
        cache_key = self._make_cache_key(changed_files)
        row = self.db.execute(
            text("""
                SELECT result_json
                FROM prediction_cache
                WHERE project_id         = :project_id
                  AND changed_files_hash = :cache_key
                  AND expires_at         > NOW()
                LIMIT 1
            """),
            {"project_id": project_id, "cache_key": cache_key},
        ).fetchone()

        if row:
            return json.loads(row[0])
        return None

    def _save_cached_impact(
        self,
        project_id: int,
        changed_files: List[str],
        result: Dict[str, Any],
    ) -> None:
        """Upsert cached impact result with TTL of CACHE_TTL_MINUTES."""
        cache_key = self._make_cache_key(changed_files)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=CACHE_TTL_MINUTES)

        # Delete old entry if exists (simple upsert pattern)
        self.db.execute(
            text("""
                DELETE FROM prediction_cache
                WHERE project_id = :project_id AND changed_files_hash = :cache_key
            """),
            {"project_id": project_id, "cache_key": cache_key},
        )

        self.db.execute(
            text("""
                INSERT INTO prediction_cache
                    (project_id, changed_files_hash, result_json, created_at, expires_at)
                VALUES
                    (:project_id, :cache_key, :result_json, :now, :expires_at)
            """),
            {
                "project_id": project_id,
                "cache_key": cache_key,
                "result_json": json.dumps(result),
                "now": now,
                "expires_at": expires_at,
            },
        )
        self.db.commit()

    # ==================== GRAPH LOADER ====================

    def _load_graph(self, project_id: int) -> DependencyGraph:
        """Load dependency graph from DB for the given project.

        Uses file_embeddings (indexed files) as the file list — NOT
        file_specifications which is only populated by the project_builder flow.
        The dependency edges come from file_dependencies (populated by the
        file_indexer service during repository indexing).
        """
        files_result = self.db.execute(
            text("""
                SELECT file_path
                FROM file_embeddings
                WHERE project_id = :project_id
            """),
            {"project_id": project_id},
        ).fetchall()
        files = [row[0] for row in files_result]

        deps_result = self.db.execute(
            text("""
                SELECT source_file, target_file
                FROM file_dependencies
                WHERE project_id = :project_id
            """),
            {"project_id": project_id},
        ).fetchall()
        dependencies = [(row[0], row[1]) for row in deps_result]

        print(
            f"📊 [Prediction] Loaded {len(files)} files, "
            f"{len(dependencies)} deps for project {project_id}"
        )
        return build_dependency_graph(files, dependencies)
