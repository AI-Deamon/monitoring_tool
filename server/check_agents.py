import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)

# Never hardcode credentials: this file previously carried a real password.
database_url = os.getenv('DATABASE_URL')
if not database_url:
    sys.exit("DATABASE_URL is not set (put it in server/.env)")

conn = psycopg2.connect(database_url)
cur = conn.cursor()

# Check agent_current_status for username
cur.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_name = 'agent_current_status'"
)
cols = [c[0] for c in cur.fetchall()]
print("agent_current_status columns:", cols)

# Check for usernames
cur.execute(
    "SELECT agent_id, username FROM agent_current_status WHERE username IS NOT NULL LIMIT 10"
)
print("\nAgent usernames:")
for row in cur.fetchall():
    print(f"  {row}")

conn.close()
