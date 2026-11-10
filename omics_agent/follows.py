"""Following researchers (F5): who a person page's name is, by ORCID, and the /follows/people routes.

A person page searches Europe PMC by surname and initials, which mixes people who share a name. Following keys on
ORCID only (DECISIONS D7, after papertok's unverified-identity guard). `identity(name)` reads the name's newest 100
papers with their author lists and counts, per ORCID, the papers that tag it on the matching author (same surname,
compatible initials, where a single initial never stands in for two: "C" is not "CC"). It names an ORCID ("one", the
only case where the page offers Follow) only when all of these hold:

- the name is not common: Europe PMC finds at most COMMON_NAME papers under it (the person page's own line says a
  name past that belongs to several people);
- the ORCID is tagged on at least MIN_CLAIMED of those papers and on more than half of the papers that tag any
  ORCID on the matching author;
- the ORCID record's own public name (ORCID public API) agrees with the page's name (names_agree; docs/accounts.md
  "Names that agree" has the rule with examples). When ORCID does not answer in time, the answer is "unconfirmed"
  (could not confirm) and kept NO_RECORD_SECONDS only; when locus's own ORCID pace is full, PaceTimeout passes up as
  503 busy and nothing is kept.

Otherwise the answer is "several" (shared, or common), "none" (no tags) or "unconfirmed" (too few tags, the record is
someone else's, or the record could not be read). What a followed person brings is the datasets locus holds that
their ORCID-linked papers deposited or cite (Europe PMC `AUTHORID:"<orcid>"`, never the name query), newest paper
first, each marked new until the account marks it seen.

Bounds: 200 follows an account; one /updates call reads at most 40 of them (newest follows first) on one shared pool of
4 workers, within 45 seconds overall, at most once per account every UPDATES_EVERY seconds (in between it answers
from the cache), with one fetch per ORCID however many accounts ask at once. Answers are kept 6 hours per ORCID,
failures 5 minutes; at most UPDATES_AT_ONCE fresh /updates calls run at once. New follows are limited per account
(FOLLOW_LIMIT). /person/identity is rate-limited per caller and overall for uncached answers only, and every upstream call goes through
pace.py (Europe PMC at most 5 a second, ORCID at most 2 a second, app-wide, with a 2 s cap on any wait).
Sessions, the CSRF guard and the error shape come from users.py.
"""

import json
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait

import httpx
from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from . import pace, person, users
from .saved import ACCESSION
from .users import ApiError, Db, User, iso

router = APIRouter(prefix="/follows/people", tags=["follows"], dependencies=[Depends(users.require_intent), Depends(users.write_quota)])
public = APIRouter(tags=["follows"])

MAX_FOLLOWS = 200
FETCH_MAX = 40
FETCH_WORKERS = 4
FETCH_SECONDS = 45.0
CACHE_SECONDS = 6 * 3600
FAIL_SECONDS = 5 * 60
NO_RECORD_SECONDS = 20  # ORCID failed or timed out: says nothing about the record, so kept only moments
UPDATES_EVERY = 10.0
ORCID_SECONDS = 5.0
NAME_MAX = 200
SEEN_MAX = 500
SEEN_KEEP = 5000
PAGE = 100
COMMON_NAME = 300  # the person page's own threshold (web/components/person.tsx)
MIN_CLAIMED = 3
LIMITS = {"follows": MAX_FOLLOWS, "checked": FETCH_MAX, "seen": SEEN_MAX}
ORCID_ID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")

# Unauthenticated person reads that need upstream work (cache misses only), per caller address (an IPv6 caller by its
# /64) and overall, a minute. Cached answers cost nothing upstream and are not counted.
IDENTITY_LIMIT = users.RateLimiter(per_ip=30, overall=240)
PERSON_LIMIT = users.RateLimiter(per_ip=30, overall=240)
# Follows made, per account and overall, a minute: each new follow reads one ORCID record; 60 overall is half the ORCID pace (2/s, 120/min).
FOLLOW_LIMIT = users.RateLimiter(per_ip=30, overall=60)
# Fresh /updates calls under way at once, app-wide; one more is refused at once with 503 (each holds a server thread).
UPDATES_AT_ONCE = 8


