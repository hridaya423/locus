-- Followed researchers (F5). A person is followed by ORCID only, never by a bare name (DECISIONS D7): following uses
-- the papers Europe PMC links to that ORCID, so no one else's datasets appear.
-- `seen` holds the accessions the account has marked as seen for this person; the others show as new on /following.
CREATE TABLE follows (
  id INTEGER PRIMARY KEY,                   -- newest follow has the highest id; lists show newest first
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'person' CHECK (kind = 'person'),
  orcid TEXT NOT NULL,                      -- 0000-0000-0000-000X, checksum verified
  display_name TEXT NOT NULL,               -- at most 200 characters, as the person page showed it
  followed_at TEXT NOT NULL,
  seen TEXT NOT NULL DEFAULT '[]',          -- JSON list of at most 500 accessions
  UNIQUE (user_id, kind, orcid)
);
