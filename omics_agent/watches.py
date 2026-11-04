"""/follows/questions routes: watched searches kept in an account (F4).

A watch remembers a question, the day watching started (`since`) and the accessions the search has shown so far
(`seen`). When the search runs again, the web app marks results outside `seen` as new and then adds them to `seen`, so
the next run marks only what arrived after it. Guests keep the same shape in the browser (localStorage
`locus:watched`); nothing here serves them, and a guest's watches come into the account through `/import`.

Limits: 200 watches an account, a question of at most 500 characters, at most 500 accessions in `seen` (the oldest
are dropped first when a run would pass that). Sessions, the CSRF guard and the error shape come from users.py.
"""

import json
import re
from datetime import date

from fastapi import APIRouter, Depends, FastAPI, Response
from pydantic import BaseModel, Field, field_validator

from . import users
from .saved import ACCESSION
from .users import ApiError, Db, User, iso

router = APIRouter(prefix="/follows/questions", tags=["follows"], dependencies=[Depends(users.require_intent), Depends(users.write_quota)])

MAX_WATCHES = 200
QUESTION_MAX = 500
SEEN_MAX = 500
LIMITS = {"watches": MAX_WATCHES, "question": QUESTION_MAX, "seen": SEEN_MAX}
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _question(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("a watched search needs a question")
    if len(value) > QUESTION_MAX:
        raise ValueError(f"a watched question has at most {QUESTION_MAX} characters")
    return value


def _seen(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        v = str(v).strip()
        if not ACCESSION.match(v):
            raise ValueError("not an accession locus knows how to keep")
        if v not in out:
            out.append(v)
    return out


class WatchIn(BaseModel):
    """Start watching a question, or record what a new run of a watched question showed."""

    question: str
    seen: list[str] = Field(default_factory=list, max_length=SEEN_MAX)

    _q = field_validator("question")(_question)
    _s = field_validator("seen")(_seen)


class QuestionIn(BaseModel):
    question: str

    _q = field_validator("question")(_question)


class GuestWatch(WatchIn):
    """A watch as a guest's browser kept it, with the day watching started."""

    since: str

    @field_validator("since")
    @classmethod
    def _check_since(cls, value: str) -> str:
        if not DAY.match(value):
            raise ValueError("since is a day as YYYY-MM-DD")
        try:
            day = date.fromisoformat(value)
        except ValueError:
            raise ValueError("since is not a real day") from None
        if day > users.now().date():
            raise ValueError("since lies in the future")
        return value


class ImportIn(BaseModel):
    watches: list[GuestWatch] = Field(max_length=MAX_WATCHES)


def _watch(row) -> dict:
    return {"question": row["question"], "since": row["since"], "seen": json.loads(row["seen"]), "created_at": row["created_at"]}


def _find(conn, user_id: int, question: str):
    return conn.execute("SELECT * FROM watches WHERE user_id = ? AND question = ?", (user_id, question)).fetchone()


def _count(conn, user_id: int) -> int:
    return conn.execute("SELECT count(*) FROM watches WHERE user_id = ?", (user_id,)).fetchone()[0]


def merge_seen(old: list[str], new: list[str]) -> list[str]:
    """Everything shown so far, oldest first, keeping the newest SEEN_MAX when there are more."""
    out = old + [a for a in new if a not in old]
    return out[-SEEN_MAX:]


@router.get("")
def all_watches(user: User = Depends(users.current_user)) -> dict:
    """Every watched search of the account, newest first."""
    with Db() as conn:
        rows = conn.execute("SELECT * FROM watches WHERE user_id = ? ORDER BY id DESC", (user.id,)).fetchall()
    return {"watches": [_watch(r) for r in rows], "limits": LIMITS}


@router.post("")
def watch(body: WatchIn, response: Response, user: User = Depends(users.current_user)) -> dict:
    """Starts watching a question (201, since today, seen as given). For a question already watched, adds the given
    accessions to `seen` and keeps `since` (200): this is what a new run of a watched search sends."""
    with Db() as conn:
        conn.execute("BEGIN IMMEDIATE")  # the count and the insert see no other change in between
        old = _find(conn, user.id, body.question)
        if old:
            seen = merge_seen(json.loads(old["seen"]), body.seen)
            conn.execute("UPDATE watches SET seen = ? WHERE id = ?", (json.dumps(seen), old["id"]))
            return {"added": False, "watch": _watch(_find(conn, user.id, body.question))}
        if _count(conn, user.id) >= MAX_WATCHES:
            raise ApiError(409, "LIMIT_REACHED", f"An account watches at most {MAX_WATCHES} searches. Stop watching one to make room.")
        t = users.now()
        conn.execute("INSERT INTO watches (user_id, question, since, seen, created_at) VALUES (?, ?, ?, ?, ?)",
                     (user.id, body.question, t.date().isoformat(), json.dumps(body.seen), iso(t)))
        row = _find(conn, user.id, body.question)
    response.status_code = 201
    return {"added": True, "watch": _watch(row)}


@router.delete("")
def unwatch(body: QuestionIn, user: User = Depends(users.current_user)) -> dict:
    """Stops watching a question. The question goes in the JSON body, since it is free text of up to 500 characters."""
    with Db() as conn:
        if not conn.execute("DELETE FROM watches WHERE user_id = ? AND question = ?", (user.id, body.question)).rowcount:
            raise ApiError(404, "WATCH_NOT_FOUND", "Your account does not watch this search.")
    return {"ok": True}


@router.post("/import")
def import_watches(body: ImportIn, user: User = Depends(users.current_user)) -> dict:
    """Adds a guest's watched searches (newest first, as the browser keeps them) in one transaction, keeping each one's
    `since` and `seen`. Idempotent: a question the account already watches is left as it is and reported in
    "already". Past the 200-watch limit the rest are reported in "left_out". "held" lists every question of the batch
    the account now watches, so the browser knows which local copies it may drop."""
    with Db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        room = MAX_WATCHES - _count(conn, user.id)
        added: list[str] = []
        already: list[str] = []
        left_out: list[str] = []
        fits: list[GuestWatch] = []
        for w in body.watches:
            if w.question in added or w.question in already or w.question in left_out:
                continue
            if _find(conn, user.id, w.question):
                already.append(w.question)
            elif room > 0:
                fits.append(w)
                added.append(w.question)
                room -= 1
            else:
                left_out.append(w.question)
        t = iso(users.now())
        for w in reversed(fits):  # oldest first, so the newest gets the highest id and stays first
            conn.execute("INSERT INTO watches (user_id, question, since, seen, created_at) VALUES (?, ?, ?, ?, ?)",
                         (user.id, w.question, w.since, json.dumps(w.seen), t))
        if added:
            users.audit(conn, user.id, f"imported {len(added)} watched searches from a browser")
    return {"added": added, "already": already, "left_out": left_out, "held": added + already}


def install(app: FastAPI) -> None:
    """Adds the /follows/questions routes; call after users.install(app), which provides the error handlers."""
    if "/follows" not in users.SHAPED_PREFIXES:
        users.SHAPED_PREFIXES.append("/follows")
    app.include_router(router)
