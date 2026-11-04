"""/account settings routes (F7): what /settings shows and changes.

- Display name; passkeys (list, rename, add another with a registration ceremony, remove but never the last one);
  recovery codes (how many are left, regenerate); ORCID (unlink).
- Confirming it is you: a passkey or recovery-code check that marks the current session (sessions.strong_at). Deleting
  the account, regenerating recovery codes, adding a passkey, removing a passkey and unlinking ORCID need one within the
  last five minutes. A dev sign-in or ORCID sign-in never counts, and nothing outside these routes and a real passkey or
  recovery-code sign-in sets strong_at.
- A passkey added from /settings cannot confirm the session that added it (credentials.added_in_session). A stolen
  session cookie therefore cannot add its own key and confirm with it; the new key confirms from its next sign-in on.
- The one exception to "adding a passkey needs a confirmation": an account with no passkey (one made by ORCID) may add
  its first passkey within five minutes of an ORCID sign-in on this session, since it has nothing else to confirm with.
- Download everything as JSON: every row the users DB holds about the account, without secrets (no session token
  hashes, no recovery code hashes, no passkey public keys, no WebAuthn user handle).
- Delete the account: every row in one transaction, then the cookie is cleared. One audit row stays: the time and
  "account deleted", with no user id, name or anything else that points at the person.

Sessions, the CSRF guard, rate limits and the error shape come from users.py; the WebAuthn helpers from account.py.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, Response
from pydantic import BaseModel, Field
from webauthn import base64url_to_bytes, generate_authentication_options, generate_registration_options, options_to_json
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement,
)

from . import account, mailer, users
from .users import ApiError, Db, User, auth_rate_limit, iso, now

router = APIRouter(prefix="/account", tags=["settings"], dependencies=[Depends(users.require_intent), Depends(users.write_quota)])
NICKNAME_MAX = 80
TOO_NEW = "A passkey added in this session cannot confirm it. Sign out, sign in with that passkey, then confirm."


class Empty(BaseModel):
    pass


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class NicknameIn(BaseModel):
    nickname: str = Field(max_length=NICKNAME_MAX)


class RecoveryIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)


def _passkeys(conn, user_id: int) -> list[dict]:
    return [
        {"id": r["credential_id"], "nickname": r["nickname"], "created_at": r["created_at"], "last_used_at": r["last_used_at"]}
        for r in conn.execute("SELECT credential_id, nickname, created_at, last_used_at FROM credentials WHERE user_id = ? ORDER BY created_at, rowid", (user_id,))
    ]


def _state(conn, user: User) -> dict:
    return {
        "user": user.public(conn), "passkeys": _passkeys(conn, user.id), "orcid_available": account.orcid_configured(), "email_available": mailer.configured(),
        "session_method": user.session_method, "confirmed_until": user.strong_until(),
    }


# ---------------------------------------------------------------- what /settings shows


@router.get("/settings")
def settings(user: User = Depends(users.current_user)) -> dict:
    """The account as /settings shows it: name, passkeys, recovery codes left, ORCID, and until when this session may
    delete the account or regenerate recovery codes ("confirmed_until", null when it must confirm first)."""
    with Db() as conn:
        return _state(conn, user)


@router.patch("/profile")
def edit_profile(body: ProfileIn, user: User = Depends(users.current_user)) -> dict:
    """Changes the display name. A public list keeps the name it was published with until its page is updated."""
    name = " ".join(body.display_name.split())
    if not name:
        raise ApiError(422, "INVALID_REQUEST", "Choose a display name.")
    with Db() as conn:
        conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (name, user.id))
        users.audit(conn, user.id, "display name changed")
        user.display_name = name
        return _state(conn, user)


# ---------------------------------------------------------------- passkeys


def _held(conn, user_id: int) -> int:
    return conn.execute("SELECT count(*) FROM credentials WHERE user_id = ?", (user_id,)).fetchone()[0]


def _fresh_orcid(user: User) -> bool:
    """Whether this session was made by an ORCID sign-in within the confirmation window."""
    if user.session_method != "orcid":
        return False
    started = datetime.strptime(user.session_created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return users.now() < started + users.STRONG_WINDOW


def _may_add_passkey(conn, user: User) -> None:
    """Adding a passkey needs a confirmation within five minutes, except an account's first passkey within five minutes
    of an ORCID sign-in on this session (F7-r1-1)."""
    if user.strong_until() is not None:
        return
    if _held(conn, user.id) == 0:
        if _fresh_orcid(user):
            return
        if conn.execute("SELECT 1 FROM orcid_links WHERE user_id = ?", (user.id,)).fetchone() and not conn.execute(
                "SELECT 1 FROM recovery_codes WHERE user_id = ? AND used_at IS NULL", (user.id,)).fetchone():
            raise ApiError(403, "ORCID_SIGN_IN_REQUIRED", "Sign in with ORCID again, then add your first passkey within five minutes.")
    users.require_strong(user)


def _own_passkey(conn, user_id: int, credential_id: str):
    row = conn.execute("SELECT credential_id FROM credentials WHERE credential_id = ? AND user_id = ?", (credential_id, user_id)).fetchone()
    if not row:
        raise ApiError(404, "PASSKEY_NOT_FOUND", "There is no such passkey in your account.")
    return row


@router.patch("/passkeys/{credential_id}")
def rename_passkey(credential_id: str, body: NicknameIn, user: User = Depends(users.current_user)) -> dict:
    with Db() as conn:
        _own_passkey(conn, user.id, credential_id)
        conn.execute("UPDATE credentials SET nickname = ? WHERE credential_id = ?", (" ".join(body.nickname.split()), credential_id))
        return _state(conn, user)


@router.delete("/passkeys/{credential_id}")
def remove_passkey(credential_id: str, _: Empty | None = None, user: User = Depends(users.current_user)) -> dict:
    """Removes a passkey; the account's last one stays, so the account can always be signed in to. Needs a confirmation
    within five minutes."""
    users.require_strong(user)
    with Db() as conn:
        conn.execute("BEGIN IMMEDIATE")  # the count and the delete see no other removal in between
        _own_passkey(conn, user.id, credential_id)
        if conn.execute("SELECT count(*) FROM credentials WHERE user_id = ?", (user.id,)).fetchone()[0] <= 1:
            raise ApiError(409, "LAST_PASSKEY", "This is your only passkey. Add another one before you remove it.")
        conn.execute("DELETE FROM credentials WHERE credential_id = ?", (credential_id,))
        users.audit(conn, user.id, "passkey removed")
        return _state(conn, user)


@router.post("/passkeys/options", dependencies=[Depends(auth_rate_limit)])
def add_passkey_options(_: Empty | None = None, user: User = Depends(users.current_user)) -> dict:
    """Starts adding another passkey to the signed-in account (the same ceremony as creating an account). The browser
    is told which passkeys the account already has, so it does not make a second one on the same device. Needs a
    confirmation within five minutes (or, for an account's first passkey, a fresh ORCID sign-in)."""
    with Db() as conn:
        _may_add_passkey(conn, user)
        handle = conn.execute("SELECT user_handle FROM users WHERE id = ?", (user.id,)).fetchone()["user_handle"]
        held = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(p["id"])) for p in _passkeys(conn, user.id)]
        options = generate_registration_options(
            rp_id=account.rp_id(), rp_name=account.RP_NAME, user_name=user.display_name, user_id=base64url_to_bytes(handle),
            user_display_name=user.display_name, exclude_credentials=held,
            authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
        )
        cid = account._put_challenge(conn, "add-passkey", options.challenge, user.id)
    return {"challenge_id": cid, "options": json.loads(options_to_json(options))}


