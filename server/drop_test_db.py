import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Step 1: Drop and recreate the database as superuser
conn = psycopg2.connect(dbname="postgres", user="postgres", password="moon", host="localhost", port=5432)
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()

cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'sentinel_test' AND pid <> pg_backend_pid()")
cur.execute("DROP DATABASE IF EXISTS sentinel_test")
cur.execute("CREATE DATABASE sentinel_test OWNER sentinel_user")
cur.close()
conn.close()
print("Database sentinel_test recreated successfully")

# Step 2: Grant schema privileges to sentinel_user
conn2 = psycopg2.connect(dbname="sentinel_test", user="postgres", password="moon", host="localhost", port=5432)
conn2.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur2 = conn2.cursor()
cur2.execute("GRANT ALL ON SCHEMA public TO sentinel_user")
cur2.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sentinel_user")
cur2.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO sentinel_user")
cur2.close()
conn2.close()
print("Permissions granted to sentinel_user on sentinel_test")
