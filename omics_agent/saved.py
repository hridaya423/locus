"""/lists routes: the built-in "Saved" list and named lists of datasets (papertok's lists, adapted to accessions).

Every account has one built-in list, "Saved", created when first needed, plus up to 100 named lists. A list holds at
most 500 datasets in the order they were added. Each item carries the user's note and tags and a snapshot of what the
page showed when it was saved (title, repository, organism, data type, samples), so a list renders without asking any
repository again. Guests keep the same item shape in the browser (localStorage `locus:saved`); nothing here serves them.

Sessions, the CSRF guard and the error shape come from users.py.
"""

import csv
import io
import json
import re
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Response
from pydantic import BaseModel, Field, field_validator

from . import users
from .users import ApiError, Db, User, iso

router = APIRouter(prefix="/lists", tags=["lists"], dependencies=[Depends(users.require_intent), Depends(users.write_quota)])

SAVED = "Saved"
MAX_LISTS = 100
MAX_ITEMS = 500
NAME_MAX = 120
DESCRIPTION_MAX = 600
NOTE_MAX = 10_000
TAGS_MAX = 12
TAG_MAX = 40
ACCESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
# Display names of repositories whose id is not already readable; the web app's repositoryName uses the same table.
REPOSITORY_NAMES = {"MetabolomicsWorkbench": "Metabolomics Workbench", "ExpressionAtlas": "Expression Atlas", "PanoramaPublic": "Panorama Public"}
PUBLIC_ITEMS = 50  # items a public page shows (papertok's limit)
PUBLISH_PER_DAY = 60  # publishes and updates per account in any 24 hours
SHARE_ID = re.compile(r"^[0-9a-f]{32}$")
STORAGE_MAX = 5_000_000
LIMITS = {"public_items": PUBLIC_ITEMS, "lists": MAX_LISTS, "items": MAX_ITEMS, "name": NAME_MAX, "description": DESCRIPTION_MAX, "note": NOTE_MAX, "tags": TAGS_MAX, "tag": TAG_MAX, "storage": STORAGE_MAX}


# ---------------------------------------------------------------- request bodies


def _name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("a list needs a name")
    if len(value) > NAME_MAX:
        raise ValueError(f"a list name has at most {NAME_MAX} characters")
    return value


def clean_tags(tags: list[str]) -> list[str]:
    """Trimmed, single-spaced, without repeats (ignoring case), in the order given."""
    out: list[str] = []
    for tag in tags:
        tag = " ".join(str(tag).split())
        if not tag:
            continue
        if len(tag) > TAG_MAX:
            raise ValueError(f"a tag has at most {TAG_MAX} characters")
        if tag.lower() not in {t.lower() for t in out}:
            out.append(tag)
    if len(out) > TAGS_MAX:
        raise ValueError(f"an item has at most {TAGS_MAX} tags")
    return out


class Snapshot(BaseModel):
    """What the search hit or dataset record showed when the item was saved. Only these fields are kept."""

    title: str = Field("", max_length=1000)
    source: str = Field("", max_length=60)
    organism: str = Field("", max_length=500)
    modality: str = Field("", max_length=500)  # the readable data type, as the page showed it ("RNA-seq")
    samples: int | None = Field(None, ge=0)


class ListIn(BaseModel):
    name: str
    description: str = Field("", max_length=DESCRIPTION_MAX)

    _n = field_validator("name")(_name)


class ListPatch(BaseModel):
    name: str | None = None
    description: str | None = Field(None, max_length=DESCRIPTION_MAX)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        return None if value is None else _name(value)


class ItemIn(BaseModel):
    accession: str
    snapshot: Snapshot = Field(default_factory=Snapshot)
    note: str = Field("", max_length=NOTE_MAX)
    tags: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("accession")
    @classmethod
    def _check_accession(cls, value: str) -> str:
        value = value.strip()
        if not ACCESSION.match(value):
            raise ValueError("not an accession locus knows how to keep")
        return value

    _t = field_validator("tags")(clean_tags)


