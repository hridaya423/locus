"""Hardening (F9, goal M2.G1): acceptance tests for every backend and docs item of FEATURES.md F9.

Written against branch `accounts` at 244da1e, where every test here fails because the feature is missing. The contracts
(env var names, header names, cookie names, limits, error codes) are fixed here and in specs-f9/F9.md; do not change
this file to make it pass. Style as tests/test_accounts.py and tests/test_follows.py: FastAPI TestClient, a temporary
OMICS_USERS_DB, dev sign-in from a loopback peer, no network.
"""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from omics_agent import account, follows, saved, settings, users, watches

INTENT = {"X-Locus-Intent": "1"}
LOCAL = ("127.0.0.1", 50000)
SNAP = {"title": "Ribosome profiling of HEK293 cells", "source": "GEO", "organism": "Homo sapiens", "modality": "RNA-seq", "samples": 12}
REPO = Path(__file__).resolve().parent.parent
DEV_SECRET = "gate-run-7f3c9a1e5b2d4f60"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OMICS_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("LOCUS_DEV_LOGIN", "1")
    monkeypatch.setenv("LOCUS_RP_ID", "localhost")
    for name in ("LOCUS_COOKIE_INSECURE", "LOCUS_TRUSTED_PROXIES", "LOCUS_DEV_LOGIN_SECRET", "LOCUS_ORIGIN",
                 "ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET", "ORCID_BASE"):
        monkeypatch.delenv(name, raising=False)
    users.AUTH_LIMIT.reset()
    follows.clear_caches()
    yield tmp_path / "users.db"
    users.AUTH_LIMIT.reset()
    follows.clear_caches()


def make_app() -> FastAPI:
    app = FastAPI()
    users.install(app)
    saved.install(app)
    watches.install(app)
    follows.install(app)
    settings.install(app)
    return app


def client(peer=LOCAL, base="https://testserver") -> TestClient:
    return TestClient(make_app(), base_url=base, client=peer, follow_redirects=False)


def dev_login(c: TestClient, name="Gate", **headers):
    return c.post("/account/dev-login", json={"display_name": name}, headers=INTENT | headers)


def signed_in(name="Gate") -> TestClient:
    c = client()
    assert dev_login(c, name).status_code == 200
    return c


def call(c: TestClient, method: str, url: str, body=None, **headers):
    return c.request(method, url, json={} if body is None else body, headers=INTENT | headers)


def add(c, ref, accession, note=""):
    return call(c, "POST", f"/lists/{ref}/items", {"accession": accession, "snapshot": SNAP, "note": note})


def request_from(peer: str, forwarded: str | None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "client": (peer, 1234), "query_string": b""})


# ---------------------------------------------------------------- F1-r1-3: trusted proxy hops


