# backend/scripts/patch_add_project_id_int.py
import os, sqlite3, sys

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "memory.db"))
print(f"🛠 Using DB: {DB_PATH}")

if not os.path.exists(DB_PATH):
    print("❌ DB file does not exist.")
    sys.exit(1)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

print("→ Checking current columns ...")
cur.execute("PRAGMA table_info(memory_entries)")
cols = [r[1] for r in cur.fetchall()]
print("   Columns:", cols)

if "project_id_int" not in cols:
    print("→ Adding column project_id_int (INTEGER) ...")
    cur.execute("ALTER TABLE memory_entries ADD COLUMN project_id_int INTEGER")
    con.commit()
    print("   ✅ Column added.")
else:
    print("   ℹ️ Column project_id_int already exists.")

print("→ Backfilling project_id_int for numeric project_id values ...")
cur.execute("""
    UPDATE memory_entries
       SET project_id_int = CAST(project_id AS INTEGER)
     WHERE project_id GLOB '[0-9]*'
       AND (project_id_int IS NULL OR project_id_int = '')
""")
print(f"   ✅ Rows updated: {con.total_changes}")

con.commit()
con.close()
print("🎉 Patch complete.")
