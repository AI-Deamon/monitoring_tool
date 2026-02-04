"""add_domain_classification_rules

Revision ID: 668a1f8f863e
Revises: 7204218e0a8e
Create Date: 2026-02-03 21:19:53.631027

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '668a1f8f863e'
down_revision: Union[str, Sequence[str], None] = '7204218e0a8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create domain_classification_rules table
    op.execute("""
        CREATE TABLE IF NOT EXISTS domain_classification_rules (
            id SERIAL PRIMARY KEY,
            pattern VARCHAR(500) NOT NULL,
            pattern_type VARCHAR(20) DEFAULT 'substring',
            classified_as VARCHAR(200) NOT NULL,
            action VARCHAR(20) DEFAULT 'map',
            priority INTEGER DEFAULT 100,
            is_active BOOLEAN DEFAULT TRUE,
            match_count INTEGER DEFAULT 0,
            last_matched_at TIMESTAMP,
            created_by VARCHAR(100) DEFAULT 'admin',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    
    # 2. Add indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_classification_rules_pattern ON domain_classification_rules(pattern);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_classification_rules_active ON domain_classification_rules(is_active, priority);")
    
    # 3. Seed default rules
    op.execute("""
        INSERT INTO domain_classification_rules (pattern, pattern_type, classified_as, action, priority) 
        VALUES
            ('perplexity.ai', 'substring', 'perplexity.com', 'map', 10),
            ('accounts.google.com', 'substring', 'google.com', 'map', 10),
            ('mail.google.com', 'substring', 'gmail.com', 'map', 10),
            ('drive.google.com', 'substring', 'google-drive.com', 'map', 10),
            ('docs.google.com', 'substring', 'google-docs.com', 'map', 10),
            ('localhost', 'substring', 'localhost', 'ignore', 5),
            ('127.0.0.1', 'substring', 'localhost', 'ignore', 5),
            ('192.168.', 'substring', 'internal', 'ignore', 5),
            ('youtube', 'substring', 'youtube.com', 'map', 100),
            ('facebook', 'substring', 'facebook.com', 'map', 100),
            ('instagram', 'substring', 'instagram.com', 'map', 100),
            ('twitter', 'substring', 'twitter.com', 'map', 100),
            ('x.com', 'exact', 'twitter.com', 'map', 100),
            ('slack', 'substring', 'slack.com', 'map', 50),
            ('notion', 'substring', 'notion.so', 'map', 50),
            ('github', 'substring', 'github.com', 'map', 50)
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    pass
