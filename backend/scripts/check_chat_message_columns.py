from sqlalchemy import create_engine, inspect
import os

DB_PATH = os.path.abspath("E:/projects/ai-assistant/backend/memory.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL)
inspector = inspect(engine)

print(f"📋 Columns in 'chat_messages':")
for column in inspector.get_columns("chat_messages"):
    print(f"- {column['name']} ({column['type']})")
