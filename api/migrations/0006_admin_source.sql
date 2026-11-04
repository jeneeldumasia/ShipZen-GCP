-- 0006: where a user's admin role came from (security finding M4).
--   'env'    granted because the user is listed in ADMIN_GITHUB_USERS / ADMIN_EMAILS;
--            taken away again at sign-in once they're no longer listed.
--   'manual' granted by another admin through PUT /admin/users/{id}/role; kept.
-- Existing admins are treated as 'env' (that was the only way to become one at
-- first), so removing someone from the lists now really removes their access.

ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_source VARCHAR(10);
UPDATE users SET admin_source = 'env' WHERE role = 'admin' AND admin_source IS NULL;
