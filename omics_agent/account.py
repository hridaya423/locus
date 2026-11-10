"""/account routes: create an account with a passkey, sign in with a passkey or a recovery code, ORCID (when configured),
the local dev sign-in for page checks, who am I, and sign out. Shared machinery (sessions, CSRF guard, rate limits,
errors) is in users.py."""

import json
import logging
import os
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from webauthn import base64url_to_bytes, generate_authentication_options, generate_registration_options, options_to_json, verify_authentication_response, verify_registration_response
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement

from . import mailer, users
from .users import ApiError, Db, User, auth_rate_limit, iso, now

router = APIRouter(prefix="/account", tags=["account"], dependencies=[Depends(users.require_intent)])
CHALLENGE_TTL = timedelta(minutes=5)
ORCID_COOKIE = "locus_orcid"  # ties an ORCID attempt to the browser that started it
log = logging.getLogger(__name__)
RP_NAME = "locus"


def orcid_cookie_name() -> str:
    return "__Host-locus_orcid" if users.cookie_secure() else ORCID_COOKIE


def rp_id() -> str:
    return os.environ.get("LOCUS_RP_ID") or "localhost"


def origin() -> str:
    return (os.environ.get("LOCUS_ORIGIN") or "http://localhost:3000").rstrip("/")


def safe_return(path: str | None) -> str:
    """A same-site path to send the user back to; anything else becomes /account."""
    if path and path.startswith("/") and not path.startswith("//") and "\\" not in path and len(path) <= 500:
        return path
    return "/account"


# ---------------------------------------------------------------- challenges