def valid_orcid(value: str) -> bool:
    """The ORCID form and its ISO 7064 11,2 check digit."""
    if not ORCID_ID.match(value):
        return False
    total = 0
    for ch in value.replace("-", "")[:-1]:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    return value[-1] == ("X" if check == 10 else str(check))


# ---------------------------------------------------------------- caches


IDENTITIES = pace.TtlCache(CACHE_SECONDS)
WORK = pace.TtlCache(CACHE_SECONDS)
RECORDS = pace.TtlCache(CACHE_SECONDS)
LAST_UPDATES: dict[int, float] = {}


def clear_caches() -> None:
    """Empties every cache and limiter here (tests)."""
    for c in (IDENTITIES, WORK, RECORDS, person.PEOPLE):
        c.clear()
    LAST_UPDATES.clear()
    IDENTITY_LIMIT.reset()
    PERSON_LIMIT.reset()
    FOLLOW_LIMIT.reset()


# ---------------------------------------------------------------- who a name is


def initials_agree(a: str, b: str) -> bool:
    """Equal, or one extends the other when both have at least two letters: "CC" and "CCT" agree, "C" and "CC" do not."""
    return bool(a) and bool(b) and (a == b or (min(len(a), len(b)) >= 2 and (a.startswith(b) or b.startswith(a))))


def _initials(author: dict) -> str:
    return re.sub(r"[^A-Z]", "", (author.get("initials") or "").upper())


def _same_author(author: dict, surname: str, initials: str) -> bool:
    return person._plain(author.get("lastName") or "") == person._plain(surname) and initials_agree(_initials(author), initials)


def _spelled(word: str) -> str | None:
    """A given name written out ("Carson", "Yu"), folded; None for an initial or a run of initials ("C", "CC", "J.")."""
    w = word.strip(".")
    return person._plain(w) if len(w) >= 2 and not w.isupper() else None


def _record_spelled(word: str) -> str | None:
    if "." not in word and len(word) >= 3 and word.isalpha():
        return person._plain(word)
    return _spelled(word)


def _surname(words: list[str]) -> str:
    return re.sub(r"[\s'-]+", " ", person._plain(" ".join(words))).strip()


def names_agree(page: str, given: str | None, family: str | None) -> bool:
    """Whether a page's name and a record's given and family names can be the same person: the same surname (accents and
    case aside), then the same first given name when both spell it out (middle initials may be missing on one side);
    for a page in Europe PMC's form against a record that spells its first name, the record's initials must be the
    page's or their start; otherwise initials that agree (initials_agree)."""
    if not family or not given:
        return False
    query = person.author_query(page)
    if not query:
        return False
    split = person.split_name(page)
    surname, _, page_initials = query.rpartition(" ")
    if _surname(surname.split()) != _surname(family.split()):
        return False
    record_words = [w for w in given.split() if not person.TITLES.match(w)]
    if not record_words:
        return False
    record_initials = person.initials_of(record_words)
    page_first = _spelled(split[0][0]) if split and split[0] else None
    record_first = _record_spelled(record_words[0]) if record_words else None
    if page_first and record_first:
        if page_first != record_first:
            return False
        return len(page_initials) == 1 or len(record_initials) == 1 or initials_agree(page_initials, record_initials)
    if record_first and not split:
        # The page is in Europe PMC's form ("Thoreen CC", what a paper's author list links to) and the record spells its
        # first given name ("Carson Thoreen"): the record may leave out middle initials the page carries, never the
        # reverse, and the first initial must be the same. "Thoreen CC" agrees with "Carson Thoreen" and "Carson C
        # Thoreen", not with "Carson J Thoreen"; "Thoreen C" does not agree with "Carson C Thoreen".
        return page_initials.startswith(record_initials)
    return initials_agree(page_initials, record_initials)


