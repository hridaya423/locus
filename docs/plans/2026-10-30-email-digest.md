# Email digest (design note, not built)

Status: a design only (DECISIONS D9). Nothing here is built, no email is sent, and building it needs Juri's yes.

papertok sends an opt-in weekly email of new papers from the people a reader follows. locus could send the same kind of
email about datasets: new datasets deposited or cited by the papers of followed researchers (F5), and new results for
watched searches (F4). This note adapts papertok's ranking (papertok-inventory.md, section 2) to datasets and lists
what would have to exist before it could be built.

## What it would send

- One email a week, on Monday morning (UK time), only to accounts that opted in on /settings. The default is off.
- 3, 5 or 10 datasets, as the reader chooses. Each entry shows the accession, title, repository, organism, data type,
  sample count, and the followed person or watched search it came from, with links to its locus page and to the
  paper.
- Nothing is sent in a week with nothing new. A test email can be sent from /settings.
- Every email has a one-click unsubscribe link (RFC 8058 List-Unsubscribe-Post) that works without signing in.

## Ranking

papertok scores each candidate paper and sends the best. For datasets the score of a candidate is:

- Recency: 48 x e^(-age/10), with age in days since the dataset became public (or since its citing paper appeared,
  for a dataset found through a citation).
- Follows matched: 32 for one followed person or watched search behind the dataset, up to 48 for several.
- Reuse in place of citations (papertok caps citations at 22): up to 22 points, from how many papers in Europe PMC
  cite the accession.
- Metadata: up to 10 points when the dataset has a sample table, a processed counts table, or both.

Candidates below a minimum score are dropped. No two entries from the same followed person or search come back to
back. Datasets sent in the last 400 entries to this reader are left out. When a reader follows more than 24 people,
the people considered rotate from week to week, as in papertok, so the upstream reads stay bounded.

## What it needs before it can be built

- Juri's yes: locus asks for no email address today (D4), and this would add one to the users DB, to
  web/lib/privacy.ts and to the account export and deletion.
- A mail provider (for example Postmark, Amazon SES or the university's SMTP relay) with SPF, DKIM and DMARC set up
  for the sending domain, and its API key kept outside git.
- A verified email address per account (a confirmation link) and a stored opt-in with its time.
- A weekly job that runs outside the API process (a systemd timer), reads the follows and watches, reuses the bounded
  /updates fetch (F5) and the watched-search runs (F4) without calling the model, and records what it sent.

## Not decided

- Whether watched searches belong in the digest at all, since a search run calls the model (D12 keeps /following
  cheap for the same reason).
- The day, the time and the sender address.
- Whether the reuse points should count only papers that cite the accession in their data availability statement.
