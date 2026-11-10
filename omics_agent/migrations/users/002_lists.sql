-- Saved datasets and lists (F2). Each account has one built-in "Saved" list (is_builtin = 1) plus named lists.
-- Items keep the order they were added (list_items.id); note and tags belong to the item, not the list.
CREATE TABLE lists (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,                       -- at most 120 characters
  description TEXT NOT NULL DEFAULT '',     -- at most 600 characters
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,                 -- moves on any change to the list or its items
  share_id TEXT UNIQUE,                     -- public lists (F6): random 32-hex, NULL while private
  published_at TEXT,
  is_builtin INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX lists_user ON lists(user_id);
CREATE UNIQUE INDEX lists_one_builtin ON lists(user_id) WHERE is_builtin = 1;

CREATE TABLE list_items (
  id INTEGER PRIMARY KEY,                   -- insertion order is the list's order
  list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
  accession TEXT NOT NULL,
  added_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',            -- at most 10,000 characters
  tags TEXT NOT NULL DEFAULT '[]',          -- JSON list: at most 12 tags of at most 40 characters
  snapshot TEXT NOT NULL DEFAULT '{}',      -- JSON {title, source, organism, modality, samples} as the page showed it
  UNIQUE (list_id, accession)
);
CREATE INDEX list_items_accession ON list_items(accession);
