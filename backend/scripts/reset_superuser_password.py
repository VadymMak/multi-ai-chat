"""
Reset superuser password from SUPERUSER_PASSWORD env variable.
Runs at startup if SUPERUSER_PASSWORD is set.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.memory.db import SessionLocal
from app.memory.models import User

SUPERUSER_EMAIL = os.environ.get("SUPERUSER_EMAIL", "")
SUPERUSER_PASSWORD = os.environ.get("SUPERUSER_PASSWORD", "")

if not SUPERUSER_EMAIL or not SUPERUSER_PASSWORD:
    print("⏭️  [reset_superuser] SUPERUSER_EMAIL or SUPERUSER_PASSWORD not set — skipping")
    sys.exit(0)

db = SessionLocal()
try:
    user = db.query(User).filter(User.email == SUPERUSER_EMAIL).first()
    if not user:
        print(f"❌ [reset_superuser] User not found: {SUPERUSER_EMAIL}")
        sys.exit(0)

    user.password_hash = User.hash_password(SUPERUSER_PASSWORD)
    db.commit()
    print(f"✅ [reset_superuser] Password updated for {SUPERUSER_EMAIL}")
except Exception as e:
    print(f"❌ [reset_superuser] Error: {e}")
    db.rollback()
finally:
    db.close()