class CredentialIn(BaseModel):
    challenge_id: str = Field(max_length=64)
    credential: dict
    nickname: str = Field(default="", max_length=NICKNAME_MAX)


@router.post("/passkeys/verify", dependencies=[Depends(auth_rate_limit)])
def add_passkey_verify(body: CredentialIn, user: User = Depends(users.current_user)) -> dict:
    with Db() as conn:
        row = account._take_challenge(conn, body.challenge_id, "add-passkey")
    if row["user_id"] != user.id:
        raise ApiError(400, "CHALLENGE_EXPIRED", "This sign-in attempt has expired. Please start again.")
    try:
        verified = account.verify_registration_response(
            credential=body.credential, expected_challenge=base64url_to_bytes(row["challenge"]), expected_rp_id=account.rp_id(),
            expected_origin=account.origin(), require_user_verification=True)
    except (InvalidRegistrationResponse, ValueError, KeyError, TypeError) as error:
        raise account._passkey_rejected("registration", error)
    transports = (body.credential.get("response") or {}).get("transports") or []
    with Db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _may_add_passkey(conn, user)  # again: the window may have closed, or a first passkey arrived meanwhile
        account.add_credential(conn, user.id, verified, transports, " ".join(body.nickname.split()))
        conn.execute("UPDATE credentials SET added_in_session = ? WHERE credential_id = ?",
                     (user.token_sha256, account.bytes_to_base64url(verified.credential_id)))
        return _state(conn, user)


