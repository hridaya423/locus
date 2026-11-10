"""Accounts core (F1): sessions, CSRF guard, dev sign-in guard, recovery codes, rate limits, passkeys with a mocked
verifier, ORCID with a mocked token endpoint, and the shared error shape. No network: every outside call is faked."""

import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import cbor2
import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from webauthn.helpers.exceptions import InvalidAuthenticationResponse

from omics_agent import account, users

INTENT = {"X-Locus-Intent": "1"}
LOCAL = ("127.0.0.1", 50000)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OMICS_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("LOCUS_DEV_LOGIN", "1")
    monkeypatch.setenv("LOCUS_ORIGIN", "http://localhost:3051")
    monkeypatch.setenv("LOCUS_RP_ID", "localhost")
    for name in ("LOCUS_COOKIE_INSECURE", "ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET", "ORCID_BASE"):
        monkeypatch.delenv(name, raising=False)
    users.AUTH_LIMIT.reset()
    yield tmp_path / "users.db"
    users.AUTH_LIMIT.reset()


def make_app() -> FastAPI:
    app = FastAPI()
    users.install(app)

    class Thing(BaseModel):
        n: int

    @app.post("/elsewhere")
    def elsewhere(body: Thing) -> dict:
        return {"n": body.n}

    return app


def client(peer=LOCAL, **kw) -> TestClient:
    return TestClient(make_app(), base_url="https://testserver", client=peer, follow_redirects=False, **kw)


def dev_login(c: TestClient, name="Gate", **headers):
    return c.post("/account/dev-login", json={"display_name": name}, headers=INTENT | headers)


