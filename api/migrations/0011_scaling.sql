-- 0011: per-project instance size and instance counts (shipzen_common/sizes.py).
--   min_instances = max_instances: fixed count; max > min: CPU autoscaling between them.

ALTER TABLE projects ADD COLUMN IF NOT EXISTS instance_size VARCHAR(10) NOT NULL DEFAULT 'small';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS min_instances INTEGER NOT NULL DEFAULT 1;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS max_instances INTEGER NOT NULL DEFAULT 1;

DO $$ BEGIN
    ALTER TABLE projects ADD CONSTRAINT projects_scaling_check
        CHECK (instance_size IN ('small', 'medium', 'large')
               AND min_instances >= 1 AND max_instances >= min_instances AND max_instances <= 5);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