# ---------------------------------------------------------------- confirming it is you


@router.post("/confirm/options", dependencies=[Depends(auth_rate_limit)])
def confirm_options(_: Empty | None = None, user: User = Depends(users.current_user)) -> dict:
    """Starts a passkey check for the signed-in account; the browser may offer only this account's passkeys, and not one
    added in this session."""
    with Db() as conn:
        held = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(r["credential_id"])) for r in conn.execute(
            "SELECT credential_id FROM credentials WHERE user_id = ? AND added_in_session IS NOT ? ORDER BY created_at, rowid", (user.id, user.token_sha256))]
        if not held:
            if _held(conn, user.id):
                raise ApiError(409, "PASSKEY_TOO_NEW", TOO_NEW)
            raise ApiError(409, "NO_PASSKEY", "This account has no passkey. Confirm with a recovery code, or add a passkey first.")
        options = generate_authentication_options(rp_id=account.rp_id(), user_verification=UserVerificationRequirement.REQUIRED, allow_credentials=held)
        cid = account._put_challenge(conn, "confirm", options.challenge, user.id)
    return {"challenge_id": cid, "options": json.loads(options_to_json(options))}


@router.post("/confirm/verify", dependencies=[Depends(auth_rate_limit)])
def confirm_verify(body: CredentialIn, user: User = Depends(users.current_user)) -> dict:
    """Finishes the passkey check. The passkey must belong to the signed-in account; the session is then confirmed for
    five minutes."""
    with Db() as conn:
        row = account._take_challenge(conn, body.challenge_id, "confirm")
        credential_id = str(body.credential.get("id") or body.credential.get("rawId") or "")
        stored = conn.execute("SELECT public_key, sign_count, added_in_session FROM credentials WHERE credential_id = ? AND user_id = ?", (credential_id, user.id)).fetchone()
    if row["user_id"] != user.id:
        raise ApiError(400, "CHALLENGE_EXPIRED", "This sign-in attempt has expired. Please start again.")
    if not stored:
        raise ApiError(400, "PASSKEY_UNKNOWN", "This passkey does not belong to the account you are signed in to.")
    if stored["added_in_session"] == user.token_sha256:
        raise ApiError(400, "PASSKEY_TOO_NEW", TOO_NEW)
    try:
        verified = account.verify_authentication_response(
            credential=body.credential, expected_challenge=base64url_to_bytes(row["challenge"]), expected_rp_id=account.rp_id(),
            expected_origin=account.origin(), credential_public_key=stored["public_key"], credential_current_sign_count=stored["sign_count"],
            require_user_verification=True)
    except (InvalidAuthenticationResponse, ValueError, KeyError, TypeError) as error:
        raise account._passkey_rejected("confirmation", error)
    with Db() as conn:
        conn.execute("UPDATE credentials SET sign_count = ?, last_used_at = ? WHERE credential_id = ?", (verified.new_sign_count, iso(now()), credential_id))
        users.mark_strong(conn, user)
        users.audit(conn, user.id, "confirmed with a passkey")
        return _state(conn, user)


