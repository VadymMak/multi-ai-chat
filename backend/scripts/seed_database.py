"""
Database seeding script
Runs on application startup to ensure default data exists
"""
import logging
from sqlalchemy.orm import Session
from app.memory.db import SessionLocal
from app.memory.models import Role, Project, User

logger = logging.getLogger(__name__)

DEFAULT_ROLES = [
    {
        "name": "AI Assistant",
        "description": "General-purpose AI assistant for various tasks"
    },
    {
        "name": "Assistant",
        "description": "Helpful assistant for everyday questions"
    },
    {
        "name": "Creative Helper",
        "description": "Creative writing and brainstorming assistant"
    },
    {
        "name": "Writing Assistant",
        "description": "Professional writing and editing assistant"
    },
    {
        "name": "Code Assistant",
        "description": "Programming and technical documentation assistant"
    }
]


def seed_roles(db: Session) -> dict:
    """Ensure default roles exist, return role mapping"""
    logger.info("🌱 Seeding roles...")
    
    role_mapping = {}
    for role_data in DEFAULT_ROLES:
        existing = db.query(Role).filter(Role.name == role_data["name"]).first()
        if not existing:
            role = Role(
                name=role_data["name"],
                description=role_data["description"]
            )
            db.add(role)
            db.flush()  # Get ID without committing
            role_mapping[role.name] = role.id
            logger.info(f"  ✅ Created role: {role_data['name']} (id={role.id})")
        else:
            role_mapping[existing.name] = existing.id
            logger.info(f"  ℹ️  Role already exists: {role_data['name']} (id={existing.id})")
    
    db.commit()
    logger.info("✅ Roles seeding completed")
    return role_mapping


def fix_projects_without_assistant(db: Session, default_role_id: int) -> None:
    """Fix projects that have NULL assistant_id"""
    logger.info("🔧 Checking projects without assistant_id...")
    
    projects = db.query(Project).filter(Project.assistant_id == None).all()
    if projects:
        for project in projects:
            project.assistant_id = default_role_id
            logger.info(f"  ✅ Fixed project '{project.name}' (id={project.id}) - set assistant_id={default_role_id}")
        db.commit()
        logger.info(f"✅ Fixed {len(projects)} projects")
    else:
        logger.info("  ℹ️  All projects already have assistant_id")


def seed_default_project_for_superuser(db: Session, user_id: int, role_id: int) -> None:
    """Create default project for superuser if none exists"""
    logger.info(f"🌱 Checking default project for superuser (id={user_id})...")
    
    existing = db.query(Project).filter(Project.user_id == user_id).first()
    if not existing:
        project = Project(
            name="Default Workspace",
            user_id=user_id,
            assistant_id=role_id
        )
        db.add(project)
        db.commit()
        logger.info(f"  ✅ Created default project for superuser (id={user_id})")
    else:
        logger.info(f"  ℹ️  Superuser already has {db.query(Project).filter(Project.user_id == user_id).count()} project(s)")


def run_seed():
    """Main seeding function"""
    logger.info("=" * 70)
    logger.info("🌱 DATABASE SEEDING STARTED")
    logger.info("=" * 70)
    
    db = SessionLocal()
    try:
        # Step 1: Seed roles
        role_mapping = seed_roles(db)
        
        # Step 2: Fix existing projects without assistant_id
        if role_mapping:
            first_role_id = list(role_mapping.values())[0]
            fix_projects_without_assistant(db, first_role_id)
        
        # Step 3: Ensure superuser has at least one project
        superuser = db.query(User).filter(User.is_superuser == True).first()
        if superuser:
            first_role_id = list(role_mapping.values())[0] if role_mapping else None
            if first_role_id:
                seed_default_project_for_superuser(db, superuser.id, first_role_id)
            else:
                logger.warning("  ⚠️  No roles available to create default project")
        else:
            logger.info("  ℹ️  No superuser found - skipping default project creation")
        
        logger.info("=" * 70)
        logger.info("✅ DATABASE SEEDING COMPLETED SUCCESSFULLY")
        logger.info("=" * 70)
        
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