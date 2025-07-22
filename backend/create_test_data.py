# Create file: backend/create_test_data.py

from app.memory.db import SessionLocal
from app.memory.models import Role, Project

def create_test_data():
    db = SessionLocal()
    
    try:
        # Create role
        role = Role(
            id=1,
            role_name="LLM Engineer",
            instructions="You are a helpful AI assistant."
        )
        db.add(role)
        
        # Create project
        project = Project(
            id=1,
            project_name="Test Project",
            project_structure=""
        )
        db.add(project)
        
        db.commit()
        print("✅ Created role_id=1 and project_id=1")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_test_data()