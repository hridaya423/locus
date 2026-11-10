-- Step-up hardening (F7-r1-1). credentials.added_in_session: the SHA-256 of the session token that added this passkey
-- from /settings (NULL for the passkey an account was created with, and for every passkey that existed before). A
-- passkey cannot confirm the session that added it, so a session cookie alone cannot add a key and then use it to
-- confirm a delete or new recovery codes.
ALTER TABLE credentials ADD COLUMN added_in_session TEXT;
