-- 0016: invitations, so admins can let people in without editing the
-- ALLOWED_GITHUB_USERS list in the deployment manifests (roadmap: invite flow).
--
-- An invitation names a GitHub login or a verified email address. The first
-- time that person signs in it is accepted (accepted_by = their user id) and
-- from then on it is their standing access. Revoking it (deleting the row)
-- takes the access away again.

CREATE TABLE IF NOT EXISTS user_invitations (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    github_login VARCHAR(39),
    email        VARCHAR(255),
    role         VARCHAR(10) NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    created_by   VARCHAR(255) NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ,
    accepted_at  TIMESTAMPTZ,
    accepted_by  VARCHAR(255),
    CHECK (github_login IS NOT NULL OR email IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_invitations_pending_login
    ON user_invitations (LOWER(github_login)) WHERE accepted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_invitations_pending_email
    ON user_invitations (LOWER(email)) WHERE accepted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_invitations_accepted_by
    ON user_invitations (accepted_by) WHERE accepted_by IS NOT NULL;