class ItemPatch(BaseModel):
    note: str | None = Field(None, max_length=NOTE_MAX)
    tags: list[str] | None = Field(None, max_length=100)

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else clean_tags(value)


class Empty(BaseModel):
    pass


class PublishIn(BaseModel):
    """Choices made at publish time. Both are off unless the owner ticks them: the public page then shows neither the
    owner's name nor their notes. Tags are never published."""

    show_owner: bool = False
    include_notes: bool = False


# ---------------------------------------------------------------- storage


def saved_list_id(conn, user_id: int) -> int:
    """The user's built-in "Saved" list, created on first use."""
    row = conn.execute("SELECT id FROM lists WHERE user_id = ? AND is_builtin = 1", (user_id,)).fetchone()
    if row:
        return row["id"]
    t = iso(users.now())
    cur = conn.execute(
        "INSERT INTO lists (user_id, name, created_at, updated_at, is_builtin) VALUES (?, ?, ?, ?, 1) ON CONFLICT DO NOTHING",
        (user_id, SAVED, t, t),
    )
    if cur.rowcount:
        return cur.lastrowid
    return conn.execute("SELECT id FROM lists WHERE user_id = ? AND is_builtin = 1", (user_id,)).fetchone()["id"]


def _summary(row) -> dict:
    shared = json.loads(row["share_snapshot"]) if row["share_id"] and row["share_snapshot"] else None
    return {
        "id": row["id"], "name": row["name"], "description": row["description"], "builtin": bool(row["is_builtin"]),
        "count": row["count"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        # Only the owner ever sees this summary. "stale": the list changed after the public page was last updated, told by
        # the list's change counter (rev) against the one stored at publish, never by comparing timestamps.
        "public": None if shared is None else {
            "share_id": row["share_id"], "published_at": row["published_at"], "show_owner": shared["show_owner"],
            "include_notes": shared["include_notes"], "stale": row["rev"] != row["published_rev"],
        },
    }


_SUMMARY = (
    "SELECT l.*, (SELECT count(*) FROM list_items i WHERE i.list_id = l.id) AS count FROM lists l "
)


def _own(conn, user_id: int, list_id: int):
    """The list if this user owns it; 404 otherwise (another account's list looks the same as a missing one)."""
    row = conn.execute(_SUMMARY + "WHERE l.id = ? AND l.user_id = ?", (list_id, user_id)).fetchone()
    if not row:
        raise ApiError(404, "LIST_NOT_FOUND", "There is no such list in your account.")
    return row


def _touch(conn, list_id: int) -> None:
    """Records a change to a list or its items: a new updated_at and the next rev (what the stale check compares)."""
    conn.execute("UPDATE lists SET updated_at = ?, rev = rev + 1 WHERE id = ?", (iso(users.now()), list_id))


def _item(row) -> dict:
    return {
        "accession": row["accession"], "added_at": row["added_at"], "note": row["note"],
        "tags": json.loads(row["tags"]), "snapshot": json.loads(row["snapshot"]),
    }


def _items(conn, list_id: int) -> list[dict]:
    return [_item(r) for r in conn.execute("SELECT * FROM list_items WHERE list_id = ? ORDER BY id", (list_id,))]


def _name_free(conn, user_id: int, name: str, but: int | None = None) -> None:
    clash = conn.execute("SELECT id FROM lists WHERE user_id = ? AND lower(name) = lower(?) AND id IS NOT ?", (user_id, name, but)).fetchone()
    if clash:
        raise ApiError(409, "NAME_TAKEN", f"You already have a list called {name}.")


# ---------------------------------------------------------------- routes


@router.get("")
def all_lists(user: User = Depends(users.current_user)) -> dict:
    """Every list of the account with its item count (Saved first, then newest first), and which lists hold each
    accession, so a page can mark what is already saved with one request."""
    with Db() as conn:
        saved_list_id(conn, user.id)
        rows = conn.execute(_SUMMARY + "WHERE l.user_id = ? ORDER BY l.is_builtin DESC, l.created_at DESC, l.id DESC", (user.id,)).fetchall()
        holds: dict[str, list[int]] = {}
        for r in conn.execute("SELECT i.accession, i.list_id FROM list_items i JOIN lists l ON l.id = i.list_id WHERE l.user_id = ? ORDER BY i.id", (user.id,)):
            holds.setdefault(r["accession"], []).append(r["list_id"])
    return {"lists": [_summary(r) for r in rows], "holds": holds, "limits": LIMITS}


@router.post("", status_code=201)
def create_list(body: ListIn, user: User = Depends(users.current_user)) -> dict:
    with Db() as conn:
        saved_list_id(conn, user.id)
        if conn.execute("SELECT count(*) FROM lists WHERE user_id = ?", (user.id,)).fetchone()[0] >= MAX_LISTS:
            raise ApiError(409, "LIMIT_REACHED", f"An account holds at most {MAX_LISTS} lists. Delete one to make room.")
        _name_free(conn, user.id, body.name)
        t = iso(users.now())
        cur = conn.execute("INSERT INTO lists (user_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                           (user.id, body.name, body.description.strip(), t, t))
        return {"list": _summary(_own(conn, user.id, cur.lastrowid)), "items": []}


@router.get("/{list_id}")
def one_list(list_id: int, user: User = Depends(users.current_user)) -> dict:
    with Db() as conn:
        row = _own(conn, user.id, list_id)
        return {"list": _summary(row), "items": _items(conn, list_id), "limits": LIMITS}


@router.patch("/{list_id}")
def edit_list(list_id: int, body: ListPatch, user: User = Depends(users.current_user)) -> dict:
    with Db() as conn:
        row = _own(conn, user.id, list_id)
        changed = False
        if body.name is not None and body.name != row["name"]:
            if row["is_builtin"]:
                raise ApiError(400, "BUILTIN_LIST", "The Saved list keeps its name.")
            _name_free(conn, user.id, body.name, but=list_id)
            conn.execute("UPDATE lists SET name = ? WHERE id = ?", (body.name, list_id))
            changed = True
        if body.description is not None and body.description.strip() != row["description"]:
            conn.execute("UPDATE lists SET description = ? WHERE id = ?", (body.description.strip(), list_id))
            changed = True
        if changed:
            _touch(conn, list_id)
        return {"list": _summary(_own(conn, user.id, list_id))}


@router.delete("/{list_id}")
def delete_list(list_id: int, _: Empty | None = None, user: User = Depends(users.current_user)) -> dict:
    with Db() as conn:
        row = _own(conn, user.id, list_id)
        if row["is_builtin"]:
            raise ApiError(400, "BUILTIN_LIST", "The Saved list cannot be deleted. Remove its items instead.")
        conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))
        users.audit(conn, user.id, f"deleted list {list_id} ({row['count']} items)")
    return {"ok": True}


