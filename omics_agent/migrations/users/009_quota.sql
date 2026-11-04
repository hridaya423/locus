-- Write quota ledger (F9): one row per state-changing request of a signed-in account, kept for one minute.
CREATE TABLE quota_events (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, at TEXT NOT NULL);
CREATE INDEX quota_events_user_at ON quota_events (user_id, at);