@router.post("/confirm/recovery", dependencies=[Depends(auth_rate_limit)])
def confirm_recovery(body: RecoveryIn, user: User = Depends(users.current_user)) -> dict:
    """Confirms with one of this account's recovery codes, which is spent like a recovery sign-in."""
    with Db() as conn:
        spent = conn.execute("UPDATE recovery_codes SET used_at = ? WHERE code_sha256 = ? AND user_id = ? AND used_at IS NULL RETURNING id",
                             (iso(now()), users.sha256(users.normalise_code(body.code)), user.id)).fetchone()
        if not spent:
            raise ApiError(400, "RECOVERY_CODE_INVALID", "This recovery code is not valid for this account or has been used.")
        users.mark_strong(conn, user)
        users.audit(conn, user.id, "confirmed with a recovery code")
        return _state(conn, user)


# ---------------------------------------------------------------- recovery codes, ORCID


@router.post("/recovery-codes")
def regenerate_codes(_: Empty | None = None, user: User = Depends(users.current_user)) -> dict:
    """Ten new recovery codes, shown this once; the old ones stop working. Needs a confirmation within five minutes."""
    users.require_strong(user)
    with Db() as conn:
        codes = users.new_recovery_codes(conn, user.id)
        users.audit(conn, user.id, "recovery codes regenerated")
        return _state(conn, user) | {"recovery_codes": codes}


@router.delete("/orcid")
def unlink_orcid(_: Empty | None = None, user: User = Depends(users.current_user)) -> dict:
    """Unlinks the ORCID iD. Refused when the account has no passkey, since ORCID is then its only way in. Needs a
    confirmation within five minutes, like every change to how the account is signed in to."""
    with Db() as conn:
        if not conn.execute("SELECT 1 FROM orcid_links WHERE user_id = ?", (user.id,)).fetchone():
            raise ApiError(404, "ORCID_NOT_LINKED", "No ORCID iD is linked to this account.")
        if not conn.execute("SELECT 1 FROM credentials WHERE user_id = ? UNION ALL SELECT 1 FROM emails WHERE user_id = ?", (user.id, user.id)).fetchone():
            raise ApiError(409, "ORCID_ONLY_SIGN_IN", "ORCID is the only way into this account. Add a passkey or an email address before you unlink it.")
        users.require_strong(user)
        conn.execute("DELETE FROM orcid_links WHERE user_id = ?", (user.id,))
        users.audit(conn, user.id, "orcid unlinked")
        return _state(conn, user)


# ---------------------------------------------------------------- your data