def orcid_record(orcid: str) -> dict | None:
    """The public name on an ORCID record, {"given", "family", "credit", "display"} (each possibly None), kept 6 hours.
    A record ORCID says does not exist (404) comes back with every name None and "missing" set, kept FAIL_SECONDS.
    None when ORCID fails or does not answer within ORCID_SECONDS (not kept: that says nothing about the record).
    PaceTimeout (locus itself is busy) passes through, so callers answer "busy" and keep nothing."""
    if (hit := RECORDS.get(orcid)) is not None:
        return hit
    try:
        name = pace.orcid_get(f"/{orcid}/person", timeout=ORCID_SECONDS, deadline=time.monotonic() + ORCID_SECONDS).get("name") or {}
    except pace.PaceTimeout:
        raise
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (404, 410):
            out = {"given": None, "family": None, "credit": None, "display": None, "missing": True}
            RECORDS.put(orcid, out, FAIL_SECONDS)
            return out
        return None
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    given, family = (name.get("given-names") or {}).get("value"), (name.get("family-name") or {}).get("value")
    credit = (name.get("credit-name") or {}).get("value")
    out = {"given": given, "family": family, "credit": credit, "display": credit or " ".join(p for p in (given, family) if p) or None}
    RECORDS.put(orcid, out)
    return out


def record_agrees(page: str, record: dict) -> bool:
    """The record's given and family names, or its credit name read as a written name, agree with the page's name."""
    if names_agree(page, record.get("given"), record.get("family")):
        return True
    split = person.split_name(record.get("credit") or "")
    return bool(split) and names_agree(page, " ".join(split[0]), " ".join(split[1]))


def identity(name: str, admit=None) -> dict:
    """Which ORCID a person page's name stands for, judged from the name's newest 100 papers (see the module doc).
    status: "one" (orcid set), "several" (reason "shared" or "common"), "none", "unconfirmed" (reason "few",
    "other_name" or "no_record") or "no_name". httpx errors (PaceTimeout among them) pass through. `admit`, when
    given, is called only before upstream work (a cache miss), so cached answers never count against a rate limit.
    Every answer is kept except "no_record", which is kept NO_RECORD_SECONDS only."""
    query = person.author_query(name)
    if not query:
        return {"name": name, "status": "no_name"}
    split = person.split_name(name)
    key = f"{query}|{(_spelled(split[0][0]) if split and split[0] else '') or ''}"
    if (hit := IDENTITIES.get(key)) is not None:
        return hit | {"name": name}
    if admit is not None:
        admit()
    with pace.UPSTREAM:
        out, seconds = _identity(name, query)
    IDENTITIES.put(key, out, seconds)
    return out


def _identity(name: str, query: str) -> tuple[dict, float]:
    body = pace.epmc_get("/search", {"query": f'AUTH:"{query}"', "format": "json", "resultType": "core", "pageSize": PAGE, "sort": "P_PDATE_D desc"})
    surname, _, initials = query.rpartition(" ")
    results = body["resultList"]["result"]
    per_orcid: dict[str, int] = {}
    tagged = 0
    for r in results:
        ids = {(a.get("authorId") or {}).get("value") for a in (r.get("authorList") or {}).get("author", [])
               if (a.get("authorId") or {}).get("type") == "ORCID" and _same_author(a, surname, initials)}
        ids = {i for i in ids if i and valid_orcid(i)}
        tagged += bool(ids)
        for i in ids:
            per_orcid[i] = per_orcid.get(i, 0) + 1
    matched = body.get("hitCount", 0)
    out = {"name": name, "query": query, "matched": matched, "scanned": len(results), "tagged": tagged, "orcids": len(per_orcid)}
    if matched > COMMON_NAME:
        return out | {"status": "several", "reason": "common"}, CACHE_SECONDS
    if not per_orcid:
        return out | {"status": "none"}, CACHE_SECONDS
    top, claimed = max(per_orcid.items(), key=lambda kv: (kv[1], kv[0]))
    if claimed * 2 <= tagged:
        return out | {"status": "several", "reason": "shared"}, CACHE_SECONDS
    out |= {"orcid": top, "claimed": claimed}
    if claimed < MIN_CLAIMED:
        return out | {"status": "unconfirmed", "reason": "few"}, CACHE_SECONDS
    record = orcid_record(top)
    if record is None:
        return out | {"status": "unconfirmed", "reason": "no_record"}, NO_RECORD_SECONDS
    out["orcid_name"] = record["display"]
    if not record_agrees(name, record):
        return out | {"status": "unconfirmed", "reason": "other_name"}, CACHE_SECONDS
    linked = pace.epmc_get("/search", {"query": f'AUTHORID:"{top}"', "format": "json", "resultType": "lite", "pageSize": 1})
    return out | {"status": "one", "linked": linked.get("hitCount", 0)}, CACHE_SECONDS


