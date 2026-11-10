-- Public lists (F6). lists.share_id (002) is set while a list is public; share_snapshot holds what the public page
-- shows, frozen at the last publish or update: name, description, the owner's display name only if they chose to show
-- it, and at most 50 items (notes only if the owner chose to include them; tags never). JSON, NULL while private.
ALTER TABLE lists ADD COLUMN share_snapshot TEXT;
