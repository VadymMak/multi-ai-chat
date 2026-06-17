"""Make family accounts permanent (idempotent, safe to re-run)."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.memory.db import SessionLocal
from app.memory.models import User

FAMILY_USER_IDS = [2, 3]

db = SessionLocal()
try:
    users = db.query(User).filter(User.id.in_(FAMILY_USER_IDS)).all()

    if not users:
        print(f"⚠️  No users found with id in {FAMILY_USER_IDS}")
        sys.exit(0)

    updated = 0
    for u in users:
        if u.status == "active" and u.trial_ends_at is None and u.subscription_ends_at is None:
            print(f"✅ id={u.id} ({u.username}) already permanent — skipping")
            continue
        u.status = "active"
        u.trial_ends_at = None
        u.subscription_ends_at = None
        updated += 1
        print(f"🔧 id={u.id} ({u.username}) → status=active, trial_ends_at=NULL, subscription_ends_at=NULL")

    if updated:
        db.commit()
        print(f"✅ Committed {updated} update(s)")
    else:
        print("✅ Nothing to update")
finally:
    db.close()