# ---------------------------------------------------------------- what a followed person brings


class RecentFailure(httpx.HTTPError):
    """Europe PMC failed for this ORCID within the last FAIL_SECONDS; not asked again until then."""


def work(orcid: str, deadline: float | None = None) -> dict:
    """The datasets locus holds that the ORCID's Europe PMC papers deposited or cite, newest paper first, from at most
    the newest 100 of those papers. Kept 6 hours per ORCID; an upstream failure is kept 5 minutes (RecentFailure).
    httpx errors and PaceTimeout (not kept: it says locus was busy, not that Europe PMC failed) pass through."""
    if (hit := WORK.get(orcid)) is not None:
        if "failed" in hit:
            raise RecentFailure(hit["failed"])
        return hit
    try:
        body = pace.epmc_get("/search", {"query": f'AUTHORID:"{orcid}"', "format": "json", "resultType": "lite", "pageSize": PAGE, "sort": "P_PDATE_D desc"},
                             deadline=deadline)
        results = body["resultList"]["result"]
    except pace.PaceTimeout:
        raise
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        WORK.put(orcid, {"failed": str(error)[:200]}, FAIL_SECONDS)
        raise RecentFailure(str(error)[:200]) from error
    papers = [{"key": r["id"], "pmid": r.get("pmid"), "doi": r.get("doi"), "title": (r.get("title") or "").rstrip("."), "year": r.get("pubYear")}
              for r in results]
    linked = person.datasets_of(papers)
    datasets: list[dict] = []
    for p in papers:
        for d in linked.get(p["key"], []):
            if d["accession"] not in {x["accession"] for x in datasets}:
                datasets.append(d | {"paper": {k: p[k] for k in ("title", "year", "pmid", "doi")}})
    out = {"linked": body.get("hitCount", 0), "read": len(papers), "datasets": datasets}
    WORK.put(orcid, out)
    return out


# One pool for every /updates call, and at most one fetch in flight per ORCID that every caller shares.
POOL = ThreadPoolExecutor(max_workers=FETCH_WORKERS, thread_name_prefix="follows")
INFLIGHT: dict[str, Future] = {}
INFLIGHT_LOCK = threading.RLock()
UPDATES_GATE = pace.Gate(UPDATES_AT_ONCE)


def _fetch(orcid: str, deadline: float) -> Future:
    with INFLIGHT_LOCK:
        future = INFLIGHT.get(orcid)
        if future is None:
            future = POOL.submit(work, orcid, deadline)
            INFLIGHT[orcid] = future
            future.add_done_callback(lambda f, o=orcid: _landed(o, f))
        return future


def _landed(orcid: str, future: Future) -> None:
    with INFLIGHT_LOCK:
        if INFLIGHT.get(orcid) is future:
            del INFLIGHT[orcid]


# ---------------------------------------------------------------- routes


def _orcid(value: str) -> str:
    value = value.strip().removeprefix("https://orcid.org/").removeprefix("http://orcid.org/").upper()
    if not valid_orcid(value):
        raise ValueError("not a valid ORCID iD")
    return value


class OrcidIn(BaseModel):
    orcid: str

    _o = field_validator("orcid")(_orcid)


class FollowIn(OrcidIn):
    display_name: str | None = Field(default=None, max_length=NAME_MAX)  # accepted for older clients, not used
    # The person page's name the follow was made from ("Thoreen CC", "Carson C Thoreen"), so /following links back to
    # the page that names this ORCID. Only ever shown to the account that made the follow.
    page_name: str | None = Field(default=None, max_length=120)

    @field_validator("page_name")
    @classmethod
    def _page_name(cls, value: str | None) -> str | None:
        value = " ".join((value or "").split())
        return value if len(value) >= 3 and person.author_query(value) else None


