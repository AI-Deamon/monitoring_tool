"""add dashboard_users.must_change_password (feature 037, FR-006f)

Forces existing local administrators to set a password meeting the new strength
rule (14 characters, all four character classes) at next sign-in.

Scope of the data migration — deliberately narrow:
  - Local administrators (auth_type='local' AND role='admin')  -> flagged
  - Local ordinary users                                       -> NOT flagged
  - Active Directory accounts (auth_type='ad')                 -> NEVER flagged

Ordinary local users keep working with their existing password so nobody is
locked out by this release (FR-006f). AD accounts are exempt from product-level
password policy entirely (FR-006a) — their policy belongs to the directory.

Why every local admin is flagged rather than only non-compliant ones: password
hashes cannot be inspected to test compliance. The sign-in flow can, because it
holds the plaintext at that moment — so it should clear this flag immediately
when the supplied password already satisfies the administrator rule. That keeps
the migration safe (no admin left on a weak password) without forcing a change
on admins who are already compliant.

Break-glass recovery exists for the case where the forced-change flow itself
fails: server/scripts/admin/reset_admin_password.py (FR-006h).

Revision ID: 20260807_admin_password_rotation
Revises: 20260807_add_bios_version
Create Date: 2026-08-07
"""
import sqlalchemy as sa
from alembic import op

revision = '20260807_admin_password_rotation'
down_revision = '20260807_add_bios_version'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'dashboard_users',
        sa.Column(
            'must_change_password',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Flag existing local administrators only. Never AD accounts, never
    # ordinary local users.
    op.execute("""
        UPDATE dashboard_users
           SET must_change_password = TRUE
         WHERE role = 'admin'
           AND auth_type = 'local'
    """)


def downgrade():
    op.drop_column('dashboard_users', 'must_change_password')
