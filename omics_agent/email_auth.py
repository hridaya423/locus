"""/account/email routes: sign in (or create an account) with a six-digit code sent to an email address, link an address
to an account, confirm it is you with a code before a sensitive change, and remove the address.

A code is good for ten minutes and five guesses, and is stored only as a hash. Asking for a code answers the same way
whether or not the address has an account, so the form cannot be used to find out who uses locus. Sending is limited per
address (3 in 15 minutes, 10 a day) and overall (LOCUS_MAIL_DAILY_CAP, default 250 a day, under Brevo's free 300).
The mail itself goes out through mailer.py; with no mail settings every route here is a 404.
"""

import hashlib
import json
import os
import re
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from . import mailer, users
from .account import _signed_in
from .users import ApiError, Db, User, auth_rate_limit, iso, now

router = APIRouter(prefix="/account/email", tags=["account"], dependencies=[Depends(users.require_intent)])
CODE_TTL = timedelta(minutes=10)
MAX_GUESSES = 5
PER_ADDRESS = ((timedelta(minutes=15), 3), (timedelta(days=1), 10))
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

SUBJECT = "Your locus sign-in code"
TEXT = """Your locus code is {code}

Type it into the page where you asked for it. It works once, for ten minutes.

{why}

If you did not ask for this, you can ignore this email; nothing changes without the code.
"""
WHY = {
    "sign-in": "You asked to sign in to locus (or create an account) with this address.",
    "link": "You asked to add this address to your locus account.",
    "confirm": "You asked to confirm it is you before changing your locus account.",
}


def _need_mail() -> None:
    if not mailer.configured():
        raise ApiError(404, "NOT_FOUND", "Email sign-in is not set up on this server.")


def normalise(address: str) -> str:
    address = address.strip().lower()
    if len(address) > 254 or not EMAIL.match(address):
        raise ApiError(422, "EMAIL_INVALID", "That does not look like an email address.")
    return address


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def email_of(conn, user_id: int) -> str | None:
    row = conn.execute("SELECT email FROM emails WHERE user_id = ?", (user_id,)).fetchone()
    return row["email"] if row else None


def _check_send_limits(conn, address: str) -> None:
    key = _sha(address)
    t = now()
    conn.execute("DELETE FROM email_sends WHERE at <= ?", (iso(t - timedelta(days=1)),))
    for window, limit in PER_ADDRESS:
        n = conn.execute("SELECT count(*) FROM email_sends WHERE email_sha256 = ? AND at > ?", (key, iso(t - window))).fetchone()[0]
        if n >= limit:
            raise ApiError(429, "EMAIL_TOO_MANY", "Several codes have gone to this address already. Please use the latest one, or try again later.", transient=True)
    cap = int(os.environ.get("LOCUS_MAIL_DAILY_CAP") or 250)
    if conn.execute("SELECT count(*) FROM email_sends").fetchone()[0] >= cap:
        raise ApiError(503, "EMAIL_DAILY_CAP", "locus has sent as many emails as it can today. Please try again tomorrow or use a passkey.", transient=True)
    conn.execute("INSERT INTO email_sends (email_sha256, at) VALUES (?, ?)", (key, iso(t)))


class StartIn(BaseModel):
    purpose: Literal["sign-in", "link", "confirm"] = "sign-in"
    email: str = Field(default="", max_length=254)


@router.post("/start", dependencies=[Depends(auth_rate_limit)])
def start(body: StartIn, user: User | None = Depends(users.optional_user)) -> dict:
    """Emails a six-digit code. sign-in: to the address given. link: to a new address for the signed-in account.
    confirm: to the signed-in account's own address."""
    _need_mail()
    if body.purpose != "sign-in" and user is None:
        raise ApiError(401, "SIGN_IN_REQUIRED", "Please sign in first.")
    with Db() as conn:
        if body.purpose == "confirm":
            address = email_of(conn, user.id)
            if not address:
                raise ApiError(400, "NO_EMAIL", "This account has no email address to send a code to.")
        else:
            address = normalise(body.email)
        _check_send_limits(conn, address)
        code = f"{secrets.randbelow(1_000_000):06d}"
        cid = secrets.token_urlsafe(24)
        conn.execute("DELETE FROM challenges WHERE expires_at <= ?", (iso(now()),))
        conn.execute("INSERT INTO challenges (id, kind, challenge, user_id, payload, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (cid, f"email-{body.purpose}", _sha(cid + code), user.id if user else None,
                      json.dumps({"email": address, "guesses": 0}), iso(now() + CODE_TTL)))
    # Sent after the row is committed, so a code that arrives always works.
    try:
        mailer.send(address, SUBJECT, TEXT.format(code=code, why=WHY[body.purpose]))
    except mailer.MailError:
        with Db() as conn:
            conn.execute("DELETE FROM challenges WHERE id = ?", (cid,))
        raise ApiError(503, "EMAIL_NOT_SENT", "locus could not send the email just now. Please try again in a minute.", transient=True)
    return {"challenge_id": cid, "sent_to": address if body.purpose != "confirm" else _mask(address)}


