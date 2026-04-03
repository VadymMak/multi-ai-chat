"""
Pattern Analyzer Service — categorizes errors and finds cross-project solutions.
File: backend/app/services/pattern_analyzer.py
"""
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone
import json
import re


def _normalize_pattern(pattern: str) -> str:
    """
    Normalize error pattern for cross-project fuzzy matching.
    Mirrors AutoLearningService._normalize_error_pattern logic.
    """
    pattern = re.sub(r"'\./[^']+'", "'./MODULE'", pattern)
    pattern = re.sub(r"'[^']+'", "'X'", pattern)
    pattern = re.sub(r"line \d+", "line N", pattern)
    pattern = re.sub(r"type '([A-Z][a-zA-Z]+)'", "type 'T'", pattern)
    return pattern


def _suggested_action(error_type: Optional[str]) -> str:
    """Return a suggested action string based on error type."""
    mapping = {
        "import": "Consider adding path aliases in tsconfig to prevent import errors",
        "type":   "Add explicit type annotations or type guards",
        "lint":   "Add an ESLint rule to enforce this pattern project-wide",
        "syntax": "Review code structure — syntax errors often signal a larger refactor need",
    }
    return mapping.get(error_type or "", "Review and document the root cause to prevent recurrence")


class PatternAnalyzer:
    """
    Analyzes learned error patterns across one or all projects.

    Features:
    - Categorize errors by type with resolution statistics
    - Detect recurring "zombie" errors that keep coming back after fixes
    - Search other projects for solutions to unsolved error patterns
    - Generate concise learning insights for AI prompt injection
    """

    def __init__(self, db: Session):
        self.db = db

    # ==================== CATEGORIZATION ====================

    def categorize_errors(self, project_id: int) -> Dict[str, Any]:
        """
        Group all learned_errors for a project into categories based on error_type.

        Checks error_categories cache first (1-hour TTL).
        On cache miss: queries learned_errors, groups by error_type, writes cache.

        Returns:
            {
                "categories": {
                    "import": {"count": 5, "resolved": 3, "top_files": ["auth.ts", "index.ts"]},
                    "type":   {"count": 8, "resolved": 2, "top_files": ["types.ts"]},
                    ...
                },
                "most_problematic_category": "type",
                "overall_resolution_rate": 0.45
            }
        """
        # --- Try cache ---
        cached = self._get_cached_categories(project_id)
        if cached:
            print(f"🗂️ [PatternAnalyzer] Cache hit for categories project={project_id}")
            return cached

        # --- Query summary per error_type ---
        rows = self.db.execute(
            text("""
                SELECT
                    COALESCE(error_type, 'other')                                     AS category,
                    COUNT(*)                                                           AS error_count,
                    SUM(occurrence_count)                                              AS total_occurrences,
                    SUM(resolved_count)                                                AS total_resolved,
                    ARRAY_AGG(DISTINCT file_path)
                        FILTER (WHERE file_path IS NOT NULL)                           AS files
                FROM learned_errors
                WHERE project_id = :project_id
                GROUP BY COALESCE(error_type, 'other')
                ORDER BY SUM(occurrence_count) DESC
            """),
            {"project_id": project_id},
        ).fetchall()

        categories: Dict[str, Any] = {}
        total_occurrences = 0
        total_resolved = 0
        most_problematic = None
        most_problematic_count = 0

        for row in rows:
            category      = row[0]
            error_count   = int(row[1] or 0)
            occurrences   = int(row[2] or 0)
            resolved      = int(row[3] or 0)
            files         = list(row[4])[:3] if row[4] else []

            categories[category] = {
                "count":     error_count,
                "resolved":  resolved,
                "top_files": files,
            }

            total_occurrences += occurrences
            total_resolved    += resolved

            if occurrences > most_problematic_count:
                most_problematic_count = occurrences
                most_problematic       = category

        overall_rate = round(total_resolved / total_occurrences, 4) if total_occurrences > 0 else 0.0

        result: Dict[str, Any] = {
            "categories":               categories,
            "most_problematic_category": most_problematic,
            "overall_resolution_rate":   overall_rate,
        }

        print(
            f"🗂️ [PatternAnalyzer] Categorized {len(categories)} error types "
            f"for project {project_id} (rate={overall_rate:.0%})"
        )

        # --- Write cache ---
        self._save_cached_categories(project_id, categories)

        return result

    # ==================== RECURRING PATTERNS ====================

    def find_recurring_patterns(
        self, project_id: int, min_occurrences: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Find errors where occurrence_count >= min_occurrences AND resolved_count > 0
        but the error keeps coming back (recurrence_ratio > 2).

        These are "zombie errors" — fixed multiple times but never truly resolved.

        Returns list of:
            {
                "error_id", "pattern", "error_type", "occurrence_count",
                "resolved_count", "recurrence_ratio", "file_path", "suggested_action"
            }
        """
        rows = self.db.execute(
            text("""
                SELECT
                    id,
                    error_pattern,
                    error_type,
                    occurrence_count,
                    resolved_count,
                    file_path,
                    (occurrence_count::float / GREATEST(resolved_count, 1)) AS recurrence_ratio
                FROM learned_errors
                WHERE project_id       = :project_id
                  AND occurrence_count >= :min_occurrences
                  AND resolved_count   >  0
                ORDER BY recurrence_ratio DESC
                LIMIT 10
            """),
            {"project_id": project_id, "min_occurrences": min_occurrences},
        ).fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows:
            ratio = round(float(row[6]), 2)
            results.append(
                {
                    "error_id":         int(row[0]),
                    "pattern":          row[1],
                    "error_type":       row[2],
                    "occurrence_count": int(row[3]),
                    "resolved_count":   int(row[4]),
                    "file_path":        row[5],
                    "recurrence_ratio": ratio,
                    "suggested_action": _suggested_action(row[2]),
                }
            )

        print(
            f"🔁 [PatternAnalyzer] Found {len(results)} recurring patterns "
            f"for project {project_id} (min={min_occurrences})"
        )
        return results

    # ==================== CROSS-PROJECT SEARCH ====================

    def cross_project_search(
        self, error_pattern: str, exclude_project_id: int
    ) -> List[Dict[str, Any]]:
        """
        Search all projects (except exclude_project_id) for similar errors
        that already have a solution_pattern.

        Uses ILIKE with both the original and normalized pattern.
        Joins with the projects table to return the project name.

        Returns list of:
            {
                "project_id", "project_name", "error_pattern",
                "solution_pattern", "solution_example",
                "occurrence_count", "resolved_count"
            }
        """
        normalized = _normalize_pattern(error_pattern)

        # Build ILIKE search term — match any substring
        def _ilike(p: str) -> str:
            return f"%{p[:80]}%"  # cap length for safety

        rows = self.db.execute(
            text("""
                SELECT
                    le.project_id,
                    p.name          AS project_name,
                    le.error_pattern,
                    le.solution_pattern,
                    le.solution_example,
                    le.occurrence_count,
                    le.resolved_count
                FROM learned_errors le
                JOIN projects p ON p.id = le.project_id
                WHERE le.project_id      != :exclude_project_id
                  AND le.solution_pattern IS NOT NULL
                  AND (
                      le.error_pattern ILIKE :raw_pattern
                      OR le.error_pattern ILIKE :norm_pattern
                  )
                ORDER BY le.resolved_count DESC
                LIMIT 5
            """),
            {
                "exclude_project_id": exclude_project_id,
                "raw_pattern":        _ilike(error_pattern),
                "norm_pattern":       _ilike(normalized),
            },
        ).fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "project_id":      int(row[0]),
                    "project_name":    row[1],
                    "error_pattern":   row[2],
                    "solution_pattern": row[3],
                    "solution_example": row[4],
                    "occurrence_count": int(row[5]),
                    "resolved_count":   int(row[6]),
                }
            )

        print(
            f"🌐 [PatternAnalyzer] Cross-project search: {len(results)} solutions found "
            f"(excluded project {exclude_project_id})"
        )
        return results

    # ==================== INSIGHTS ====================

    def generate_project_insights(self, project_id: int) -> str:
        """
        Combine categorize_errors + find_recurring_patterns into a compact string
        suitable for AI prompt injection (target: under 500 chars).

        Returns empty string if no data.
        """
        try:
            categorized  = self.categorize_errors(project_id)
            recurring    = self.find_recurring_patterns(project_id, min_occurrences=3)
        except Exception as e:
            print(f"❌ [PatternAnalyzer] Insights failed: {e}")
            return ""

        categories = categorized.get("categories", {})
        if not categories:
            return ""

        lines = ["🧠 PROJECT LEARNING INSIGHTS:"]

        # Most problematic category
        top_cat  = categorized.get("most_problematic_category")
        if top_cat and top_cat in categories:
            info = categories[top_cat]
            rate = (
                round(info["resolved"] / info["count"] * 100)
                if info["count"] > 0 else 0
            )
            lines.append(
                f"- Most common: {top_cat} errors "
                f"({info['count']} occurrences, {rate}% resolved)"
            )

        # Overall resolution rate
        overall = categorized.get("overall_resolution_rate", 0)
        lines.append(f"- Overall fix rate: {overall:.0%}")

        # Top recurring pattern
        if recurring:
            top = recurring[0]
            file_hint = f" in {top['file_path']}" if top["file_path"] else ""
            lines.append(
                f"- Recurring: '{top['pattern'][:60]}'{file_hint} "
                f"(seen {top['occurrence_count']}x, fixed {top['resolved_count']}x)"
            )
            lines.append(f"- Tip: {top['suggested_action']}")

        result = "\n".join(lines)

        # Trim to 500 chars if needed
        if len(result) > 500:
            result = result[:497] + "..."

        return result

    # ==================== CACHE HELPERS ====================

    def _get_cached_categories(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Return cached category data if analysed within the last hour, else None."""
        try:
            rows = self.db.execute(
                text("""
                    SELECT category_name, error_count, resolved_count, top_files
                    FROM error_categories
                    WHERE project_id       = :project_id
                      AND last_analyzed_at > NOW() - INTERVAL '1 hour'
                """),
                {"project_id": project_id},
            ).fetchall()
        except Exception:
            # Table may not exist yet
            return None

        if not rows:
            return None

        categories: Dict[str, Any] = {}
        total_count    = 0
        total_resolved = 0
        most_problematic = None
        most_count = 0

        for row in rows:
            name     = row[0]
            count    = int(row[1] or 0)
            resolved = int(row[2] or 0)
            files    = json.loads(row[3]) if row[3] else []

            categories[name] = {
                "count":     count,
                "resolved":  resolved,
                "top_files": files,
            }
            total_count    += count
            total_resolved += resolved

            if count > most_count:
                most_count       = count
                most_problematic = name

        overall_rate = round(total_resolved / total_count, 4) if total_count > 0 else 0.0

        return {
            "categories":               categories,
            "most_problematic_category": most_problematic,
            "overall_resolution_rate":   overall_rate,
        }

    def _save_cached_categories(
        self, project_id: int, categories: Dict[str, Any]
    ) -> None:
        """Upsert category analysis into error_categories cache table."""
        try:
            # Delete stale entries
            self.db.execute(
                text("DELETE FROM error_categories WHERE project_id = :project_id"),
                {"project_id": project_id},
            )

            now = datetime.now(timezone.utc)
            for name, info in categories.items():
                self.db.execute(
                    text("""
                        INSERT INTO error_categories
                            (project_id, category_name, error_count, resolved_count,
                             top_files, last_analyzed_at)
                        VALUES
                            (:project_id, :name, :count, :resolved, :files, :now)
                    """),
                    {
                        "project_id": project_id,
                        "name":       name,
                        "count":      info["count"],
                        "resolved":   info["resolved"],
                        "files":      json.dumps(info["top_files"]),
                        "now":        now,
                    },
                )

            self.db.commit()
        except Exception as e:
            print(f"⚠️ [PatternAnalyzer] Cache write failed (table may not exist yet): {e}")
            try:
                self.db.rollback()
            except Exception:
                pass
