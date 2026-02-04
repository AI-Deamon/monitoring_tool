-- Migration: Domain Classification System
-- Creates tables and seeds default rules for domain classification

-- Table 1: Classification rules (patterns admin creates)
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
);

-- Table 2: Manual classifications (admin tagged individual sessions)
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
);

-- Add needs_review column to domain_sessions if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'domain_sessions' AND column_name = 'needs_review'
    ) THEN
        ALTER TABLE domain_sessions ADD COLUMN needs_review BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- Seed default classification rules
INSERT INTO domain_classification_rules (pattern, pattern_type, classified_as, action, priority)
VALUES 
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
    ('linkedin', 'substring', 'linkedin.com', 'map', 50)
ON CONFLICT DO NOTHING;
