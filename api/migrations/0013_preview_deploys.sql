-- 0013: preview deployments for pull requests.
--   kind:      'production' (default) | 'preview' (never becomes the live release)
--   pr_number: the pull request a preview was built from
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'production';
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS pr_number INTEGER;
CREATE INDEX IF NOT EXISTS idx_deployments_previews ON deployments (project_id, pr_number) WHERE kind = 'preview';
