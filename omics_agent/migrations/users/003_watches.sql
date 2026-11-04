-- Watched searches kept in an account (F4). A guest keeps the same shape in the browser (localStorage `locus:watched`).
-- `seen` holds the accessions the search has shown so far; a later run marks the others as new and adds them.
CREATE TABLE watches (
  id INTEGER PRIMARY KEY,                   -- newest watch has the highest id; lists show newest first
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question TEXT NOT NULL,                   -- at most 500 characters, trimmed
  since TEXT NOT NULL,                      -- YYYY-MM-DD, the day watching started
  seen TEXT NOT NULL DEFAULT '[]',          -- JSON list of at most 500 accessions
  created_at TEXT NOT NULL,
  UNIQUE (user_id, question)
);
