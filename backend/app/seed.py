"""
Database seeding for production
Seeds only essential roles - NO auto-created projects
"""
import logging
from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import Role

logger = logging.getLogger(__name__)

DEFAULT_ROLES = [
    {
        "name": "AI Assistant",
        "description": "General-purpose AI assistant for various tasks and questions"
    },
    {
        "name": "Code Helper",
        "description": "Programming assistant for coding, debugging, and technical documentation"
    },
    {
        "name": "Creative Writer",
        "description": "Creative writing and content creation assistant"
    },
]


def seed_roles(db: Session) -> None:
    """Ensure default roles exist"""
    logger.info("=" * 70)
    logger.info("🌱 SEEDING ROLES")
    logger.info("=" * 70)
    
    for role_data in DEFAULT_ROLES:
        existing = db.query(Role).filter(Role.name == role_data["name"]).first()
        if not existing:
            role = Role(
                name=role_data["name"],
                description=role_data["description"]
            )
            db.add(role)
            db.flush()
            logger.info(f"  ✅ Created role: {role_data['name']} (id={role.id})")
        else:
            logger.info(f"  ℹ️  Role exists: {role_data['name']} (id={existing.id})")
    
    db.commit()
    logger.info("=" * 70)
    logger.info("✅ ROLES SEEDING COMPLETED")
    logger.info("=" * 70)


def run_seed():
    """Main seeding function - called on app startup"""
    db = SessionLocal()
    try:
        seed_roles(db)
    except Exception as e:
        logger.error(f"❌ Error during seeding: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_seed()