def _resolve(conn, user_id: int, list_ref: str) -> int:
    """A list id from the path: a number, or "saved" for the built-in list (so one click needs no lookup first)."""
    if list_ref == "saved":
        return saved_list_id(conn, user_id)
    if not list_ref.isdigit():
        raise ApiError(404, "LIST_NOT_FOUND", "There is no such list in your account.")
    _own(conn, user_id, int(list_ref))
    return int(list_ref)


def _storage_usage(conn, user_id: int) -> int:
    return conn.execute(
        "SELECT coalesce(sum(length(i.note) + length(i.tags) + length(i.snapshot)), 0) FROM list_items i "
        "JOIN lists l ON l.id = i.list_id WHERE l.user_id = ?",
        (user_id,),
    ).fetchone()[0]


def _stored_size(note: str, tags_json: str, snapshot_json: str) -> int:
    return len(note) + len(tags_json) + len(snapshot_json)


_STORAGE_MSG = "Your lists hold as much as one account may keep. Remove items or shorten notes to make room."


@router.post("/{list_ref}/items")
def add_item(list_ref: str, body: ItemIn, response: Response, user: User = Depends(users.current_user)) -> dict:
    """Adds a dataset; adding one the list already holds changes nothing and answers 200 with "added": false."""
    with Db() as conn:
        conn.execute("BEGIN IMMEDIATE")  # the existence check, the count and the insert see no other save in between
        list_id = _resolve(conn, user.id, list_ref)
        old = conn.execute("SELECT * FROM list_items WHERE list_id = ? AND accession = ?", (list_id, body.accession)).fetchone()
        if old:
            return {"list_id": list_id, "added": False, "item": _item(old)}
        if conn.execute("SELECT count(*) FROM list_items WHERE list_id = ?", (list_id,)).fetchone()[0] >= MAX_ITEMS:
            raise ApiError(409, "LIMIT_REACHED", f"A list holds at most {MAX_ITEMS} datasets. Start another list for more.")
        tags_json = json.dumps(body.tags)
        snapshot_json = body.snapshot.model_dump_json()
        if _storage_usage(conn, user.id) + _stored_size(body.note, tags_json, snapshot_json) > STORAGE_MAX:
            raise ApiError(409, "STORAGE_FULL", _STORAGE_MSG)
        conn.execute(
            "INSERT INTO list_items (list_id, accession, added_at, note, tags, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
            (list_id, body.accession, iso(users.now()), body.note, tags_json, snapshot_json),
        )
        _touch(conn, list_id)
        row = conn.execute("SELECT * FROM list_items WHERE list_id = ? AND accession = ?", (list_id, body.accession)).fetchone()
    response.status_code = 201
    return {"list_id": list_id, "added": True, "item": _item(row)}