def _mask(address: str) -> str:
    name, domain = address.split("@", 1)
    return f"{name[:2]}{'•' * max(1, len(name) - 2)}@{domain}"


class VerifyIn(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=20)
    display_name: str = Field(default="", max_length=80)


def _take_code(conn, cid: str, code: str):
    """The challenge if the code matches (and removes it); a wrong code uses up one of five guesses."""
    row = conn.execute("SELECT kind, challenge, user_id, payload, expires_at FROM challenges WHERE id = ? AND kind LIKE 'email-%'", (cid,)).fetchone()
    if not row or row["expires_at"] <= iso(now()):
        raise ApiError(400, "CHALLENGE_EXPIRED", "This code has expired. Please ask for a new one.")
    payload = json.loads(row["payload"])
    if not secrets.compare_digest(_sha(cid + re.sub(r"\D", "", code)), row["challenge"]):
        payload["guesses"] = payload.get("guesses", 0) + 1
        if payload["guesses"] >= MAX_GUESSES:
            conn.execute("DELETE FROM challenges WHERE id = ?", (cid,))
            raise ApiError(400, "CHALLENGE_EXPIRED", "That code was wrong too many times. Please ask for a new one.")
        conn.execute("UPDATE challenges SET payload = ? WHERE id = ?", (json.dumps(payload), cid))
        raise ApiError(400, "EMAIL_CODE_WRONG", "That code is not right. Please check the latest email from locus.")
    conn.execute("DELETE FROM challenges WHERE id = ?", (cid,))
    return row["kind"].removeprefix("email-"), row["user_id"], payload["email"]


@router.post("/verify", dependencies=[Depends(auth_rate_limit)])
def verify(body: VerifyIn, request: Request, response: Response, user: User | None = Depends(users.optional_user)) -> dict:
    _need_mail()
    # Wrong guesses must be saved even though the request fails, so the check commits before raising.
    conn = users.connect()
    try:
        with conn:
            try:
                purpose, owner, address = _take_code(conn, body.challenge_id, body.code)
            except ApiError as e:
                wrong = e
            else:
                wrong = None
        if wrong:
            raise wrong
        with conn:
            if purpose == "sign-in":
                row = conn.execute("SELECT user_id FROM emails WHERE email = ?", (address,)).fetchone()
                created = row is None
                if created:
                    name = " ".join(body.display_name.split()) or address.split("@", 1)[0][:80]
                    user_id = users.create_user(conn, name)
                    conn.execute("INSERT INTO emails (user_id, email, verified_at) VALUES (?, ?, ?)", (user_id, address, iso(now())))
                else:
                    user_id = row["user_id"]
                users.audit(conn, user_id, "email code used to sign in")
                return {"user": _signed_in(conn, response, request, user_id, "email"), "created": created}
            if user is None or user.id != owner:
                raise ApiError(401, "SIGN_IN_REQUIRED", "Please sign in again in the browser that asked for the code.")
            if purpose == "link":
                other = conn.execute("SELECT user_id FROM emails WHERE email = ?", (address,)).fetchone()
                if other and other["user_id"] != user.id:
                    raise ApiError(409, "EMAIL_IN_USE", "That address already belongs to another locus account.")
                conn.execute("INSERT INTO emails (user_id, email, verified_at) VALUES (?, ?, ?) "
                             "ON CONFLICT(user_id) DO UPDATE SET email = excluded.email, verified_at = excluded.verified_at",
                             (user.id, address, iso(now())))
                users.audit(conn, user.id, "email address linked")
            else:
                users.mark_strong(conn, user)
                users.audit(conn, user.id, "confirmed with an email code")
            return {"user": user.public(conn)}
    finally:
        conn.close()


class Empty(BaseModel):
    pass


@router.post("/unlink")
def unlink(_: Empty | None = None, user: User = Depends(users.current_user)) -> dict:
    """Removes the account's address, unless it is the only way into the account."""
    users.require_strong(user)
    with Db() as conn:
        other_ways = conn.execute(
            "SELECT (SELECT count(*) FROM credentials WHERE user_id = :u) + (SELECT count(*) FROM recovery_codes WHERE user_id = :u AND used_at IS NULL)"
            " + (SELECT count(*) FROM orcid_links WHERE user_id = :u)", {"u": user.id}).fetchone()[0]
        if not other_ways:
            raise ApiError(409, "LAST_WAY_IN", "Your email address is the only way into this account, so it stays. Add a passkey first.")
        conn.execute("DELETE FROM emails WHERE user_id = ?", (user.id,))
        users.audit(conn, user.id, "email address removed")
        return {"user": user.public(conn)}
