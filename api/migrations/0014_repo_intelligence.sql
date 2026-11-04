-- 0014: repo intelligence.
--   build_context: the folder built (chosen on the deploy page; shipzen.yaml wins)
--   notes:         [{type: diagnosis|auto_fix, code, message, suggestion?}] from the worker
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS build_context VARCHAR(200);
ALTER TABLE deployments ADD COLUMN IF NOT EXISTS notes JSONB NOT NULL DEFAULT '[]'::jsonb;