@router.patch("/{list_ref}/items/{accession}")
def edit_item(list_ref: str, accession: str, body: ItemPatch, user: User = Depends(users.current_user)) -> dict:
    with Db() as conn:
        list_id = _resolve(conn, user.id, list_ref)
        row = conn.execute("SELECT * FROM list_items WHERE list_id = ? AND accession = ?", (list_id, accession)).fetchone()
        if not row:
            raise ApiError(404, "ITEM_NOT_FOUND", f"This list does not hold {accession}.")
        new_note = body.note if body.note is not None else row["note"]
        new_tags_json = json.dumps(body.tags) if body.tags is not None else row["tags"]
        snapshot_json = row["snapshot"]
        old_size = _stored_size(row["note"], row["tags"], row["snapshot"])
        new_size = _stored_size(new_note, new_tags_json, snapshot_json)
        if new_size > old_size and _storage_usage(conn, user.id) - old_size + new_size > STORAGE_MAX:
            raise ApiError(409, "STORAGE_FULL", _STORAGE_MSG)
        if body.note is not None:
            conn.execute("UPDATE list_items SET note = ? WHERE list_id = ? AND accession = ?", (body.note, list_id, accession))
        if body.tags is not None:
            conn.execute("UPDATE list_items SET tags = ? WHERE list_id = ? AND accession = ?", (new_tags_json, list_id, accession))
        row = conn.execute("SELECT * FROM list_items WHERE list_id = ? AND accession = ?", (list_id, accession)).fetchone()
        _touch(conn, list_id)
    return {"list_id": list_id, "item": _item(row)}


@router.delete("/{list_ref}/items/{accession}")
def remove_item(list_ref: str, accession: str, _: Empty | None = None, user: User = Depends(users.current_user)) -> dict:
    with Db() as conn:
        list_id = _resolve(conn, user.id, list_ref)
        gone = conn.execute("DELETE FROM list_items WHERE list_id = ? AND accession = ?", (list_id, accession)).rowcount
        if not gone:
            raise ApiError(404, "ITEM_NOT_FOUND", f"This list does not hold {accession}.")
        _touch(conn, list_id)
    return {"list_id": list_id, "ok": True}


# ---------------------------------------------------------------- public lists (F6)

PUBLISHED = "published list "  # audit event prefix; the daily publish limit counts these