class SeenIn(OrcidIn):
    accessions: list[str] = Field(max_length=SEEN_MAX)

    @field_validator("accessions")
    @classmethod
    def _accessions(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for v in values:
            v = str(v).strip()
            if not ACCESSION.match(v):
                raise ValueError("not an accession locus knows how to keep")
            if v not in out:
                out.append(v)
        return out


def _follow(row) -> dict:
    return {"orcid": row["orcid"], "display_name": row["display_name"], "page_name": row["page_name"], "followed_at": row["followed_at"],
            "seen": json.loads(row["seen"])}


def _rows(user_id: int) -> list:
    with Db() as conn:
        return conn.execute("SELECT * FROM follows WHERE user_id = ? AND kind = 'person' ORDER BY id DESC", (user_id,)).fetchall()


@router.get("")
def all_follows(user: User = Depends(users.current_user)) -> dict:
    """Every person the account follows, newest follow first. Reads nothing upstream."""
    return {"follows": [_follow(r) for r in _rows(user.id)], "limits": LIMITS}


@router.post("")
def follow(body: FollowIn, response: Response, user: User = Depends(users.current_user)) -> dict:
    """Follows a person by ORCID (201); following someone already followed changes nothing (200). The name kept is the
    one on the ORCID record, read here; the client's display_name is not used. The duplicate and the 200-follow checks
    come before the ORCID read, and an account may make at most FOLLOW_LIMIT.per_ip follows a minute, so no account can
    spend the app-wide ORCID pace that person pages need."""
    with Db() as conn:
        if conn.execute("SELECT 1 FROM follows WHERE user_id = ? AND kind = 'person' AND orcid = ?", (user.id, body.orcid)).fetchone():
            return {"added": False}
        if conn.execute("SELECT count(*) FROM follows WHERE user_id = ?", (user.id,)).fetchone()[0] >= MAX_FOLLOWS:
            raise ApiError(409, "LIMIT_REACHED", f"An account follows at most {MAX_FOLLOWS} people. Unfollow someone to make room.")
    FOLLOW_LIMIT.check(f"account:{user.id}")
    try:
        record = orcid_record(body.orcid)
    except pace.PaceTimeout:
        raise ApiError(503, "BUSY", "locus is reading ORCID for many people at once. Please try again in a few seconds.", transient=True,
                       headers={"Retry-After": str(pace.RETRY_AFTER)})
    if record is None:
        raise ApiError(503, "UPSTREAM_FAILED", "ORCID did not answer, so locus could not confirm whose record this is. Please try again.", transient=True)
    if record.get("missing"):
        raise ApiError(404, "ORCID_NOT_FOUND", "ORCID has no record with this iD.")
    if not record["display"]:
        raise ApiError(422, "ORCID_NO_NAME", "This ORCID record shows no public name, so locus cannot follow it.")
    with Db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM follows WHERE user_id = ? AND kind = 'person' AND orcid = ?", (user.id, body.orcid)).fetchone():
            return {"added": False}
        if conn.execute("SELECT count(*) FROM follows WHERE user_id = ?", (user.id,)).fetchone()[0] >= MAX_FOLLOWS:
            raise ApiError(409, "LIMIT_REACHED", f"An account follows at most {MAX_FOLLOWS} people. Unfollow someone to make room.")
        conn.execute("INSERT INTO follows (user_id, kind, orcid, display_name, page_name, followed_at) VALUES (?, 'person', ?, ?, ?, ?)",
                     (user.id, body.orcid, record["display"][:NAME_MAX], body.page_name, iso(users.now())))
    response.status_code = 201
    return {"added": True, "display_name": record["display"][:NAME_MAX]}


@router.delete("")
def unfollow(body: OrcidIn, user: User = Depends(users.current_user)) -> dict:
    with Db() as conn:
        if not conn.execute("DELETE FROM follows WHERE user_id = ? AND kind = 'person' AND orcid = ?", (user.id, body.orcid)).rowcount:
            raise ApiError(404, "FOLLOW_NOT_FOUND", "Your account does not follow this person.")
    return {"ok": True}


@router.post("/seen")
def mark_seen(body: SeenIn, user: User = Depends(users.current_user)) -> dict:
    """Marks datasets of a followed person as seen (at most 500 a call), keeping the newest 5000."""
    with Db() as conn:
        row = conn.execute("SELECT * FROM follows WHERE user_id = ? AND kind = 'person' AND orcid = ?", (user.id, body.orcid)).fetchone()
        if not row:
            raise ApiError(404, "FOLLOW_NOT_FOUND", "Your account does not follow this person.")
        old = json.loads(row["seen"])
        seen = (old + [a for a in body.accessions if a not in old])[-SEEN_KEEP:]
        conn.execute("UPDATE follows SET seen = ? WHERE id = ?", (json.dumps(seen), row["id"]))
    return {"seen": seen}


@router.get("/updates")
def updates(user: User = Depends(users.current_user)) -> dict:
    """For each followed person (the newest 40 follows), the datasets their ORCID-linked papers deposited or cite, each
    marked new unless seen. status per person: "ok", "failed" (Europe PMC refused or broke, now or in the last 5
    minutes), "late" (not read within the 45 s budget, or locus was too busy), "wait" (this account asked moments
    ago; only cached answers are given until UPDATES_EVERY seconds have passed) or "not_checked" (past the first 40)."""
    rows = _rows(user.id)
    t = time.monotonic()
    with INFLIGHT_LOCK:
        fresh = t - LAST_UPDATES.get(user.id, -UPDATES_EVERY) >= UPDATES_EVERY
        if fresh:
            for key in [k for k, v in LAST_UPDATES.items() if t - v >= UPDATES_EVERY]:
                del LAST_UPDATES[key]
            LAST_UPDATES[user.id] = t
    answers: dict[str, tuple[str, dict | None]] = {}
    if fresh and rows:
        try:
            with UPDATES_GATE:
                deadline = t + FETCH_SECONDS
                futures = {_fetch(r["orcid"], deadline): r["orcid"] for r in rows[:FETCH_MAX]}
                wait(futures, timeout=FETCH_SECONDS)
        except pace.PaceTimeout:
            with INFLIGHT_LOCK:
                if LAST_UPDATES.get(user.id) == t:
                    del LAST_UPDATES[user.id]
            raise ApiError(503, "BUSY", "locus is checking followed people for many accounts at once. Please try again in a few seconds.",
                           transient=True, headers={"Retry-After": str(pace.RETRY_AFTER)})
        for future, orcid in futures.items():
            if not future.done() or isinstance(future.exception(), pace.PaceTimeout):
                answers[orcid] = ("late", None)
            elif future.exception() is not None:
                answers[orcid] = ("failed", None)
            else:
                answers[orcid] = ("ok", future.result())
    else:
        for r in rows[:FETCH_MAX]:
            hit = WORK.get(r["orcid"])
            answers[r["orcid"]] = ("wait", None) if hit is None else ("failed", None) if "failed" in hit else ("ok", hit)
    people = []
    for r in rows:
        status, got = answers.get(r["orcid"], ("not_checked", None))
        entry = _follow(r) | {"status": status}
        if got is not None:
            seen = set(entry["seen"])
            entry |= {"linked": got["linked"], "read": got["read"], "datasets": [d | {"new": d["accession"] not in seen} for d in got["datasets"]]}
            entry["new"] = sum(d["new"] for d in entry["datasets"])
        people.append(entry)
    return {"people": people, "limits": LIMITS}


@public.get("/person/identity")
def person_identity(request: Request, name: str = Query(min_length=3, max_length=120)) -> dict:
    """Which ORCID a contributor's name stands for, as Europe PMC's ORCID tags and the ORCID record show it (see
    identity()). Answers that need upstream work: at most 30 a minute from one address (an IPv6 /64) and 240 overall;
    cached answers are not counted. 503 with Retry-After when locus is busy."""
    ip = users.client_ip(request)
    try:
        return identity(name, admit=lambda: IDENTITY_LIMIT.check(ip))
    except pace.PaceTimeout:
        raise ApiError(503, "BUSY", "locus is reading Europe PMC for many people at once. Please try again in a few seconds.", transient=True,
                       headers={"Retry-After": str(pace.RETRY_AFTER)})
    except (httpx.HTTPError, KeyError, ValueError):
        raise ApiError(502, "UPSTREAM_FAILED", "Europe PMC did not answer. Please try again.", transient=True)


def install(app: FastAPI) -> None:
    """Adds /follows/people and /person/identity; call after users.install(app), which provides the error handlers."""
    if "/follows" not in users.SHAPED_PREFIXES:
        users.SHAPED_PREFIXES.append("/follows")
    app.include_router(router)
    app.include_router(public)
