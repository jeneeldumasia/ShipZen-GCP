-- 0010: what each deployment built and who started it, for the deploy history.
--   commit_*:      the commit the release was built from (worker, or the push payload)
--   branch:        branch requested
--   triggered_by:  'user:<id>' | 'push' | 'rollback' | 'redeploy:<id>' | 'preview'

ALTER TABLE deployments ADD COLUMN IF NOT EXISTS commit_sha VARCHAR(40);
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS commit_message TEXT;
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS commit_author VARCHAR(255);
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS commit_url TEXT;
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS branch VARCHAR(255);
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS triggered_by VARCHAR(80);
