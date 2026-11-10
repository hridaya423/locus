"""Accounts core: the users DB, sessions, the CSRF guard, rate limits, the shared error shape and `current_user`.

Everything a route that touches an account needs lives here, so later routers (lists, follows, settings) reuse it:

    router = APIRouter(prefix="/lists", dependencies=[Depends(users.require_intent)])
    @router.post("")
    def create(body: ListIn, user: users.User = Depends(users.current_user)): ...

User data lives in its own SQLite file, OMICS_USERS_DB (default data/users.db), never in omics.db, which is a
downloadable read-only release. Numbered migrations in migrations/users/NNN_*.sql are applied on first connect.
"""

import hashlib
import ipaddress
import os
import secrets
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "users.db"
MIGRATIONS = Path(__file__).resolve().parent / "migrations" / "users"
COOKIE = "locus_session"
SESSION_DAYS = 30
STRONG_METHODS = ("passkey", "recovery", "email")  # sign-ins that prove the person holds the account's passkey, codes or address
STRONG_WINDOW = timedelta(minutes=5)  # how recent such a sign-in must be to delete the account or regenerate codes
SESSION_REFRESH = timedelta(hours=1)  # how stale last_seen_at may get before a request slides the expiry forward
# Paths whose errors (including request validation) use the shared {"error": {...}} shape. Later routers add theirs.
SHAPED_PREFIXES = ["/account"]


# ---------------------------------------------------------------- errors


