"""
Knowledge Extractor Service

Analyzes indexed files and extracts architectural patterns into
knowledge_entities and knowledge_relationships tables.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.memory.db import SessionLocal
from app.services.vector_service import create_embedding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenAI client (lazy, mirrors vector_service pattern)
# ---------------------------------------------------------------------------

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        from app.config.settings import settings
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        _client = OpenAI(
            api_key=api_key,
            http_client=httpx.Client(
                timeout=httpx.Timeout(60.0, connect=10.0),
                trust_env=False,
            ),
        )
    return _client


def _open_db() -> Session:
    """Return a new SQLAlchemy Session. Caller is responsible for closing it."""
    return SessionLocal()


# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = """\
Analyze this {language} code file and extract:
1. Frameworks/libraries used (Next.js, React, FastAPI, etc.)
2. Architectural patterns (CSS Modules, REST API, pgvector, etc.)
3. Key components/classes defined
4. Style approaches (Tailwind, CSS Modules, etc.)

Return JSON only:
{{
  "entities": [
    {{"name": "<str>", "type": "<entity_type>", "description": "<str>"}}
  ],
  "relationships": [
    {{"from": "<name>", "to": "<name>", "type": "<relationship_type>", "strength": <float>}}
  ]
}}

entity types: framework, library, pattern, component, style_approach
relationship types: uses, depends_on, preferred_with

