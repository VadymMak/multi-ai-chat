#!/usr/bin/env python3
"""
Migration: Add knowledge_entities and knowledge_relationships tables

knowledge_entities — stores extracted architectural knowledge per project
  (frameworks, libraries, patterns, decisions, components, style approaches)
  with pgvector embeddings for semantic search.

knowledge_relationships — stores typed edges between entities
  (uses, extends, depends_on, preferred_with, replaces).

Usage:
    python backend/migrations/add_knowledge_graph.py

Safe to run multiple times (idempotent).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text


def get_database_url():
    """Get database URL from environment"""
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        try:
            from dotenv import load_dotenv
            env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
            load_dotenv(env_path)
            database_url = os.environ.get("DATABASE_URL")
        except ImportError:
            pass

    if not database_url:
        print("❌ DATABASE_URL not found in environment")
        sys.exit(1)

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url


def run_migration():
    """Run the knowledge graph migration"""
    print("🚀 Starting migration: add_knowledge_graph")

    database_url = get_database_url()
    engine = create_engine(database_url)

    with engine.connect() as conn:

        # ============================================================
        # Step 1: Ensure pgvector extension exists
        # ============================================================
        print("  📦 Checking pgvector extension...")
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            print("  ✅ pgvector extension ready")
        except Exception as e:
            print(f"  ⚠️ pgvector extension check: {e}")

        # ============================================================
        # Step 2: knowledge_entities table
        # ============================================================
        print("  📋 Checking if knowledge_entities table exists...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'knowledge_entities'
            )
        """))
        ke_exists = result.scalar()

        if ke_exists:
            print("  ℹ️ Table knowledge_entities already exists, skipping creation")
        else:
            print("  📝 Creating knowledge_entities table...")
            conn.execute(text("""
                CREATE TABLE knowledge_entities (
                    id          SERIAL PRIMARY KEY,

                    -- Project reference
                    project_id  INTEGER NOT NULL
                                REFERENCES projects(id) ON DELETE CASCADE,

                    -- Entity classification
                    -- Allowed: 'framework', 'library', 'pattern',
                    --          'architectural_decision', 'component', 'style_approach'
                    entity_type VARCHAR(50) NOT NULL,

                    -- Human-readable identity
                    name        VARCHAR(255) NOT NULL,
                    description TEXT,

                    -- Origin file (nullable — may be inferred from multiple files)
                    source_file TEXT,

                    -- Semantic embedding (text-embedding-3-small, 1536 dims)
                    embedding   vector(1536),

                    -- Flexible extra data (tags, confidence, etc.)
                    metadata    JSONB DEFAULT '{}',

                    created_at  TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
            print("  ✅ Table knowledge_entities created")

        # ============================================================
        # Step 3: knowledge_relationships table
        # ============================================================
        print("  📋 Checking if knowledge_relationships table exists...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'knowledge_relationships'
            )
        """))
        kr_exists = result.scalar()

        if kr_exists:
            print("  ℹ️ Table knowledge_relationships already exists, skipping creation")
        else:
            print("  📝 Creating knowledge_relationships table...")
            conn.execute(text("""
                CREATE TABLE knowledge_relationships (
                    id                  SERIAL PRIMARY KEY,

                    -- Directed edge
                    from_entity_id      INTEGER NOT NULL
                                        REFERENCES knowledge_entities(id) ON DELETE CASCADE,
                    to_entity_id        INTEGER NOT NULL
                                        REFERENCES knowledge_entities(id) ON DELETE CASCADE,

                    -- Edge classification
                    -- Allowed: 'uses', 'extends', 'depends_on', 'preferred_with', 'replaces'
                    relationship_type   VARCHAR(50) NOT NULL,

                    -- Edge weight in [0, 1]
                    strength            FLOAT DEFAULT 1.0,

                    -- Denormalised for fast project-scoped queries
                    project_id          INTEGER NOT NULL
                                        REFERENCES projects(id) ON DELETE CASCADE,

                    created_at          TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
            print("  ✅ Table knowledge_relationships created")

        # ============================================================
        # Step 4: Indexes
        # ============================================================
        print("  📊 Creating indexes...")

        indexes = [
            (
                "idx_ke_project",
                "CREATE INDEX idx_ke_project ON knowledge_entities(project_id)",
            ),
            (
                "idx_ke_type",
                "CREATE INDEX idx_ke_type ON knowledge_entities(entity_type)",
            ),
            (
                "idx_kr_from",
                "CREATE INDEX idx_kr_from ON knowledge_relationships(from_entity_id)",
            ),
            (
                "idx_kr_to",
                "CREATE INDEX idx_kr_to ON knowledge_relationships(to_entity_id)",
            ),
        ]

        for idx_name, idx_sql in indexes:
            # Check if index already exists before creating
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = :idx_name
                )
            """), {"idx_name": idx_name})
            if result.scalar():
                print(f"  ℹ️ Index {idx_name} already exists, skipping")
                continue
            try:
                conn.execute(text(idx_sql))
                conn.commit()
                print(f"  ✅ Index {idx_name} created")
            except Exception as e:
                print(f"  ⚠️ Index {idx_name}: {e}")

        # ============================================================
        # Step 5: Vector index on knowledge_entities.embedding
        # ============================================================
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_ke_embedding'
            )
        """))
        if result.scalar():
            print("  ℹ️ Vector index idx_ke_embedding already exists, skipping")
        else:
            try:
                conn.execute(text("""
                    CREATE INDEX idx_ke_embedding
                    ON knowledge_entities USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """))
                conn.commit()
                print("  ✅ Vector index idx_ke_embedding created")
            except Exception as e:
                print(f"  ⚠️ Vector index idx_ke_embedding: {e}")

        # ============================================================
        # Step 6: UNIQUE constraint on knowledge_entities(project_id, name, entity_type)
        # ============================================================
        print("  🔑 Checking unique constraint uq_ke_project_name_type...")
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_ke_project_name_type'
            )
        """))
        if result.scalar():
            print("  ℹ️ Unique constraint uq_ke_project_name_type already exists, skipping")
        else:
            try:
                conn.execute(text("""
                    ALTER TABLE knowledge_entities
                    ADD CONSTRAINT uq_ke_project_name_type
                    UNIQUE (project_id, name, entity_type)
                """))
                conn.commit()
                print("  ✅ Unique constraint uq_ke_project_name_type created")
            except Exception as e:
                print(f"  ⚠️ Unique constraint uq_ke_project_name_type: {e}")

        print("🎉 Migration completed successfully!")
        return True


