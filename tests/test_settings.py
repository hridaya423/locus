"""Settings (F7): display name, passkeys (rename, add another, remove but never the last), recovery codes (regenerate
needs a recent strong sign-in), ORCID unlink, the confirmation step (passkey or recovery code; dev sign-in never
counts), download everything as JSON (own rows only, no secrets) and deleting the account (one transaction, public
links 404, cookie cleared). WebAuthn is mocked as in test_accounts.py; no network."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from omics_agent import account, follows, saved, settings, users, watches

INTENT = {"X-Locus-Intent": "1"}
LOCAL = ("127.0.0.1", 50000)
SNAP = {"title": "Ribosome profiling of HEK293 cells", "source": "GEO", "organism": "Homo sapiens", "modality": "RNA-seq", "samples": 12}
ORCID = "0000-0003-1164-7224"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OMICS_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("LOCUS_DEV_LOGIN", "1")
    monkeypatch.setenv("LOCUS_ORIGIN", "http://localhost:3051")
    monkeypatch.setenv("LOCUS_RP_ID", "localhost")
    for name in ("LOCUS_COOKIE_INSECURE", "ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    users.AUTH_LIMIT.reset()
    yield tmp_path / "users.db"
    users.AUTH_LIMIT.reset()


def make_app() -> FastAPI:
    app = FastAPI()
    users.install(app)
    saved.install(app)
    watches.install(app)
    follows.install(app)
    settings.install(app)
    return app


def client() -> TestClient:
    return TestClient(make_app(), base_url="https://testserver", client=LOCAL)


def call(c: TestClient, method: str, url: str, body=None):
    return c.request(method, url, json={} if body is None else body, headers=INTENT)


def rows(sql, *args):
    conn = users.connect()
    try:
        return [tuple(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def dev(name="Dev Gate") -> TestClient:
    c = client()
    assert call(c, "POST", "/account/dev-login", {"display_name": name}).status_code == 200
    return c


def register(monkeypatch, name="Grace", credential_id=b"cred-1") -> tuple[TestClient, list[str]]:
    """A real account (passkey + ten recovery codes) through the mocked registration verifier."""
    monkeypatch.setattr(account, "verify_registration_response",
                        lambda **kw: SimpleNamespace(credential_id=credential_id, credential_public_key=b"public-key-" + credential_id, sign_count=0))
    c = client()
    opts = call(c, "POST", "/account/register/options", {"display_name": name}).json()
    r = call(c, "POST", "/account/register/verify", {"challenge_id": opts["challenge_id"], "credential": {"id": "x", "response": {"transports": ["internal"]}}})
    assert r.status_code == 200
    return c, r.json()["recovery_codes"]


def add_passkey(c, monkeypatch, credential_id: bytes, nickname=""):
    monkeypatch.setattr(account, "verify_registration_response",
                        lambda **kw: SimpleNamespace(credential_id=credential_id, credential_public_key=b"public-key-" + credential_id, sign_count=0))
    started = call(c, "POST", "/account/passkeys/options")
    opts = started.json()
    if started.status_code != 200:
        return opts, started
    return opts, call(c, "POST", "/account/passkeys/verify", {"challenge_id": opts["challenge_id"], "credential": {"id": "y"}, "nickname": nickname})


def confirm_with_passkey(c, monkeypatch, credential_id: bytes = b"cred-1"):
    monkeypatch.setattr(account, "verify_authentication_response", lambda **kw: SimpleNamespace(new_sign_count=3))
    started = call(c, "POST", "/account/confirm/options")
    opts = started.json()
    if started.status_code != 200:
        return opts, started
    return opts, call(c, "POST", "/account/confirm/verify", {"challenge_id": opts["challenge_id"], "credential": {"id": account.bytes_to_base64url(credential_id)}})


def fill(c):
    """Lists (one public, with a note), a watched search and a follow."""
    lid = call(c, "POST", "/lists", {"name": "Stress atlas", "description": "HEK293"}).json()["list"]["id"]
    call(c, "POST", f"/lists/{lid}/items", {"accession": "GSE1", "snapshot": SNAP, "note": "my note", "tags": ["todo"]})
    call(c, "POST", "/lists/saved/items", {"accession": "GSE2", "snapshot": SNAP})
    share = call(c, "POST", f"/lists/{lid}/publish", {}).json()["list"]["public"]["share_id"]
    assert call(c, "POST", "/follows/questions", {"question": "ribosome stalling", "seen": ["GSE1"]}).status_code in (200, 201)
    conn = users.connect()
    uid = conn.execute("SELECT user_id FROM sessions ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO follows (user_id, orcid, display_name, followed_at) VALUES (?, ?, 'Carson Thoreen', '2026-10-30T00:00:00Z')", (uid,ORCID))
    conn.commit()
    conn.close()
    return lid, share


# ---------------------------------------------------------------- what /settings shows, name, passkeys


def test_settings_needs_sign_in_and_intent(env):
    c = client()
    r = c.get("/account/settings")
    assert r.status_code == 401 and r.json()["error"]["code"] == "SIGN_IN_REQUIRED"
    s = dev()
    assert s.patch("/account/profile", json={"display_name": "X"}).status_code == 403  # no X-Locus-Intent
    assert s.request("DELETE", "/account", content="{}", headers={"X-Locus-Intent": "1", "Content-Type": "text/plain"}).status_code == 403


def test_settings_lists_passkeys_and_renames_the_account(env, monkeypatch):
    c, _ = register(monkeypatch)
    body = c.get("/account/settings").json()
    assert body["user"]["display_name"] == "Grace" and body["user"]["recovery_codes_left"] == 10
    [key] = body["passkeys"]
    assert set(key) == {"id", "nickname", "created_at", "last_used_at"} and key["last_used_at"] is None
    assert body["session_method"] == "passkey" and body["confirmed_until"] is not None  # just signed in with a passkey
    r = call(c, "PATCH", "/account/profile", {"display_name": "  Grace   Hopper "})
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Grace Hopper"
    assert c.get("/account/me").json()["user"]["display_name"] == "Grace Hopper"
    assert call(c, "PATCH", "/account/profile", {"display_name": "   "}).status_code == 422
    assert call(c, "PATCH", "/account/profile", {"display_name": "x" * 81}).status_code == 422


def test_add_rename_and_remove_passkeys_but_never_the_last(env, monkeypatch):
    c, _ = register(monkeypatch)
    opts, r = add_passkey(c, monkeypatch, b"cred-2", "Work laptop")
    # The browser is told which passkeys the account holds, under the account's own WebAuthn user handle.
    assert [d["id"] for d in opts["options"]["excludeCredentials"]] == [account.bytes_to_base64url(b"cred-1")]
    assert r.status_code == 200 and [p["nickname"] for p in r.json()["passkeys"]] == ["", "Work laptop"]
    assert r.json()["user"]["passkeys"] == 2
    # The same passkey twice is refused.
    assert add_passkey(c, monkeypatch, b"cred-2")[1].json()["error"]["code"] == "PASSKEY_EXISTS"
    first, second = (p["id"] for p in r.json()["passkeys"])
    r = call(c, "PATCH", f"/account/passkeys/{first}", {"nickname": " Phone "})
    assert r.status_code == 200 and r.json()["passkeys"][0]["nickname"] == "Phone"
    assert call(c, "DELETE", f"/account/passkeys/{second}").status_code == 200
    last = call(c, "DELETE", f"/account/passkeys/{first}")
    assert last.status_code == 409 and last.json()["error"]["code"] == "LAST_PASSKEY"
    assert rows("SELECT count(*) FROM credentials") == [(1,)]
    # Another account's passkey looks like a missing one.
    other = dev("Other")
    assert call(other, "PATCH", f"/account/passkeys/{first}", {"nickname": "mine"}).status_code == 404
    assert call(other, "DELETE", f"/account/passkeys/{first}").status_code == 403  # a dev sign-in never removes one
    assert rows("SELECT count(*) FROM credentials") == [(1,)]


def test_add_passkey_challenge_belongs_to_the_account_that_asked(env, monkeypatch):
    c, _ = register(monkeypatch)
    opts = call(c, "POST", "/account/passkeys/options").json()
    other = dev("Other")
    r = call(other, "POST", "/account/passkeys/verify", {"challenge_id": opts["challenge_id"], "credential": {"id": "y"}})
    assert r.status_code == 400 and rows("SELECT count(*) FROM credentials") == [(1,)]


# ---------------------------------------------------------------- strong sign-in: dev never counts; confirm


def test_dev_sign_in_cannot_delete_or_regenerate(env):
    c = dev()
    assert c.get("/account/settings").json()["confirmed_until"] is None
    for method, url in [("DELETE", "/account"), ("POST", "/account/recovery-codes")]:
        r = call(c, method, url)
        assert r.status_code == 403 and r.json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert rows("SELECT count(*) FROM users") == [(1,)]
    # A dev account has no passkey to confirm with, and no recovery codes.
    assert call(c, "POST", "/account/confirm/options").json()["error"]["code"] == "NO_PASSKEY"
    assert call(c, "POST", "/account/confirm/recovery", {"code": "AAAA-BBBB-CCCC"}).status_code == 400


def test_strong_sign_in_lasts_five_minutes_then_confirm_renews_it(env, monkeypatch):
    c, codes = register(monkeypatch)
    start = users.now()
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=6))
    assert c.get("/account/settings").json()["confirmed_until"] is None
    assert call(c, "POST", "/account/recovery-codes").json()["error"]["code"] == "CONFIRM_REQUIRED"
    opts, r = confirm_with_passkey(c, monkeypatch)
    assert [d["id"] for d in opts["options"]["allowCredentials"]] == [account.bytes_to_base64url(b"cred-1")]
    assert r.status_code == 200 and r.json()["confirmed_until"] is not None
    assert rows("SELECT sign_count FROM credentials") == [(3,)]
    r = call(c, "POST", "/account/recovery-codes")
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10 and r.json()["user"]["recovery_codes_left"] == 10
    # The old codes no longer work; the new ones do.
    fresh = client()
    assert call(fresh, "POST", "/account/recovery", {"code": codes[0]}).status_code == 400
    assert call(fresh, "POST", "/account/recovery", {"code": r.json()["recovery_codes"][0]}).status_code == 200


def test_confirm_refuses_another_accounts_passkey_and_codes(env, monkeypatch):
    a, a_codes = register(monkeypatch, "A", b"cred-a")
    b, _ = register(monkeypatch, "B", b"cred-b")
    start = users.now()
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=6))
    _, r = confirm_with_passkey(b, monkeypatch, b"cred-a")
    assert r.status_code == 400 and r.json()["error"]["code"] == "PASSKEY_UNKNOWN"
    r = call(b, "POST", "/account/confirm/recovery", {"code": a_codes[0]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "RECOVERY_CODE_INVALID"
    assert rows("SELECT count(*) FROM recovery_codes WHERE used_at IS NOT NULL") == [(0,)]  # A's code was not spent
    assert b.get("/account/settings").json()["confirmed_until"] is None
    # A's own code confirms A, once.
    assert call(a, "POST", "/account/confirm/recovery", {"code": a_codes[0].lower()}).json()["confirmed_until"] is not None
    assert call(a, "POST", "/account/confirm/recovery", {"code": a_codes[0]}).status_code == 400


def test_a_failed_passkey_check_does_not_confirm(env, monkeypatch):
    c, _ = register(monkeypatch)
    start = users.now()
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=6))

    def bad(**kw):
        raise account.InvalidAuthenticationResponse("bad signature")

    monkeypatch.setattr(account, "verify_authentication_response", bad)
    opts = call(c, "POST", "/account/confirm/options").json()
    r = call(c, "POST", "/account/confirm/verify", {"challenge_id": opts["challenge_id"], "credential": {"id": account.bytes_to_base64url(b"cred-1")}})
    assert r.status_code == 400 and c.get("/account/settings").json()["confirmed_until"] is None


# ---------------------------------------------------------------- ORCID unlink


def test_orcid_unlink_refused_when_it_is_the_only_way_in(env, monkeypatch):
    c, _ = register(monkeypatch)
    assert call(c, "DELETE", "/account/orcid").status_code == 404
    uid = rows("SELECT id FROM users")[0][0]
    conn = users.connect()
    conn.execute("INSERT INTO orcid_links VALUES (?, ?, '2026-10-30T00:00:00Z')", (uid, ORCID))
    conn.commit()
    conn.close()
    r = call(c, "DELETE", "/account/orcid")
    assert r.status_code == 200 and r.json()["user"]["orcid"] is None
    only = dev("ORCID only")
    oid = rows("SELECT max(id) FROM users")[0][0]
    conn = users.connect()
    conn.execute("INSERT INTO orcid_links VALUES (?, ?, '2026-10-30T00:00:00Z')", (oid, "0000-0002-1825-0097"))
    conn.commit()
    conn.close()
    assert call(only, "DELETE", "/account/orcid").json()["error"]["code"] == "ORCID_ONLY_SIGN_IN"


# ---------------------------------------------------------------- your data


def test_export_holds_own_rows_and_no_secrets(env, monkeypatch):
    c, codes = register(monkeypatch)
    lid, share = fill(c)
    other = dev("Someone Else")
    call(other, "POST", "/lists/saved/items", {"accession": "GSE999", "snapshot": SNAP | {"title": "other person's dataset"}})
    r = c.get("/account/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert r.headers["content-disposition"].startswith("attachment;") and r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["account"]["display_name"] == "Grace"
    by_name = {li["name"]: li for li in data["lists"]}
    assert set(by_name) == {"Saved", "Stress atlas"}
    stress = by_name["Stress atlas"]
    assert stress["items"][0] | {"added_at": None} == {"accession": "GSE1", "note": "my note", "tags": ["todo"], "snapshot": SNAP, "added_at": None}
    assert stress["public"]["share_id"] == share and stress["public"]["page"]["items"][0]["accession"] == "GSE1"
    assert [w["question"] for w in data["watched_searches"]] == ["ribosome stalling"]
    assert [f["orcid"] for f in data["followed_people"]] == [ORCID]
    assert data["recovery_codes"] == {"total": 10, "left": 10, "used_at": []}
    assert data["passkeys"][0]["transports"] == ["internal"] and data["sessions"][0]["method"] == "passkey"
    assert any(a["event"] == "account created" for a in data["activity"])
    text = r.text
    # No other account's rows, and none of the secrets the DB holds.
    assert "GSE999" not in text and "Someone Else" not in text
    for (token_hash,) in rows("SELECT token_sha256 FROM sessions"):
        assert token_hash not in text
    for (code_hash,) in rows("SELECT code_sha256 FROM recovery_codes"):
        assert code_hash not in text
    for (handle,) in rows("SELECT user_handle FROM users"):
        assert handle not in text
    assert "public-key" not in text and "public_key" not in text and all(code not in text for code in codes)
    assert c.cookies.get(users.cookie_name()) not in text
    assert client().get("/account/export").status_code == 401


# ---------------------------------------------------------------- delete the account


def test_delete_account_removes_every_row_at_once(env, monkeypatch):
    c, _ = register(monkeypatch)
    lid, share = fill(c)
    other = dev("Keeper")
    call(other, "POST", "/lists/saved/items", {"accession": "GSE5", "snapshot": SNAP})
    uid = rows("SELECT id FROM users WHERE display_name = 'Grace'")[0][0]
    assert client().get(f"/public/lists/{share}").status_code == 200
    r = call(c, "DELETE", "/account")
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "locus_session=" in cookie and ("Max-Age=0" in cookie or "expires=" in cookie.lower())
    assert c.get("/account/me").json()["user"] is None
    # Every table is empty of this account; the other account is untouched.
    for table in ("users", "credentials", "sessions", "recovery_codes", "orcid_links", "challenges", "lists", "watches", "follows"):
        col = "id" if table == "users" else "user_id"
        assert rows(f"SELECT count(*) FROM {table} WHERE {col} = ?", uid) == [(0,)], table
    assert rows("SELECT count(*) FROM list_items WHERE accession IN ('GSE1', 'GSE2')") == [(0,)]
    assert client().get(f"/public/lists/{share}").status_code == 404
    # The activity log keeps one row: when an account was deleted, with nothing that points at it.
    assert rows("SELECT user_id, event FROM audit WHERE user_id = ? OR user_id IS NULL", uid) == [(None, "account deleted")]
    assert rows("SELECT count(*) FROM users") == [(1,)] and "GSE5" in call(other, "GET", "/lists").json()["holds"]
    # The deleted account's passkey no longer signs in.
    opts = call(client(), "POST", "/account/login/options").json()
    gone = call(client(), "POST", "/account/login/verify", {"challenge_id": opts["challenge_id"], "credential": {"id": account.bytes_to_base64url(b"cred-1")}})
    assert gone.json()["error"]["code"] == "PASSKEY_UNKNOWN"


def test_delete_is_one_transaction(env, monkeypatch):
    c, _ = register(monkeypatch)
    fill(c)
    before = {t: rows(f"SELECT count(*) FROM {t}") for t in ("users", "lists", "list_items", "watches", "follows", "credentials", "sessions", "audit")}
    # The last statement fails: nothing before it may stay deleted.
    monkeypatch.setattr(settings, "_OWNED", settings._OWNED + ("DELETE FROM no_such_table WHERE id = ?",))
    with pytest.raises(Exception):
        call(c, "DELETE", "/account")
    assert {t: rows(f"SELECT count(*) FROM {t}") for t in before} == before


def test_deleting_needs_a_fresh_confirmation(env, monkeypatch):
    c, codes = register(monkeypatch)
    start = users.now()
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=5, seconds=1))
    assert call(c, "DELETE", "/account").json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert call(c, "POST", "/account/confirm/recovery", {"code": codes[3]}).status_code == 200
    assert call(c, "DELETE", "/account").status_code == 200
    assert rows("SELECT count(*) FROM users") == [(0,)]
    assert json.loads(json.dumps(rows("SELECT event FROM audit"))) == [["account deleted"]]


# ---------------------------------------------------------------- F7-r1-1: a session cookie alone cannot step up


def orcid_only(fresh_minutes_ago: float, orcid: str = "0000-0002-1825-0097") -> TestClient:
    """An account made by ORCID (no passkey, no recovery codes) whose ORCID session began some minutes ago."""
    c = dev("ORCID made")
    uid = rows("SELECT max(id) FROM users")[0][0]
    started = users.iso(users.now() - timedelta(minutes=fresh_minutes_ago))
    conn = users.connect()
    conn.execute("INSERT INTO orcid_links VALUES (?, ?, '2026-10-30T00:00:00Z')", (uid, orcid))
    conn.execute("UPDATE sessions SET method = 'orcid', created_at = ? WHERE user_id = ?", (started, uid))
    conn.commit()
    conn.close()
    return c


def test_the_reviewers_takeover_chain_is_refused_at_every_step(env, monkeypatch):
    victim, codes = register(monkeypatch, "Victim", b"victim-key")
    start = users.now()
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=6))  # the cookie holder's confirmation expired
    assert call(victim, "DELETE", "/account").json()["error"]["code"] == "CONFIRM_REQUIRED"
    # 1. Add an attacker passkey: refused at the options step, and at the verify step for options fetched in time.
    _, r = add_passkey(victim, monkeypatch, b"attacker-key")
    assert r.status_code == 403 and r.json()["error"]["code"] == "CONFIRM_REQUIRED"
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=4))
    early = call(victim, "POST", "/account/passkeys/options").json()
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=6))
    r = call(victim, "POST", "/account/passkeys/verify", {"challenge_id": early["challenge_id"], "credential": {"id": "y"}})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert rows("SELECT credential_id FROM credentials") == [(account.bytes_to_base64url(b"victim-key"),)]
    # 2. Confirm with it: it is not there, so it does not confirm.
    _, r = confirm_with_passkey(victim, monkeypatch, b"attacker-key")
    assert r.status_code == 400 and r.json()["error"]["code"] == "PASSKEY_UNKNOWN"
    # 3. Remove the owner's passkey (even with a second one present), 4. regenerate codes, 5. delete: all refused.
    conn = users.connect()
    conn.execute("INSERT INTO credentials (credential_id, user_id, public_key, sign_count, transports, created_at, nickname) "
                 "SELECT 'owner-second', user_id, x'00', 0, '[]', created_at, 'Laptop' FROM credentials")
    conn.commit()
    conn.close()
    r = call(victim, "DELETE", f"/account/passkeys/{account.bytes_to_base64url(b'victim-key')}")
    assert r.status_code == 403 and r.json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert call(victim, "POST", "/account/recovery-codes").json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert call(victim, "DELETE", "/account").json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert rows("SELECT count(*) FROM credentials") == [(2,)] and rows("SELECT count(*) FROM users") == [(1,)]
    assert call(client(), "POST", "/account/recovery", {"code": codes[0]}).status_code == 200  # the owner's codes still work


def test_a_passkey_added_in_this_session_cannot_confirm_it(env, monkeypatch):
    c, _ = register(monkeypatch, "Grace", b"cred-1")
    _, r = add_passkey(c, monkeypatch, b"cred-new")  # allowed: the sign-up just now is a strong sign-in
    assert r.status_code == 200 and r.json()["user"]["passkeys"] == 2
    start = users.now()
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=6))
    opts, r = confirm_with_passkey(c, monkeypatch, b"cred-new")
    assert [d["id"] for d in opts["options"]["allowCredentials"]] == [account.bytes_to_base64url(b"cred-1")]
    assert r.status_code == 400 and r.json()["error"]["code"] == "PASSKEY_TOO_NEW"
    assert c.get("/account/settings").json()["confirmed_until"] is None
    # The older passkey confirms this session; the new one confirms from its own next sign-in on.
    assert confirm_with_passkey(c, monkeypatch, b"cred-1")[1].status_code == 200
    assert call(c, "DELETE", f"/account/passkeys/{account.bytes_to_base64url(b'cred-1')}").status_code == 200
    _, r = confirm_with_passkey(c, monkeypatch, b"cred-new")
    assert r.status_code == 409 and r.json()["error"]["code"] == "PASSKEY_TOO_NEW"  # no older passkey left to offer
    users.AUTH_LIMIT.reset()  # this test makes more passkey ceremonies than one caller may in a minute
    other = client()
    monkeypatch.setattr(account, "verify_authentication_response", lambda **kw: SimpleNamespace(new_sign_count=4))
    opts = call(other, "POST", "/account/login/options").json()
    signed = call(other, "POST", "/account/login/verify", {"challenge_id": opts["challenge_id"], "credential": {"id": account.bytes_to_base64url(b"cred-new")}})
    assert signed.status_code == 200
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=13))
    assert confirm_with_passkey(other, monkeypatch, b"cred-new")[1].status_code == 200


def test_an_orcid_account_adds_its_first_passkey_only_soon_after_an_orcid_sign_in(env, monkeypatch):
    fresh = orcid_only(fresh_minutes_ago=2)
    opts, r = add_passkey(fresh, monkeypatch, b"first-key")
    assert opts["options"]["excludeCredentials"] == [] and r.status_code == 200 and r.json()["user"]["passkeys"] == 1
    # The exception covers the first passkey only.
    _, r = add_passkey(fresh, monkeypatch, b"second-key")
    assert r.status_code == 403 and r.json()["error"]["code"] == "CONFIRM_REQUIRED"
    # And that passkey cannot confirm this session: deleting needs a sign-in with it.
    assert call(fresh, "POST", "/account/confirm/options").json()["error"]["code"] == "PASSKEY_TOO_NEW"
    assert call(fresh, "DELETE", "/account").json()["error"]["code"] == "CONFIRM_REQUIRED"
    stale = orcid_only(fresh_minutes_ago=6, orcid="0000-0001-5109-3700")
    r = call(stale, "POST", "/account/passkeys/options")
    assert r.status_code == 403 and r.json()["error"]["code"] == "ORCID_SIGN_IN_REQUIRED"
    # A dev sign-in never qualifies.
    assert call(dev("Dev"), "POST", "/account/passkeys/options").json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_unlinking_orcid_needs_a_fresh_confirmation(env, monkeypatch):
    c, _ = register(monkeypatch)
    uid = rows("SELECT id FROM users")[0][0]
    conn = users.connect()
    conn.execute("INSERT INTO orcid_links VALUES (?, ?, '2026-10-30T00:00:00Z')", (uid, ORCID))
    conn.commit()
    conn.close()
    start = users.now()
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=6))
    assert call(c, "DELETE", "/account/orcid").json()["error"]["code"] == "CONFIRM_REQUIRED"
    confirm_with_passkey(c, monkeypatch)
    assert call(c, "DELETE", "/account/orcid").status_code == 200
