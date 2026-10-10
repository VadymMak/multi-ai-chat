"""
Tests for the auto-learning write path:
  1. AutoLearningService.report_error — new error (insert) path
  2. AutoLearningService.report_error — dedup (update) path
  3. AutoLearningService.report_fix   — marks error resolved
  4. Smoke test: record_error / record_fix are registered in mcp_server
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, call
import pytest

from app.services.auto_learning import AutoLearningService


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _mock_db_for_new_error(new_id: int = 7) -> MagicMock:
    """DB session that returns no existing row → triggers INSERT path."""
    db = MagicMock()
    select_result = MagicMock()
    select_result.fetchone.return_value = None          # no existing row

    insert_result = MagicMock()
    insert_result.fetchone.return_value = (new_id,)     # RETURNING id

    db.execute.side_effect = [select_result, insert_result]
    return db


def _mock_db_for_existing_error(error_id: int = 3, count: int = 4) -> MagicMock:
    """DB session that returns an existing row → triggers UPDATE path."""
    db = MagicMock()
    existing_row = (error_id, count)                    # (id, occurrence_count)

    select_result = MagicMock()
    select_result.fetchone.return_value = existing_row

    update_result = MagicMock()
    db.execute.side_effect = [select_result, update_result]
    return db


# ─────────────────────────────────────────────────────────────────
# report_error — new error
# ─────────────────────────────────────────────────────────────────

def test_report_error_new_returns_correct_shape():
    db = _mock_db_for_new_error(new_id=42)
    svc = AutoLearningService(db)

    result = svc.report_error(
        project_id=20,
        error_pattern="Cannot find module './UserService'",
        error_type="import",
        error_code="TS2307",
    )

    assert result["is_new"] is True
    assert result["error_id"] == 42
    assert result["occurrence_count"] == 1
    db.commit.assert_called_once()


def test_report_error_new_fires_two_execute_calls():
    """SELECT then INSERT — exactly two DB round-trips."""
    db = _mock_db_for_new_error()
    AutoLearningService(db).report_error(
        project_id=20,
        error_pattern="Cannot find module './foo'",
        error_type="import",
    )
    assert db.execute.call_count == 2


# ─────────────────────────────────────────────────────────────────
# report_error — dedup path
# ─────────────────────────────────────────────────────────────────

def test_report_error_dedup_increments_count():
    db = _mock_db_for_existing_error(error_id=5, count=3)
    svc = AutoLearningService(db)

    result = svc.report_error(
        project_id=20,
        error_pattern="Cannot find module './foo'",
        error_type="import",
    )

    assert result["is_new"] is False
    assert result["error_id"] == 5
    assert result["occurrence_count"] == 4   # 3 + 1


def test_report_error_dedup_fires_two_execute_calls():
    """SELECT then UPDATE — exactly two DB round-trips (no INSERT)."""
    db = _mock_db_for_existing_error()
    AutoLearningService(db).report_error(
        project_id=20,
        error_pattern="Cannot find module './foo'",
        error_type="import",
    )
    assert db.execute.call_count == 2


# ─────────────────────────────────────────────────────────────────
# report_fix — marks resolved
# ─────────────────────────────────────────────────────────────────

def test_report_fix_returns_true_on_success():
    db = MagicMock()
    db.execute.return_value = MagicMock()    # UPDATE + optional INSERT

    svc = AutoLearningService(db)
    success = svc.report_fix(
        error_id=42,
        solution_pattern="Add @types/node to devDependencies",
        fix_method="ai_edit",
        fixed_code='npm install --save-dev @types/node',
    )

    assert success is True
    db.commit.assert_called_once()


def test_report_fix_calls_update_execute():
    """Must fire at least one execute (UPDATE resolved_count)."""
    db = MagicMock()
    db.execute.return_value = MagicMock()

    AutoLearningService(db).report_fix(
        error_id=1,
        solution_pattern="fix it",
    )

    assert db.execute.call_count >= 1


def test_report_fix_returns_false_on_db_error():
    db = MagicMock()
    db.execute.side_effect = Exception("DB connection lost")

    svc = AutoLearningService(db)
    success = svc.report_fix(error_id=99, solution_pattern="any fix")

    assert success is False
    db.rollback.assert_called_once()


# ─────────────────────────────────────────────────────────────────
# Smoke test — MCP tool registration
# ─────────────────────────────────────────────────────────────────

def test_record_error_is_registered_in_mcp():
    """record_error must be an async callable exported from mcp_server.
    Skipped when the `mcp` package is not installed locally (CI-only dep)."""
    import asyncio
    mcp_server = pytest.importorskip(
        "app.mcp_server",
        reason="mcp package not installed in this environment",
    )
    assert hasattr(mcp_server, "record_error"), "record_error not found in mcp_server"
    assert asyncio.iscoroutinefunction(mcp_server.record_error), \
        "record_error must be an async function"


def test_record_fix_is_registered_in_mcp():
    """record_fix must be an async callable exported from mcp_server.
    Skipped when the `mcp` package is not installed locally (CI-only dep)."""
    import asyncio
    mcp_server = pytest.importorskip(
        "app.mcp_server",
        reason="mcp package not installed in this environment",
    )
    assert hasattr(mcp_server, "record_fix"), "record_fix not found in mcp_server"
    assert asyncio.iscoroutinefunction(mcp_server.record_fix), \
        "record_fix must be an async function"