def verify_migration():
    """Verify the migration was applied correctly"""
    print("\n🔍 Verifying migration...")

    database_url = get_database_url()
    engine = create_engine(database_url)

    with engine.connect() as conn:
        all_ok = True

        for table in ("knowledge_entities", "knowledge_relationships"):
            result = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = :t
            """), {"t": table})
            if result.scalar() == 0:
                print(f"  ❌ Table {table} does not exist!")
                all_ok = False
            else:
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_name = :t
                """), {"t": table})
                col_count = result.scalar()
                print(f"  ✅ Table {table} exists ({col_count} columns)")

        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_ke_project_name_type'
            )
        """))
        if result.scalar():
            print("  ✅ Unique constraint uq_ke_project_name_type present")
        else:
            print("  ⚠️ Unique constraint uq_ke_project_name_type missing")

        for idx in ("idx_ke_project", "idx_ke_type", "idx_kr_from", "idx_kr_to", "idx_ke_embedding"):
            result = conn.execute(text("""
                SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :i)
            """), {"i": idx})
            if result.scalar():
                print(f"  ✅ Index {idx} present")
            else:
                print(f"  ⚠️ Index {idx} missing")

        if all_ok:
            print("\n✅ Migration verified successfully!")
        else:
            print("\n❌ Verification found issues — check output above")
        return all_ok


if __name__ == "__main__":
    try:
        success = run_migration()
        if success:
            verify_migration()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