def _put_challenge(conn, kind: str, challenge: bytes | str, user_id: int | None = None, payload: dict | None = None) -> str:
    conn.execute("DELETE FROM challenges WHERE expires_at <= ?", (iso(now()),))
    cid = secrets.token_urlsafe(24)
    value = challenge if isinstance(challenge, str) else bytes_to_base64url(challenge)
    conn.execute("INSERT INTO challenges (id, kind, challenge, user_id, payload, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (cid, kind, value, user_id, json.dumps(payload or {}), iso(now() + CHALLENGE_TTL)))
    return cid


def _take_challenge(conn, cid: str, kind: str):
    """Removes and returns a challenge: each is good for one attempt, for five minutes."""
    row = conn.execute("DELETE FROM challenges WHERE id = ? AND kind = ? RETURNING challenge, user_id, payload, expires_at", (cid, kind)).fetchone()
    if not row or row["expires_at"] <= iso(now()):
        raise ApiError(400, "CHALLENGE_EXPIRED", "This sign-in attempt has expired. Please start again.")
    return row


# ---------------------------------------------------------------- who am I, sign out


@router.get("/me")
def me(user: User | None = Depends(users.optional_user)) -> dict:
    """The signed-in account, or {"user": null}; also which sign-in methods this server offers."""
    return {"user": user.public() if user else None, "orcid_available": orcid_configured(), "email_available": mailer.configured()}


class Empty(BaseModel):
    pass


@router.post("/sign-out")
def sign_out(request: Request, response: Response, _: Empty | None = None) -> dict:
    users.end_session(response, request.cookies.get(users.cookie_name()))
    return {"ok": True}


def _signed_in(conn, response: Response, request: Request, user_id: int, method: str) -> dict:
    users.start_session(conn, response, user_id, method, request.headers.get("user-agent", ""), request.cookies.get(users.cookie_name()))
    row = conn.execute("SELECT display_name, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    return User(user_id, row["display_name"], row["created_at"], method, iso(now())).public(conn)


# ---------------------------------------------------------------- passkeys

DisplayName = Field(min_length=1, max_length=80)


class RegisterOptionsIn(BaseModel):
    display_name: str = DisplayName


class CredentialIn(BaseModel):
    challenge_id: str = Field(max_length=64)
    credential: dict
    nickname: str = Field(default="", max_length=80)


@router.post("/register/options", dependencies=[Depends(auth_rate_limit)])
def register_options(body: RegisterOptionsIn) -> dict:
    """Starts creating an account: WebAuthn creation options for a new passkey under the chosen display name."""
    name = " ".join(body.display_name.split())
    if not name:
        raise ApiError(422, "INVALID_REQUEST", "Choose a display name.")
    handle = secrets.token_urlsafe(32)
    options = generate_registration_options(
        rp_id=rp_id(), rp_name=RP_NAME, user_name=name, user_id=base64url_to_bytes(handle), user_display_name=name,
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
    )
    with Db() as conn:
        cid = _put_challenge(conn, "register", options.challenge, payload={"display_name": name, "handle": handle})
    return {"challenge_id": cid, "options": json.loads(options_to_json(options))}


@router.post("/register/verify", dependencies=[Depends(auth_rate_limit)])
def register_verify(body: CredentialIn, request: Request, response: Response) -> dict:
    """Finishes creating the account: checks the new passkey, creates the account, signs in, and returns ten recovery
    codes. They are shown this once; only their hashes are kept."""
    with Db() as conn:
        row = _take_challenge(conn, body.challenge_id, "register")
    try:
        verified = verify_registration_response(credential=body.credential, expected_challenge=base64url_to_bytes(row["challenge"]),
                                                expected_rp_id=rp_id(), expected_origin=origin(), require_user_verification=True)
    except (InvalidRegistrationResponse, ValueError, KeyError, TypeError) as error:
        raise _passkey_rejected("registration", error)
    payload = json.loads(row["payload"])
    transports = (body.credential.get("response") or {}).get("transports") or []
    with Db() as conn:
        user_id = users.create_user(conn, payload["display_name"], payload["handle"])
        add_credential(conn, user_id, verified, transports, body.nickname)
        codes = users.new_recovery_codes(conn, user_id)
        user = _signed_in(conn, response, request, user_id, "passkey")
    return {"user": user, "recovery_codes": codes}


def _passkey_rejected(step: str, error: Exception) -> ApiError:
    """The library's reason goes to the server log only; the browser gets one fixed message."""
    log.info("passkey %s rejected: %s: %s", step, type(error).__name__, error)
    return ApiError(400, "PASSKEY_REJECTED", "The passkey could not be verified. Please try again, and unlock it with your PIN, fingerprint or face when asked.")


def add_credential(conn, user_id: int, verified, transports: list, nickname: str = "") -> None:
    """Stores a verified passkey for a user (account creation now; adding another one from settings later)."""
    credential_id = bytes_to_base64url(verified.credential_id)
    if conn.execute("SELECT 1 FROM credentials WHERE credential_id = ?", (credential_id,)).fetchone():
        raise ApiError(409, "PASSKEY_EXISTS", "This passkey is already registered.")
    conn.execute("INSERT INTO credentials (credential_id, user_id, public_key, sign_count, transports, created_at, nickname) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (credential_id, user_id, verified.credential_public_key, verified.sign_count, json.dumps([str(t) for t in transports][:8]), iso(now()), nickname.strip()))
    users.audit(conn, user_id, "passkey added")


@router.post("/login/options", dependencies=[Depends(auth_rate_limit)])
def login_options(_: Empty | None = None) -> dict:
    """Starts a passkey sign-in. No account name is asked for: the browser offers the passkeys it holds for this site."""
    options = generate_authentication_options(rp_id=rp_id(), user_verification=UserVerificationRequirement.REQUIRED,
                                              allow_credentials=[])
    with Db() as conn:
        cid = _put_challenge(conn, "login", options.challenge)
    return {"challenge_id": cid, "options": json.loads(options_to_json(options))}


@router.post("/login/verify", dependencies=[Depends(auth_rate_limit)])
def login_verify(body: CredentialIn, request: Request, response: Response) -> dict:
    """Finishes a passkey sign-in: checks the signature against the stored public key and signs in."""
    with Db() as conn:
        row = _take_challenge(conn, body.challenge_id, "login")
        credential_id = str(body.credential.get("id") or body.credential.get("rawId") or "")
        stored = conn.execute("SELECT user_id, public_key, sign_count FROM credentials WHERE credential_id = ?", (credential_id,)).fetchone()
    if not stored:
        raise ApiError(400, "PASSKEY_UNKNOWN", "locus does not know this passkey. It may belong to an account that was deleted.")
    try:
        verified = verify_authentication_response(credential=body.credential, expected_challenge=base64url_to_bytes(row["challenge"]), expected_rp_id=rp_id(),
                                                  expected_origin=origin(), credential_public_key=stored["public_key"], credential_current_sign_count=stored["sign_count"],
                                                  require_user_verification=True)
    except (InvalidAuthenticationResponse, ValueError, KeyError, TypeError) as error:
        raise _passkey_rejected("sign-in", error)
    with Db() as conn:
        conn.execute("UPDATE credentials SET sign_count = ?, last_used_at = ? WHERE credential_id = ?", (verified.new_sign_count, iso(now()), credential_id))
        return {"user": _signed_in(conn, response, request, stored["user_id"], "passkey")}


# ---------------------------------------------------------------- recovery codes


class RecoveryIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)


@router.post("/recovery", dependencies=[Depends(auth_rate_limit)])
def recovery_sign_in(body: RecoveryIn, request: Request, response: Response) -> dict:
    """Signs in with one of the account's recovery codes; each code works once."""
    with Db() as conn:
        user_id = users.use_recovery_code(conn, body.code)
        if user_id is None:
            raise ApiError(400, "RECOVERY_CODE_INVALID", "This recovery code is not valid or has been used.")
        users.audit(conn, user_id, "recovery code used")
        return {"user": _signed_in(conn, response, request, user_id, "recovery")}


# ---------------------------------------------------------------- dev sign-in (page checks only)


class DevLoginIn(BaseModel):
    display_name: str = DisplayName


@router.post("/dev-login", dependencies=[Depends(auth_rate_limit)])
def dev_login(body: DevLoginIn, request: Request, response: Response) -> dict:
    """Creates an account and signs in without a passkey, for automated page checks. Exists only when LOCUS_DEV_LOGIN=1
    and the request comes from this machine; otherwise it is a 404 like any unknown path."""
    if os.environ.get("LOCUS_DEV_LOGIN") != "1" or not users.is_local(request):
        raise ApiError(404, "NOT_FOUND", "Not Found")
    secret = os.environ.get("LOCUS_DEV_LOGIN_SECRET", "")
    if secret and not secrets.compare_digest(request.headers.get("X-Locus-Dev-Secret", "").encode(), secret.encode()):
        raise ApiError(404, "NOT_FOUND", "Not Found")
    with Db() as conn:
        user_id = users.create_user(conn, " ".join(body.display_name.split()) or "Dev")
        return {"user": _signed_in(conn, response, request, user_id, "dev")}


# ---------------------------------------------------------------- ORCID


ORCID_ID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def orcid_configured() -> bool:
    return bool(os.environ.get("ORCID_CLIENT_ID") and os.environ.get("ORCID_CLIENT_SECRET"))


def orcid_base() -> str:
    """https://orcid.org, or https://sandbox.orcid.org while testing a client (ORCID_BASE)."""
    return (os.environ.get("ORCID_BASE") or "https://orcid.org").rstrip("/")


def orcid_redirect_uri() -> str:
    return f"{origin()}/api/account/orcid/callback"


def orcid_client() -> httpx.Client:
    return httpx.Client(timeout=15)


def _need_orcid() -> None:
    if not orcid_configured():
        raise ApiError(404, "ORCID_NOT_CONFIGURED", "ORCID sign-in is not configured on this server.")


@router.get("/orcid/start", dependencies=[Depends(auth_rate_limit)])
def orcid_start(to: str = "/account", user: User | None = Depends(users.optional_user)) -> RedirectResponse:
    """Sends the browser to ORCID to sign in, or to link an ORCID iD to the signed-in account. The attempt is tied to
    this browser by a five-minute HttpOnly cookie holding a random nonce; only its hash is stored with the state, and
    the callback refuses a browser without it (RFC 6749 s10.12)."""
    _need_orcid()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    with Db() as conn:
        _put_challenge(conn, "orcid", state, user.id if user else None, {"to": safe_return(to), "nonce_sha256": users.sha256(nonce)})
    query = urlencode({"client_id": os.environ["ORCID_CLIENT_ID"], "response_type": "code", "scope": "/authenticate",
                       "redirect_uri": orcid_redirect_uri(), "state": state})
    response = RedirectResponse(f"{orcid_base()}/oauth/authorize?{query}", status_code=302)
    response.set_cookie(orcid_cookie_name(), nonce, max_age=int(CHALLENGE_TTL.total_seconds()), path="/", httponly=True, samesite="lax", secure=users.cookie_secure())
    return response


def _orcid_back(to: str, outcome: str) -> RedirectResponse:
    sep = "&" if "?" in to else "?"
    response = RedirectResponse(f"{to}{sep}orcid={outcome}", status_code=302)
    response.delete_cookie(orcid_cookie_name(), path="/", httponly=True, samesite="lax", secure=users.cookie_secure())
    return response


@router.get("/orcid/callback", dependencies=[Depends(auth_rate_limit)])
def orcid_callback(request: Request, state: str = "", code: str = "", error: str = "") -> RedirectResponse:
    """ORCID sends the browser back here. Links the iD when the attempt began signed in (and the same account is still
    signed in); otherwise signs in the account the iD is linked to, or creates one. Only the browser that started the
    attempt can finish it. Always ends in a redirect to where the user started, with ?orcid=<outcome> (linked,
    signed-in, in-use, cancelled, expired, failed)."""
    _need_orcid()
    nonce = request.cookies.get(orcid_cookie_name(), "")
    with Db() as conn:
        found = conn.execute("SELECT id, payload FROM challenges WHERE kind = 'orcid' AND challenge = ?", (state,)).fetchone() if state else None
        if found and not (nonce and secrets.compare_digest(json.loads(found["payload"]).get("nonce_sha256", ""), users.sha256(nonce))):
            # Another browser's attempt (a forwarded authorize or callback link): refuse it and leave it untouched.
            log.info("orcid callback refused: the browser did not start this attempt")
            return _orcid_back("/account", "failed")
        try:
            row = _take_challenge(conn, found["id"] if found else "", "orcid")
        except ApiError:
            return _orcid_back("/account", "expired")
    to = json.loads(row["payload"]).get("to", "/account")
    if error or not code:
        return _orcid_back(to, "cancelled")
    if row["user_id"] is not None:
        signed_in = users.optional_user(request, Response())
        if signed_in is None or signed_in.id != row["user_id"]:
            return _orcid_back(to, "failed")
        with Db() as conn:
            has_passkey = conn.execute("SELECT 1 FROM credentials WHERE user_id = ?", (signed_in.id,)).fetchone()
        if has_passkey and signed_in.strong_until() is None:
            # Linking adds a way into the account, so it needs the same fresh confirmation as adding a passkey (F7-r1-1).
            return _orcid_back(to, "confirm-first")
    try:
        with orcid_client() as client:
            answer = client.post(f"{orcid_base()}/oauth/token", headers={"Accept": "application/json"}, data={
                "client_id": os.environ["ORCID_CLIENT_ID"], "client_secret": os.environ["ORCID_CLIENT_SECRET"],
                "grant_type": "authorization_code", "code": code, "redirect_uri": orcid_redirect_uri()})
        answer.raise_for_status()
        token = answer.json()
    except (httpx.HTTPError, ValueError) as failure:
        log.info("orcid token exchange failed: %s", failure)
        return _orcid_back(to, "failed")
    orcid = str(token.get("orcid") or "") if isinstance(token, dict) else ""
    if not ORCID_ID.match(orcid):
        return _orcid_back(to, "failed")
    response = _orcid_back(to, "linked")
    with Db() as conn:
        linked = conn.execute("SELECT user_id FROM orcid_links WHERE orcid = ?", (orcid,)).fetchone()
        if row["user_id"] is not None:
            if linked and linked["user_id"] != row["user_id"]:
                return _orcid_back(to, "in-use")
            if linked and not has_passkey:
                # The account's own iD again, on an account with no passkey: a fresh ORCID sign-in, which lets it add
                # its first passkey within five minutes (settings.py).
                response = _orcid_back(to, "signed-in")
                users.start_session(conn, response, row["user_id"], "orcid", request.headers.get("user-agent", ""), request.cookies.get(users.cookie_name()))
                return response
            if not linked and not has_passkey and conn.execute("SELECT 1 FROM orcid_links WHERE user_id = ?", (row["user_id"],)).fetchone():
                # An account whose only way in is its ORCID iD never swaps it for another one: that would hand it over.
                return _orcid_back(to, "already-linked")
            if not linked:
                conn.execute("DELETE FROM orcid_links WHERE user_id = ?", (row["user_id"],))
                conn.execute("INSERT INTO orcid_links (user_id, orcid, linked_at) VALUES (?, ?, ?)", (row["user_id"], orcid, iso(now())))
                users.audit(conn, row["user_id"], "orcid linked")
            return response
        if linked:
            user_id = linked["user_id"]
        else:
            user_id = users.create_user(conn, " ".join(str(token.get("name") or "").split())[:80] or f"ORCID {orcid}")
            conn.execute("INSERT INTO orcid_links (user_id, orcid, linked_at) VALUES (?, ?, ?)", (user_id, orcid, iso(now())))
            users.audit(conn, user_id, "orcid linked")
        response = _orcid_back(to, "signed-in")
        users.start_session(conn, response, user_id, "orcid", request.headers.get("user-agent", ""), request.cookies.get(users.cookie_name()))
    return response
