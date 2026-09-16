-- Migration to rename s3_log_uri to gcs_log_uri

ALTER TABLE builds RENAME COLUMN s3_log_uri TO gcs_log_uri;
