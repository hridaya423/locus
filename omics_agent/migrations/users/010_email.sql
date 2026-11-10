-- Email sign-in (2 Nov). One address per account and one account per address, stored lower-cased. An address is only
-- ever stored after its owner typed back a code sent to it, so every row here is verified.
CREATE TABLE emails (
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  email TEXT NOT NULL UNIQUE,
  verified_at TEXT NOT NULL
);

-- Codes sent, for the per-address and daily limits (the codes themselves live hashed in `challenges`).
CREATE TABLE email_sends (
  id INTEGER PRIMARY KEY,
  email_sha256 TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX email_sends_at ON email_sends(at);
CREATE INDEX email_sends_email ON email_sends(email_sha256, at);
