"""add_agent_update_control_columns

Revision ID: c7c09b33cce8
Revises: fix_missing_agent_columns
Create Date: 2026-02-12 15:39:03.568987

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7c09b33cce8'
down_revision: Union[str, Sequence[str], None] = 'fix_missing_agent_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create asset_info table safely
    op.execute("""
        CREATE TABLE IF NOT EXISTS asset_info (
            id SERIAL PRIMARY KEY,
            agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            hostname VARCHAR(255),
            serial_number VARCHAR(255),
            manufacturer VARCHAR(255),
            model VARCHAR(255),
            bios_uuid VARCHAR(255),
            system_uuid VARCHAR(255),
            asset_tag VARCHAR(255),
            domain VARCHAR(255),
            workgroup VARCHAR(255),
            cpu_name VARCHAR(255),
            cpu_cores INTEGER,
            cpu_threads INTEGER,
            cpu_speed_mhz INTEGER,
            ram_total_gb FLOAT,
            ram_slots_used INTEGER,
            ram_slots_total INTEGER,
            gpu_name VARCHAR(255),
            gpu_memory_gb FLOAT,
            disks_json TEXT,
            motherboard VARCHAR(255),
            primary_mac VARCHAR(255),
            primary_ip VARCHAR(255),
            all_macs_json TEXT,
            all_ips_json TEXT,
            dns_servers_json TEXT,
            domain_joined BOOLEAN,
            domain_name VARCHAR(255),
            os_name VARCHAR(255),
            os_version VARCHAR(255),
            os_build VARCHAR(255),
            os_architecture VARCHAR(255),
            antivirus_json TEXT,
            firewall_enabled BOOLEAN,
            last_boot_time VARCHAR(255),
            windows_update_enabled BOOLEAN,
            bitlocker_status VARCHAR(255),
            collected_at TIMESTAMP WITH TIME ZONE,
            collection_hash VARCHAR(255),
            agent_version VARCHAR(50)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_info_agent_id ON asset_info(agent_id);
    """)

    # Add missing columns to agents table safely
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='target_version') THEN
                ALTER TABLE agents ADD COLUMN target_version VARCHAR(50);
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='update_status') THEN
                ALTER TABLE agents ADD COLUMN update_status VARCHAR(50) DEFAULT 'up_to_date';
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='last_update_check') THEN
                ALTER TABLE agents ADD COLUMN last_update_check TIMESTAMP;
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='update_attempts') THEN
                ALTER TABLE agents ADD COLUMN update_attempts INTEGER DEFAULT 0;
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='last_update_error') THEN
                ALTER TABLE agents ADD COLUMN last_update_error TEXT;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('asset_info')
    op.execute("""
        ALTER TABLE agents DROP COLUMN IF EXISTS target_version;
        ALTER TABLE agents DROP COLUMN IF EXISTS update_status;
        ALTER TABLE agents DROP COLUMN IF EXISTS last_update_check;
        ALTER TABLE agents DROP COLUMN IF EXISTS update_attempts;
        ALTER TABLE agents DROP COLUMN IF EXISTS last_update_error;
    """)