def export_data(conn, user_id: int) -> dict:
    """Every row the users DB holds about one account, as plain JSON, with secrets left out."""
    one = lambda sql: conn.execute(sql, (user_id,)).fetchone()  # noqa: E731
    many = lambda sql: [dict(r) for r in conn.execute(sql, (user_id,))]  # noqa: E731
    u = one("SELECT id, display_name, created_at FROM users WHERE id = ?")
    codes = many("SELECT used_at FROM recovery_codes WHERE user_id = ? ORDER BY id")
    lists = []
    for row in conn.execute("SELECT * FROM lists WHERE user_id = ? ORDER BY is_builtin DESC, id", (user_id,)):
        items = [
            {"accession": i["accession"], "added_at": i["added_at"], "note": i["note"], "tags": json.loads(i["tags"]), "snapshot": json.loads(i["snapshot"])}
            for i in conn.execute("SELECT * FROM list_items WHERE list_id = ? ORDER BY id", (row["id"],))
        ]
        lists.append({
            "id": row["id"], "name": row["name"], "description": row["description"], "builtin": bool(row["is_builtin"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"], "items": items,
            "public": None if not row["share_id"] else {"share_id": row["share_id"], "published_at": row["published_at"], "page": json.loads(row["share_snapshot"] or "null")},
        })
    link = one("SELECT orcid, linked_at FROM orcid_links WHERE user_id = ?")
    email = one("SELECT email, verified_at FROM emails WHERE user_id = ?")
    return {
        "format": "locus account export, version 1",
        "exported_at": iso(now()),
        "account": dict(u) if u else None,
        "passkeys": [dict(p) | {"transports": json.loads(p["transports"])} for p in many(
            "SELECT credential_id AS id, nickname, created_at, last_used_at, transports FROM credentials WHERE user_id = ? ORDER BY created_at, rowid")],
        "sessions": many("SELECT method, created_at, expires_at, last_seen_at, user_agent FROM sessions WHERE user_id = ? ORDER BY created_at"),
        "recovery_codes": {"total": len(codes), "left": sum(1 for c in codes if c["used_at"] is None), "used_at": [c["used_at"] for c in codes if c["used_at"]]},
        "orcid": dict(link) if link else None,
        "email": dict(email) if email else None,
        "lists": lists,
        "watched_searches": [dict(w) | {"seen": json.loads(w["seen"])} for w in many(
            "SELECT question, since, created_at, seen FROM watches WHERE user_id = ? ORDER BY id")],
        "followed_people": [dict(f) | {"seen": json.loads(f["seen"])} for f in many(
            "SELECT orcid, display_name, page_name, followed_at, seen FROM follows WHERE user_id = ? ORDER BY id")],
        "activity": many("SELECT at, event FROM audit WHERE user_id = ? ORDER BY id"),
    }


@router.get("/export")
def export(user: User = Depends(users.current_user)) -> Response:
    """Everything as one JSON file (Download everything as JSON on /settings)."""
    with Db() as conn:
        data = export_data(conn, user.id)
    name = f"locus-account-{iso(now())[:10]}.json"
    return Response(json.dumps(data, indent=2, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------- delete the account

# Every table holding a user's rows, children first. list_items and public share snapshots go with lists.
_OWNED = (
    "DELETE FROM list_items WHERE list_id IN (SELECT id FROM lists WHERE user_id = ?)",
    "DELETE FROM lists WHERE user_id = ?",
    "DELETE FROM watches WHERE user_id = ?",
    "DELETE FROM follows WHERE user_id = ?",
    "DELETE FROM credentials WHERE user_id = ?",
    "DELETE FROM recovery_codes WHERE user_id = ?",
    "DELETE FROM orcid_links WHERE user_id = ?",
    "DELETE FROM challenges WHERE user_id = ?",
    "DELETE FROM sessions WHERE user_id = ?",
    "DELETE FROM audit WHERE user_id = ?",
    "DELETE FROM quota_events WHERE user_id = ?",
    "DELETE FROM users WHERE id = ?",
)


@router.delete("")
def delete_account(response: Response, _: Empty | None = None, user: User = Depends(users.current_user)) -> dict:
    """Deletes the account and everything in it in one transaction: passkeys, sessions on every device, recovery codes,
    the ORCID link, lists and their items (a public link answers 404 at once), watched searches, follows and the
    account's activity log. Then this browser's cookie is cleared. Needs a confirmation within five minutes."""
    users.require_strong(user)
    with Db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for sql in _OWNED:
            conn.execute(sql, (user.id,))
        users.audit(conn, None, "account deleted")
    response.delete_cookie(users.cookie_name(), path="/", httponly=True, samesite="lax", secure=users.cookie_secure())
    return {"ok": True}


def install(app: FastAPI) -> None:
    """Adds the settings routes; call after users.install(app), which provides the error handlers and /account."""
    app.include_router(router)

