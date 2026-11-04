-- 0007: 'Superseded' deployment state (task 22). When a new release goes live,
-- releases beyond the newest few scaled-down ones (kept for rollback) become
-- Superseded, and the controller's cleanup removes their Kubernetes objects and
-- GitOps files. The row stays as history.

ALTER TABLE deployments DROP CONSTRAINT IF EXISTS deployments_state_check;
ALTER TABLE deployments ADD CONSTRAINT deployments_state_check
    CHECK (state IN ('Queued', 'Building', 'Deploying', 'Verifying',
                     'Running', 'Failed', 'Retry', 'DLQ', 'Superseded')) NOT VALID;
