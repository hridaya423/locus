"""Public lists (F6): publish, update and unpublish (owner only, CSRF guard), the signed-out public read with only the
fields the owner chose, the 50-item cap, the stale flag, the daily publish limit and unguessable, unlistable share ids.
No network: lists never call a repository."""

import re
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from omics_agent import saved, users

INTENT = {"X-Locus-Intent": "1"}
LOCAL = ("127.0.0.1", 50000)
SNAP = {"title": "Ribosome profiling of HEK293 cells", "source": "GEO", "organism": "Homo sapiens", "modality": "RNA-seq", "samples": 12}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OMICS_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("LOCUS_DEV_LOGIN", "1")
    monkeypatch.delenv("LOCUS_COOKIE_INSECURE", raising=False)
    users.AUTH_LIMIT.reset()
    yield tmp_path / "users.db"
    users.AUTH_LIMIT.reset()


def make_app() -> FastAPI:
    app = FastAPI()
    users.install(app)
    saved.install(app)
    return app


def guest() -> TestClient:
    return TestClient(make_app(), base_url="https://testserver", client=LOCAL)


def signed_in(name="Ada Owner") -> TestClient:
    c = guest()
    assert c.post("/account/dev-login", json={"display_name": name}, headers=INTENT).status_code == 200
    return c


def call(c: TestClient, method: str, url: str, body=None):
    return c.request(method, url, json={} if body is None else body, headers=INTENT)


def make_list(c, name="Translation atlas", n=2, **item):
    lid = call(c, "POST", "/lists", {"name": name, "description": "HEK293 studies"}).json()["list"]["id"]
    for k in range(n):
        assert call(c, "POST", f"/lists/{lid}/items", {"accession": f"GSE{k + 1}", "snapshot": SNAP} | item).status_code == 201
    return lid


def test_publish_then_read_signed_out_then_unpublish(env):
    owner = signed_in()
    lid = make_list(owner, note="my private thought", tags=["todo"])
    r = call(owner, "POST", f"/lists/{lid}/publish", {})
    assert r.status_code == 200
    public = r.json()["list"]["public"]
    assert re.fullmatch(r"[0-9a-f]{32}", public["share_id"]) and public["stale"] is False
    assert public["show_owner"] is False and public["include_notes"] is False

    page = guest().get(f"/public/lists/{public['share_id']}")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store" and page.headers["x-robots-tag"] == "noindex"
    body = page.json()
    assert body["name"] == "Translation atlas" and body["description"] == "HEK293 studies" and body["owner"] is None
    assert [i["accession"] for i in body["items"]] == ["GSE1", "GSE2"] and body["items"][0]["snapshot"]["title"] == SNAP["title"]
    # Notes and tags are personal: neither appears unless the owner chose to include notes; tags never.
    assert "my private thought" not in page.text and "todo" not in page.text and "Ada Owner" not in page.text

    r = call(owner, "DELETE", f"/lists/{lid}/publish")
    assert r.status_code == 200 and r.json()["list"]["public"] is None
    gone = guest().get(f"/public/lists/{public['share_id']}")
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "LIST_NOT_FOUND"

    # Publishing again draws a new id; the withdrawn one stays dead.
    again = call(owner, "POST", f"/lists/{lid}/publish", {}).json()["list"]["public"]["share_id"]
    assert again != public["share_id"] and guest().get(f"/public/lists/{public['share_id']}").status_code == 404


def test_owner_name_and_notes_only_when_chosen(env):
    owner = signed_in()
    lid = make_list(owner, note="look at the controls", tags=["todo"])
    share = call(owner, "POST", f"/lists/{lid}/publish", {"show_owner": True, "include_notes": True}).json()["list"]["public"]["share_id"]
    body = guest().get(f"/public/lists/{share}").json()
    assert body["owner"] == "Ada Owner" and body["items"][0]["note"] == "look at the controls"
    assert "tags" not in body["items"][0] and "todo" not in str(body)


def test_public_page_is_frozen_until_update_and_marks_stale(env, monkeypatch):
    owner = signed_in()
    lid = make_list(owner)
    pub = call(owner, "POST", f"/lists/{lid}/publish", {}).json()["list"]["public"]
    later = users.now() + timedelta(minutes=5)
    monkeypatch.setattr(users, "now", lambda: later)
    call(owner, "POST", f"/lists/{lid}/items", {"accession": "GSE9", "snapshot": SNAP})
    assert call(owner, "GET", f"/lists/{lid}").json()["list"]["public"]["stale"] is True
    assert [i["accession"] for i in guest().get(f"/public/lists/{pub['share_id']}").json()["items"]] == ["GSE1", "GSE2"]
    # Update keeps the link and shows the list as it is now.
    later2 = later + timedelta(minutes=1)
    monkeypatch.setattr(users, "now", lambda: later2)
    upd = call(owner, "POST", f"/lists/{lid}/publish", {}).json()["list"]["public"]
    assert upd["share_id"] == pub["share_id"] and upd["stale"] is False
    assert [i["accession"] for i in guest().get(f"/public/lists/{pub['share_id']}").json()["items"]] == ["GSE1", "GSE2", "GSE9"]


