"""
Add domain classification system:
- Classification rules table
- Review queue support
- Historical data correction
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

from server_app import create_app
from extensions import db
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    app = create_app()
    with app.app_context():
        try:
            logger.info("Creating domain classification tables...")

            # Table 1: Classification rules (patterns admin creates)
            db.session.execute(text('''
                CREATE TABLE IF NOT EXISTS domain_classification_rules (
                    id SERIAL PRIMARY KEY,
                    pattern TEXT NOT NULL,
                    pattern_type VARCHAR(20) NOT NULL DEFAULT 'substring',
                    -- substring, regex, exact

                    classified_as TEXT,
                    -- The proper domain name OR 'ignore' OR 'localhost'

                    action VARCHAR(20) NOT NULL DEFAULT 'map',
                    -- 'map' (to domain), 'ignore' (don't store)

                    priority INTEGER DEFAULT 100,
                    -- Lower = higher priority (checked first)

                    created_by VARCHAR(100),
                    -- Admin username who created this rule

                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),

                    is_active BOOLEAN DEFAULT TRUE,

                    -- Stats
                    match_count INTEGER DEFAULT 0,
                    -- How many times this rule matched

                    last_matched_at TIMESTAMP
                )
            '''))
            logger.info("  Created table: domain_classification_rules")

            # Table 2: Manual classifications (admin tagged individual sessions)
            db.session.execute(text('''
                CREATE TABLE IF NOT EXISTS domain_manual_classifications (
                    id SERIAL PRIMARY KEY,
                    raw_title TEXT NOT NULL,
                    raw_url TEXT,

                    classified_domain TEXT NOT NULL,
                    -- The correct domain admin assigned

                    action VARCHAR(20) DEFAULT 'map',
                    -- 'map' or 'ignore'

                    classified_by VARCHAR(100),
                    classified_at TIMESTAMP DEFAULT NOW(),

                    notes TEXT,

                    -- Link back to sessions if needed
                    applied_to_session_ids INTEGER[]
                )
            '''))
            logger.info("  Created table: domain_manual_classifications")

            # Add needs_review column to domain_sessions if not exists
            try:
                db.session.execute(text('''
                    ALTER TABLE domain_sessions 
                    ADD COLUMN needs_review BOOLEAN DEFAULT FALSE
                '''))
                logger.info("  Added column: domain_sessions.needs_review")
            except Exception as e:
                if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                    logger.info("  Column needs_review already exists, skipping")
                else:
                    raise

            db.session.commit()

            # Seed with basic rules (skip if already exist)
            logger.info("Seeding default classification rules...")

            rules = [
                ('localhost', 'substring', 'localhost', 'ignore', 1),
                ('127.0.0.1', 'substring', 'localhost', 'ignore', 1),
                ('192.168.', 'substring', 'localhost', 'ignore', 1),
                ('10.0.', 'substring', 'localhost', 'ignore', 1),
                ('sentineledge', 'substring', 'localhost', 'ignore', 1),
                ('baki', 'substring', 'localhost', 'ignore', 1),
                ('chatgpt', 'substring', 'chatgpt.com', 'map', 50),
                ('gmail', 'substring', 'mail.google.com', 'map', 50),
                ('youtube', 'substring', 'youtube.com', 'map', 50),
                ('github', 'substring', 'github.com', 'map', 50),
                ('stackoverflow', 'substring', 'stackoverflow.com', 'map', 50),
                ('linkedin', 'substring', 'linkedin.com', 'map', 50),
            ]

            for pattern, ptype, classified, action, priority in rules:
                try:
                    # Check if rule already exists
                    existing = db.session.execute(text(
                        "SELECT id FROM domain_classification_rules WHERE pattern = :pattern"
                    ), {'pattern': pattern}).first()
                    
                    if not existing:
                        db.session.execute(text('''
                            INSERT INTO domain_classification_rules 
                            (pattern, pattern_type, classified_as, action, priority)
                            VALUES (:pattern, :ptype, :classified, :action, :priority)
                        '''), {
                            'pattern': pattern,
                            'ptype': ptype,
                            'classified': classified,
                            'action': action,
                            'priority': priority
                        })
                        logger.info(f"  Added rule: {pattern}")
                except Exception as e:
                    logger.debug(f"  Skipping rule {pattern}: {e}")

            db.session.commit()
            logger.info("✅ Migration completed successfully!")

        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Migration failed: {e}")
            raise

if __name__ == '__main__':
    run_migration()
