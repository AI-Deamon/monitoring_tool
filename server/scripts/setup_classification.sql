-- SentinelEdge Domain Classification Tables Setup
-- Run this SQL script in your PostgreSQL database

-- ============================================================================
-- 1. CREATE CLASSIFICATION RULES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS domain_classification_rules (
    id SERIAL PRIMARY KEY,
    pattern VARCHAR(500) NOT NULL,
    pattern_type VARCHAR(20) DEFAULT 'substring' CHECK (pattern_type IN ('substring', 'regex', 'exact')),
    classified_as VARCHAR(200) NOT NULL,
    action VARCHAR(20) DEFAULT 'map' CHECK (action IN ('map', 'ignore', 'needs_review')),
    priority INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT TRUE,
    match_count INTEGER DEFAULT 0,
    last_matched_at TIMESTAMP,
    created_by VARCHAR(100) DEFAULT 'admin',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create index for fast pattern matching
CREATE INDEX IF NOT EXISTS idx_classification_rules_pattern 
    ON domain_classification_rules(pattern);
CREATE INDEX IF NOT EXISTS idx_classification_rules_active 
    ON domain_classification_rules(is_active, priority);

-- ============================================================================
-- 2. ADD CLASSIFICATION COLUMNS TO domain_sessions (if missing)
-- ============================================================================
-- Note: Using snake_case to match existing code

ALTER TABLE domain_sessions ADD COLUMN IF NOT EXISTS domain VARCHAR(200);
ALTER TABLE domain_sessions ADD COLUMN IF NOT EXISTS domain_source VARCHAR(50) DEFAULT 'agent';
ALTER TABLE domain_sessions ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT TRUE;

-- Create indexes for classification queries
CREATE INDEX IF NOT EXISTS idx_domain_sessions_needs_review 
    ON domain_sessions(needs_review) WHERE needs_review = TRUE;
CREATE INDEX IF NOT EXISTS idx_domain_sessions_domain 
    ON domain_sessions(domain);

-- ============================================================================
-- 3. INSERT DEFAULT CLASSIFICATION RULES
-- ============================================================================
INSERT INTO domain_classification_rules (pattern, pattern_type, classified_as, action, priority) 
VALUES
    -- Common patterns
    ('perplexity.ai', 'substring', 'perplexity.com', 'map', 10),
    ('accounts.google.com', 'substring', 'google.com', 'map', 10),
    ('mail.google.com', 'substring', 'gmail.com', 'map', 10),
    ('drive.google.com', 'substring', 'google-drive.com', 'map', 10),
    ('docs.google.com', 'substring', 'google-docs.com', 'map', 10),
    
    -- Ignore localhost/internal
    ('localhost', 'substring', 'localhost', 'ignore', 5),
    ('127.0.0.1', 'substring', 'localhost', 'ignore', 5),
    ('192.168.', 'substring', 'internal', 'ignore', 5),
    
    -- Security products
    ('paloaltonetwork', 'substring', 'cortex-xdr.com', 'map', 10),
    ('paloalto', 'substring', 'cortex-xdr.com', 'map', 15),
    
    -- Social/Entertainment
    ('youtube', 'substring', 'youtube.com', 'map', 100),
    ('facebook', 'substring', 'facebook.com', 'map', 100),
    ('instagram', 'substring', 'instagram.com', 'map', 100),
    ('twitter', 'substring', 'twitter.com', 'map', 100),
    ('x.com', 'exact', 'twitter.com', 'map', 100),
    ('netflix', 'substring', 'netflix.com', 'map', 100),
    ('reddit', 'substring', 'reddit.com', 'map', 100),
    
    -- Productivity
    ('chatgpt', 'substring', 'chatgpt.com', 'map', 100),
    ('openai', 'substring', 'openai.com', 'map', 100),
    ('slack', 'substring', 'slack.com', 'map', 50),
    ('notion', 'substring', 'notion.so', 'map', 50),
    ('github', 'substring', 'github.com', 'map', 50),
    ('stackoverflow', 'substring', 'stackoverflow.com', 'map', 50),
    ('linkedin', 'substring', 'linkedin.com', 'map', 100)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 4. VERIFY SETUP
-- ============================================================================
SELECT 'Classification rules created:' as status, COUNT(*) as count FROM domain_classification_rules;
SELECT 'Domain sessions with needs_review:' as status, COUNT(*) as count FROM domain_sessions WHERE needs_review = TRUE;
