# Accounts

locus works without an account. An account keeps what you save on every device you sign in from. This page says what
an account does, what locus stores for it, and what is not built yet.

## Signing in

- **Passkeys.** You create an account by choosing a display name and making a passkey on your phone, computer or
  password manager. locus never sees a password. Sign in later with the same passkey. Browsers allow passkeys only on
  https or `localhost`, so on a plain-http address use email instead.
- **Email codes.** Type an address, get a six-digit code by email, type it back. The first code for an address creates
  an account (named after the part before the @, changeable in Settings); later codes sign in to it. A code works once,
  for ten minutes and five guesses, and is stored only as a hash. Asking for a code answers the same way whether or not
  the address has an account. Limits: 3 codes per address in 15 minutes, 10 a day, and `LOCUS_MAIL_DAILY_CAP` (default
  250) in total a day. A passkey account can add an address in Settings (a code to the new address proves it), and an
  email code counts as a fresh confirmation for deleting the account or new recovery codes. The address cannot be
  removed while it is the only way in. Mail goes out over SMTP: `LOCUS_SMTP_HOST`, `LOCUS_SMTP_PORT` (587),
  `LOCUS_SMTP_USER`, `LOCUS_SMTP_PASSWORD`, `LOCUS_MAIL_FROM` (Brevo's relay on the public site). Without them the email
  routes answer 404 and the form is hidden. For local trials only, `LOCUS_MAIL_DEV_LOG=1` writes the mail to
  `data/dev-mail.log` instead of sending it.
- **Recovery codes.** When the account is created, locus shows ten one-time recovery codes, once. Each signs you in a
  single time if you lose your passkey. locus keeps only their SHA-256 hashes.
- **ORCID.** When the server has an ORCID client (`ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET`, optional `ORCID_BASE` for
  the sandbox), you can sign in with ORCID or link your iD to an existing account. Without a client the ORCID routes
  answer 404 and the button is hidden. The redirect URI to register with ORCID is `<LOCUS_ORIGIN>/api/account/orcid/callback`.
  An ORCID attempt can only be finished in the browser that started it, and a link only by the account that started it.
- **Signing out** ends the session on the server and removes the cookie. Signing in again in the same browser ends the
  session it had before.

## What locus stores

Account data lives in its own SQLite file, `OMICS_USERS_DB` (default `data/users.db`, not in git), never in
`omics.db`. For each account: the display name and creation time; each passkey's public key, counter, transports,
creation and last-use times; hashed recovery codes; your lists and their items (and the public copy of any list you share), your watched searches and the people you follow (their ORCID, name and the datasets you marked seen; see below); a linked ORCID iD; sessions (a hash of the cookie token, the
sign-in method, times and the browser's user-agent string); and a short audit trail of sign-ins and changes. It also keeps
the times of an account's writes in the last minute, for the write quota. locus runs
no analytics. The wording users read lives in one place, `web/lib/privacy.ts`, which the in-app `/privacy` page and the
Privacy section of `/settings` render; change it together with this section when the users DB changes.

## Security, for whoever runs the server

- Sessions: a random 32-byte token in an HttpOnly, SameSite=Lax, Path=/ cookie (Secure unless
  `LOCUS_COOKIE_INSECURE=1`, for plain-http localhost only), stored server-side as SHA-256, 30 days from last use.
- Every state-changing account request must be JSON and carry the header `X-Locus-Intent: 1`, else 403
  `INTENT_REQUIRED`.
- Sign-in routes accept at most 10 requests a minute from one address and 100 a minute overall (in-process, so the
  counts reset when the API restarts). Behind the web app's `/api` rewrite the address is read from
  `X-Forwarded-For`, which a client can forge unless a proxy in front rewrites it; the overall cap still holds. A
  public deployment must have a proxy in front of the web app (the Cloudflare tunnel, Caddy or nginx) that appends the
  caller's address to `X-Forwarded-For`, because Next's rewrite keeps whatever header the client sent.
- Passkeys: relying-party id `LOCUS_RP_ID` (default `localhost`) and origin `LOCUS_ORIGIN` (default
  `http://localhost:3000`) must match the address people use. Each challenge works once and for five minutes. User
  verification (PIN, fingerprint or face) is required when creating a passkey and at every sign-in, and a response
  without it is refused, since the passkey is the only factor. A refused passkey gets one fixed message; the reason is
  logged on the server.
- ORCID: `/account/orcid/start` sets a five-minute HttpOnly cookie `__Host-locus_orcid` (`locus_orcid` under `LOCUS_COOKIE_INSECURE=1`) with a random nonce whose hash is
  stored with the OAuth state. The callback refuses a browser without the matching cookie, so a forwarded authorize or
  callback link signs no one in and links nothing. A link attempt also needs the same account to be signed in when
  ORCID sends the browser back.
- `POST /account/dev-login` signs in without a passkey for automated page checks. It exists only when
  `LOCUS_DEV_LOGIN=1` and the API's peer and every hop listed in `X-Forwarded-For` are loopback addresses. Those hops
  are what the header reports: without a proxy in front that appends the real address, a client can forge them, so the
  web app must listen on 127.0.0.1 wherever this flag is set (the page gate does). Never set it on a public server.
- Client address: `LOCUS_TRUSTED_PROXIES` is the number of proxies in front of the web app that each append the
  caller's address to `X-Forwarded-For` (default 1, for the Cloudflare tunnel alone). The API counts that many entries
  from the right and takes that one. With `0` it ignores the header and uses its peer address, so every caller behind
  the web app shares one address. A header with fewer entries than that counts as absent, and only a loopback peer
  (the web app's `/api` rewrite) is ever replaced by a forwarded address.
- An IPv6 address counts as its /64 network for every rate limit, sign-in included.
- Dev sign-in secret: when `LOCUS_DEV_LOGIN_SECRET` is set, `POST /account/dev-login` also needs the header
  `X-Locus-Dev-Secret` with exactly that value, else it answers 404 like any unknown path. Set a fresh random value
  whenever `LOCUS_DEV_LOGIN=1` runs on a machine other people can reach.
- Cookies: while cookies are Secure, the session cookie is `__Host-locus_session` and the ORCID cookie is
  `__Host-locus_orcid`. The prefix makes the browser refuse a copy set by a sibling subdomain. Under
  `LOCUS_COOKIE_INSECURE=1` they are `locus_session` and `locus_orcid`. A cookie under the other name is ignored.
- Origin: when `LOCUS_ORIGIN` is set, a state-changing request whose `Origin` header names another origin gets 403
  `ORIGIN_REFUSED`. CORS grants only the `Content-Type` header to `localhost:3000` and `:3020`, never
  `X-Locus-Intent`.
- Write quota: Every write by a signed-in account counts against one ledger of 120 a minute. It covers lists, watched
  searches, follows and settings (sign-in and sign-out have their own limits), lives in the users DB table
  `quota_events`, which keeps the last minute only, and answers 429 `RATE_LIMITED` with `Retry-After` when full.
- Storage cap: the notes, tags and snapshots of all of an account's list items together hold at most 5,000,000
  characters. A save or edit that would pass it gets 409 `STORAGE_FULL`, and a guest import leaves out the items that
  do not fit.
- The follow limit is 30 a minute per account and 60 a minute overall, half of the ORCID pace.
- Caching: every API response under `/account`, `/lists` and `/follows` carries `Cache-Control: no-store`, and the
  `/account` and `/settings` pages are rendered per request.
- Errors from account routes have one shape: `{"error": {"code", "message", "transient"}}`.

## Threat model

**What locus protects.** An account holds lists with private notes, watched searches, followed ORCID iDs, the
account's passkeys and recovery codes, and an activity log. None of it is medical or financial, but notes and follows
show what a person is working on, so only the signed-in owner can read them, and a public list shows only what its
owner chose when publishing it.

**Who it protects against.** Other websites the user visits (CSRF, login CSRF, and cookies tossed from a sibling
subdomain); other locus accounts (every row is scoped to its owner, and another account's id answers 404); anyone
guessing or brute-forcing a sign-in (passkeys with user verification, 60-bit recovery codes, per-address and overall
rate limits); a stolen session cookie on its own (deleting the account, new recovery codes, adding a passkey and
linking ORCID need a passkey or recovery-code confirmation within five minutes); and a single account or address
trying to fill the disk or spend the upstream budgets (the write ledger, the storage cap, and the follow and person
limits).

**What it does not protect against.** A compromised device or browser; anyone holding the server or the users DB
file, which is not encrypted at rest (session tokens and recovery codes are stored only as hashes); a deployment
without the front proxy, or with `LOCUS_TRUSTED_PROXIES` set wrong, where client addresses can be forged and the
per-address limits weaken; many accounts acting together within the overall limits; and identity claims upstream,
since ORCID records and Europe PMC author claims are taken as their owners wrote them.

## Saved datasets and lists

- **Save.** Every search result and dataset page has a Save control. One click keeps the dataset in your built-in
  list, Saved; a message offers "Add to a list" and Undo. The arrow beside Save opens the list picker, where you tick
  the lists that should hold the dataset or make a new one.
- **Lists** (`/lists`) shows every list with its count. A list's page (`/lists/<id>`) keeps datasets in the order you
  added them. Each dataset has a note and tags, edited in place with one Save. Named lists can be renamed or deleted
  (after a confirmation); Saved keeps its name and cannot be deleted.
- **Export.** Each list downloads as plain accessions (one a line) or as CSV with the columns accession, title,
  repository, organism, data type, samples, note, tags, added. A cell that starts with `=`, `+`, `-` or `@` gets a
  leading `'` so a spreadsheet shows it as text.
- **What a list keeps.** Besides the accession, note, tags and the time it was added, each item stores what the page
  showed when you saved it: title, repository, organism, data type and sample count. A list renders from that copy and
  never asks a repository; the dataset page has the current record.
- **Limits.** 100 lists an account (Saved included), 500 datasets a list, names up to 120 characters, descriptions up
  to 600, notes up to 10,000, and 12 tags of up to 40 characters an item.
- **Without an account** Save works into this browser only (localStorage `locus:saved`, same item shape, up to 500).
  `/lists` shows that list and says it lives only in this browser; named lists, notes and tags need an account.
- **API** (all need a session; changes need JSON and `X-Locus-Intent: 1`): `GET/POST /lists`, `GET/PATCH/DELETE
  /lists/{id}`, `POST /lists/{id|saved}/items`, `PATCH/DELETE /lists/{id|saved}/items/{accession}`,
  `GET /lists/{id}/export?format=accessions|csv`. Another account's list answers 404, as a missing one does.

## Public lists

- **Share.** On a list's page, "Share a public link" offers two choices, both unticked: show your display name, and
  include your notes. Publish makes a read-only copy at `/s/<id>`, where `<id>` is 32 random hex characters from
  Python's `secrets`. Anyone with the link can open it, signed in or not. Tags are never published.
- **What the public page shows.** The list's name and description, the date it was last published, your display name
  only if you chose it, and the first 50 datasets with what each page showed when you saved it (title, repository,
  organism, data type, samples), linked to the dataset pages; notes only if you chose them. The page is not indexed
  (`robots: noindex`) and sends no referrer.
- **A frozen copy.** The public page keeps what the list held when you published. After any change the list's page
  says so ("the public page still shows the earlier version") with "Update public page", which keeps the same link.
  Each list counts its changes, and the copy remembers the count it was taken at, so a change made in the same second
  as publishing still shows as one. When the list holds more than 50 datasets the page says "Showing the first 50 of N".
- **Stop sharing** removes the copy at once: the link then answers 404, the same as a link that never existed.
  Publishing again draws a new link. Deleting the list or the account withdraws it too.
- **Limits.** 60 publishes and updates an account in any 24 hours (counted on the server); stopping is never limited.
  No route lists share ids.
- **API.** `POST /lists/{id}/publish` with `{show_owner, include_notes}` (publish or update) and `DELETE
  /lists/{id}/publish` (owner only, JSON and `X-Locus-Intent: 1`); `GET /public/lists/{share_id}` needs no session.
  A list's summary carries `public: {share_id, published_at, show_owner, include_notes, stale}` or null.

## Watched searches

- **Watch.** Above a search's results, "Watch this search" remembers the question, today's date and the datasets the
  search shows. The home page lists your watched searches under "Watching since". Select the control again to stop
  watching.
- **New since.** When a watched search runs again, results it had not shown before are marked "new" and counted next to
  "Watching since" as "N new since your last run". Those datasets then count as seen, so the run after that marks only what arrived after it. Going
  back to the same results (from a dataset page, say) keeps that run's marks.
- **Where they live.** Signed in, watches are kept in your account and follow you to every device. Without an
  account they live in this browser (localStorage `locus:watched`, same shape) and can be brought into an account
  with the panel described below.
- **Limits.** 200 watched searches an account, a question of up to 500 characters, and up to 500 seen datasets a watch
  (past that, the oldest are dropped, and could be marked new again).
- **API** (all need a session; changes need JSON and `X-Locus-Intent: 1`): `GET /follows/questions` (newest first),
  `POST /follows/questions` with `{question, seen}` (starts watching with 201, or for a question already watched adds
  `seen` to what it has seen and keeps its start date, 200), `DELETE /follows/questions` with `{question}` in the body,
  and `POST /follows/questions/import` (below).

## Bringing this browser's saves into an account

- **When.** After you sign in, if this browser still holds datasets you saved or searches you watched as a guest, a
  strip along the bottom of the window says how many of each it has, names up to three of them, and asks whether to add
  them to your account. It sits over the bottom edge of the page, so nothing on the page moves.
- **Add** sends the saved datasets to your account's Saved list and the watched searches to your account, one request
  each, in the order this browser kept them. Adding twice changes nothing: a dataset Saved already holds keeps its note,
  tags and details, and a search the account already watches keeps its date and what it has seen. The browser's copies
  are removed only for what the server confirms it now holds. If Saved would pass 500 datasets or the account 200
  watches, the ones that fit are added and the rest stay in this browser. An entry locus cannot read (a hand-edited
  accession, say) is not sent and stays in this browser. The strip says how many of each, once: after an Add that left
  something behind, it is not offered again to that account.
- **Not now** leaves everything in this browser (saved datasets show on Lists whenever you are signed out) and is
  remembered for this browser and this account (localStorage `locus:import-declined`, a list of account ids). Another
  account signing in from the same browser is asked again.
- **Clear from this browser** removes the guest saves and watches from this browser after a confirmation, for a shared
  computer where they belong to someone else. Guest state belongs to the browser and is seen by whoever uses it.
- **API:** `POST /lists/saved/import` with `{"items": [{accession, snapshot, note?, tags?}, …]}`, at most 500 items,
  and `POST /follows/questions/import` with `{"watches": [{question, since, seen}, …]}`, at most 200, `since` a past
  day as YYYY-MM-DD. Each entry is checked exactly as a single save or watch; one invalid entry refuses the whole batch
  with 422 and adds nothing. Both answer `added`, `already`, `left_out` and `held` (added plus already). Both need a
  session, JSON and `X-Locus-Intent: 1`, and each runs as one transaction that no other change interleaves with.

## Following researchers

- **By ORCID only.** A person page searches Europe PMC by surname and initials, which mixes people who share a name.
  So the page also reads the author lists of the name's newest 100 papers and counts, per ORCID, the papers that tag
  it on that author (same surname and initials; one initial never stands in for two, so "Thoreen C" is not
  "Thoreen CC"). The page shows the ORCID and a Follow button only when all of these hold: the name is not common (at
  most 300 papers, the page's own threshold for "belongs to several people"); the ORCID is tagged on at least 3 of
  those papers and on more than half of the papers that tag any ORCID there; and the ORCID record's own public name
  agrees with the page's name (see "Names that agree" below). Otherwise the page says why: the name matches several
  people, no paper is tagged, too few are, the ORCID record is someone else's, or ORCID did not answer in time ("could
  not confirm", rechecked after 20 seconds). When locus itself is too busy to ask ORCID, the page says locus is busy
  and nothing is kept. Following a guest opens the sign-in prompt, which brings you back. The name kept with a follow
  is the one on the ORCID record, together with the person page's name it was made from, which `/following` links to.
- **Names that agree.** The surname must match (accents, case and hyphens aside). Then, by the form of the page's name:
  - The page spells the first name ("Carson C Thoreen", "Carson Thoreen") and so does the record: the first names
    must be equal, and a middle initial may be missing on either side. "Carson C Thoreen" agrees with "Carson
    Thoreen"; "Yu Zhang" does not agree with "Yang Zhang".
  - The page is in Europe PMC's form, surname then initials ("Thoreen CC", the form a paper page's author links use),
    and the record spells the first name: the record's initials must be the page's or their start, so the record may
    leave out middle initials but never add one. "Thoreen CC" agrees with "Carson Thoreen" and "Carson C Thoreen",
    not with "Carson J Thoreen" or "Kevin Thoreen"; "Thoreen C" does not agree with "Carson C Thoreen".
  - Otherwise (the record gives initials only): the initials must be equal, or one must extend the other when both
    have at least two letters. "Thoreen CC" agrees with "C. C. Thoreen", not with "C. Thoreen".

  The papers counted for an ORCID are stricter still: an author printed "Thoreen C" is never counted for the page
  "Thoreen CC", so a different "Thoreen C" with many tagged papers cannot win that page. A common name ("Wang W",
  48,000 papers) never gets Follow whatever the record says, and a split between two ORCIDs ("Zhang Y" with Yang's
  and Yu's) gives "several people".
- **What following brings.** `/following` lists, for each person, the locus datasets that their ORCID-linked papers
  deposited or cite (Europe PMC `AUTHORID:"<orcid>"`, newest 100 papers, newest paper first). The name search is never
  used, so another person's datasets cannot appear. Each dataset is marked new until you choose "Mark all as seen".
- **Coverage.** Europe PMC links only part of a person's papers to their ORCID, more often the recent ones (29 Oct:
  5 of 42 papers for Carson Thoreen). The person page says how many of the papers it read carry the ORCID, and how
  many Europe PMC links to the ORCID in all, e.g. "Europe PMC ties 5 of the 42 papers under this name to this ORCID.
  Following uses the 7 papers Europe PMC links to this ORCID, never the name search." Past 100 linked papers it says
  "the newest 100 of the 250 papers". A dataset from an older paper without the link does not show.
- **Watched searches** are listed on `/following` too, each with its link and the day watching started. The page runs
  none of them (a search uses the model), so it shows no new-dataset count for them (DECISIONS D12); opening one runs
  it and marks what is new.
- **Limits.** 200 follows an account, and at most 30 new follows a minute (each reads the ORCID record once; the
  200 check and a repeated follow read nothing). An ORCID iD that does not exist is refused, and that answer is kept 5
  minutes. Each visit to `/following` reads the 40 most recent follows on one server-wide
  pool of 4 workers, within 45 seconds; a person not read in time says so. An account reads upstream at most once
  every 10 seconds (in between, the page shows what is cached), and accounts that follow the same ORCID share one
  fetch. Each ORCID's answer is kept for 6 hours (a failure for 5 minutes), so a dataset that arrives in Europe PMC or
  locus shows within that time; person pages keep theirs 6 hours too. Calls to Europe PMC are paced to at most 5 a
  second and to ORCID at most 2 a second across the whole server (`omics_agent/pace.py`), and no call waits more than
  2 seconds for its turn: past that, and when more than 8 person reads are under way at once, the answer is 503 with
  Retry-After and the page says locus is busy. At most 8 `/following` reads run at once across the server; one more
  gets 503 at once. `/person` and `/person/identity` answers that need Europe PMC are limited to 30 a minute from
  one address and 240 overall; an IPv6 address counts as its /64, an IPv4 address as itself, and answers locus
  already holds are never counted. `LOCUS_EPMC_BASE` and `LOCUS_ORCID_BASE` point the upstream calls elsewhere (the
  page checks use fixtures).
- **API:** `GET /person/identity?name=` (anyone); `GET /follows/people`, `POST /follows/people` `{orcid, page_name}`,
  `DELETE /follows/people` `{orcid}`, `POST /follows/people/seen` `{orcid, accessions}`, `GET /follows/people/updates`.
  Changes need a session, JSON and `X-Locus-Intent: 1`. One account cannot read or change another's follows.

## Settings

`/settings` (Settings in the account menu) has five sections.

- **Account.** Change the display name (a public list keeps the name it was published with until you update it).
  Passkeys are listed with their name, when they were added and last used; each can be renamed, another can be added
  with the same passkey ceremony as creating an account, and any can be removed except the last one. Recovery codes
  show how many of ten are left; "Make ten new codes" shows the new ones once and the old ones stop working. ORCID
  shows the linked iD with Unlink (refused when ORCID is the account's only way in, i.e. no passkey), or a link button
  when ORCID is configured.
- **Following.** The people you follow and your watched searches, each with Unfollow or Stop watching.
- **Privacy.** One paragraph on what locus keeps for an account, its two cookies (the session one and the five-minute
  ORCID nonce) and that it runs no analytics, with "How accounts work" linking to `/privacy`, a static page in the app
  built from `web/lib/privacy.ts`. It works without anything being pushed or published.
- **Your data.** "Download everything as JSON" (`GET /account/export`) returns every row the users DB holds about the
  account: name, passkey names and dates, sessions (method, times, browser), how many recovery codes are left and when
  codes were used, the ORCID link, lists with items, notes, tags and the public copy, watched searches, follows and the
  account's activity log. It leaves out secrets: session token hashes, recovery code hashes, passkey public keys and the
  WebAuthn user handle. No other account's rows are included.
- **Delete account.** Deletes the account and everything in it in one transaction: the user row, passkeys, sessions on
  every device, recovery codes, the ORCID link, pending sign-in challenges, lists and items (public links answer 404 at
  once), watched searches, follows and the account's activity log. The browser's cookie is then cleared. What stays:
  one activity row with the time and "account deleted", with no user id, name or anything else that points at the
  person, so whoever runs the server can count deletions. Server logs outside the users DB are not touched: uvicorn's access log (on by default) records the client address,
  taken from `X-Forwarded-For` behind the local proxy, and the full request line, including search query strings and
  `/s/<id>` paths, and the reverse proxy on the public host logs the same. Their retention is the host's log settings.
  The sign-in rate limiter keeps addresses in process memory only, and drops each one a minute after its last attempt.
  /privacy (web/lib/privacy.ts) says all of this in plain words.
- **Confirming it is you.** Deleting the account, making new recovery codes, adding a passkey, removing a passkey,
  unlinking ORCID and linking ORCID to an account that has a passkey need a passkey or recovery-code check within the
  last five minutes. Signing in with a passkey or a recovery code counts; so does "Confirm with a passkey"
  or "Confirm with a recovery code" on the page (`POST /account/confirm/options` + `/confirm/verify`, or
  `/confirm/recovery`), which accepts only the signed-in account's own passkeys and codes and records the time on the
  session (`sessions.strong_at`). A recovery code used to confirm is spent. ORCID and the test sign-in never count.
  There is no other way to set it.
- **A new passkey cannot confirm the session that added it.** A passkey added from Settings records the session that
  added it (`credentials.added_in_session`); the confirm routes neither offer nor accept it in that session. It confirms
  from its own next sign-in on. This is defence in depth only: adding a passkey already needs a confirmation within
  the last five minutes, and that is the real guard. A passkey sign-in with the new key is strong at once, so the rule
  mostly adds friction (F7-r2-3). The residual risk is the usual step-up trade-off: a cookie stolen within five minutes
  of a confirmation can add a lasting passkey, which the owner sees only in the passkey list and the export's log.
- **An account made by ORCID.** It has no passkey and no recovery codes, so it has nothing to confirm with. Its one
  exception: it may add its first passkey within five minutes of an ORCID sign-in on this session (signing in with
  ORCID again while signed in, with the same iD, counts). Confirm says so and offers "Add a passkey". To delete such an
  account: add a passkey, sign in with it, then delete. Its linked iD can never be swapped for another one, since that
  would hand the account to whoever owns the other iD.
- **API.** `GET /account/settings`, `PATCH /account/profile`, `PATCH|DELETE /account/passkeys/{id}`,
  `POST /account/passkeys/options|verify`, `POST /account/recovery-codes`, `DELETE /account/orcid`,
  `GET /account/export`, `DELETE /account`; all JSON with `X-Locus-Intent: 1` for changes.

## Not built yet

A list cannot be reordered by hand, and the nf-core sample sheet is not offered for a
whole list yet. Email is not used, so following sends no digest; following institutions or topics, and a person without an ORCID, are not supported.
