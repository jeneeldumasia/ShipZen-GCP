-- 0009: blue-green releases.
--   projects.live_deployment_id: the release that serves the project's stable
--     (vanity) URL. Set by the controller when a release goes live, and by an
--     instant rollback.
--   deployments.scale_down_after: a release that just stopped being live keeps
--     running until then (the grace period), so the switch has no gap and a
--     rollback within it is instant. Then the controller scales it to 0.

ALTER TABLE projects ADD COLUMN IF NOT EXISTS live_deployment_id VARCHAR(255);
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS scale_down_after TIMESTAMPTZ;

-- Existing projects: the newest running release is the live one.
UPDATE projects p SET live_deployment_id = d.deployment_id
FROM (
    SELECT DISTINCT ON (project_id) project_id, deployment_id
    FROM deployments
    WHERE state = 'Running' AND replicas > 0
    ORDER BY project_id, created_at DESC
) d
WHERE p.id = d.project_id AND p.live_deployment_id IS NULL;
