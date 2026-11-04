-- 0012: users can turn deployment emails off (shipzen_common/notify.py).
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_notifications BOOLEAN NOT NULL DEFAULT TRUE;
