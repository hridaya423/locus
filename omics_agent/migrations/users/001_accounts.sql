-- Accounts core (F1). Times are UTC ISO-8601 strings ("2026-10-29T22:20:00Z"), so they sort and compare as text.
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  display_name TEXT NOT NULL,
  user_handle TEXT NOT NULL UNIQUE          -- WebAuthn user.id, base64url of 32 random bytes
);

CREATE TABLE credentials (
  credential_id TEXT PRIMARY KEY,           -- base64url
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  public_key BLOB NOT NULL,
  sign_count INTEGER NOT NULL DEFAULT 0,
  transports TEXT NOT NULL DEFAULT '[]',    -- JSON list
  created_at TEXT NOT NULL,
  last_used_at TEXT,
  nickname TEXT NOT NULL DEFAULT ''
);
CREATE INDEX credentials_user ON credentials(user_id);

CREATE TABLE sessions (
  token_sha256 TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  method TEXT NOT NULL,                     -- passkey, recovery, orcid, dev
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  user_agent TEXT NOT NULL DEFAULT ''
);
CREATE INDEX sessions_user ON sessions(user_id);

CREATE TABLE recovery_codes (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_sha256 TEXT NOT NULL UNIQUE,
  used_at TEXT
);
CREATE INDEX recovery_codes_user ON recovery_codes(user_id);

CREATE TABLE orcid_links (
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  orcid TEXT NOT NULL UNIQUE,
  linked_at TEXT NOT NULL
);

-- Single-use, short-lived challenges: WebAuthn ceremonies and ORCID OAuth state.
CREATE TABLE challenges (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,                       -- register, login, orcid
  challenge TEXT NOT NULL,                  -- base64url
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  payload TEXT NOT NULL DEFAULT '{}',       -- JSON
  expires_at TEXT NOT NULL
);

CREATE TABLE audit (
  id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  at TEXT NOT NULL,
  event TEXT NOT NULL
);
CREATE INDEX audit_user ON audit(user_id);
