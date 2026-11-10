"""Watched searches kept in an account (F4): watch, record a new run's results, unwatch, list, the guest import
batch, per-account isolation, limits, the CSRF guard and the session requirement. No network."""

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from omics_agent import saved, users, watches

INTENT = {"X-Locus-Intent": "1"}
LOCAL = ("127.0.0.1", 50000)
Q = "ribosome profiling in HEK293 cells"


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
    watches.install(app)
    return app


def signed_in(name="Gate") -> TestClient:
    c = TestClient(make_app(), base_url="https://testserver", client=LOCAL)
    assert c.post("/account/dev-login", json={"display_name": name}, headers=INTENT).status_code == 200
    return c


def call(c, method, path, body=None):
    return c.request(method, path, json=body if body is not None else {}, headers=INTENT)


def listed(c):
    r = c.get("/follows/questions")
    assert r.status_code == 200
    return r.json()["watches"]


def test_needs_a_session_and_the_intent_header(env):
    guest = TestClient(make_app(), base_url="https://testserver", client=LOCAL)
    r = guest.get("/follows/questions")
    assert r.status_code == 401 and r.json()["error"]["code"] == "SIGN_IN_REQUIRED"
    assert call(guest, "POST", "/follows/questions", {"question": Q}).status_code == 401

    c = signed_in()
    r = c.post("/follows/questions", json={"question": Q})
    assert r.status_code == 403 and r.json()["error"]["code"] == "INTENT_REQUIRED"
    r = c.post("/follows/questions", content="question=x", headers=INTENT | {"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 403
    assert c.request("DELETE", "/follows/questions", json={"question": Q}).status_code == 403
    assert c.post("/follows/questions/import", json={"watches": []}).status_code == 403
    assert listed(c) == []


def test_watch_rerun_and_unwatch(env, monkeypatch):
    c = signed_in()
    r = call(c, "POST", "/follows/questions", {"question": f"  {Q} ", "seen": ["GSE1", "GSE2", "GSE1"]})
    assert r.status_code == 201 and r.json()["added"] is True
    w = r.json()["watch"]
    assert w["question"] == Q and w["seen"] == ["GSE1", "GSE2"] and w["since"] == users.now().date().isoformat()

    # A later run of the same search adds what it showed to "seen" and keeps the day watching started.
    later = users.now() + timedelta(days=3)
    monkeypatch.setattr(users, "now", lambda: later)
    r = call(c, "POST", "/follows/questions", {"question": Q, "seen": ["GSE3", "GSE2"]})
    assert r.status_code == 200 and r.json()["added"] is False
    assert r.json()["watch"]["seen"] == ["GSE1", "GSE2", "GSE3"] and r.json()["watch"]["since"] == w["since"]

    call(c, "POST", "/follows/questions", {"question": "second question", "seen": []})
    assert [x["question"] for x in listed(c)] == ["second question", Q]  # newest first

    assert call(c, "DELETE", "/follows/questions", {"question": Q}).json() == {"ok": True}
    r = call(c, "DELETE", "/follows/questions", {"question": Q})
    assert r.status_code == 404 and r.json()["error"]["code"] == "WATCH_NOT_FOUND"
    assert [x["question"] for x in listed(c)] == ["second question"]

    # Watching again starts afresh on today's date.
    r = call(c, "POST", "/follows/questions", {"question": Q, "seen": ["GSE9"]})
    assert r.status_code == 201 and r.json()["watch"]["seen"] == ["GSE9"] and r.json()["watch"]["since"] == later.date().isoformat()


def test_accounts_do_not_see_each_others_watches(env):
    a, b = signed_in("A"), signed_in("B")
    call(a, "POST", "/follows/questions", {"question": Q, "seen": ["GSE1"]})
    assert listed(b) == []
    assert call(b, "DELETE", "/follows/questions", {"question": Q}).status_code == 404
    r = call(b, "POST", "/follows/questions", {"question": Q, "seen": ["GSE7"]})
    assert r.status_code == 201
    assert listed(a)[0]["seen"] == ["GSE1"] and listed(b)[0]["seen"] == ["GSE7"]


def test_limits(env, monkeypatch):
    c = signed_in()
    assert call(c, "POST", "/follows/questions", {"question": "   "}).json()["error"]["code"] == "INVALID_REQUEST"
    assert call(c, "POST", "/follows/questions", {"question": "q" * 501}).status_code == 422
    assert call(c, "POST", "/follows/questions", {"question": "q" * 500}).status_code == 201
    assert call(c, "POST", "/follows/questions", {"question": Q, "seen": [f"GSE{i}" for i in range(501)]}).status_code == 422
    assert call(c, "POST", "/follows/questions", {"question": Q, "seen": ["GSE1; DROP"]}).status_code == 422

    # A run that would pass 500 seen accessions keeps the newest 500.
    assert call(c, "POST", "/follows/questions", {"question": Q, "seen": [f"GSE{i}" for i in range(500)]}).status_code == 201
    seen = call(c, "POST", "/follows/questions", {"question": Q, "seen": ["GSE9001", "GSE9002"]}).json()["watch"]["seen"]
    assert len(seen) == 500 and seen[0] == "GSE2" and seen[-2:] == ["GSE9001", "GSE9002"]

    monkeypatch.setattr(watches, "MAX_WATCHES", 3)
    assert call(c, "POST", "/follows/questions", {"question": "third"}).status_code == 201
    r = call(c, "POST", "/follows/questions", {"question": "fourth"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LIMIT_REACHED"
    assert call(c, "POST", "/follows/questions", {"question": Q, "seen": ["GSE5"]}).status_code == 200  # a re-run is not refused


def test_import_keeps_since_order_and_is_idempotent(env):
    c = signed_in()
    batch = [
        {"question": "newest", "since": "2026-10-20", "seen": ["GSE3"]},
        {"question": Q, "since": "2026-10-01", "seen": ["GSE1", "GSE2"]},
        {"question": "newest", "since": "2026-09-01", "seen": []},  # repeated in the batch: the first one counts
    ]
    r = call(c, "POST", "/follows/questions/import", {"watches": batch})
    assert r.status_code == 200
    assert r.json() == {"added": ["newest", Q], "already": [], "left_out": [], "held": ["newest", Q]}
    got = listed(c)
    assert [(w["question"], w["since"], w["seen"]) for w in got] == [("newest", "2026-10-20", ["GSE3"]), (Q, "2026-10-01", ["GSE1", "GSE2"])]

    # Again, with the account's own copy changed: nothing is added and the account's copy is kept.
    call(c, "POST", "/follows/questions", {"question": Q, "seen": ["GSE4"]})
    r = call(c, "POST", "/follows/questions/import", {"watches": batch})
    assert r.json()["added"] == [] and r.json()["already"] == ["newest", Q] and r.json()["held"] == ["newest", Q]
    assert next(w for w in listed(c) if w["question"] == Q)["seen"] == ["GSE1", "GSE2", "GSE4"]


def test_import_validation_and_the_limit(env, monkeypatch):
    c = signed_in()
    good = {"question": Q, "since": "2026-10-01", "seen": []}
    for bad in ({"question": "x", "since": "1 Oct", "seen": []}, {"question": "x", "since": "2026-02-30", "seen": []},
                {"question": "x", "since": "2999-01-01", "seen": []}, {"question": "", "since": "2026-10-01", "seen": []},
                {"question": "x", "since": "2026-10-01", "seen": ["no good"]}):
        r = call(c, "POST", "/follows/questions/import", {"watches": [good, bad]})
        assert r.status_code == 422, bad
    assert listed(c) == []  # one invalid watch refuses the whole batch
    assert call(c, "POST", "/follows/questions/import", {"watches": [good] * 201}).status_code == 422

    monkeypatch.setattr(watches, "MAX_WATCHES", 2)
    call(c, "POST", "/follows/questions", {"question": "mine"})
    r = call(c, "POST", "/follows/questions/import", {"watches": [good, {"question": "b", "since": "2026-10-02", "seen": []}, {"question": "mine", "since": "2026-10-02", "seen": []}]})
    assert r.json() == {"added": [Q], "already": ["mine"], "left_out": ["b"], "held": [Q, "mine"]}
