"""Check users in Railway database"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.memory.db import SessionLocal
from app.memory.models import User

db = SessionLocal()
try:
    users = db.query(User).all()
    print("\n📋 Users in Railway database:")
    print("=" * 80)
    
    if not users:
        print("❌ No users found!")
    else:
        for user in users:
            print(f"\nID: {user.id}")
            print(f"Email: {user.email}")
            print(f"Username: {user.username}")
            print(f"Password Hash: {user.password_hash[:60]}...")
            print(f"Is Superuser: {user.is_superuser}")
            print(f"Is Active: {user.is_active}")
            print(f"Status: {user.status}")
            print("-" * 80)
            
            # Test password
            from passlib.hash import bcrypt
            test_passwords = ['admin123', 'Admin123!', 'admin']
            for pwd in test_passwords:
                if bcrypt.verify(pwd, user.password_hash):
                    print(f"✅ Password '{pwd}' MATCHES!")
                    
    print(f"\n✅ Total users: {len(users)}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()