-- Add missing idempotency_key column to domain_sessions table
-- This column is required by the process_domain_switch_event stored procedure

ALTER TABLE domain_sessions 
ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255);

-- Add index for faster lookups
CREATE INDEX IF NOT EXISTS idx_domain_sessions_idempotency_key 
ON domain_sessions(idempotency_key);

-- Verify the column was added
SELECT column_name, data_type, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'domain_sessions'
AND column_name = 'idempotency_key';
