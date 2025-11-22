"""Check database structure"""
import psycopg2
from app.config.settings import settings

def check_database():
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        cur = conn.cursor()
        
        print("=" * 80)
        print("DATABASE CONNECTION: SUCCESS ✅")
        print("=" * 80)
        
        # 1. List all tables
        print("\n📋 ALL TABLES:")
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = cur.fetchall()
        for table in tables:
            print(f"   - {table[0]}")
        
        # 2. Check projects table structure
        print("\n🔍 PROJECTS TABLE STRUCTURE:")
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'projects'
            ORDER BY ordinal_position;
        """)
        columns = cur.fetchall()
        
        if columns:
            print(f"   {'Column':<20} {'Type':<15} {'Nullable':<10} {'Default':<20}")
            print("   " + "-" * 70)
            for col in columns:
                col_name, data_type, nullable, default = col
                default = str(default)[:20] if default else ""
                print(f"   {col_name:<20} {data_type:<15} {nullable:<10} {default:<20}")
        else:
            print("   ⚠️  Table 'projects' does not exist!")
        
        # 3. Check if user_id column exists
        print("\n🔎 CHECKING FOR user_id COLUMN:")
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_name = 'projects' 
                AND column_name = 'user_id'
            );
        """)
        has_user_id = cur.fetchone()[0]
        
        if has_user_id:
            print("   ✅ Column 'user_id' EXISTS in projects table")
        else:
            print("   ❌ Column 'user_id' DOES NOT EXIST in projects table")
            print("   🔧 Need to add user_id column for multi-user support!")
        
        # 4. Check users table
        print("\n👥 USERS TABLE:")
        cur.execute("SELECT id, username, email, status FROM users ORDER BY id;")
        users = cur.fetchall()
        print(f"   {'ID':<5} {'Username':<15} {'Email':<30} {'Status':<10}")
        print("   " + "-" * 65)
        for user in users:
            print(f"   {user[0]:<5} {user[1]:<15} {user[2]:<30} {user[3]:<10}")
        
        # 5. Check projects data
        print("\n📁 EXISTING PROJECTS:")
        cur.execute("SELECT COUNT(*) FROM projects;")
        count = cur.fetchone()[0]
        print(f"   Total projects: {count}")
        
        if count > 0:
            try:
                cur.execute("SELECT id, name FROM projects LIMIT 5;")
                projects = cur.fetchall()
                for proj in projects:
                    print(f"   - ID {proj[0]}: {proj[1]}")
            except Exception as e:
                print(f"   ⚠️  Error reading projects: {e}")
        
        print("\n" + "=" * 80)
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    check_database()