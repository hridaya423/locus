-- Following (F5-r2-2). follows.page_name: the person page's name a follow was made from ("Thoreen CC", "Carson C
-- Thoreen"), so /following links back to the page that names the ORCID. NULL for follows made before this column, which
-- then link by the ORCID record's name as before.
ALTER TABLE follows ADD COLUMN page_name TEXT;
