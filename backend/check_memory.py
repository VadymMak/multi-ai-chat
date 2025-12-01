import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="ai_assistant",
    user="postgres",
    password="admin"
)

cursor = conn.cursor()

# Структура memory_entries
cursor.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'memory_entries'
""")

print("📋 Columns in memory_entries:")
for col in cursor.fetchall():
    print(f"  - {col[0]} ({col[1]})")

print("\n")

# Проверка записей для project 7
cursor.execute("SELECT COUNT(*) FROM memory_entries WHERE project_id = 7")
count = cursor.fetchone()[0]
print(f"📊 Found {count} memory entries for project 7")

# Посмотреть несколько записей
cursor.execute("""
    SELECT id, role_id, project_id, LEFT(summary, 50) 
    FROM memory_entries 
    WHERE project_id = 7 
    LIMIT 5
""")

print("\n📝 Sample entries:")
for row in cursor.fetchall():
    print(f"  ID: {row[0]}, Role: {row[1]}, Project: {row[2]}, Summary: {row[3]}...")

cursor.close()
conn.close()