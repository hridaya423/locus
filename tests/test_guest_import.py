"""Bringing a guest's saved datasets into the account (F3): one batch request into Saved, idempotent, validated with
the same limits as a single save, the 500-item cap, the CSRF guard and the session requirement. No network."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from omics_agent import saved, users

INTENT = {"X-Locus-Intent": "1"}
LOCAL = ("127.0.0.1", 50000)


def snap(title="Ribosome profiling of HEK293 cells", **extra):
    return {"title": title, "source": "GEO", "organism": "Homo sapiens", "modality": "RNA-seq", "samples": 12} | extra


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OMICS_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("LOCUS_DEV_LOGIN", "1")
    monkeypatch.delenv("LOCUS_COOKIE_INSECURE", raising=False)
    users.AUTH_LIMIT.reset()
    yield
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


def bring(c, items):
    return c.post("/lists/saved/import", json={"items": items}, headers=INTENT)


def saved_items(c):
    lists = c.get("/lists").json()["lists"]
    sid = next(l["id"] for l in lists if l["builtin"])
    return c.get(f"/lists/{sid}").json()["items"]


def test_import_adds_in_order_and_is_idempotent(env):
    c = signed_in()
    items = [{"accession": "GSE2", "snapshot": snap("Second")}, {"accession": "GSE1", "snapshot": snap("First")}]
    r = bring(c, items)
    assert r.status_code == 200
    assert r.json()["added"] == ["GSE2", "GSE1"] and r.json()["held"] == ["GSE2", "GSE1"] and r.json()["left_out"] == []
    assert [(i["accession"], i["snapshot"]["title"]) for i in saved_items(c)] == [("GSE2", "Second"), ("GSE1", "First")]

    again = bring(c, items + [{"accession": "GSE1", "snapshot": snap("Changed")}])
    assert again.json()["added"] == [] and again.json()["already"] == ["GSE2", "GSE1"]
    assert [(i["accession"], i["snapshot"]["title"]) for i in saved_items(c)] == [("GSE2", "Second"), ("GSE1", "First")]


def test_import_keeps_what_the_account_already_has(env):
    c = signed_in()
    c.post("/lists/saved/items", json={"accession": "GSE1", "snapshot": snap(), "note": "mine"}, headers=INTENT)
    r = bring(c, [{"accession": "GSE1", "snapshot": snap("guest copy")}, {"accession": "GSE3", "snapshot": snap()}, {"accession": "GSE3", "snapshot": snap()}])
    assert r.json()["added"] == ["GSE3"] and r.json()["already"] == ["GSE1"]
    got = {i["accession"]: i for i in saved_items(c)}
    assert len(got) == 2 and got["GSE1"]["note"] == "mine" and got["GSE1"]["snapshot"]["title"] == "Ribosome profiling of HEK293 cells"


def test_import_goes_into_the_callers_account_only(env):
    a, b = signed_in("A"), signed_in("B")
    bring(a, [{"accession": "GSE1", "snapshot": snap()}])
    assert [i["accession"] for i in saved_items(a)] == ["GSE1"]
    assert saved_items(b) == []


def test_import_validates_like_a_single_save(env):
    c = signed_in()
    for bad in (
        [{"accession": "not an accession", "snapshot": snap()}],
        [{"accession": "GSE1", "snapshot": snap("x" * 1001)}],
        [{"accession": "GSE1", "snapshot": snap(samples=-1)}],
        [{"accession": "GSE1", "snapshot": snap(), "note": "n" * 10_001}],
        [{"accession": "GSE1", "snapshot": snap(), "tags": ["t" * 41]}],
        [{"accession": f"GSE{n}", "snapshot": snap()} for n in range(501)],
    ):
        assert bring(c, bad).status_code == 422
    assert saved_items(c) == []  # a refused batch adds nothing
    extra = bring(c, [{"accession": "GSE1", "snapshot": snap(secret="dropped")}])
    assert extra.status_code == 200 and "secret" not in saved_items(c)[0]["snapshot"]


def test_import_stops_at_the_list_limit_and_says_what_was_left_out(env, monkeypatch):
    monkeypatch.setattr(saved, "MAX_ITEMS", 3)
    c = signed_in()
    c.post("/lists/saved/items", json={"accession": "GSE1", "snapshot": snap()}, headers=INTENT)
    r = bring(c, [{"accession": a, "snapshot": snap()} for a in ("GSE1", "GSE2", "GSE3", "GSE4", "GSE5")])
    assert r.json()["added"] == ["GSE2", "GSE3"] and r.json()["left_out"] == ["GSE4", "GSE5"]
    assert r.json()["held"] == ["GSE2", "GSE3", "GSE1"]
    assert len(saved_items(c)) == 3


def test_import_needs_a_session_and_intent(env):
    guest = TestClient(make_app(), base_url="https://testserver", client=LOCAL)
    r = bring(guest, [{"accession": "GSE1", "snapshot": snap()}])
    assert r.status_code == 401 and r.json()["error"]["code"] == "SIGN_IN_REQUIRED"
    c = signed_in()
    r = c.post("/lists/saved/import", json={"items": []})
    assert r.status_code == 403 and r.json()["error"]["code"] == "INTENT_REQUIRED"
