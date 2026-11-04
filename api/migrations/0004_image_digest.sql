-- 0004: deploy images by digest (security finding C4). A tag can be moved to
-- other content; a digest (sha256:...) can't. Set by the worker after a build.

ALTER TABLE deployments ADD COLUMN IF NOT EXISTS image_digest TEXT;
