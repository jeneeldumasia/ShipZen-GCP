-- 0002: repair databases created from the old second schema copy
-- (infra/system/schema-configmap.yaml, now removed). It differed from
-- api/schema.sql: builds.s3_log_uri instead of gcs_log_uri, no projects.repo_url
-- / branch, and audit_logs.project_id ON DELETE CASCADE instead of SET NULL.
-- Each step only acts when the old shape is found.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'builds' AND column_name = 's3_log_uri')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'builds' AND column_name = 'gcs_log_uri') THEN
        ALTER TABLE builds RENAME COLUMN s3_log_uri TO gcs_log_uri;
    END IF;
END $$;

ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_url TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS branch VARCHAR(255) DEFAULT 'main';

-- audit_logs.project_id must be ON DELETE SET NULL (keep the log when a
-- project goes). Recreate the foreign key if it was created as CASCADE.
DO $$
DECLARE
    fk_name TEXT;
BEGIN
    SELECT con.conname INTO fk_name
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE rel.relname = 'audit_logs' AND con.contype = 'f' AND con.confdeltype = 'c';
    IF fk_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE audit_logs DROP CONSTRAINT %I', fk_name);
        ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_project_id_fkey
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL;
    END IF;
END $$;

-- One in-flight deployment per project. Skipped (with a notice) if existing
-- rows already break the rule; the API also checks before inserting.
DO $$
BEGIN
    CREATE UNIQUE INDEX IF NOT EXISTS idx_deployments_one_active_per_project
        ON deployments (project_id)
        WHERE state IN ('Queued', 'Building', 'Deploying', 'Verifying');
EXCEPTION WHEN unique_violation THEN
    RAISE NOTICE 'idx_deployments_one_active_per_project not created: a project has several active deployments';
END $$;
