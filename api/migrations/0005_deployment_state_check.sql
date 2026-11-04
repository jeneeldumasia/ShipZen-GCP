-- 0005: only known deployment states. NOT VALID: enforced for new and updated
-- rows without failing on any odd historical row.

DO $$
BEGIN
    ALTER TABLE deployments ADD CONSTRAINT deployments_state_check
        CHECK (state IN ('Queued', 'Building', 'Deploying', 'Verifying',
                         'Running', 'Failed', 'Retry', 'DLQ')) NOT VALID;
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;
