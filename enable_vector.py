
import psycopg2

try:
    # Connect to 'omnicortex' db to enable extension
    conn = psycopg2.connect(
        dbname="omnicortex",
        user="postgres",
        password="postgresdb",
        host="localhost",
        port="5432"
    )
    conn.autocommit = True
    cursor = conn.cursor()

    cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    print("✅ Extension 'vector' enabled successfully")

except Exception as e:
    print(f"❌ Failed to enable extension: {e}")
finally:
    if 'cursor' in locals(): cursor.close()
    if 'conn' in locals(): conn.close()