def test_at_most_50_items_shown(env):
    owner = signed_in()
    lid = make_list(owner, n=53)
    share = call(owner, "POST", f"/lists/{lid}/publish", {}).json()["list"]["public"]["share_id"]
    body = guest().get(f"/public/lists/{share}").json()
    assert body["count"] == 53 and body["shown"] == 50 and len(body["items"]) == 50 and body["items"][-1]["accession"] == "GSE50"


def test_only_the_owner_publishes_and_the_guard_applies(env):
    owner = signed_in()
    lid = make_list(owner)
    other = signed_in("Mallory")
    assert call(other, "POST", f"/lists/{lid}/publish", {}).status_code == 404
    share = call(owner, "POST", f"/lists/{lid}/publish", {}).json()["list"]["public"]["share_id"]
    assert call(other, "DELETE", f"/lists/{lid}/publish").status_code == 404
    assert guest().get(f"/public/lists/{share}").status_code == 200
    assert call(guest(), "POST", f"/lists/{lid}/publish", {}).status_code == 401
    r = owner.post(f"/lists/{lid}/publish", json={})  # no intent header
    assert r.status_code == 403 and r.json()["error"]["code"] == "INTENT_REQUIRED"
    # Another account's list summary never carries a share id.
    assert all(x["public"] is None for x in other.get("/lists").json()["lists"])


def test_daily_publish_limit(env, monkeypatch):
    owner = signed_in()
    lid = make_list(owner)
    for _ in range(saved.PUBLISH_PER_DAY):
        assert call(owner, "POST", f"/lists/{lid}/publish", {}).status_code == 200
    r = call(owner, "POST", f"/lists/{lid}/publish", {})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    # Unpublishing is never limited, and a day later publishing works again.
    assert call(owner, "DELETE", f"/lists/{lid}/publish").status_code == 200
    later = users.now() + timedelta(days=1, minutes=1)
    monkeypatch.setattr(users, "now", lambda: later)
    assert call(owner, "POST", f"/lists/{lid}/publish", {}).status_code == 200


def test_share_ids_are_not_listable_or_guessable(env):
    owner = signed_in()
    lid = make_list(owner)
    call(owner, "POST", f"/lists/{lid}/publish", {})
    c = guest()
    for path in ("/public/lists", "/public/lists/", "/public/lists/0", "/public/lists/" + "0" * 32, "/public/lists/" + "A" * 32, f"/public/lists/{lid}"):
        assert c.get(path).status_code in (404, 405), path
    ids = {call(owner, "POST", f"/lists/{make_list(owner, name=f'L{k}', n=0)}/publish", {}).json()["list"]["public"]["share_id"] for k in range(5)}
    assert len(ids) == 5 and all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)


def test_deleting_a_published_list_withdraws_it(env):
    owner = signed_in()
    lid = make_list(owner)
    share = call(owner, "POST", f"/lists/{lid}/publish", {}).json()["list"]["public"]["share_id"]
    assert call(owner, "DELETE", f"/lists/{lid}").status_code == 200
    assert guest().get(f"/public/lists/{share}").status_code == 404


def test_a_change_in_the_same_second_as_publish_is_stale(env, monkeypatch):
    # F6-r1-1: the clock stands still, so updated_at == published_at; the change counter still tells.
    frozen = users.now()
    monkeypatch.setattr(users, "now", lambda: frozen)
    owner = signed_in()
    lid = make_list(owner, n=1)
    call(owner, "POST", f"/lists/{lid}/publish", {})
    assert call(owner, "GET", f"/lists/{lid}").json()["list"]["public"]["stale"] is False
    call(owner, "POST", f"/lists/{lid}/items", {"accession": "GSE77", "snapshot": SNAP})
    summary = call(owner, "GET", f"/lists/{lid}").json()["list"]
    assert summary["updated_at"] == summary["public"]["published_at"] and summary["public"]["stale"] is True
    assert call(owner, "POST", f"/lists/{lid}/publish", {}).json()["list"]["public"]["stale"] is False
    # Each kind of change marks it: a note, removing an item, the description; a PATCH that changes nothing does not.
    for method, url, body in [("PATCH", f"/lists/{lid}/items/GSE77", {"note": "n"}), ("DELETE", f"/lists/{lid}/items/GSE77", {}),
                              ("PATCH", f"/lists/{lid}", {"description": "new words"})]:
        assert call(owner, method, url, body).status_code == 200
        assert call(owner, "GET", f"/lists/{lid}").json()["list"]["public"]["stale"] is True
        call(owner, "POST", f"/lists/{lid}/publish", {})
    assert call(owner, "PATCH", f"/lists/{lid}", {"description": "new words"}).json()["list"]["public"]["stale"] is False
    # Stop sharing, then publish again: fresh.
    call(owner, "DELETE", f"/lists/{lid}/publish", {})
    assert call(owner, "POST", f"/lists/{lid}/publish", {}).json()["list"]["public"]["stale"] is False