def rows(db, sql, *args):
    assert str(db) == str(users.db_path())
    conn = users.connect()
    try:
        return [tuple(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


# ---------------------------------------------------------------- sessions


def test_session_lifecycle_sign_in_me_sign_out(env):
    c = client()
    assert c.get("/account/me").json()["user"] is None
    r = dev_login(c, "  Ada   Lovelace ")
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Ada Lovelace"
    cookie = r.headers["set-cookie"]
    assert "locus_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie and "Secure" in cookie
    assert "Domain" not in cookie
    token = c.cookies.get(users.cookie_name())
    assert len(token) >= 43
    # The DB keeps only the token's hash.
    stored = rows(env, "SELECT token_sha256, method FROM sessions")
    assert stored == [(users.sha256(token), "dev")]
    me = c.get("/account/me").json()["user"]
    assert me["display_name"] == "Ada Lovelace" and me["orcid"] is None
    assert c.post("/account/sign-out", json={}, headers=INTENT).json() == {"ok": True}
    assert c.get("/account/me").json()["user"] is None
    assert rows(env, "SELECT count(*) FROM sessions") == [(0,)]
    # A stolen copy of the old token no longer works either.
    other = client()
    other.cookies.set(users.cookie_name(), token)
    assert other.get("/account/me").json()["user"] is None


def test_signing_in_again_ends_the_old_session(env):
    c = client()
    dev_login(c, "First")
    old = c.cookies.get(users.cookie_name())
    dev_login(c, "Second")
    assert c.cookies.get(users.cookie_name()) != old
    assert c.get("/account/me").json()["user"]["display_name"] == "Second"
    assert rows(env, "SELECT count(*) FROM sessions") == [(1,)]
    stale = client()
    stale.cookies.set(users.cookie_name(), old)
    assert stale.get("/account/me").json()["user"] is None


def test_insecure_cookie_only_when_asked(env, monkeypatch):
    monkeypatch.setenv("LOCUS_COOKIE_INSECURE", "1")
    assert "Secure" not in dev_login(client()).headers["set-cookie"]


def test_session_expires_after_30_idle_days_and_slides_when_used(env, monkeypatch):
    c = client()
    dev_login(c)
    start = users.now()
    monkeypatch.setattr(users, "now", lambda: start + timedelta(days=20))
    assert c.get("/account/me").json()["user"] is not None  # use on day 20 pushes expiry to day 50
    monkeypatch.setattr(users, "now", lambda: start + timedelta(days=45))
    assert c.get("/account/me").json()["user"] is not None
    monkeypatch.setattr(users, "now", lambda: start + timedelta(days=76))
    assert c.get("/account/me").json()["user"] is None
    assert rows(env, "SELECT count(*) FROM sessions") == [(0,)]


def test_current_user_dependency_requires_a_session(env):
    app = make_app()

    @app.get("/account/private")
    def private(user: users.User = users.Depends(users.current_user)) -> dict:
        return {"id": user.id}

    c = TestClient(app, base_url="https://testserver", client=LOCAL)
    r = c.get("/account/private")
    assert r.status_code == 401 and r.json() == {"error": {"code": "SIGN_IN_REQUIRED", "message": "Sign in to do this.", "transient": False}}
    uid = dev_login(c).json()["user"]["id"]
    assert c.get("/account/private").json() == {"id": uid}


# ---------------------------------------------------------------- CSRF guard


@pytest.mark.parametrize("headers, kwargs", [
    ({}, {"json": {"display_name": "x"}}),                                           # no intent header
    ({"X-Locus-Intent": "0"}, {"json": {"display_name": "x"}}),                      # wrong value
    (INTENT, {"data": {"display_name": "x"}}),                                       # form body
    (INTENT | {"Content-Type": "text/plain"}, {"content": '{"display_name": "x"}'}),  # simple-request content type
])
def test_state_changing_requests_need_intent_header_and_json(env, headers, kwargs):
    c = client()
    r = c.post("/account/dev-login", headers=headers, **kwargs)
    assert r.status_code == 403 and r.json()["error"]["code"] == "INTENT_REQUIRED"
    assert rows(env, "SELECT count(*) FROM users") == [(0,)]


def test_sign_out_without_intent_keeps_the_session(env):
    c = client()
    dev_login(c)
    assert c.post("/account/sign-out", json={}).status_code == 403
    assert c.get("/account/me").json()["user"] is not None


# ---------------------------------------------------------------- dev sign-in guard


def test_dev_login_refused_when_unset(env, monkeypatch):
    monkeypatch.delenv("LOCUS_DEV_LOGIN")
    r = dev_login(client())
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    monkeypatch.setenv("LOCUS_DEV_LOGIN", "true")
    assert dev_login(client()).status_code == 404


def test_dev_login_refused_off_localhost(env):
    assert dev_login(client(peer=("203.0.113.9", 1))).status_code == 404
    # Through a local proxy (the web app's /api rewrite) for a remote browser.
    assert dev_login(client(), **{"X-Forwarded-For": "203.0.113.9"}).status_code == 404
    assert dev_login(client(), **{"X-Forwarded-For": "127.0.0.1, 198.51.100.4"}).status_code == 404
    assert dev_login(client(), **{"X-Forwarded-For": "::1"}).status_code == 200
    assert dev_login(client(peer=("::1", 1))).status_code == 200


# ---------------------------------------------------------------- passkeys (mocked verifier)


def fake_registration(calls, credential_id=b"cred-1"):
    def verify(**kw):
        calls.append(kw)
        return SimpleNamespace(credential_id=credential_id, credential_public_key=b"public-key", sign_count=0)
    return verify


def register(c, monkeypatch, calls, name="Grace", credential_id=b"cred-1"):
    monkeypatch.setattr(account, "verify_registration_response", fake_registration(calls, credential_id))
    opts = c.post("/account/register/options", json={"display_name": name}, headers=INTENT).json()
    cred = {"id": "x", "rawId": "x", "type": "public-key", "response": {"transports": ["internal", "hybrid"]}}
    return opts, c.post("/account/register/verify", json={"challenge_id": opts["challenge_id"], "credential": cred}, headers=INTENT)


def test_register_creates_account_with_passkey_and_ten_recovery_codes(env, monkeypatch):
    c, calls = client(), []
    opts, r = register(c, monkeypatch, calls)
    o = opts["options"]
    assert o["rp"]["id"] == "localhost" and o["user"]["name"] == "Grace" and o["authenticatorSelection"]["residentKey"] == "required"
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["display_name"] == "Grace" and body["user"]["passkeys"] == 1 and body["user"]["recovery_codes_left"] == 10
    assert len(body["recovery_codes"]) == 10 and len(set(body["recovery_codes"])) == 10
    # The verifier was asked about this server's origin and RP id, with the challenge that was issued.
    assert calls[0]["expected_origin"] == "http://localhost:3051" and calls[0]["expected_rp_id"] == "localhost"
    assert account.bytes_to_base64url(calls[0]["expected_challenge"]) == o["challenge"]
    assert rows(env, "SELECT credential_id, sign_count, transports FROM credentials") == [(account.bytes_to_base64url(b"cred-1"), 0, '["internal", "hybrid"]')]
    assert c.get("/account/me").json()["user"]["display_name"] == "Grace"
    # Codes are kept only as hashes.
    stored = {h for (h,) in rows(env, "SELECT code_sha256 FROM recovery_codes")}
    assert all(code not in stored and code.replace("-", "") not in stored for code in body["recovery_codes"])


def test_challenge_is_single_use_and_expires(env, monkeypatch):
    c, calls = client(), []
    opts, first = register(c, monkeypatch, calls)
    assert first.status_code == 200
    again = c.post("/account/register/verify", json={"challenge_id": opts["challenge_id"], "credential": {}}, headers=INTENT)
    assert again.status_code == 400 and again.json()["error"]["code"] == "CHALLENGE_EXPIRED"
    late = c.post("/account/login/options", json={}, headers=INTENT).json()
    start = users.now()
    monkeypatch.setattr(account, "now", lambda: start + timedelta(minutes=6))
    r = c.post("/account/login/verify", json={"challenge_id": late["challenge_id"], "credential": {"id": "x"}}, headers=INTENT)
    assert r.json()["error"]["code"] == "CHALLENGE_EXPIRED"


def test_passkey_sign_in_checks_the_stored_key_and_updates_the_counter(env, monkeypatch):
    c, calls = client(), []
    register(c, monkeypatch, calls)
    c.post("/account/sign-out", json={}, headers=INTENT)
    seen = []

    def verify(**kw):
        seen.append(kw)
        return SimpleNamespace(new_sign_count=7)

    monkeypatch.setattr(account, "verify_authentication_response", verify)
    opts = c.post("/account/login/options", json={}, headers=INTENT).json()
    assert opts["options"]["rpId"] == "localhost" and opts["options"]["allowCredentials"] == []
    cred_id = account.bytes_to_base64url(b"cred-1")
    r = c.post("/account/login/verify", json={"challenge_id": opts["challenge_id"], "credential": {"id": cred_id}}, headers=INTENT)
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Grace"
    assert seen[0]["credential_public_key"] == b"public-key" and seen[0]["credential_current_sign_count"] == 0
    assert rows(env, "SELECT sign_count, last_used_at IS NOT NULL FROM credentials") == [(7, 1)]
    assert rows(env, "SELECT method FROM sessions") == [("passkey",)]


def test_passkey_sign_in_rejections(env, monkeypatch):
    c, calls = client(), []
    register(c, monkeypatch, calls)
    c.post("/account/sign-out", json={}, headers=INTENT)
    opts = c.post("/account/login/options", json={}, headers=INTENT).json()
    r = c.post("/account/login/verify", json={"challenge_id": opts["challenge_id"], "credential": {"id": "unknown"}}, headers=INTENT)
    assert r.status_code == 400 and r.json()["error"]["code"] == "PASSKEY_UNKNOWN"

    def bad(**kw):
        raise InvalidAuthenticationResponse("signature did not match")

    monkeypatch.setattr(account, "verify_authentication_response", bad)
    opts = c.post("/account/login/options", json={}, headers=INTENT).json()
    r = c.post("/account/login/verify", json={"challenge_id": opts["challenge_id"], "credential": {"id": account.bytes_to_base64url(b"cred-1")}}, headers=INTENT)
    assert r.status_code == 400 and r.json()["error"]["code"] == "PASSKEY_REJECTED"
    assert c.get("/account/me").json()["user"] is None


def test_real_verifier_rejects_a_forged_registration(env):
    c = client()
    opts = c.post("/account/register/options", json={"display_name": "Mallory"}, headers=INTENT).json()
    forged = {"id": "AAAA", "rawId": "AAAA", "type": "public-key", "response": {"clientDataJSON": "e30", "attestationObject": "oA"}}
    r = c.post("/account/register/verify", json={"challenge_id": opts["challenge_id"], "credential": forged}, headers=INTENT)
    assert r.status_code == 400 and r.json()["error"]["code"] == "PASSKEY_REJECTED"
    assert rows(env, "SELECT count(*) FROM users") == [(0,)]


# ---------------------------------------------------------------- recovery codes


class SoftAuthenticator:
    """A software passkey (ES256, attestation "none") that answers real WebAuthn ceremonies, with or without the user
    verification flag, so the real verifier in py_webauthn runs end to end."""

    ORIGIN, RP = "http://localhost:3051", "localhost"

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = b"soft-authenticator-1"
        self.count = 0

    @staticmethod
    def b64(data: bytes) -> str:
        return account.bytes_to_base64url(data)

    def _auth_data(self, uv: bool, attested: bytes = b"") -> bytes:
        self.count += 1
        flags = 0x01 | (0x04 if uv else 0) | (0x40 if attested else 0)
        return hashlib.sha256(self.RP.encode()).digest() + bytes([flags]) + self.count.to_bytes(4, "big") + attested

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.ORIGIN, "crossOrigin": False}).encode()

    def register(self, options: dict, uv: bool) -> dict:
        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})
        attested = bytes(16) + len(self.cred_id).to_bytes(2, "big") + self.cred_id + cose
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": self._auth_data(uv, attested)})
        return {"id": self.b64(self.cred_id), "rawId": self.b64(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": self.b64(self._client_data("webauthn.create", options["challenge"])),
                             "attestationObject": self.b64(attestation), "transports": ["internal"]}}

    def sign_in(self, options: dict, uv: bool) -> dict:
        data, client_data = self._auth_data(uv), self._client_data("webauthn.get", options["challenge"])
        signature = self.key.sign(data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": self.b64(self.cred_id), "rawId": self.b64(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": self.b64(client_data), "authenticatorData": self.b64(data), "signature": self.b64(signature)}}


