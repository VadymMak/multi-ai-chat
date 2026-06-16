#!/usr/bin/env python3
"""
Migration: Add telegram_chat_history table

Stores per-user conversation history for the Telegram AI chat mode
(triggered by "ответь" / "/chat").  Used to provide multi-turn context
to the AI provider on each turn.

Safe to run multiple times (idempotent).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent.parent / ".env")
            url = os.environ.get("DATABASE_URL", "")
        except ImportError:
            pass
    if not url:
        print("❌ DATABASE_URL not found")
        sys.exit(1)
    return url.replace("postgres://", "postgresql://", 1)


def run_migration() -> bool:
    print("🚀 Starting migration: add_telegram_chat_history")
    engine = create_engine(get_database_url())

    with engine.connect() as conn:
        # ── Table ────────────────────────────────────────────────
        exists = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name   = 'telegram_chat_history'
            )
        """)).scalar()

        if exists:
            print("  ℹ️  Table telegram_chat_history already exists — skipping CREATE")
        else:
            print("  📝 Creating telegram_chat_history table...")
            conn.execute(text("""
                CREATE TABLE telegram_chat_history (
                    id          BIGSERIAL PRIMARY KEY,
                    tg_user_id  BIGINT    NOT NULL,
                    role        TEXT      NOT NULL,
                    content     TEXT      NOT NULL,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
            conn.commit()
            print("  ✅ Table telegram_chat_history created")

        # ── Index on (tg_user_id, created_at DESC) ───────────────
        idx_exists = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'telegram_chat_history'
                  AND indexname  = 'ix_tg_chat_history_user_time'
            )
        """)).scalar()

        if idx_exists:
            print("  ℹ️  Index ix_tg_chat_history_user_time already exists")
        else:
            print("  📊 Creating index on (tg_user_id, created_at DESC)...")
            conn.execute(text("""
                CREATE INDEX ix_tg_chat_history_user_time
                    ON telegram_chat_history(tg_user_id, created_at DESC)
            """))
            conn.commit()
            print("  ✅ Index created")

    print("🎉 Migration add_telegram_chat_history completed")
    return True


def verify_migration() -> bool:
    print("\n🔍 Verifying migration...")
    engine = create_engine(get_database_url())
    with engine.connect() as conn:
        ok = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'telegram_chat_history'
            )
        """)).scalar()
        if ok:
            print("  ✅ Table telegram_chat_history exists")
        else:
            print("  ❌ Table telegram_chat_history missing!")
        return bool(ok)


if __name__ == "__main__":
    try:
        if run_migration():
            verify_migration()
    except Exception as exc:
        import traceback
        print(f"\n❌ Migration failed: {exc}")
        traceback.print_exc()
        sys.exit(1)
