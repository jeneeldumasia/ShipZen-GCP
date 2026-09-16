CREATE TABLE IF NOT EXISTS project_members (
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (project_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_project_members_user_id ON project_members(user_id);

INSERT INTO project_members (project_id, user_id, role, created_at)
SELECT p.id, u.id, 'owner', NOW()
FROM projects p
CROSS JOIN users u
WHERE u.role = 'admin'
ON CONFLICT DO NOTHING;

-- Backfill: grants admin users ownership of all pre-existing projects.
-- Required because projects created before this migration have no
-- membership rows. Without this, verify_project_access returns 403
-- for all existing projects on first deploy.
