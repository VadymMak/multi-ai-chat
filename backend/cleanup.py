import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="ai_assistant",
    user="postgres",
    password="admin"
)

cursor = conn.cursor()

# Проверка записей для project '7' (строка!)
cursor.execute("SELECT COUNT(*) FROM memory_entries WHERE project_id = '7'")
count = cursor.fetchone()[0]
print(f"📊 Found {count} memory entries for project 7")

# Посмотреть несколько записей
cursor.execute("""
    SELECT id, role_id, project_id, tokens, LEFT(summary, 50) 
    FROM memory_entries 
    WHERE project_id = '7' 
    ORDER BY timestamp DESC
    LIMIT 10
""")

print("\n📝 Recent entries:")
for row in cursor.fetchall():
    print(f"  ID: {row[0]}, Role: {row[1]}, Tokens: {row[3]}, Summary: {row[4]}...")

# УДАЛЕНИЕ
print("\n⚠️  Deleting all memory entries for project 7...")
cursor.execute("DELETE FROM memory_entries WHERE project_id = '7'")
conn.commit()

# Проверка
cursor.execute("SELECT COUNT(*) FROM memory_entries WHERE project_id = '7'")
new_count = cursor.fetchone()[0]
print(f"✅ Deleted! Remaining: {new_count}")

cursor.close()
conn.close()