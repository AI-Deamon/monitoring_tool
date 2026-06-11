import os
import psycopg2

db_url = os.environ.get('DATABASE_URL')
if not db_url:
    raise SystemExit("DATABASE_URL environment variable is not set")

conn = psycopg2.connect(db_url)
cur = conn.cursor()

ad_username   = os.environ.get('AD_USERNAME',    'Pittala Bhaskar')
ad_domain     = os.environ.get('AD_DOMAIN',      'BSOLAD')
ad_user_email = os.environ.get('AD_USER_EMAIL',  '')

cur.execute("""
    INSERT INTO dashboard_users (username, password_hash, role, org_id, linked_username, auth_type, is_active, email)
    VALUES (%s, 'AD_NO_PASSWORD', 'user', NULL, %s, 'ad', true, %s)
    RETURNING id, username, linked_username, auth_type
""", (ad_username, f'{ad_domain}\\{ad_username}', ad_user_email))

user = cur.fetchone()
conn.commit()

print(f"Created new AD user:")
print(f"  id: {user[0]}")
print(f"  username (login): {user[1]}")
print(f"  linked_username: {user[2]}")
print(f"  auth_type: {user[3]}")

print("\nLogin credentials:")
print(f"  Username: Pittala Bhaskar (or BSOLAD\\Pittala Bhaskar)")
print(f"  Password: Welcome@54321# (AD password)")

conn.close()
