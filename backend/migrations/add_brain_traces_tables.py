#!/usr/bin/env python3
"""
Migration: Add brain_traces and brain_trace_spans tables.

brain_traces  — one row per request (trace_id, kind, status, cost, duration).
brain_trace_spans — ordered spans within a trace (layer, name, status, cost, duration).

Crash-proof and idempotent: safe to run on every boot.
Always exits 0.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import create_engine, text


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
            url = os.environ.get("DATABASE_URL", "")
        except ImportError:
            pass
    if not url:
        url = f"sqlite:///{os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'memory.db'))}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _is_pg(url: str) -> bool:
    return url.startswith("postgresql")


def _table_exists(conn, name: str, pg: bool) -> bool:
    if pg:
        r = conn.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:n)"
        ), {"n": name})
    else:
        r = conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:n"
        ), {"n": name})
    return bool(r.scalar())


def _index_exists(conn, name: str, pg: bool) -> bool:
    if pg:
        r = conn.execute(text(
            "SELECT EXISTS (SELECT FROM pg_indexes WHERE indexname=:n)"
        ), {"n": name})
    else:
        r = conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=:n"
        ), {"n": name})
    return bool(r.scalar())


def run_migration() -> None:
    print("Migration: add_brain_traces_tables")
    url = _db_url()
    pg = _is_pg(url)
    engine = create_engine(url)

    with engine.connect() as conn:
        # ── brain_traces ─────────────────────────────────────────────────────
        if _table_exists(conn, "brain_traces", pg):
            print("  brain_traces already exists — skipping CREATE")
        else:
            print("  creating brain_traces")
            if pg:
                conn.execute(text("""
                    CREATE TABLE brain_traces (
                        id              SERIAL PRIMARY KEY,
                        trace_id        TEXT NOT NULL,
                        kind            TEXT NOT NULL,
                        summary         TEXT,
                        status          TEXT NOT NULL DEFAULT 'ok',
                        total_cost_usd  FLOAT,
                        total_ms        INTEGER,
                        created_at      TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE brain_traces (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id        TEXT NOT NULL,
                        kind            TEXT NOT NULL,
                        summary         TEXT,
                        status          TEXT NOT NULL DEFAULT 'ok',
                        total_cost_usd  REAL,
                        total_ms        INTEGER,
                        created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            conn.commit()
            print("  brain_traces created")

        # ── brain_trace_spans ────────────────────────────────────────────────
        if _table_exists(conn, "brain_trace_spans", pg):
            print("  brain_trace_spans already exists — skipping CREATE")
        else:
            print("  creating brain_trace_spans")
            if pg:
                conn.execute(text("""
                    CREATE TABLE brain_trace_spans (
                        id              SERIAL PRIMARY KEY,
                        trace_id        TEXT NOT NULL,
                        seq             INTEGER NOT NULL,
                        layer           TEXT NOT NULL,
                        name            TEXT NOT NULL,
                        status          TEXT NOT NULL DEFAULT 'ok',
                        input_summary   TEXT,
                        output_summary  TEXT,
                        error           TEXT,
                        model_key       TEXT,
                        cost_usd        FLOAT,
                        duration_ms     INTEGER,
                        created_at      TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE brain_trace_spans (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id        TEXT NOT NULL,
                        seq             INTEGER NOT NULL,
                        layer           TEXT NOT NULL,
                        name            TEXT NOT NULL,
                        status          TEXT NOT NULL DEFAULT 'ok',
                        input_summary   TEXT,
                        output_summary  TEXT,
                        error           TEXT,
                        model_key       TEXT,
                        cost_usd        REAL,
                        duration_ms     INTEGER,
                        created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            conn.commit()
            print("  brain_trace_spans created")

        # ── indexes ──────────────────────────────────────────────────────────
        indexes = [
            ("ix_brain_traces_trace_id",   "brain_traces(trace_id)"),
            ("ix_brain_traces_kind",        "brain_traces(kind)"),
            ("ix_brain_traces_created_at",  "brain_traces(created_at)"),
            ("ix_brain_spans_trace_id",     "brain_trace_spans(trace_id)"),
            ("ix_brain_spans_seq",          "brain_trace_spans(trace_id, seq)"),
        ]
        for idx_name, idx_expr in indexes:
            if not _index_exists(conn, idx_name, pg):
                try:
                    conn.execute(text(f"CREATE INDEX {idx_name} ON {idx_expr}"))
                    conn.commit()
                    print(f"  index {idx_name} created")
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    print(f"  index {idx_name} skipped: {e}")
            else:
                print(f"  index {idx_name} already exists")

    print("Migration add_brain_traces_tables: done")


if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"Migration add_brain_traces_tables failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()
    sys.exit(0)
