
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

try:
    # Connect to 'postgres' db to create 'omnicortex'
    conn = psycopg2.connect(
        dbname="postgres",
        user="postgres",
        password="postgresdb",
        host="localhost",
        port="5432"
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()

    cursor.execute("SELECT 1 FROM pg_database WHERE datname = 'omnicortex'")
    exists = cursor.fetchone()
    
    if not exists:
        cursor.execute("CREATE DATABASE omnicortex;")
        print("✅ Database 'omnicortex' created successfully")
    else:
        print("ℹ️ Database 'omnicortex' already exists")

except Exception as e:
    print(f"❌ Operation failed: {e}")
finally:
    if 'cursor' in locals(): cursor.close()
    if 'conn' in locals(): conn.close()
