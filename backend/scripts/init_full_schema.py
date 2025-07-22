import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.memory.db import engine
from app.memory.models import Base

def init_schema():
    Base.metadata.create_all(bind=engine)
    print("✅ All tables created from models.")

if __name__ == "__main__":
    init_schema()