def test_passkeys_require_user_verification(env):
    c, device = client(), SoftAuthenticator()
    # Registration: the options ask for verification, and a response without it creates nothing.
    opts = c.post("/account/register/options", json={"display_name": "Grace"}, headers=INTENT).json()
    assert opts["options"]["authenticatorSelection"]["userVerification"] == "required"
    r = c.post("/account/register/verify", json={"challenge_id": opts["challenge_id"], "credential": device.register(opts["options"], uv=False)}, headers=INTENT)
    assert r.status_code == 400 and r.json()["error"]["code"] == "PASSKEY_REJECTED"
    no_uv_message = r.json()["error"]["message"]
    assert rows(env, "SELECT count(*) FROM users") == [(0,)] and c.get("/account/me").json()["user"] is None
    opts = c.post("/account/register/options", json={"display_name": "Grace"}, headers=INTENT).json()
    r = c.post("/account/register/verify", json={"challenge_id": opts["challenge_id"], "credential": device.register(opts["options"], uv=True)}, headers=INTENT)
    assert r.status_code == 200 and r.json()["user"]["passkeys"] == 1
    c.post("/account/sign-out", json={}, headers=INTENT)
    # Sign-in: the same passkey without verification is refused; with it, it signs in.
    opts = c.post("/account/login/options", json={}, headers=INTENT).json()
    assert opts["options"]["userVerification"] == "required"
    r = c.post("/account/login/verify", json={"challenge_id": opts["challenge_id"], "credential": device.sign_in(opts["options"], uv=False)}, headers=INTENT)
    assert r.status_code == 400 and r.json()["error"]["code"] == "PASSKEY_REJECTED"
    assert c.get("/account/me").json()["user"] is None
    opts = c.post("/account/login/options", json={}, headers=INTENT).json()
    r = c.post("/account/login/verify", json={"challenge_id": opts["challenge_id"], "credential": device.sign_in(opts["options"], uv=True)}, headers=INTENT)
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Grace"
    # The browser learns only that the passkey was refused, never which check failed.
    forged = {"id": "AAAA", "rawId": "AAAA", "type": "public-key", "response": {"clientDataJSON": "e30", "attestationObject": "oA"}}
    opts = c.post("/account/register/options", json={"display_name": "Mallory"}, headers=INTENT).json()
    other = c.post("/account/register/verify", json={"challenge_id": opts["challenge_id"], "credential": forged}, headers=INTENT)
    assert other.json()["error"]["message"] == no_uv_message