class ApiError(Exception):
    """An error every account-facing route returns as {"error": {"code", "message", "transient"}}."""

    def __init__(self, status: int, code: str, message: str, transient: bool = False, headers: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.transient, self.headers = status, code, message, transient, headers


def error_body(code: str, message: str, transient: bool = False) -> dict:
    return {"error": {"code": code, "message": message, "transient": transient}}


async def _api_error(_: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(error_body(error.code, error.message, error.transient), status_code=error.status, headers=error.headers)


async def _validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    if not any(request.url.path.startswith(p) for p in SHAPED_PREFIXES):
        return await request_validation_exception_handler(request, error)
    first = error.errors()[0] if error.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", ())[1:])
    return JSONResponse(error_body("INVALID_REQUEST", f"{where}: {first.get('msg', 'invalid')}" if where else "The request was not valid."), status_code=422)


# ---------------------------------------------------------------- time


def now() -> datetime:
    """The current UTC time; tests replace it to move the clock."""
    return datetime.now(timezone.utc)


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- database

_migrated: set[str] = set()
_migrate_lock = threading.Lock()


def db_path() -> Path:
    return Path(os.environ.get("OMICS_USERS_DB") or DEFAULT_DB)


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Applies every numbered migration newer than the DB's, each in its own transaction; returns those applied."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:3])
        if version in done:
            continue
        conn.executescript("BEGIN;\n" + path.read_text() + f"\nINSERT INTO schema_migrations VALUES ({version}, '{path.stem}', '{iso(now())}');\nCOMMIT;")
        applied.append(version)
    return applied


def connect() -> sqlite3.Connection:
    """A connection to the users DB with foreign keys on, migrated to the newest schema. Use as a context manager for a
    transaction (`with users.connect() as conn:` commits or rolls back), then close it."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    key = str(path.resolve())
    if key not in _migrated:
        with _migrate_lock:
            if key not in _migrated:
                conn.execute("PRAGMA journal_mode = WAL")
                migrate(conn)
                _migrated.add(key)
    return conn


class Db:
    """`with Db() as conn:` runs one transaction and closes the connection afterwards."""

    def __enter__(self) -> sqlite3.Connection:
        self.conn = connect()
        return self.conn

    def __exit__(self, kind, *_):
        try:
            if kind is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def audit(conn: sqlite3.Connection, user_id: int | None, event: str) -> None:
    conn.execute("INSERT INTO audit (user_id, at, event) VALUES (?, ?, ?)", (user_id, iso(now()), event[:200]))


def create_user(conn: sqlite3.Connection, display_name: str, handle: str | None = None) -> int:
    handle = handle or secrets.token_urlsafe(32)
    cur = conn.execute("INSERT INTO users (created_at, display_name, user_handle) VALUES (?, ?, ?)", (iso(now()), display_name, handle))
    audit(conn, cur.lastrowid, "account created")
    return cur.lastrowid


# ---------------------------------------------------------------- recovery codes

RECOVERY_COUNT = 10
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1


def normalise_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def new_recovery_codes(conn: sqlite3.Connection, user_id: int) -> list[str]:
    """Replaces the user's recovery codes with ten fresh ones (60 bits each) and returns them; only hashes are kept."""
    conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
    codes = []
    for _ in range(RECOVERY_COUNT):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(12))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
        conn.execute("INSERT INTO recovery_codes (user_id, code_sha256) VALUES (?, ?)", (user_id, sha256(raw)))
    return codes


def use_recovery_code(conn: sqlite3.Connection, code: str) -> int | None:
    """Spends a recovery code; the user it belongs to, or None when it is unknown or already used."""
    digest = sha256(normalise_code(code))
    row = conn.execute("UPDATE recovery_codes SET used_at = ? WHERE code_sha256 = ? AND used_at IS NULL RETURNING user_id", (iso(now()), digest)).fetchone()
    return row["user_id"] if row else None


# ---------------------------------------------------------------- sessions


def cookie_secure() -> bool:
    return os.environ.get("LOCUS_COOKIE_INSECURE") != "1"


def cookie_name() -> str:
    return "__Host-locus_session" if cookie_secure() else COOKIE


def start_session(conn: sqlite3.Connection, response: Response, user_id: int, method: str, user_agent: str = "", previous: str | None = None) -> None:
    """Creates a session and sets its cookie: a random 32-byte token in the browser, its SHA-256 in the DB. `previous` is
    the session cookie the browser came with, if any: that session ends, since the browser is about to lose its token."""
    if previous:
        conn.execute("DELETE FROM sessions WHERE token_sha256 = ?", (sha256(previous),))
    token = secrets.token_urlsafe(32)
    t = now()
    conn.execute(
        "INSERT INTO sessions (token_sha256, user_id, method, created_at, expires_at, last_seen_at, user_agent, strong_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (sha256(token), user_id, method, iso(t), iso(t + timedelta(days=SESSION_DAYS)), iso(t), user_agent[:300], iso(t) if method in STRONG_METHODS else None),
    )
    audit(conn, user_id, f"signed in ({method})")
    set_cookie(response, token)


def set_cookie(response: Response, token: str) -> None:
    # Path=/ and no Domain: the web app reaches the API through its own /api rewrite, so the cookie is first-party.
    response.set_cookie(cookie_name(), token, max_age=SESSION_DAYS * 86400, path="/", httponly=True, samesite="lax", secure=cookie_secure())


def end_session(response: Response, token: str | None) -> None:
    if token:
        with Db() as conn:
            row = conn.execute("DELETE FROM sessions WHERE token_sha256 = ? RETURNING user_id", (sha256(token),)).fetchone()
            if row:
                audit(conn, row["user_id"], "signed out")
    response.delete_cookie(cookie_name(), path="/", httponly=True, samesite="lax", secure=cookie_secure())


@dataclass
class User:
    id: int
    display_name: str
    created_at: str
    session_method: str
    session_created_at: str
    strong_at: str | None = None  # the session's last passkey or recovery-code sign-in or confirmation
    token_sha256: str = ""

    def strong_until(self) -> str | None:
        """Until when this session may delete the account or regenerate recovery codes; None when it may not now."""
        if not self.strong_at:
            return None
        until = datetime.strptime(self.strong_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + STRONG_WINDOW
        return iso(until) if until > now() else None

    def public(self, conn: sqlite3.Connection | None = None) -> dict:
        """What the browser may know about the signed-in account."""
        own = conn is None
        conn = conn or connect()
        try:
            link = conn.execute("SELECT orcid FROM orcid_links WHERE user_id = ?", (self.id,)).fetchone()
            passkeys = conn.execute("SELECT count(*) FROM credentials WHERE user_id = ?", (self.id,)).fetchone()[0]
            codes = conn.execute("SELECT count(*) FROM recovery_codes WHERE user_id = ? AND used_at IS NULL", (self.id,)).fetchone()[0]
            email = conn.execute("SELECT email FROM emails WHERE user_id = ?", (self.id,)).fetchone()
        finally:
            if own:
                conn.close()
        return {"id": self.id, "display_name": self.display_name, "created_at": self.created_at, "orcid": link["orcid"] if link else None, "email": email["email"] if email else None,
                "passkeys": passkeys, "recovery_codes_left": codes}


def optional_user(request: Request, response: Response) -> User | None:
    """The signed-in user, or None. Slides the session's 30-day expiry forward at most once an hour."""
    token = request.cookies.get(cookie_name())
    if not token:
        return None
    digest, t = sha256(token), now()
    with Db() as conn:
        row = conn.execute(
            "SELECT s.user_id, s.method, s.created_at AS session_created_at, s.expires_at, s.last_seen_at, s.strong_at, u.display_name, u.created_at "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_sha256 = ?",
            (digest,),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] <= iso(t):
            conn.execute("DELETE FROM sessions WHERE token_sha256 = ?", (digest,))
            return None
        if row["last_seen_at"] <= iso(t - SESSION_REFRESH):
            conn.execute("UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token_sha256 = ?", (iso(t), iso(t + timedelta(days=SESSION_DAYS)), digest))
            set_cookie(response, token)
    return User(row["user_id"], row["display_name"], row["created_at"], row["method"], row["session_created_at"], row["strong_at"], digest)


def current_user(user: User | None = Depends(optional_user)) -> User:
    """The signed-in user; 401 SIGN_IN_REQUIRED otherwise."""
    if user is None:
        raise ApiError(401, "SIGN_IN_REQUIRED", "Sign in to do this.")
    return user


def require_strong(user: User) -> None:
    """Refuses (403 CONFIRM_REQUIRED) unless this session saw a passkey or recovery-code sign-in in the last five
    minutes. A dev sign-in or ORCID sign-in never counts; /account/confirm/* records a fresh one on the session."""
    if user.strong_until() is None:
        raise ApiError(403, "CONFIRM_REQUIRED", "Confirm it is you with your passkey, a recovery code or an email code first. The confirmation lasts five minutes.")


def mark_strong(conn: sqlite3.Connection, user: User) -> str:
    """Records a passkey or recovery-code confirmation on the user's current session; returns its time."""
    t = iso(now())
    conn.execute("UPDATE sessions SET strong_at = ? WHERE token_sha256 = ? AND user_id = ?", (t, user.token_sha256, user.id))
    user.strong_at = t
    return t


# ---------------------------------------------------------------- CSRF guard

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def require_intent(request: Request) -> None:
    """State-changing requests must say so: header X-Locus-Intent: 1 and a JSON body (on top of SameSite=Lax). A
    cross-site form cannot set either, and a fetch from another origin that sets them needs a CORS preflight. The API
    never grants a preflight for X-Locus-Intent; CORS allows only Content-Type to locus's own local front ends
    (api.py: localhost:3000 and :3020)."""
    if request.method in SAFE_METHODS:
        return
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if request.headers.get("x-locus-intent") != "1" or kind != "application/json":
        raise ApiError(403, "INTENT_REQUIRED", "This request needs the header X-Locus-Intent: 1 and a JSON body.")
    expected = (os.environ.get("LOCUS_ORIGIN") or "").rstrip("/")
    sent = request.headers.get("origin")
    if expected and sent is not None and sent.rstrip("/") != expected:
        raise ApiError(403, "ORIGIN_REFUSED", "This request came from another site.")


WRITE_PER_MINUTE = 120


def write_quota(request: Request, user: User | None = Depends(optional_user)) -> None:
    if request.method in SAFE_METHODS or user is None:
        return
    t = now()
    cutoff = iso(t - timedelta(seconds=60))
    with Db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM quota_events WHERE user_id = ? AND at <= ?", (user.id, cutoff))
        rows = conn.execute("SELECT at FROM quota_events WHERE user_id = ? ORDER BY at", (user.id,)).fetchall()
        if len(rows) >= WRITE_PER_MINUTE:
            oldest = datetime.strptime(rows[0]["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            wait = max(1, int((oldest + timedelta(seconds=60) - t).total_seconds()) + 1)
            raise ApiError(429, "RATE_LIMITED", f"Too many changes at once. Please wait {wait} seconds and try again.", transient=True, headers={"Retry-After": str(wait)})
        conn.execute("INSERT INTO quota_events (user_id, at) VALUES (?, ?)", (user.id, iso(t)))


# ---------------------------------------------------------------- client address


def _ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(text.strip())
    except ValueError:
        return None


def forwarded_chain(request: Request) -> list[str]:
    return [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]


def client_ip(request: Request) -> str:
    """The caller's address. Behind the web app's /api rewrite the API's peer is always loopback, so then the right-most
    X-Forwarded-For entry is used (the one the nearest proxy saw). A client can forge that header when nothing in front
    of the web app rewrites it; the overall rate limit still bounds what that buys."""
    raw = os.environ.get("LOCUS_TRUSTED_PROXIES", "")
    stripped = raw.strip()
    hops = int(stripped) if stripped.isdigit() else 1
    peer = request.client.host if request.client else ""
    peer_ip = _ip(peer)
    chain = forwarded_chain(request)
    if peer_ip is not None and peer_ip.is_loopback and hops > 0 and len(chain) >= hops:
        return chain[-hops]
    return peer or "unknown"


def is_local(request: Request) -> bool:
    """True only when the peer and every forwarded hop are loopback addresses."""
    hops = [request.client.host if request.client else ""] + forwarded_chain(request)
    return all((ip := _ip(h)) is not None and ip.is_loopback for h in hops)


# ---------------------------------------------------------------- rate limits


def limit_key(caller: str) -> str:
    """The rate-limit key of a caller: an IPv4 address as is, an IPv6 address as its /64 network (an IPv4-mapped IPv6
    address as its IPv4 address), anything else unchanged."""
    ip = _ip(caller)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network(f"{ip}/64", strict=False))
    return str(ip) if ip is not None else caller


class RateLimiter:
    """In-process sliding one-minute windows: per caller address and overall, for one bucket of routes."""

    def __init__(self, per_ip: int, overall: int, window: float = 60.0):
        self.per_ip, self.overall, self.window = per_ip, overall, window
        self.lock = threading.Lock()
        self.hits: dict[str, deque] = {}
        self.swept = float("-inf")

    def reset(self) -> None:
        with self.lock:
            self.hits.clear()

    def _count(self, key: str, t: float) -> deque:
        q = self.hits.setdefault(key, deque())
        while q and q[0] <= t - self.window:
            q.popleft()
        return q

    def check(self, ip: str) -> None:
        """Counts one attempt for a caller: an address (an IPv6 address counts as its /64, which one client usually
        holds whole) or any other key ("account:7")."""
        t = time.monotonic()
        with self.lock:
            mine, everyone = self._count("ip:" + limit_key(ip), t), self._count("*", t)
            if len(mine) >= self.per_ip or len(everyone) >= self.overall:
                wait = int(self.window - (t - (mine[0] if len(mine) >= self.per_ip else everyone[0]))) + 1
                raise ApiError(429, "RATE_LIMITED", f"Too many attempts. Please wait {wait} seconds and try again.", transient=True, headers={"Retry-After": str(wait)})
            mine.append(t)
            everyone.append(t)
            self._forget(t)

    def _forget(self, t: float) -> None:
        """Drops every caller with no attempt inside the window, so no address is held longer than a minute (/privacy
        says so). Runs at most once a second; the overall limit keeps the number of live keys small."""
        if t - self.swept < 1.0 and len(self.hits) <= 10_000:
            return
        self.swept = t
        for key in [k for k, q in self.hits.items() if not q or q[-1] <= t - self.window]:
            del self.hits[key]


AUTH_LIMIT = RateLimiter(per_ip=10, overall=100)


def auth_rate_limit(request: Request) -> None:
    """Sign-in and account-creation routes: at most 10 a minute from one address and 100 a minute overall."""
    AUTH_LIMIT.check(client_ip(request))


# ---------------------------------------------------------------- wiring


def install(app: FastAPI) -> None:
    """Adds the shared error handlers and the /account routes to an app."""
    from . import account, email_auth

    @app.middleware("http")
    async def no_store_account(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith(("/account", "/lists", "/follows")) and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(account.router)
    app.include_router(email_auth.router)
