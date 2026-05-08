#!/usr/bin/env python3
"""
Migration: Add brain_skills table

Purpose: Skills library — reusable instruction snippets the model can call
         via MCP tools (get_skill, list_skills, save_skill).
Date: 2026-05-08
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


SEED_SKILLS = [
    {
        "name": "startup",
        "description": "Session-start checklist: load project, patterns, recent summaries.",
        "category": "workflow",
        "content": (
            "At the start of a new session, call these in order:\n"
            "  1. brain get_active_project — confirm project_id and name\n"
            "  2. brain get_session_summaries project=<id> limit=3 — recall recent work\n"
            "  3. brain get_developer_patterns query=\"<topic of current task>\" — reuse known patterns\n"
            "  4. brain build_context_for_query query=\"<user question>\" — gather targeted context\n"
            "\n"
            "Then proceed with the user's request. Skip any step that is clearly irrelevant\n"
            "to the task at hand (e.g. patterns for a one-line typo fix)."
        ),
    },
    {
        "name": "commit-deploy",
        "description": "Standard commit + push + Railway deploy wait.",
        "category": "deploy",
        "content": (
            "Standard commit + deploy flow:\n"
            "  1. git status — review what is staged vs unstaged\n"
            "  2. git add <specific files>  (avoid 'git add -A' to skip secrets/binaries)\n"
            "  3. git commit -m \"<type>(<scope>): <subject>\\n\\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>\"\n"
            "     - types: feat, fix, refactor, docs, chore, test\n"
            "     - keep subject under 72 chars, focus on the WHY\n"
            "  4. git push origin <branch>\n"
            "  5. If branch is main: Railway auto-deploys. Wait ~2-3 min for build.\n"
            "     Check Railway logs or hit /healthz to confirm the new revision is live.\n"
            "\n"
            "Never skip hooks (--no-verify) unless the user asks. Never amend a previous\n"
            "commit unless explicitly told."
        ),
    },
    {
        "name": "session-end",
        "description": "Save a session summary covering fixes, decisions, and next steps.",
        "category": "workflow",
        "content": (
            "At session end (or when context is getting long), call:\n"
            "  brain save_session_summary project_id=<id> content=\"<markdown body>\" topics=[...]\n"
            "\n"
            "Body structure:\n"
            "  ## Session YYYY-MM-DD — <one-line theme>\n"
            "  ### Bugs fixed\n"
            "    - <bug>: <root cause> → <fix> (commit <sha>)\n"
            "  ### Decisions\n"
            "    - <decision> — Why: <rationale>\n"
            "  ### Next steps\n"
            "    - <follow-up> (owner / blocker)\n"
            "\n"
            "Topics: short tags for retrieval, e.g. [\"auth\", \"migration\", \"FastAPI\"].\n"
            "Body is capped at 8000 chars server-side — be concise."
        ),
    },
]


def run_migration():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    print("🔧 Starting migration: add_skills_table")
    print(f"📊 Database: {database_url.split('@')[1] if '@' in database_url else 'localhost'}")

    try:
        engine = create_engine(database_url)
        with engine.connect() as conn:
            check_table = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'brain_skills'
                );
            """)
            table_exists = conn.execute(check_table).scalar()

            if not table_exists:
                print("📝 Creating table 'brain_skills'...")
                conn.execute(text("""
                    CREATE TABLE brain_skills (
                        id          SERIAL PRIMARY KEY,
                        name        VARCHAR(100) NOT NULL UNIQUE,
                        description TEXT,
                        content     TEXT NOT NULL,
                        category    VARCHAR(20) NOT NULL,
                        created_at  TIMESTAMP DEFAULT NOW(),
                        updated_at  TIMESTAMP DEFAULT NOW(),
                        CONSTRAINT valid_skill_category
                            CHECK (category IN ('workflow', 'coding', 'deploy', 'debug', 'review'))
                    );
                """))
                conn.commit()
                print("✅ Table created")

                for index_name, column in [
                    ("idx_brain_skills_name",     "name"),
                    ("idx_brain_skills_category", "category"),
                ]:
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} ON brain_skills({column});"
                    ))
                    print(f"  ✅ Index '{index_name}' created")
                conn.commit()

                conn.execute(text(
                    "COMMENT ON TABLE brain_skills IS "
                    "'Reusable instruction snippets surfaced via MCP get_skill/list_skills/save_skill'"
                ))
                conn.commit()
            else:
                print("✅ Table 'brain_skills' already exists. Skipping create.")

            print("🌱 Seeding default skills (idempotent)...")
            inserted = 0
            for skill in SEED_SKILLS:
                row = conn.execute(
                    text("""
                        INSERT INTO brain_skills (name, description, content, category)
                        VALUES (:name, :description, :content, :category)
                        ON CONFLICT (name) DO NOTHING
                        RETURNING id
                    """),
                    skill,
                ).fetchone()
                if row:
                    inserted += 1
                    print(f"  ✅ inserted '{skill['name']}'")
                else:
                    print(f"  ⏭️  '{skill['name']}' already present, left as-is")
            conn.commit()
            print(f"🌱 Seed complete — {inserted}/{len(SEED_SKILLS)} new rows")

            print("\n🎉 Migration completed successfully!")

    except ProgrammingError as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()