@router.post("/{list_id}/publish")
def publish(list_id: int, body: PublishIn, user: User = Depends(users.current_user)) -> dict:
    """Publishes the list, or updates its public page to what the list holds now (papertok's public lists). The first
    publish draws a random 32-hex share id from `secrets`; updates keep it, so a shared link keeps working. The public
    page shows a copy frozen here: name, description, the first 50 items with their snapshots, notes only when
    include_notes is set, the owner's display name only when show_owner is set, and never tags. At most 60 publishes
    and updates per account in any 24 hours."""
    with Db() as conn:
        conn.execute("BEGIN IMMEDIATE")  # the daily count and the write see no other publish in between
        row = _own(conn, user.id, list_id)
        t = users.now()
        recent = conn.execute("SELECT count(*) FROM audit WHERE user_id = ? AND at > ? AND event LIKE ?",
                              (user.id, iso(t - timedelta(days=1)), PUBLISHED + "%")).fetchone()[0]
        if recent >= PUBLISH_PER_DAY:
            raise ApiError(429, "RATE_LIMITED", f"A day allows {PUBLISH_PER_DAY} publishes and updates. Please try again tomorrow.", transient=True)
        items = [
            {"accession": i["accession"], "snapshot": i["snapshot"]} | ({"note": i["note"]} if body.include_notes and i["note"] else {})
            for i in _items(conn, list_id)
        ]
        shared = {
            "name": row["name"], "description": row["description"], "owner": user.display_name if body.show_owner else None,
            "show_owner": body.show_owner, "include_notes": body.include_notes, "count": len(items), "items": items[:PUBLIC_ITEMS],
        }
        share_id = row["share_id"] or secrets.token_hex(16)
        conn.execute("UPDATE lists SET share_id = ?, published_at = ?, share_snapshot = ?, published_rev = rev WHERE id = ?",
                     (share_id, iso(t), json.dumps(shared), list_id))
        users.audit(conn, user.id, PUBLISHED + str(list_id))
        return {"list": _summary(_own(conn, user.id, list_id))}


@router.delete("/{list_id}/publish")
def unpublish(list_id: int, _: Empty | None = None, user: User = Depends(users.current_user)) -> dict:
    """Withdraws the public page: its link answers 404 from now on. Publishing again draws a new share id."""
    with Db() as conn:
        row = _own(conn, user.id, list_id)
        if row["share_id"]:
            conn.execute("UPDATE lists SET share_id = NULL, published_at = NULL, share_snapshot = NULL, published_rev = NULL WHERE id = ?", (list_id,))
            users.audit(conn, user.id, f"stopped sharing list {list_id}")
        return {"list": _summary(_own(conn, user.id, list_id))}


public_router = APIRouter(prefix="/public", tags=["lists"])


@public_router.get("/lists/{share_id}")
def public_list(share_id: str, response: Response) -> dict:
    """A published list as anyone may see it, signed in or not. There is no route that lists share ids; an id that is
    not 32 lowercase hex characters, was withdrawn, or never existed answers the same 404."""
    response.headers["Cache-Control"] = "no-store"  # withdrawing must take effect at once
    response.headers["X-Robots-Tag"] = "noindex"
    row = None
    if SHARE_ID.match(share_id):
        with Db() as conn:
            row = conn.execute("SELECT share_snapshot, published_at FROM lists WHERE share_id = ?", (share_id,)).fetchone()
    if not row or not row["share_snapshot"]:
        raise ApiError(404, "LIST_NOT_FOUND", "This list is not shared, or its owner stopped sharing it.", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})
    shared = json.loads(row["share_snapshot"])
    return {
        "name": shared["name"], "description": shared["description"], "owner": shared["owner"], "updated_at": row["published_at"],
        "count": shared["count"], "shown": len(shared["items"]), "items": shared["items"],
    }


# ---------------------------------------------------------------- bringing a guest's Saved into the account (F3)


