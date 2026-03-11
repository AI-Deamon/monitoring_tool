"""Add EOL system tables

Revision ID: 007_add_eol_system_tables
Revises: 006_add_portable_apps
Create Date: 2026-02-13

Phase 6: Creates all remaining EOL system tables:
  - software_lifecycle: EOL knowledge base (endoflife.date sync data)
  - asset_lifecycle_status: Per-agent per-product lifecycle evaluation cache
  - nvd_cache: NIST NVD vulnerability data cache for risk scoring
  - windows_updates: Windows update (KB) records per agent
  - software_metering: Software usage frequency from Prefetch/MUI
  - product_keys: Partial product keys for license compliance
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '007_add_eol_system_tables'
down_revision = '006_add_portable_apps'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # ── 1. software_lifecycle ────────────────────────────────────────────
    # EOL knowledge base. One row per product-cycle combination.
    # Populated from endoflife.date API or manual curation.
    if 'software_lifecycle' not in existing_tables:
        op.create_table(
            'software_lifecycle',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('product_name', sa.String(255), nullable=False),
            sa.Column('cycle', sa.String(100), nullable=False),
            sa.Column('release_label', sa.String(255), nullable=True),
            sa.Column('release_date', sa.Date(), nullable=True),
            sa.Column('eol_date', sa.Date(), nullable=True),
            sa.Column('eos_date', sa.Date(), nullable=True),
            sa.Column('is_lts', sa.Boolean(), default=False),
            sa.Column('latest_version', sa.String(100), nullable=True),
            sa.Column('reference_url', sa.Text(), nullable=True),
            sa.Column('source', sa.String(50), server_default='endoflife.date'),
            sa.Column('synced_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('product_name', 'cycle', name='uq_lifecycle_product_cycle')
        )
        op.create_index('ix_software_lifecycle_product_name', 'software_lifecycle', ['product_name'])
        print("[MIGRATION] Created software_lifecycle table")
    else:
        print("[MIGRATION] software_lifecycle table already exists, skipping")

    # ── 2. asset_lifecycle_status ─────────────────────────────────────────
    # Cached lifecycle evaluation result per agent per product.
    if 'asset_lifecycle_status' not in existing_tables:
        op.create_table(
            'asset_lifecycle_status',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('product_name', sa.String(255), nullable=False),
            sa.Column('installed_version', sa.String(255), nullable=True),
            sa.Column('matched_cycle', sa.String(100), nullable=True),
            sa.Column('status', sa.String(30), nullable=False, server_default='unknown'),
            sa.Column('eol_date', sa.Date(), nullable=True),
            sa.Column('risk_score', sa.Integer(), server_default='0'),
            sa.Column('severity', sa.String(20), server_default='info'),
            sa.Column('evaluated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
            sa.UniqueConstraint('agent_id', 'product_name', name='uq_asset_lifecycle_agent_product')
        )
        op.create_index('ix_asset_lifecycle_status_agent_id', 'asset_lifecycle_status', ['agent_id'])
        print("[MIGRATION] Created asset_lifecycle_status table")
    else:
        print("[MIGRATION] asset_lifecycle_status table already exists, skipping")

    # ── 3. nvd_cache ─────────────────────────────────────────────────────
    # Local cache of NIST NVD vulnerability data for risk scoring.
    if 'nvd_cache' not in existing_tables:
        op.create_table(
            'nvd_cache',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('cve_id', sa.String(20), nullable=False),
            sa.Column('cpe_string', sa.String(500), nullable=False),
            sa.Column('cvss_score', sa.Float(), server_default='0.0'),
            sa.Column('severity', sa.String(20), server_default='NONE'),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('published_date', sa.String(30), nullable=True),
            sa.Column('last_modified', sa.String(30), nullable=True),
            sa.Column('synced_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('cve_id', 'cpe_string', name='uq_nvd_cve_cpe')
        )
        op.create_index('ix_nvd_cache_cve_id', 'nvd_cache', ['cve_id'])
        op.create_index('ix_nvd_cache_cpe_string', 'nvd_cache', ['cpe_string'])
        op.create_index('ix_nvd_cvss', 'nvd_cache', ['cvss_score'])
        print("[MIGRATION] Created nvd_cache table")
    else:
        print("[MIGRATION] nvd_cache table already exists, skipping")

    # ── 4. windows_updates ───────────────────────────────────────────────
    # Windows update (KB) records collected from agents.
    if 'windows_updates' not in existing_tables:
        op.create_table(
            'windows_updates',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('kb_number', sa.String(20), nullable=False),
            sa.Column('title', sa.String(500), nullable=True),
            sa.Column('update_type', sa.String(50), server_default='Unknown'),
            sa.Column('install_date', sa.Date(), nullable=True),
            sa.Column('result_code', sa.Integer(), server_default='0'),
            sa.Column('is_pending', sa.Boolean(), server_default='false'),
            sa.Column('first_detected', sa.DateTime(), nullable=True),
            sa.Column('last_updated', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
            sa.UniqueConstraint('agent_id', 'kb_number', name='uq_update_agent_kb')
        )
        op.create_index('ix_windows_updates_agent_id', 'windows_updates', ['agent_id'])
        print("[MIGRATION] Created windows_updates table")
    else:
        print("[MIGRATION] windows_updates table already exists, skipping")

    # ── 5. software_metering ─────────────────────────────────────────────
    # Software usage frequency from Prefetch/MUI cache analysis.
    if 'software_metering' not in existing_tables:
        op.create_table(
            'software_metering',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('app_name', sa.String(255), nullable=False),
            sa.Column('executable_name', sa.String(255), nullable=True),
            sa.Column('usage_count', sa.Integer(), server_default='0'),
            sa.Column('last_used', sa.DateTime(), nullable=True),
            sa.Column('source', sa.String(50), server_default='prefetch'),
            sa.Column('first_detected', sa.DateTime(), nullable=True),
            sa.Column('last_updated', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
            sa.UniqueConstraint('agent_id', 'executable_name', name='uq_metering_agent_exe')
        )
        op.create_index('ix_software_metering_agent_id', 'software_metering', ['agent_id'])
        print("[MIGRATION] Created software_metering table")
    else:
        print("[MIGRATION] software_metering table already exists, skipping")

    # ── 6. product_keys ──────────────────────────────────────────────────
    # Partial product keys (last 5 chars) for license compliance.
    if 'product_keys' not in existing_tables:
        op.create_table(
            'product_keys',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('product_name', sa.String(255), nullable=False),
            sa.Column('partial_key', sa.String(10), nullable=True),
            sa.Column('key_source', sa.String(50), server_default='Unknown'),
            sa.Column('license_status', sa.String(50), server_default='Unknown'),
            sa.Column('first_detected', sa.DateTime(), nullable=True),
            sa.Column('last_updated', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
            sa.UniqueConstraint('agent_id', 'product_name', name='uq_key_agent_product')
        )
        op.create_index('ix_product_keys_agent_id', 'product_keys', ['agent_id'])
        print("[MIGRATION] Created product_keys table")
    else:
        print("[MIGRATION] product_keys table already exists, skipping")


def downgrade():
    # Drop in reverse order to respect FK constraints
    op.drop_index('ix_product_keys_agent_id', table_name='product_keys')
    op.drop_table('product_keys')
    print("[MIGRATION] Dropped product_keys table")

    op.drop_index('ix_software_metering_agent_id', table_name='software_metering')
    op.drop_table('software_metering')
    print("[MIGRATION] Dropped software_metering table")

    op.drop_index('ix_windows_updates_agent_id', table_name='windows_updates')
    op.drop_table('windows_updates')
    print("[MIGRATION] Dropped windows_updates table")

    op.drop_index('ix_nvd_cvss', table_name='nvd_cache')
    op.drop_index('ix_nvd_cache_cpe_string', table_name='nvd_cache')
    op.drop_index('ix_nvd_cache_cve_id', table_name='nvd_cache')
    op.drop_table('nvd_cache')
    print("[MIGRATION] Dropped nvd_cache table")

    op.drop_index('ix_asset_lifecycle_status_agent_id', table_name='asset_lifecycle_status')
    op.drop_table('asset_lifecycle_status')
    print("[MIGRATION] Dropped asset_lifecycle_status table")

    op.drop_index('ix_software_lifecycle_product_name', table_name='software_lifecycle')
    op.drop_table('software_lifecycle')
    print("[MIGRATION] Dropped software_lifecycle table")