def test_recovery_code_signs_in_once(env, monkeypatch):
    c, calls = client(), []
    codes = register(c, monkeypatch, calls)[1].json()["recovery_codes"]
    c.post("/account/sign-out", json={}, headers=INTENT)
    r = c.post("/account/recovery", json={"code": codes[3].lower().replace("-", " ")}, headers=INTENT)
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Grace" and r.json()["user"]["recovery_codes_left"] == 9
    c.post("/account/sign-out", json={}, headers=INTENT)
    again = c.post("/account/recovery", json={"code": codes[3]}, headers=INTENT)
    assert again.status_code == 400 and again.json()["error"]["code"] == "RECOVERY_CODE_INVALID"
    assert c.get("/account/me").json()["user"] is None
    assert c.post("/account/recovery", json={"code": "AAAA-BBBB-CCCC"}, headers=INTENT).status_code == 400


# ---------------------------------------------------------------- rate limits


def test_auth_routes_allow_ten_a_minute_per_address(env):
    c = client()
    assert all(dev_login(c).status_code == 200 for _ in range(10))
    r = dev_login(c)
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED" and r.json()["error"]["transient"] is True
    assert int(r.headers["Retry-After"]) > 0
    assert c.post("/account/recovery", json={"code": "AAAA"}, headers=INTENT).status_code == 429
    # Another address still gets through, and reading /me is never limited.
    assert c.post("/account/login/options", json={}, headers=INTENT | {"X-Forwarded-For": "::1, 127.0.0.2"}).status_code == 200
    assert c.get("/account/me").status_code == 200