class ImportIn(BaseModel):
    """What a browser kept as a guest (localStorage `locus:saved`), sent in one request. Each item passes the same
    checks as a single save; the batch holds at most one full list."""

    items: list[ItemIn] = Field(max_length=MAX_ITEMS)


@router.post("/saved/import")
def import_saved(body: ImportIn, user: User = Depends(users.current_user)) -> dict:
    """Adds a guest's saved datasets to the built-in Saved list, in the order the browser kept them, in one transaction.

    Idempotent: an accession Saved already holds (or one repeated in the batch) is not added again, and its note, tags
    and snapshot in the account are left as they are. When Saved would pass 500 items, the ones that fit are added and
    the rest are reported in "left_out". "held" lists every accession of the batch that Saved now holds, so the browser
    knows exactly which local copies it may drop."""
    with Db() as conn:
        conn.execute("BEGIN IMMEDIATE")  # the room count and the inserts see no other import in between
        list_id = saved_list_id(conn, user.id)
        have = {r["accession"] for r in conn.execute("SELECT accession FROM list_items WHERE list_id = ?", (list_id,))}
        room = MAX_ITEMS - len(have)
        usage = _storage_usage(conn, user.id)
        t = iso(users.now())
        added: list[str] = []
        already: list[str] = []
        left_out: list[str] = []
        for item in body.items:
            if item.accession in have or item.accession in added or item.accession in left_out:
                if item.accession in have and item.accession not in already:
                    already.append(item.accession)
                continue
            if room <= 0:
                left_out.append(item.accession)
                continue
            tags_json = json.dumps(item.tags)
            snapshot_json = item.snapshot.model_dump_json()
            size = _stored_size(item.note, tags_json, snapshot_json)
            if usage + size > STORAGE_MAX:
                left_out.append(item.accession)
                continue
            conn.execute(
                "INSERT INTO list_items (list_id, accession, added_at, note, tags, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                (list_id, item.accession, t, item.note, tags_json, snapshot_json),
            )
            added.append(item.accession)
            room -= 1
            usage += size
        if added:
            _touch(conn, list_id)
            users.audit(conn, user.id, f"imported {len(added)} saved datasets from a browser")
    return {"list_id": list_id, "added": added, "already": already, "left_out": left_out, "held": added + already}


# ---------------------------------------------------------------- export

CSV_COLUMNS = ["accession", "title", "repository", "organism", "data type", "samples", "note", "tags", "added"]


def _cell(value) -> str:
    """A CSV cell a spreadsheet will not run as a formula (OWASP CSV injection: a leading =, +, -, @, tab or CR)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _filename(name: str, ext: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()[:60] or "list"
    return f"locus-{slug}.{ext}"


@router.get("/{list_id}/export")
def export(list_id: int, format: Literal["accessions", "csv"] = Query("accessions"), user: User = Depends(users.current_user)) -> Response:
    """The list as plain accessions (one a line) or as CSV with the columns in CSV_COLUMNS, in the list's order."""
    with Db() as conn:
        row = _own(conn, user.id, list_id)
        items = _items(conn, list_id)
    if format == "accessions":
        body, kind = "".join(i["accession"] + "\n" for i in items), "text/plain; charset=utf-8"
    else:
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for i in items:
            s = i["snapshot"]
            source = s.get("source") or ""
            writer.writerow([_cell(v) for v in (
                i["accession"], s.get("title"), REPOSITORY_NAMES.get(source, source), s.get("organism"), s.get("modality"),
                s.get("samples"), i["note"], "; ".join(i["tags"]), i["added_at"],
            )])
        body, kind = out.getvalue(), "text/csv; charset=utf-8"
    name = _filename(row["name"], "txt" if format == "accessions" else "csv")
    return Response(body, media_type=kind, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------- wiring


def install(app: FastAPI) -> None:
    """Adds the /lists routes; call after users.install(app), which provides the error handlers."""
    for prefix in ("/lists", "/public"):
        if prefix not in users.SHAPED_PREFIXES:
            users.SHAPED_PREFIXES.append(prefix)
    app.include_router(router)
    app.include_router(public_router)
