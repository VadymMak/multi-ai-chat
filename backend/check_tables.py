import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="ai_assistant",
    user="postgres",
    password="admin"
)

cursor = conn.cursor()

# Посмотреть все таблицы
cursor.execute("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'public'
""")

tables = cursor.fetchall()
print("📋 Tables in database:")
for table in tables:
    print(f"  - {table[0]}")

cursor.close()
conn.close()