"""Saved datasets and lists (F2): the built-in Saved list, named lists, items with notes, tags and snapshots, limits,
ownership, the CSRF guard on /lists, and export. No network: lists never call a repository."""

import csv
import io
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


def signed_in(name="Gate") -> TestClient:
    c = TestClient(make_app(), base_url="https://testserver", client=LOCAL)
    assert c.post("/account/dev-login", json={"display_name": name}, headers=INTENT).status_code == 200
    return c


def call(c: TestClient, method: str, url: str, body=None):
    return c.request(method, url, json={} if body is None else body, headers=INTENT)


def add(c, ref, accession, **extra):
    return call(c, "POST", f"/lists/{ref}/items", {"accession": accession, "snapshot": SNAP} | extra)


def test_lists_need_an_account(env):
    c = TestClient(make_app(), base_url="https://testserver", client=LOCAL)
    r = c.get("/lists")
    assert r.status_code == 401 and r.json()["error"]["code"] == "SIGN_IN_REQUIRED"
    assert add(c, "saved", "GSE1").status_code == 401


def test_csrf_guard_covers_lists(env):
    c = signed_in()
    r = c.post("/lists/saved/items", json={"accession": "GSE1"})  # no intent header
    assert r.status_code == 403 and r.json()["error"]["code"] == "INTENT_REQUIRED"
    r = c.post("/lists", content="name=x", headers=INTENT | {"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 403
    assert c.delete("/lists/1").status_code == 403


def test_saved_list_exists_and_one_click_save_is_idempotent(env):
    c = signed_in()
    first = c.get("/lists").json()
    assert [(l["name"], l["builtin"], l["count"]) for l in first["lists"]] == [("Saved", True, 0)]
    saved_id = first["lists"][0]["id"]
    r = add(c, "saved", "GSE273888")
    assert r.status_code == 201 and r.json()["added"] is True and r.json()["list_id"] == saved_id
    assert r.json()["item"]["snapshot"] == SNAP
    again = add(c, "saved", "GSE273888", note="ignored")
    assert again.status_code == 200 and again.json()["added"] is False and again.json()["item"]["note"] == ""
    body = c.get("/lists").json()
    assert body["lists"][0]["count"] == 1 and body["holds"] == {"GSE273888": [saved_id]}
    # Asking twice never makes a second built-in list.
    assert len(c.get("/lists").json()["lists"]) == 1


def test_named_lists_keep_added_order_notes_and_tags(env):
    c = signed_in()
    r = call(c, "POST", "/lists", {"name": "  Ribo-seq   cohort ", "description": "for the TE model"})
    assert r.status_code == 201
    lid = r.json()["list"]["id"]
    assert r.json()["list"]["name"] == "Ribo-seq cohort" and r.json()["list"]["builtin"] is False
    for acc in ["PXD000001", "GSE2", "E-MTAB-123"]:
        assert add(c, lid, acc).status_code == 201
    r = call(c, "PATCH", f"/lists/{lid}/items/GSE2", {"note": "polysome too", "tags": ["HEK293", " hek293 ", "riboseq", ""]})
    assert r.status_code == 200 and r.json()["item"]["tags"] == ["HEK293", "riboseq"]
    body = c.get(f"/lists/{lid}").json()
    assert [i["accession"] for i in body["items"]] == ["PXD000001", "GSE2", "E-MTAB-123"]
    assert body["items"][1]["note"] == "polysome too"
    assert body["list"]["count"] == 3
    assert call(c, "DELETE", f"/lists/{lid}/items/GSE2").status_code == 200
    assert call(c, "DELETE", f"/lists/{lid}/items/GSE2").json()["error"]["code"] == "ITEM_NOT_FOUND"
    assert [i["accession"] for i in c.get(f"/lists/{lid}").json()["items"]] == ["PXD000001", "E-MTAB-123"]
    assert call(c, "PATCH", f"/lists/{lid}/items/GSE999", {"note": "x"}).status_code == 404


def test_rename_delete_and_the_builtin_list(env, monkeypatch):
    c = signed_in()
    saved_id = c.get("/lists").json()["lists"][0]["id"]
    lid = call(c, "POST", "/lists", {"name": "Draft"}).json()["list"]["id"]
    before = c.get(f"/lists/{lid}").json()["list"]["updated_at"]
    later = users.now() + timedelta(minutes=5)
    monkeypatch.setattr(users, "now", lambda: later)
    r = call(c, "PATCH", f"/lists/{lid}", {"name": "Final"})
    assert r.status_code == 200 and r.json()["list"]["name"] == "Final" and r.json()["list"]["updated_at"] > before
    assert call(c, "POST", "/lists", {"name": "final"}).json()["error"]["code"] == "NAME_TAKEN"
    assert call(c, "PATCH", f"/lists/{saved_id}", {"name": "Mine"}).json()["error"]["code"] == "BUILTIN_LIST"
    assert call(c, "DELETE", f"/lists/{saved_id}").status_code == 400
    add(c, lid, "GSE5")
    assert call(c, "DELETE", f"/lists/{lid}").status_code == 200
    assert c.get(f"/lists/{lid}").status_code == 404
    assert c.get("/lists").json()["holds"] == {}


def test_validation_limits(env, monkeypatch):
    c = signed_in()
    assert call(c, "POST", "/lists", {"name": "   "}).json()["error"]["code"] == "INVALID_REQUEST"
    assert call(c, "POST", "/lists", {"name": "x" * 121}).status_code == 422
    assert call(c, "POST", "/lists", {"name": "ok", "description": "d" * 601}).status_code == 422
    assert add(c, "saved", "GSE1; DROP").status_code == 422
    assert add(c, "saved", "../etc").status_code == 422
    assert add(c, "saved", "GSE1", note="n" * 10_001).status_code == 422
    assert add(c, "saved", "GSE1", tags=[f"t{i}" for i in range(13)]).status_code == 422
    assert add(c, "saved", "GSE1", tags=["x" * 41]).status_code == 422
    assert add(c, "saved", "GSE1", tags=[f"t{i}" for i in range(12)]).status_code == 201

    monkeypatch.setattr(saved, "MAX_ITEMS", 2)
    assert add(c, "saved", "GSE2").status_code == 201
    r = add(c, "saved", "GSE3")
    assert r.status_code == 409 and r.json()["error"]["code"] == "LIMIT_REACHED"
    assert add(c, "saved", "GSE2").status_code == 200  # already there: not refused

    monkeypatch.setattr(saved, "MAX_LISTS", 3)  # Saved counts as one
    assert call(c, "POST", "/lists", {"name": "a"}).status_code == 201
    assert call(c, "POST", "/lists", {"name": "b"}).status_code == 201
    assert call(c, "POST", "/lists", {"name": "c"}).json()["error"]["code"] == "LIMIT_REACHED"


def test_another_account_cannot_see_or_change_a_list(env):
    alice = signed_in("Alice")
    lid = call(alice, "POST", "/lists", {"name": "Private"}).json()["list"]["id"]
    add(alice, lid, "GSE7")
    bob = signed_in("Bob")
    assert bob.get(f"/lists/{lid}").json()["error"]["code"] == "LIST_NOT_FOUND"
    assert bob.get(f"/lists/{lid}/export?format=csv").status_code == 404
    assert add(bob, lid, "GSE8").status_code == 404
    assert call(bob, "PATCH", f"/lists/{lid}", {"name": "Mine"}).status_code == 404
    assert call(bob, "DELETE", f"/lists/{lid}/items/GSE7").status_code == 404
    assert call(bob, "DELETE", f"/lists/{lid}").status_code == 404
    assert [i["accession"] for i in alice.get(f"/lists/{lid}").json()["items"]] == ["GSE7"]
    assert bob.get("/lists").json()["holds"] == {}


def test_export_accessions_and_csv(env):
    c = signed_in()
    lid = call(c, "POST", "/lists", {"name": "TE / cohort"}).json()["list"]["id"]
    add(c, lid, "GSE1", note="=HYPERLINK(\"x\")", tags=["a", "b"])
    add(c, lid, "ST000001", snapshot={"title": "Plasma lipids", "source": "MetabolomicsWorkbench", "organism": "Homo sapiens", "modality": "metabolomics", "samples": None})
    r = c.get(f"/lists/{lid}/export?format=accessions")
    assert r.status_code == 200 and r.text == "GSE1\nST000001\n"
    assert r.headers["content-type"].startswith("text/plain")
    assert 'filename="locus-te-cohort.txt"' in r.headers["content-disposition"]
    r = c.get(f"/lists/{lid}/export?format=csv")
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["accession", "title", "repository", "organism", "data type", "samples", "note", "tags", "added"]
    assert rows[1][:8] == ["GSE1", SNAP["title"], "GEO", "Homo sapiens", "RNA-seq", "12", "'=HYPERLINK(\"x\")", "a; b"]
    assert rows[2][:6] == ["ST000001", "Plasma lipids", "Metabolomics Workbench", "Homo sapiens", "metabolomics", ""]
    assert rows[1][8].endswith("Z")
    assert c.get(f"/lists/{lid}/export?format=xlsx").status_code == 422


def test_deleting_the_account_rows_removes_lists(env):
    c = signed_in()
    add(c, "saved", "GSE1")
    conn = users.connect()
    try:
        with conn:
            conn.execute("DELETE FROM users")
        assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM list_items").fetchone()[0] == 0
    finally:
        conn.close()