def test_client_address_counts_trusted_proxy_hops(env, monkeypatch):
    chain = "198.51.100.7, 203.0.113.9"
    # Unset (and anything that is not a non-negative integer) means 1: the right-most entry, as before.
    assert users.client_ip(request_from("127.0.0.1", chain)) == "203.0.113.9"
    monkeypatch.setenv("LOCUS_TRUSTED_PROXIES", "1")
    assert users.client_ip(request_from("127.0.0.1", chain)) == "203.0.113.9"
    monkeypatch.setenv("LOCUS_TRUSTED_PROXIES", "abc")
    assert users.client_ip(request_from("127.0.0.1", chain)) == "203.0.113.9"
    # 2: two proxies in front of the web app each appended an entry; the client is the second from the right.
    monkeypatch.setenv("LOCUS_TRUSTED_PROXIES", "2")
    assert users.client_ip(request_from("127.0.0.1", chain)) == "198.51.100.7"
    assert users.client_ip(request_from("127.0.0.1", "203.0.113.9")) == "127.0.0.1"  # fewer entries than hops: the peer
    assert users.client_ip(request_from("192.0.2.5", chain)) == "192.0.2.5"  # a non-loopback peer is never overridden
    # 0: X-Forwarded-For is ignored; the peer address is the caller.
    monkeypatch.setenv("LOCUS_TRUSTED_PROXIES", "0")
    assert users.client_ip(request_from("127.0.0.1", chain)) == "127.0.0.1"
    assert users.client_ip(request_from("::1", "203.0.113.9")) == "::1"
    # ...so a client that forges a new address on every request still meets the 10-a-minute sign-in limit.
    c = client()
    codes = [c.post("/account/login/options", json={}, headers=INTENT | {"X-Forwarded-For": f"203.0.113.{i}"}).status_code for i in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


# ---------------------------------------------------------------- F1-r1-4: dev-login secret


def test_dev_login_needs_the_secret_header_when_a_secret_is_set(env, monkeypatch):
    monkeypatch.setenv("LOCUS_DEV_LOGIN_SECRET", DEV_SECRET)
    r = dev_login(client())
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert dev_login(client(), **{"X-Locus-Dev-Secret": "wrong"}).status_code == 404
    assert dev_login(client(), **{"X-Locus-Dev-Secret": DEV_SECRET[:-1]}).status_code == 404
    ok = dev_login(client(), **{"X-Locus-Dev-Secret": DEV_SECRET})
    assert ok.status_code == 200 and ok.json()["user"]["display_name"] == "Gate"
    # The secret is in addition to the other two conditions, never instead of them.
    assert dev_login(client(peer=("203.0.113.9", 1)), **{"X-Locus-Dev-Secret": DEV_SECRET}).status_code == 404
    monkeypatch.setenv("LOCUS_DEV_LOGIN", "0")
    assert dev_login(client(), **{"X-Locus-Dev-Secret": DEV_SECRET}).status_code == 404
    # An empty secret counts as unset: dev-login behaves as before (LOCUS_DEV_LOGIN=1 and a local request).
    monkeypatch.setenv("LOCUS_DEV_LOGIN", "1")
    monkeypatch.setenv("LOCUS_DEV_LOGIN_SECRET", "")
    assert dev_login(client()).status_code == 200


# ---------------------------------------------------------------- F1-r1-5: CORS narrowed, Origin checked


def test_cors_never_grants_the_intent_header(env):
    from omics_agent import api

    c = TestClient(api.app, client=LOCAL)
    preflight = {"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"}
    r = c.options("/lists/saved/items", headers=preflight | {"Access-Control-Request-Headers": "content-type, x-locus-intent"})
    assert r.status_code == 400
    assert "x-locus-intent" not in r.headers.get("access-control-allow-headers", "").lower()
    plain = c.options("/compare", headers=preflight | {"Access-Control-Request-Headers": "content-type"})
    assert plain.status_code == 200 and plain.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_state_changing_requests_from_another_origin_are_refused(env, monkeypatch):
    monkeypatch.setenv("LOCUS_ORIGIN", "http://localhost:3051")
    c = signed_in()
    r = call(c, "POST", "/lists", {"name": "Atlas"}, Origin="http://evil.example")
    assert r.status_code == 403 and r.json()["error"]["code"] == "ORIGIN_REFUSED"
    assert c.get("/lists").json()["lists"][0]["name"] == "Saved" and len(c.get("/lists").json()["lists"]) == 1
    assert call(c, "POST", "/account/sign-out", Origin="null").status_code == 403
    assert c.get("/lists", headers={"Origin": "http://evil.example"}).status_code == 200  # reads are not refused
    assert call(c, "POST", "/lists", {"name": "Atlas"}, Origin="http://localhost:3051").status_code == 201
    assert call(c, "POST", "/lists", {"name": "Other"}).status_code == 201  # no Origin header (curl, tests): allowed
    # Without LOCUS_ORIGIN there is nothing to compare with, so the check is off.
    monkeypatch.delenv("LOCUS_ORIGIN")
    assert call(c, "POST", "/lists", {"name": "Third"}, Origin="http://evil.example").status_code == 201


# ---------------------------------------------------------------- F1-r2-1: __Host- cookie names


def test_cookies_take_the_host_prefix_when_secure(env, monkeypatch):
    assert users.cookie_name() == "__Host-locus_session"
    c = client()
    r = dev_login(c, "Ada")
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-locus_session=") and "Secure" in cookie and "Path=/" in cookie and "Domain" not in cookie
    token = c.cookies.get("__Host-locus_session")
    assert token and c.get("/account/me").json()["user"]["display_name"] == "Ada"
    # A cookie under the plain name (for instance one tossed in from a sibling subdomain) is not a session.
    tossed = client()
    tossed.cookies.set("locus_session", token)
    assert tossed.get("/account/me").json()["user"] is None
    out = call(c, "POST", "/account/sign-out")
    assert out.headers["set-cookie"].startswith("__Host-locus_session=") and "Max-Age=0" in out.headers["set-cookie"]
    assert c.get("/account/me").json()["user"] is None
    # ORCID's browser-binding cookie follows the same rule.
    monkeypatch.setenv("ORCID_CLIENT_ID", "APP-TEST")
    monkeypatch.setenv("ORCID_CLIENT_SECRET", "shh")
    assert account.orcid_cookie_name() == "__Host-locus_orcid"
    start = client().get("/account/orcid/start")
    assert start.status_code == 302 and start.headers["set-cookie"].startswith("__Host-locus_orcid=")
    # Plain http on localhost (LOCUS_COOKIE_INSECURE=1) cannot use the prefix: the plain names, without Secure.
    monkeypatch.setenv("LOCUS_COOKIE_INSECURE", "1")
    assert users.cookie_name() == "locus_session" and account.orcid_cookie_name() == "locus_orcid"
    plain = client(base="http://testserver")
    cookie = dev_login(plain, "Bea").headers["set-cookie"]
    assert cookie.startswith("locus_session=") and "Secure" not in cookie
    assert plain.get("/account/me").json()["user"]["display_name"] == "Bea"
    assert client(base="http://testserver").get("/account/orcid/start").headers["set-cookie"].startswith("locus_orcid=")


# ---------------------------------------------------------------- F5-r3-1: ORCID names in capitals or with a title


def test_orcid_record_names_in_capitals_or_with_a_title_agree():
    # A given-name word of three or more letters without dots is a spelled name whatever its case.
    assert follows.names_agree("Thoreen CC", "CARSON", "THOREEN")
    assert follows.names_agree("Carson C Thoreen", "CARSON", "THOREEN")
    assert follows.names_agree("Carson C Thoreen", "CARSON C", "Thoreen")
    # Titles in the record's given names are dropped before anything is compared.
    assert follows.names_agree("Carson C Thoreen", "Dr. Carson", "Thoreen")
    assert follows.names_agree("Thoreen CC", "Dr. Carson", "Thoreen")
    assert follows.names_agree("Thoreen CC", "Prof Carson C", "Thoreen")
    assert follows.record_agrees("Thoreen CC", {"given": "Dr Carson", "family": "THOREEN", "credit": None})
    # The refusals stay refusals.
    assert not follows.names_agree("Thoreen CC", "KEVIN", "THOREEN")
    assert not follows.names_agree("Carson C Thoreen", "Dr. Kevin", "Thoreen")
    assert not follows.names_agree("Thoreen C", "CARSON C", "THOREEN")
    assert not follows.names_agree("Thoreen CC", "CARSON J", "THOREEN")
    assert not follows.names_agree("Thoreen CC", "Dr.", "Thoreen")
    assert follows.names_agree("Thoreen CC", "C. C.", "Thoreen") and not follows.names_agree("Thoreen CC", "C.", "Thoreen")


# ---------------------------------------------------------------- F5-r3-2: global follow limit


def test_follows_overall_limit_is_sixty_a_minute(env):
    assert follows.FOLLOW_LIMIT.per_ip == 30 and follows.FOLLOW_LIMIT.overall == 60
    for i in range(60):
        follows.FOLLOW_LIMIT.check(f"account:{i}")
    with pytest.raises(users.ApiError) as caught:
        follows.FOLLOW_LIMIT.check("account:999")
    assert caught.value.status == 429 and caught.value.code == "RATE_LIMITED"


# ---------------------------------------------------------------- quota ledger: writes per account


def test_account_writes_are_limited_to_120_a_minute(env, monkeypatch):
    assert users.WRITE_PER_MINUTE == 120
    a, b = signed_in("Ada"), signed_in("Bea")
    for i in range(120):
        assert add(a, "saved", f"GSE{i + 1}").status_code == 201, i
    r = call(a, "PATCH", "/lists/saved/items/GSE1", {"note": "one too many"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED" and r.json()["error"]["transient"] is True
    assert int(r.headers["Retry-After"]) > 0
    # One ledger for every write route of the account: lists, watched searches, follows and settings.
    assert call(a, "POST", "/lists", {"name": "Atlas"}).status_code == 429
    assert call(a, "POST", "/follows/questions", {"question": "ribosome profiling in HEK293", "seen": []}).status_code == 429
    assert call(a, "PATCH", "/account/profile", {"display_name": "Ada L"}).status_code == 429
    # Reads are never counted, nor are other accounts.
    assert a.get("/lists").status_code == 200 and a.get("/lists").json()["lists"][0]["count"] == 120
    assert add(b, "saved", "GSE1").status_code == 201
    # The window is one minute of users.now(); refused attempts are not recorded.
    later = users.now() + timedelta(seconds=61)
    monkeypatch.setattr(users, "now", lambda: later)
    assert call(a, "PATCH", "/lists/saved/items/GSE1", {"note": "fine now"}).status_code == 200
    assert call(a, "PATCH", "/account/profile", {"display_name": "Ada L"}).status_code == 200


# ---------------------------------------------------------------- F2-r1: per-account storage cap


def test_lists_have_a_per_account_storage_cap(env, monkeypatch):
    assert saved.STORAGE_MAX == 5_000_000 and saved.LIMITS["storage"] == 5_000_000
    monkeypatch.setattr(saved, "STORAGE_MAX", 3000)  # an item with SNAP and no tags costs 123 characters plus its note
    c = signed_in()
    lid = call(c, "POST", "/lists", {"name": "Atlas"}).json()["list"]["id"]
    assert add(c, "saved", "GSE1", note="a" * 2000).status_code == 201
    # The cap is per account, across lists.
    r = add(c, lid, "GSE2", note="b" * 2000)
    assert r.status_code == 409 and r.json()["error"]["code"] == "STORAGE_FULL"
    assert add(c, lid, "GSE2", note="b" * 500).status_code == 201
    r = call(c, "PATCH", f"/lists/{lid}/items/GSE2", {"note": "b" * 1000})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STORAGE_FULL"
    assert c.get(f"/lists/{lid}").json()["items"][0]["note"] == "b" * 500
    assert call(c, "PATCH", "/lists/saved/items/GSE1", {"note": ""}).status_code == 200  # shrinking is always allowed
    # A guest import adds each item that still fits, in order, and reports the others in left_out.
    batch = [{"accession": "GSE3", "snapshot": SNAP, "note": "c" * 1500}, {"accession": "GSE4", "snapshot": SNAP, "note": "d" * 1500},
             {"accession": "GSE5", "snapshot": SNAP}]
    out = call(c, "POST", "/lists/saved/import", {"items": batch}).json()
    assert out["added"] == ["GSE3", "GSE5"] and out["left_out"] == ["GSE4"]


# ---------------------------------------------------------------- no-store on account responses


def test_account_list_and_follow_responses_are_never_cached(env):
    guest = client()
    assert guest.get("/account/me").headers["cache-control"] == "no-store"
    refused = guest.get("/lists")
    assert refused.status_code == 401 and refused.headers["cache-control"] == "no-store"
    c = signed_in()
    for path in ("/account/me", "/account/settings", "/lists", "/follows/people", "/follows/questions"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store", path
    assert add(c, "saved", "GSE1").headers["cache-control"] == "no-store"
    assert call(c, "POST", "/account/sign-out").headers["cache-control"] == "no-store"
    # Routes that are not about an account keep their own caching.
    assert "cache-control" not in TestClient(make_app(), client=LOCAL).get("/openapi.json").headers


# ---------------------------------------------------------------- docs


def test_docs_carry_the_threat_model_and_the_new_settings():
    text = (REPO / "docs" / "accounts.md").read_text()
    lines = text.splitlines()
    assert "## Threat model" in lines
    for needle in ("LOCUS_TRUSTED_PROXIES", "LOCUS_DEV_LOGIN_SECRET", "X-Locus-Dev-Secret", "__Host-locus_session", "__Host-locus_orcid",
                   "ORIGIN_REFUSED", "STORAGE_FULL",
                   "An IPv6 address counts as its /64 network for every rate limit, sign-in included.",
                   "Every write by a signed-in account counts against one ledger of 120 a minute.",
                   "The follow limit is 30 a minute per account and 60 a minute overall, half of the ORCID pace."):
        assert needle in text, needle
    threat = text.split("## Threat model", 1)[1].split("\n## ", 1)[0]
    for needle in ("What locus protects", "Who it protects against", "What it does not protect against"):
        assert needle in threat, needle
    note = REPO / "docs" / "plans" / "2026-10-30-email-digest.md"
    body = note.read_text()
    assert body.splitlines()[0] == "# Email digest (design note, not built)"
    for heading in ("## What it would send", "## Ranking", "## What it needs before it can be built", "## Not decided"):
        assert heading in body.splitlines(), heading
    assert "Juri" in body and "mail provider" in body
