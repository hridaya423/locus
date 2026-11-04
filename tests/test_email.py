"""Email sign-in (2 Nov): codes sent through a faked mailer, sign-in and account creation, wrong guesses, expiry, the
send limits, linking an address in Settings, confirming with a code, and removing an address. No network."""

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from omics_agent import email_auth, mailer, settings, users

INTENT = {"X-Locus-Intent": "1"}
LOCAL = ("127.0.0.1", 50000)


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    monkeypatch.setenv("OMICS_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("LOCUS_DEV_LOGIN", "1")
    monkeypatch.setenv("LOCUS_ORIGIN", "http://localhost:3051")
    for name in ("LOCUS_COOKIE_INSECURE", "LOCUS_MAIL_DEV_LOG", "LOCUS_MAIL_DAILY_CAP", "LOCUS_DEV_LOGIN_SECRET"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {"LOCUS_SMTP_HOST": "smtp.test", "LOCUS_SMTP_USER": "u", "LOCUS_SMTP_PASSWORD": "p", "LOCUS_MAIL_FROM": "locus@test.org"}.items():
        monkeypatch.setenv(name, value)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, text: sent.append((to, text)))
    users.AUTH_LIMIT.reset()
    yield sent
    users.AUTH_LIMIT.reset()


def client() -> TestClient:
    app = FastAPI()
    users.install(app)
    if not any(getattr(r, "path", "").startswith("/account/settings") for r in app.routes):
        app.include_router(settings.router)
    return TestClient(app, base_url="https://testserver", client=LOCAL, follow_redirects=False)


def last_code(sent) -> str:
    return re.search(r"\b(\d{6})\b", sent[-1][1]).group(1)


def ask(c, email="Ada@Example.org", purpose="sign-in"):
    return c.post("/account/email/start", json={"purpose": purpose, "email": email}, headers=INTENT)


def verify(c, cid, code, **extra):
    return c.post("/account/email/verify", json={"challenge_id": cid, "code": code, **extra}, headers=INTENT)


def sign_in(c, sent, email="ada@example.org"):
    r = ask(c, email)
    assert r.status_code == 200, r.text
    return verify(c, r.json()["challenge_id"], last_code(sent))


def test_routes_are_404_without_mail_settings(outbox, monkeypatch):
    monkeypatch.delenv("LOCUS_SMTP_HOST")
    assert ask(client()).status_code == 404
    assert client().get("/account/me").json()["email_available"] is False


def test_first_code_creates_an_account_and_later_codes_sign_in(outbox):
    c = client()
    r = ask(c)
    assert r.json()["sent_to"] == "ada@example.org" and outbox[-1][0] == "ada@example.org"
    done = verify(c, r.json()["challenge_id"], last_code(outbox))
    assert done.status_code == 200 and done.json()["created"] is True
    user = done.json()["user"]
    assert user["email"] == "ada@example.org" and user["display_name"] == "ada"
    assert c.get("/account/me").json()["user"]["id"] == user["id"]

    other = client()
    again = sign_in(other, outbox, "ADA@example.org ")
    assert again.json()["created"] is False and again.json()["user"]["id"] == user["id"]


def test_email_sign_in_counts_as_a_fresh_confirmation(outbox):
    c = client()
    sign_in(c, outbox)
    s = c.get("/account/settings").json()
    assert s["confirmed_until"] is not None and s["session_method"] == "email"


def test_a_code_works_once_and_five_wrong_guesses_end_it(outbox):
    c = client()
    cid = ask(c).json()["challenge_id"]
    code = last_code(outbox)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        assert verify(c, cid, wrong).json()["error"]["code"] == "EMAIL_CODE_WRONG"
    assert verify(c, cid, wrong).json()["error"]["code"] == "CHALLENGE_EXPIRED"
    assert verify(c, cid, code).json()["error"]["code"] == "CHALLENGE_EXPIRED"

    cid = ask(c, "bob@example.org").json()["challenge_id"]
    code = last_code(outbox)
    assert verify(c, cid, code).status_code == 200
    assert verify(c, cid, code).json()["error"]["code"] == "CHALLENGE_EXPIRED"


def test_asking_for_a_code_answers_the_same_for_known_and_unknown_addresses(outbox):
    c = client()
    sign_in(c, outbox, "known@example.org")
    a, b = ask(client(), "known@example.org"), ask(client(), "unknown@example.org")
    assert a.status_code == b.status_code == 200 and set(a.json()) == set(b.json())


def test_sends_are_limited_per_address(outbox):
    c = client()
    for _ in range(3):
        assert ask(c, "flood@example.org").status_code == 200
    r = ask(c, "flood@example.org")
    assert r.status_code == 429 and r.json()["error"]["code"] == "EMAIL_TOO_MANY"
    assert ask(c, "other@example.org").status_code == 200


def test_daily_cap(outbox, monkeypatch):
    monkeypatch.setenv("LOCUS_MAIL_DAILY_CAP", "2")
    c = client()
    assert ask(c, "a@example.org").status_code == 200 and ask(c, "b@example.org").status_code == 200
    assert ask(c, "c@example.org").json()["error"]["code"] == "EMAIL_DAILY_CAP"


def test_a_failed_send_leaves_no_working_code(outbox, monkeypatch):
    def fail(*_):
        raise mailer.MailError("relay down")
    monkeypatch.setattr(mailer, "send", fail)
    r = ask(client())
    assert r.status_code == 503 and r.json()["error"]["code"] == "EMAIL_NOT_SENT"


def test_bad_address_is_refused(outbox):
    assert ask(client(), "not-an-address").json()["error"]["code"] == "EMAIL_INVALID"


def test_link_and_confirm_need_a_session(outbox):
    assert ask(client(), purpose="link").status_code == 401
    assert ask(client(), purpose="confirm").status_code == 401


def test_link_an_address_to_a_passkey_style_account(outbox):
    c = client()
    assert c.post("/account/dev-login", json={"display_name": "Dev"}, headers=INTENT).status_code == 200
    r = ask(c, "dev@example.org", "link")
    done = verify(c, r.json()["challenge_id"], last_code(outbox))
    assert done.status_code == 200 and done.json()["user"]["email"] == "dev@example.org"
    # The address now signs in to the same account.
    assert sign_in(client(), outbox, "dev@example.org").json()["user"]["id"] == done.json()["user"]["id"]


def test_a_link_code_only_works_for_the_session_that_asked(outbox):
    c = client()
    c.post("/account/dev-login", json={"display_name": "Dev"}, headers=INTENT)
    cid = ask(c, "dev@example.org", "link").json()["challenge_id"]
    thief = client()
    thief.post("/account/dev-login", json={"display_name": "Thief"}, headers=INTENT)
    assert verify(thief, cid, last_code(outbox)).status_code == 401


def test_an_address_belongs_to_one_account(outbox):
    sign_in(client(), outbox, "taken@example.org")
    c = client()
    c.post("/account/dev-login", json={"display_name": "Dev"}, headers=INTENT)
    cid = ask(c, "taken@example.org", "link").json()["challenge_id"]
    assert verify(c, cid, last_code(outbox)).json()["error"]["code"] == "EMAIL_IN_USE"


def test_confirm_goes_to_the_accounts_own_address_and_marks_the_session(outbox):
    c = client()
    c.post("/account/dev-login", json={"display_name": "Dev"}, headers=INTENT)
    cid = ask(c, "dev@example.org", "link").json()["challenge_id"]
    verify(c, cid, last_code(outbox))
    assert c.get("/account/settings").json()["confirmed_until"] is None  # dev sign-in never counts
    r = ask(c, "ignored@example.org", "confirm")
    assert outbox[-1][0] == "dev@example.org" and "dev@example.org" not in r.json()["sent_to"]
    verify(c, r.json()["challenge_id"], last_code(outbox))
    assert c.get("/account/settings").json()["confirmed_until"] is not None


def test_the_only_way_in_cannot_be_removed(outbox):
    c = client()
    sign_in(c, outbox)
    r = c.post("/account/email/unlink", json={}, headers=INTENT)
    assert r.status_code == 409 and r.json()["error"]["code"] == "LAST_WAY_IN"


def test_removing_needs_a_fresh_confirmation(outbox):
    c = client()
    c.post("/account/dev-login", json={"display_name": "Dev"}, headers=INTENT)
    verify(c, ask(c, "dev@example.org", "link").json()["challenge_id"], last_code(outbox))
    r = c.post("/account/email/unlink", json={}, headers=INTENT)
    assert r.status_code == 403 and r.json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_deleting_the_account_removes_the_address(outbox):
    c = client()
    sign_in(c, outbox)
    assert c.request("DELETE", "/account", json={}, headers=INTENT).status_code == 200
    again = sign_in(client(), outbox)
    assert again.json()["created"] is True
