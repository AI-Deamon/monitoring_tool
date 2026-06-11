import psycopg2

conn = psycopg2.connect("postgresql://postgres:moon@localhost:5432/sentinel_test")
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
