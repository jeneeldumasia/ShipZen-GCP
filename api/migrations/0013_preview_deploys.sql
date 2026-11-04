-- 0013: preview deployments for pull requests.
--   kind:      'production' (default) | 'preview' (never becomes the live release)
--   pr_number: the pull request a preview was built from
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'production';
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS pr_number INTEGER;
CREATE INDEX IF NOT EXISTS idx_deployments_previews ON deployments (project_id, pr_number) WHERE kind = 'preview';

-- One in-flight build per project applies to production only; previews get
-- one in-flight build per pull request instead.
DROP INDEX IF EXISTS idx_deployments_one_active_per_project;
CREATE UNIQUE INDEX IF NOT EXISTS idx_deployments_one_active_per_project
ON deployments (project_id)
WHERE kind = 'production' AND state IN ('Queued', 'Building', 'Deploying', 'Verifying');
CREATE UNIQUE INDEX IF NOT EXISTS idx_deployments_one_active_per_pr
ON deployments (project_id, pr_number)
WHERE kind = 'preview' AND state IN ('Queued', 'Building', 'Deploying', 'Verifying');
