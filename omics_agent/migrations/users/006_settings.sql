-- Settings (F7). sessions.strong_at: when this session last saw a passkey or recovery-code sign-in (a new sign-in or a
-- confirmation from /settings). Deleting the account and regenerating recovery codes need one within five minutes.
-- A dev sign-in or an ORCID sign-in never sets it.
ALTER TABLE sessions ADD COLUMN strong_at TEXT;
UPDATE sessions SET strong_at = created_at WHERE method IN ('passkey', 'recovery');

-- Public lists (F6-r1-1). lists.rev counts every change to a list or its items; published_rev is the rev the public
-- copy was taken at. The copy is stale when they differ, which needs no timestamp comparison (two changes in the same
-- second used to look like none).
ALTER TABLE lists ADD COLUMN rev INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lists ADD COLUMN published_rev INTEGER;
UPDATE lists SET published_rev = rev WHERE share_id IS NOT NULL AND updated_at <= published_at;
