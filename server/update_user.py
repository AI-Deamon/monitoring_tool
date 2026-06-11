import os
import psycopg2

db_url = os.environ.get('DATABASE_URL')
if not db_url:
    raise SystemExit("DATABASE_URL environment variable is not set")

conn = psycopg2.connect(db_url)
cur = conn.cursor()

ad_username  = os.environ.get('AD_USERNAME', 'Pittala Bhaskar')
ad_domain    = os.environ.get('AD_DOMAIN',   'BSOLAD')
admin_email  = os.environ.get('ADMIN_EMAIL', '')

# Update the ad_test user's linked_username to match the agent's username
cur.execute("""
    UPDATE dashboard_users 
    SET linked_username = %s
    WHERE username = 'ad_test'
    RETURNING id, username, linked_username, auth_type
""", (f'{ad_domain}\\{ad_username}',))

user = cur.fetchone()
conn.commit()

print(f"Updated user:")
print(f"  id: {user[0]}")
print(f"  username: {user[1]}")
print(f"  linked_username: {user[2]}")
print(f"  auth_type: {user[3]}")

# Also create an admin user that uses AD login directly with the same username
# First check if admin exists
cur.execute(
    "SELECT id, username, linked_username, auth_type FROM dashboard_users WHERE username = 'admin'"
)
admin = cur.fetchone()

if admin:
    print(f"\nAdmin user exists: {admin}")
else:
    print("\nAdmin user doesn't exist - creating...")
    cur.execute("""
        INSERT INTO dashboard_users (username, password_hash, role, org_id, linked_username, auth_type, is_active, email)
        VALUES ('admin', 'AD_NO_PASSWORD', 'admin', NULL, %s, 'ad', true, %s)
        RETURNING id, username
    """, (f'{ad_domain}\\{ad_username}', admin_email))
    new_admin = cur.fetchone()
    conn.commit()
    print(f"Created admin user: {new_admin}")

conn.close()