File path: {file_path}
---
{content}"""


class KnowledgeExtractor:
    """
    Extracts architectural knowledge from indexed source files and persists
    it into knowledge_entities / knowledge_relationships tables.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_from_file(
        self,
        project_id: int,
        file_path: str,
        content: str,
        language: str,
    ) -> Dict[str, int]:
        """
        Analyze one file with GPT-4o-mini, upsert entities + relationships.

        Returns:
            {"entities_added": int, "relationships_added": int}
        """
        # 1. Ask GPT-4o-mini to parse the file
        raw = self._call_llm(file_path, content, language)
        if raw is None:
            return {"entities_added": 0, "relationships_added": 0}

        entities: List[Dict[str, Any]] = raw.get("entities") or []
        relationships: List[Dict[str, Any]] = raw.get("relationships") or []

        db = _open_db()
        try:
            entities_added = 0
            # name -> id map for relationship resolution
            name_to_id: Dict[str, int] = {}

            # 2. Upsert entities
            for ent in entities:
                name = (ent.get("name") or "").strip()
                etype = (ent.get("type") or "").strip()
                description = (ent.get("description") or "").strip()

                if not name or not etype:
                    continue

                entity_id = self._upsert_entity(
                    db=db,
                    project_id=project_id,
                    name=name,
                    entity_type=etype,
                    description=description,
                    source_file=file_path,
                )
                if entity_id:
                    name_to_id[name] = entity_id
                    entities_added += 1

            # 3. Upsert relationships
            relationships_added = 0
            for rel in relationships:
                from_name = (rel.get("from") or "").strip()
                to_name = (rel.get("to") or "").strip()
                rel_type = (rel.get("type") or "").strip()
                strength = float(rel.get("strength") or 1.0)

                if not from_name or not to_name or not rel_type:
                    continue

                from_id = name_to_id.get(from_name) or self._find_entity_id(
                    db, project_id, from_name
                )
                to_id = name_to_id.get(to_name) or self._find_entity_id(
                    db, project_id, to_name
                )

                if not from_id or not to_id:
                    continue

                added = self._upsert_relationship(
                    db=db,
                    project_id=project_id,
                    from_entity_id=from_id,
                    to_entity_id=to_id,
                    relationship_type=rel_type,
                    strength=strength,
                )
                if added:
                    relationships_added += 1

            db.commit()
            logger.info(
                "knowledge_extractor: %s — +%d entities, +%d relationships",
                file_path,
                entities_added,
                relationships_added,
            )
            return {"entities_added": entities_added, "relationships_added": relationships_added}

        except Exception:
            db.rollback()
            logger.exception("knowledge_extractor: failed processing %s", file_path)
            return {"entities_added": 0, "relationships_added": 0}
        finally:
            db.close()

    def extract_from_project(
        self,
        project_id: int,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Run extraction over the top `limit` indexed files for the project.

        Returns:
            {"files_processed": int, "entities_added": int, "relationships_added": int}
        """
        db = _open_db()
        try:
            rows = db.execute(
                text("""
                    SELECT file_path, content, language
                    FROM file_embeddings
                    WHERE project_id = :project_id
                      AND content IS NOT NULL
                    ORDER BY indexed_at DESC
                    LIMIT :limit
                """),
                {"project_id": project_id, "limit": limit},
            ).fetchall()
        finally:
            db.close()

        total_entities = 0
        total_relationships = 0

        for row in rows:
            result = self.extract_from_file(
                project_id=project_id,
                file_path=row.file_path,
                content=row.content,
                language=row.language or "unknown",
            )
            total_entities += result["entities_added"]
            total_relationships += result["relationships_added"]

        summary = {
            "files_processed": len(rows),
            "entities_added": total_entities,
            "relationships_added": total_relationships,
        }
        logger.info("knowledge_extractor: project %d summary: %s", project_id, summary)
        return summary

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm(
        self, file_path: str, content: str, language: str
    ) -> Optional[Dict[str, Any]]:
        """Call GPT-4o-mini and return parsed JSON, or None on failure."""
        # Truncate very large files to stay within context
        truncated = content[:12_000]

        prompt = _EXTRACT_PROMPT.format(
            language=language,
            file_path=file_path,
            content=truncated,
        )

        try:
            client = _get_client()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw_text = response.choices[0].message.content or ""
            return json.loads(raw_text)
        except json.JSONDecodeError as e:
            logger.warning("knowledge_extractor: JSON parse error for %s: %s", file_path, e)
            return None
        except Exception as e:
            logger.warning("knowledge_extractor: LLM error for %s: %s", file_path, e)
            return None

    def _upsert_entity(
        self,
        db: Session,
        project_id: int,
        name: str,
        entity_type: str,
        description: str,
        source_file: str,
    ) -> Optional[int]:
        """
        Insert entity if it doesn't exist; update description if it changed.
        Returns the entity id.
        """
        existing = db.execute(
            text("""
                SELECT id, description
                FROM knowledge_entities
                WHERE project_id = :project_id AND name = :name
                LIMIT 1
            """),
            {"project_id": project_id, "name": name},
        ).fetchone()

        if existing:
            if existing.description != description and description:
                db.execute(
                    text("""
                        UPDATE knowledge_entities
                        SET description = :description
                        WHERE id = :id
                    """),
                    {"description": description, "id": existing.id},
                )
            return existing.id

        # Generate embedding for new entity
        try:
            embedding = create_embedding(f"{name} {description}")
        except Exception as e:
            logger.warning("knowledge_extractor: embedding failed for '%s': %s", name, e)
            embedding = None

        result = db.execute(
            text("""
                INSERT INTO knowledge_entities
                    (project_id, entity_type, name, description, source_file, embedding, created_at)
                VALUES
                    (:project_id, :entity_type, :name, :description, :source_file,
                     :embedding, :created_at)
                RETURNING id
            """),
            {
                "project_id": project_id,
                "entity_type": entity_type,
                "name": name,
                "description": description,
                "source_file": source_file,
                "embedding": embedding,
                "created_at": datetime.utcnow(),
            },
        )
        return result.scalar()

    def _find_entity_id(
        self, db: Session, project_id: int, name: str
    ) -> Optional[int]:
        """Look up an entity id by name within the project."""
        row = db.execute(
            text("""
                SELECT id FROM knowledge_entities
                WHERE project_id = :project_id AND name = :name
                LIMIT 1
            """),
            {"project_id": project_id, "name": name},
        ).fetchone()
        return row.id if row else None

    def _upsert_relationship(
        self,
        db: Session,
        project_id: int,
        from_entity_id: int,
        to_entity_id: int,
        relationship_type: str,
        strength: float,
    ) -> bool:
        """
        Insert relationship if it doesn't exist.
        Returns True if a new row was inserted.
        """
        existing = db.execute(
            text("""
                SELECT id FROM knowledge_relationships
                WHERE from_entity_id = :from_id
                  AND to_entity_id   = :to_id
                  AND relationship_type = :rel_type
                  AND project_id = :project_id
                LIMIT 1
            """),
            {
                "from_id": from_entity_id,
                "to_id": to_entity_id,
                "rel_type": relationship_type,
                "project_id": project_id,
            },
        ).fetchone()

        if existing:
            return False

        db.execute(
            text("""
                INSERT INTO knowledge_relationships
                    (from_entity_id, to_entity_id, relationship_type,
                     strength, project_id, created_at)
                VALUES
                    (:from_id, :to_id, :rel_type, :strength, :project_id, :created_at)
            """),
            {
                "from_id": from_entity_id,
                "to_id": to_entity_id,
                "rel_type": relationship_type,
                "strength": strength,
                "project_id": project_id,
                "created_at": datetime.utcnow(),
            },
        )
        return True
