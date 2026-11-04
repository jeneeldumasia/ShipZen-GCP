-- 0008: free vanity hostnames, <subdomain>-shipzen.jeneeldumasia.codes, that
-- always point at the project's live release. Unique among projects that still
-- exist, so a deleted project's name can be taken again.

ALTER TABLE projects ADD COLUMN IF NOT EXISTS subdomain VARCHAR(40);
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_subdomain
    ON projects (subdomain)
    WHERE subdomain IS NOT NULL AND deleted_at IS NULL;
