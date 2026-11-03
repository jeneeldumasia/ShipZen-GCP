-- 0003: bind each project to the GitHub repository its owner proved access to
-- (security finding C3). Set when a project or deployment names a github.com
-- repo the user can read with their own GitHub sign-in.

ALTER TABLE projects ADD COLUMN IF NOT EXISTS github_repo_id BIGINT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS github_repo_full_name TEXT;