def test_auth_routes_allow_a_hundred_a_minute_overall():
    limiter = users.RateLimiter(per_ip=10, overall=100)
    for i in range(100):
        limiter.check(f"10.0.0.{i}")
    with pytest.raises(users.ApiError) as caught:
        limiter.check("10.0.1.1")
    assert caught.value.status == 429


def test_rate_limiter_forgets_an_address_after_a_minute(monkeypatch):
    # /privacy says the limiter holds addresses in memory for one minute; an idle caller must be gone after that.
    clock = [1000.0]
    monkeypatch.setattr(users.time, "monotonic", lambda: clock[0])
    limiter = users.RateLimiter(per_ip=10, overall=100)
    limiter.check("203.0.113.7")
    assert any("203.0.113.7" in k for k in limiter.hits)
    clock[0] += 61
    limiter.check("198.51.100.1")
    assert not any("203.0.113.7" in k for k in limiter.hits)


# ---------------------------------------------------------------- ORCID


def test_orcid_is_404_when_not_configured(env):
    c = client()
    assert c.get("/account/me").json()["orcid_available"] is False
    for path in ("/account/orcid/start", "/account/orcid/callback?state=x&code=y"):
        r = c.get(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "ORCID_NOT_CONFIGURED"


@pytest.fixture
def orcid(env, monkeypatch):
    monkeypatch.setenv("ORCID_CLIENT_ID", "APP-TEST")
    monkeypatch.setenv("ORCID_CLIENT_SECRET", "shh")
    answers = {"orcid": "0000-0002-1825-0097", "name": "Josiah Carberry"}
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url == "https://orcid.org/oauth/token"
        return httpx.Response(200, json={"access_token": "t", "token_type": "bearer", **answers})

    monkeypatch.setattr(account, "orcid_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return SimpleNamespace(answers=answers, requests=requests)


def orcid_round_trip(c, to="/d/GSE1"):
    start = c.get("/account/orcid/start", params={"to": to})
    assert start.status_code == 302
    url = urlparse(start.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "orcid.org" and q["client_id"] == ["APP-TEST"] and q["scope"] == ["/authenticate"]
    assert q["redirect_uri"] == ["http://localhost:3051/api/account/orcid/callback"]
    return c.get("/account/orcid/callback", params={"state": q["state"][0], "code": "abc"})


def test_orcid_sign_in_creates_an_account_and_links_the_id(env, orcid):
    c = client()
    assert c.get("/account/me").json()["orcid_available"] is True
    back = orcid_round_trip(c)
    assert back.status_code == 302 and back.headers["location"] == "/d/GSE1?orcid=signed-in"
    me = c.get("/account/me").json()["user"]
    assert me["orcid"] == "0000-0002-1825-0097" and me["display_name"] == "Josiah Carberry"
    form = parse_qs(orcid.requests[0].content.decode())
    assert form["code"] == ["abc"] and form["grant_type"] == ["authorization_code"] and form["client_secret"] == ["shh"]
    # Signing in again with the same iD reaches the same account.
    c.post("/account/sign-out", json={}, headers=INTENT)
    orcid_round_trip(c)
    assert c.get("/account/me").json()["user"]["id"] == me["id"]
    assert rows(env, "SELECT count(*) FROM users") == [(1,)]


def test_orcid_links_to_the_signed_in_account_and_refuses_a_taken_id(env, orcid):
    first = client()
    orcid_round_trip(first)  # the iD now belongs to an ORCID-created account
    c = client()
    uid = dev_login(c, "Ada").json()["user"]["id"]
    assert orcid_round_trip(c).headers["location"] == "/d/GSE1?orcid=in-use"
    orcid.answers["orcid"] = "0000-0001-5109-3700"
    assert orcid_round_trip(c, "/account").headers["location"] == "/account?orcid=linked"
    me = c.get("/account/me").json()["user"]
    assert me["id"] == uid and me["orcid"] == "0000-0001-5109-3700" and me["display_name"] == "Ada"


def test_orcid_callback_with_a_bad_state_or_failed_exchange(env, orcid, monkeypatch):
    c = client()
    assert c.get("/account/orcid/callback", params={"state": "forged", "code": "x"}).headers["location"] == "/account?orcid=expired"
    start = c.get("/account/orcid/start", params={"to": "//evil.example/x"})
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    monkeypatch.setattr(account, "orcid_client", lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert c.get("/account/orcid/callback", params={"state": state, "code": "x"}).headers["location"] == "/account?orcid=failed"
    assert c.get("/account/me").json()["user"] is None


def orcid_authorize(c, to="/account"):
    """Starts an ORCID attempt in browser `c`; returns the state ORCID would send back."""
    start = c.get("/account/orcid/start", params={"to": to})
    assert start.status_code == 302 and "locus_orcid=" in start.headers["set-cookie"] and "HttpOnly" in start.headers["set-cookie"]
    return parse_qs(urlparse(start.headers["location"]).query)["state"][0]


def test_orcid_attempt_only_finishes_in_the_browser_that_started_it(env, orcid):
    # Login CSRF: the attacker starts as a guest and sends the callback link (their state and code) to the victim.
    attacker, victim = client(), client()
    state = orcid_authorize(attacker)
    back = victim.get("/account/orcid/callback", params={"state": state, "code": "attacker-code"})
    assert back.headers["location"] == "/account?orcid=failed"
    assert victim.get("/account/me").json()["user"] is None
    # A victim holding a cookie from their own attempt is refused too: the cookie must belong to this state.
    orcid_authorize(victim)
    assert victim.get("/account/orcid/callback", params={"state": state, "code": "attacker-code"}).headers["location"] == "/account?orcid=failed"
    assert victim.get("/account/me").json()["user"] is None
    assert orcid.requests == [] and rows(env, "SELECT count(*) FROM orcid_links") == [(0,)]
    # Identity hijack: a signed-in attacker's link attempt, finished by a signed-in victim, links nothing.
    uid = dev_login(attacker, "Attacker").json()["user"]["id"]
    dev_login(victim, "Victim")
    state = orcid_authorize(attacker)
    assert victim.get("/account/orcid/callback", params={"state": state, "code": "victim-code"}).headers["location"] == "/account?orcid=failed"
    assert orcid.requests == [] and rows(env, "SELECT count(*) FROM orcid_links") == [(0,)]
    # The attacker's own browser can still finish its own attempt, and the cookie is cleared afterwards.
    assert attacker.get("/account/orcid/callback", params={"state": state, "code": "abc"}).headers["location"] == "/account?orcid=linked"
    assert rows(env, "SELECT user_id FROM orcid_links") == [(uid,)]
    assert attacker.cookies.get(account.orcid_cookie_name()) is None


def test_orcid_link_must_be_finished_by_the_account_that_started_it(env, orcid):
    c = client()
    dev_login(c, "Ada")
    state = orcid_authorize(c)
    c.post("/account/sign-out", json={}, headers=INTENT)
    other = dev_login(c, "Bob").json()["user"]["id"]
    assert c.get("/account/orcid/callback", params={"state": state, "code": "abc"}).headers["location"] == "/account?orcid=failed"
    assert rows(env, "SELECT count(*) FROM orcid_links") == [(0,)] and orcid.requests == []
    assert c.get("/account/me").json()["user"]["id"] == other
    # Signed out entirely, the link attempt cannot become a sign-in either.
    state = orcid_authorize(c)
    c.post("/account/sign-out", json={}, headers=INTENT)
    assert c.get("/account/orcid/callback", params={"state": state, "code": "abc"}).headers["location"] == "/account?orcid=failed"
    assert c.get("/account/me").json()["user"] is None and rows(env, "SELECT count(*) FROM orcid_links") == [(0,)]


# ---------------------------------------------------------------- shared error shape, migrations


def test_validation_errors_use_the_shared_shape_only_on_account_routes(env):
    c = client()
    r = c.post("/account/dev-login", json={"display_name": ""}, headers=INTENT)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST" and "display_name" in r.json()["error"]["message"]
    other = c.post("/elsewhere", json={"n": "not a number"})
    assert other.status_code == 422 and "detail" in other.json()


def test_migrations_are_numbered_and_applied_once(env):
    conn = users.connect()
    try:
        assert users.migrate(conn) == []
        files = sorted(int(p.name[:3]) for p in users.MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
        assert files[0] == 1 and files == list(range(1, len(files) + 1))
        assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == files
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"users", "credentials", "sessions", "recovery_codes", "orcid_links", "audit", "challenges"} <= tables
    finally:
        conn.close()


def test_linking_orcid_is_a_way_in_so_it_needs_a_fresh_confirmation(env, orcid, monkeypatch):
    # A passkey account whose confirmation has expired cannot link an iD with only its session cookie (F7-r1-1).
    c = client()
    register(c, monkeypatch, [])
    start = users.now()
    monkeypatch.setattr(users, "now", lambda: start + timedelta(minutes=6))
    assert orcid_round_trip(c, "/settings").headers["location"] == "/settings?orcid=confirm-first"
    assert c.get("/account/me").json()["user"]["orcid"] is None
    monkeypatch.setattr(users, "now", lambda: start)
    assert orcid_round_trip(c, "/settings").headers["location"] == "/settings?orcid=linked"
    # An account made by ORCID never swaps its iD, its only way in, for another one.
    users.AUTH_LIMIT.reset()
    made = client()
    orcid.answers["orcid"] = "0000-0001-5109-3700"
    orcid_round_trip(made)
    orcid.answers["orcid"] = "0000-0003-1164-7224"
    assert orcid_round_trip(made, "/settings").headers["location"] == "/settings?orcid=already-linked"
    assert made.get("/account/me").json()["user"]["orcid"] == "0000-0001-5109-3700"
    # Its own iD again while signed in is a fresh ORCID sign-in, which may add the account's first passkey.
    orcid.answers["orcid"] = "0000-0001-5109-3700"
    assert orcid_round_trip(made, "/settings").headers["location"] == "/settings?orcid=signed-in"
    assert rows(env, "SELECT method FROM sessions WHERE user_id = (SELECT user_id FROM orcid_links WHERE orcid = ?)", "0000-0001-5109-3700") == [("orcid",)]
