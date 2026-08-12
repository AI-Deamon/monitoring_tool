"""create tab_session (feature 037, FR-002a / FR-002b)

Backs per-tab dashboard authentication and the two independent session limits
(30-minute idle, 4-hour absolute). The browser holds only an opaque token in
sessionStorage; the server decides whether that token is still valid, which is
what makes this access control rather than a client-side flag.

Notes:
  - tab_token is stored HASHED, consistent with how agent API keys are handled.
  - There is deliberately no claim_nonce column. Duplicate-tab detection was
    considered and rejected (FR-002l): browsers copy sessionStorage into a
    duplicated tab, so the copy cannot be distinguished from its parent, and
    the only workable detection would sign out both tabs. The limitation is
    accepted and documented instead.
  - This sits ALONGSIDE the existing session_version mechanism, which must keep
    invalidating other sessions on password change (FR-003). Both checks apply.
  - Revoked rows serve no authentication purpose and should be purged by the
    existing cleanup job.

Revision ID: 20260807_create_tab_session
Revises: 20260807_admin_password_rotation
Create Date: 2026-08-07
"""
import sqlalchemy as sa
from alembic import op

revision = '20260807_create_tab_session'
down_revision = '20260807_admin_password_rotation'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tab_session',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('dashboard_users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        # SHA-256 hex digest of the opaque token held in the browser.
        sa.Column('tab_token', sa.String(length=64), nullable=False),
        # Start of the absolute lifetime (FR-002b: 4 hours).
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        # Advanced on each authenticated request; start of the idle window
        # (FR-002b: 30 minutes).
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        # One of: signed_out, idle_timeout, absolute_timeout,
        # password_changed, deployment. Supplies the FR-002c message.
        sa.Column('revoked_reason', sa.String(length=32), nullable=True),
    )
    op.create_index(
        'ix_tab_session_tab_token', 'tab_session', ['tab_token'], unique=True
    )
    op.create_index('ix_tab_session_user_id', 'tab_session', ['user_id'])
    # Supports "revoke all live sessions for this user" (sign-out, password
    # change) and the deployment-wide sweep, without scanning revoked rows.
    op.create_index(
        'ix_tab_session_user_active', 'tab_session', ['user_id', 'revoked_at']
    )


def downgrade():
    op.drop_index('ix_tab_session_user_active', table_name='tab_session')
    op.drop_index('ix_tab_session_user_id', table_name='tab_session')
    op.drop_index('ix_tab_session_tab_token', table_name='tab_session')
    op.drop_table('tab_session')
