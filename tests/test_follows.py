"""Following researchers (F5): ORCID resolution with the several-people guard, follow / unfollow / mark seen, the
/updates feed (ORCID-linked papers only, new until seen, bounded and cached), app-wide upstream pacing, and that one
account can neither see nor change another's follows. Every Europe PMC and ORCID call is answered by a fake; no network."""

import threading
import time
from concurrent.futures import wait

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from omics_agent import follows, pace, saved, store, users, watches

INTENT = {"X-Locus-Intent": "1"}
LOCAL = ("127.0.0.1", 50000)
THOREEN = "0000-0003-1164-7224"
SMITH_A = "0000-0002-1825-0097"
SMITH_B = "0000-0001-5000-0007"
COAUTHOR = "0000-0002-2222-3331"


def author(last, initials, orcid=None):
    a = {"fullName": f"{last} {initials}", "lastName": last, "initials": initials}
    if orcid:
        a["authorId"] = {"type": "ORCID", "value": orcid}
    return a


def paper(pmid, year, authors):
    return {"id": pmid, "source": "MED", "pmid": pmid, "title": f"Paper {pmid}.", "pubYear": year, "authorList": {"author": authors}}


# Name query "Thoreen CC": 42 hits, of the newest 6 five tag the ORCID on Thoreen and one tags none.
THOREEN_NAME = [paper(str(1000 + i), str(2024 - i), [author("Watson", "MJ"), author("Thoreen", "CC", THOREEN)]) for i in range(1, 6)] + [
    paper("2001", "2012", [author("Thoreen", "CC")])]
THOREEN_ORCID = [paper(str(1000 + i), str(2024 - i), []) for i in range(1, 6)]
# Two people named "Smith J": three papers tag one ORCID and three another.
SMITH_NAME = [paper(f"30{i}", "2020", [author("Smith", "J", SMITH_A)]) for i in range(3)] + [paper(f"31{i}", "2021", [author("Smith", "J", SMITH_B)]) for i in range(3)]
# "Nobody X": only a co-author carries an ORCID, which says nothing about Nobody.
NOBODY_NAME = [paper("401", "2022", [author("Nobody", "X"), author("Other", "Y", COAUTHOR)])]


class Upstream:
    """Answers Europe PMC searches and ORCID person records from the fixtures above, and counts the calls."""

    def __init__(self):
        self.calls: list[str] = []
        self.lock = threading.Lock()
        self.fail: set[str] = set()
        self.delay = 0.0
        self.active = self.peak = 0
        self.names: dict[str, tuple[str, str]] = {}
        self.extra: dict[str, tuple[list, int]] = {}
        self.missing: set[str] = set()

    def get(self, url, params=None, headers=None, timeout=None):
        with self.lock:
            self.calls.append(url + " " + str((params or {}).get("query", "")))
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            return self._answer(url, params or {})
        finally:
            with self.lock:
                self.active -= 1

    def _answer(self, url, params):
        request = httpx.Request("GET", url)
        if "/orcid/" in url:
            if "orcid" in self.fail:
                return httpx.Response(503, json={}, request=request)
            orcid = url.split("/orcid/")[1].split("/")[0]
            if orcid in self.missing:
                return httpx.Response(404, json={}, request=request)
            given, family = self.names.get(orcid, ("Carson", "Thoreen"))
            body = {"name": {"given-names": {"value": given}, "family-name": {"value": family}, "credit-name": None}}
            return httpx.Response(200, json=body, request=request)
        query = params["query"]
        if any(f in query for f in self.fail):
            return httpx.Response(503, json={}, request=request)
        found, hits = {
            'AUTH:"Thoreen CC"': (THOREEN_NAME, 42),
            f'AUTHORID:"{THOREEN}"': (THOREEN_ORCID, 5),
            'AUTH:"Smith J"': (SMITH_NAME, 900),
            'AUTH:"Nobody X"': (NOBODY_NAME, 1),
            **self.extra,
        }.get(query, ([], 0))
        if query.startswith("AUTHORID:") and not found:
            orcid = query.split('"')[1]
            found, hits = [paper(f"9{abs(hash(orcid)) % 10000}", "2023", [])], 1
        return httpx.Response(200, json={"hitCount": hits, "resultList": {"result": found[: int(params.get("pageSize", 25))]}}, request=request)


@pytest.fixture
def up(tmp_path, monkeypatch):
    monkeypatch.setenv("OMICS_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("LOCUS_DEV_LOGIN", "1")
    monkeypatch.setenv("LOCUS_EPMC_BASE", "http://fixture.invalid/epmc")
    monkeypatch.setenv("LOCUS_ORCID_BASE", "http://fixture.invalid/orcid")
    monkeypatch.delenv("LOCUS_COOKIE_INSECURE", raising=False)
    monkeypatch.setattr(store, "DB", tmp_path / "omics.db")
    db = store.connect()
    store.upsert(db, [
        {"accession": a, "source": "GEO", "title": t, "summary": "", "organism": "Homo sapiens", "modality": "Expression profiling by high throughput sequencing",
         "samples": 4, "published": "2024-01-01", "papers": p, "url": ""}
        for a, t, p in [("GSE900101", "Ribosome profiling after Torin1", ["pmid:1001"]), ("GSE900103", "Polysomes in HEK293", ["pmid:1003"]),
                        ("GSE900199", "Name-only paper's dataset", ["pmid:2001"])]
    ])
    db.commit()
    db.close()
    fake = Upstream()
    monkeypatch.setattr(pace.httpx, "get", fake.get)
    monkeypatch.setattr(pace, "EUROPE_PMC", pace.Pace(10_000))
    monkeypatch.setattr(pace, "ORCID", pace.Pace(10_000))
    follows.clear_caches()
    follows.INFLIGHT.clear()
    users.AUTH_LIMIT.reset()
    yield fake
    # Fetches still running past a test's deadline would fill the next test's cache: let them land first.
    wait(list(follows.INFLIGHT.values()), timeout=5)
    follows.clear_caches()


def make_app() -> FastAPI:
    app = FastAPI()
    users.install(app)
    saved.install(app)
    watches.install(app)
    follows.install(app)
    return app


def signed_in(name="Gate") -> TestClient:
    c = TestClient(make_app(), base_url="https://testserver", client=LOCAL)
    assert c.post("/account/dev-login", json={"display_name": name}, headers=INTENT).status_code == 200
    return c


def call(c, method, path, body=None):
    return c.request(method, path, json=body if body is not None else {}, headers=INTENT)


# ---------------------------------------------------------------- who a name is


def test_one_orcid_for_most_tagged_papers_is_named_with_its_coverage(up):
    c = TestClient(make_app(), base_url="https://testserver", client=LOCAL)
    r = c.get("/person/identity", params={"name": "Carson C Thoreen"})
    assert r.status_code == 200
    got = r.json()
    assert got["status"] == "one" and got["orcid"] == THOREEN
    assert got["matched"] == 42 and got["linked"] == 5 and got["claimed"] == 5 and got["tagged"] == 5 and got["scanned"] == 6
    assert got["orcid_name"] == "Carson Thoreen"
    # The co-author's ORCID on the same papers (Watson) is not counted: there is none, and Thoreen's alone is.
    assert got["orcids"] == 1


def test_two_people_sharing_a_name_get_no_orcid(up):
    up.extra['AUTH:"Smith J"'] = (SMITH_NAME, 6)
    got = TestClient(make_app(), client=LOCAL).get("/person/identity", params={"name": "John Smith"}).json()
    assert got["status"] == "several" and got["reason"] == "shared" and "orcid" not in got
    assert got["orcids"] == 2 and got["tagged"] == 6


def test_a_coauthors_orcid_says_nothing_about_the_person(up):
    got = TestClient(make_app(), client=LOCAL).get("/person/identity", params={"name": "Xavier Nobody"}).json()
    assert got["status"] == "none" and "orcid" not in got


def test_identity_is_cached_and_reports_upstream_failure(up):
    c = TestClient(make_app(), client=LOCAL)
    c.get("/person/identity", params={"name": "Carson C Thoreen"})
    n = len(up.calls)
    assert c.get("/person/identity", params={"name": "Thoreen, Carson C."}).json()["orcid"] == THOREEN
    assert len(up.calls) == n
    up.fail.add("Smith")
    r = c.get("/person/identity", params={"name": "John Smith"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "UPSTREAM_FAILED"


# The reviewer's fixtures (F5-r1-1): names where the old guard named someone else's ORCID.
YANG, YU = SMITH_A, SMITH_B


def identity_of(up, name, query, results, hits, names=None):
    up.extra[f'AUTH:"{query}"'] = (results, hits)
    up.names.update(names or {})
    follows.clear_caches()
    return TestClient(make_app(), client=LOCAL).get("/person/identity", params={"name": name}).json()


def test_a_different_first_name_on_the_orcid_record_gets_no_follow(up):
    # 'Yu Zhang' searches 'Zhang Y'; Yang Zhang's ORCID tags 3 papers, Yu Zhang's 2, the rest none.
    results = ([paper(f"5{i}", "2024", [author("Zhang", "Y", YANG)]) for i in range(3)] + [paper(f"6{i}", "2023", [author("Zhang", "Y", YU)]) for i in range(2)]
               + [paper(f"7{i:02d}", "2022", [author("Zhang", "Y")]) for i in range(95)])
    got = identity_of(up, "Yu Zhang", "Zhang Y", results, 120, {YANG: ("Yang", "Zhang"), YU: ("Yu", "Zhang")})
    assert got["status"] != "one" and got["orcid"] == YANG
    assert got["status"] == "unconfirmed" and got["reason"] == "other_name" and got["orcid_name"] == "Yang Zhang"
    # Even with a majority of 3 of 5 tagged papers, the same fixture under a common name's hit count is "several".
    got = identity_of(up, "Yu Zhang", "Zhang Y", results, 48000)
    assert got["status"] == "several" and got["reason"] == "common"


def test_a_common_name_never_gets_follow(up):
    # 'Wei Wang': 48,000 hits, one tagged paper of the 100 scanned, and the ORCID record even agrees.
    results = [paper("801", "2024", [author("Wang", "W", YANG)])] + [paper(f"9{i:02d}", "2023", [author("Wang", "W")]) for i in range(99)]
    got = identity_of(up, "Wei Wang", "Wang W", results, 48000, {YANG: ("Wei", "Wang")})
    assert got["status"] == "several" and got["reason"] == "common" and "orcid" not in got
    assert got["matched"] == 48000 and got["tagged"] == 1
    # Not common, but one tagged paper is too little to say whose name this is.
    got = identity_of(up, "Wei Wang", "Wang W", results, 100)
    assert got["status"] == "unconfirmed" and got["reason"] == "few" and got["claimed"] == 1


def test_a_single_initial_does_not_stand_in_for_two(up):
    # Page 'Carson C Thoreen' (CC): a 'Thoreen C' with another ORCID tags 3 papers, Carson's (CC) tags 2.
    results = [paper(f"11{i}", "2024", [author("Thoreen", "C", YANG)]) for i in range(3)] + [paper(f"12{i}", "2023", [author("Thoreen", "CC", YU)]) for i in range(2)]
    got = identity_of(up, "Carson C Thoreen", "Thoreen CC", results, 42, {YANG: ("Chris", "Thoreen"), YU: ("Carson", "Thoreen")})
    assert got["status"] != "one"
    assert got.get("orcid") == YU and got["tagged"] == 2 and got["status"] == "unconfirmed" and got["reason"] == "few"


def test_names_agree():
    agree = follows.names_agree
    assert agree("Carson C Thoreen", "Carson", "Thoreen")  # the record leaves out the middle initial
    assert agree("Carson C Thoreen", "Carson C.", "Thoreen") and agree("Thoreen, Carson C.", "Carson", "thoreen")
    assert agree("José García", "Jose", "Garcia")  # accents and case aside
    assert not agree("Yu Zhang", "Yang", "Zhang")
    assert not agree("Carson C Thoreen", "Carson", "Thorne")
    assert agree("Thoreen CC", "C. C.", "Thoreen") and not agree("Thoreen CC", "C.", "Thoreen")  # "C" is not "CC"
    assert agree("Thoreen CC", "C. C. T.", "Thoreen")
    # F5-r2-1: the Europe PMC form against a record that spells the given name and leaves out the middle initial.
    assert agree("Thoreen CC", "Carson", "Thoreen") and agree("Thoreen CC", "Carson C", "Thoreen")
    assert not agree("Thoreen CC", "Carson J", "Thoreen") and not agree("Thoreen CC", "Kevin", "Thoreen")
    assert not agree("Thoreen C", "Carson C", "Thoreen")  # the record may lack initials the page has, never the reverse
    assert not agree("Carson C Thoreen", None, "Thoreen")
    assert follows.initials_agree("CC", "CCT") and not follows.initials_agree("C", "CC") and not follows.initials_agree("JS", "JP")


def test_an_unreadable_orcid_record_means_no_follow_and_is_kept_briefly(up, monkeypatch):
    up.fail.add("orcid")
    c = TestClient(make_app(), client=LOCAL)
    got = c.get("/person/identity", params={"name": "Carson C Thoreen"}).json()
    assert got["status"] == "unconfirmed" and got["reason"] == "no_record" and got["orcid"] == THOREEN
    up.fail.clear()
    n = len(up.calls)
    assert c.get("/person/identity", params={"name": "Carson C Thoreen"}).json()["status"] == "unconfirmed"
    assert len(up.calls) == n  # kept, but only for NO_RECORD_SECONDS (moments)
    assert follows.NO_RECORD_SECONDS <= 30
    t = time.monotonic()
    monkeypatch.setattr(pace.time, "monotonic", lambda: t + follows.NO_RECORD_SECONDS + 1)
    assert c.get("/person/identity", params={"name": "Carson C Thoreen"}).json()["status"] == "one"


# ---------------------------------------------------------------- bounded waits and limits


def test_a_flood_of_identity_calls_is_refused_not_queued(up):
    c = TestClient(make_app(), client=LOCAL)
    codes = [c.get("/person/identity", params={"name": f"Ann Person{i:03d}"}).status_code for i in range(follows.IDENTITY_LIMIT.per_ip + 5)]
    assert codes[: follows.IDENTITY_LIMIT.per_ip] == [200] * follows.IDENTITY_LIMIT.per_ip
    assert set(codes[follows.IDENTITY_LIMIT.per_ip:]) == {429}
    r = c.get("/person/identity", params={"name": "Ann Other"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED" and int(r.headers["Retry-After"]) > 0


def test_a_full_europe_pmc_queue_fails_fast_with_503(up, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(pace, "EUROPE_PMC", pace.Pace(5, clock=clock, sleep=clock.sleep))
    pace.EUROPE_PMC.next = clock.t + 30  # 30 s of backlog
    c = TestClient(make_app(), client=LOCAL)
    start = time.monotonic()
    r = c.get("/person/identity", params={"name": "Carson C Thoreen"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "BUSY" and r.headers["Retry-After"]
    assert time.monotonic() - start < 1 and clock.slept == [] and up.calls == []


def test_too_many_reads_at_once_are_refused(up, monkeypatch):
    monkeypatch.setattr(pace, "UPSTREAM", pace.Gate(1))
    with pace.UPSTREAM:
        r = TestClient(make_app(), client=LOCAL).get("/person/identity", params={"name": "Carson C Thoreen"})
    assert r.status_code == 503 and up.calls == []


def test_person_page_route_is_limited_and_cached(up, monkeypatch):
    from omics_agent import api

    c = TestClient(api.app, client=LOCAL)
    monkeypatch.setattr(follows.PERSON_LIMIT, "per_ip", 3)
    assert c.get("/person", params={"name": "Carson C Thoreen"}).json()["matched"] == 42
    n = len(up.calls)
    for _ in range(10):  # kept, and cached answers are not counted against the limit
        assert c.get("/person", params={"name": "Carson C Thoreen"}).status_code == 200 and len(up.calls) == n
    assert c.get("/person", params={"name": "Ann Person"}).status_code == 200
    assert c.get("/person", params={"name": "Bob Person"}).status_code == 200
    assert c.get("/person", params={"name": "Cid Person"}).status_code == 429  # the fourth uncached read
    assert c.get("/person", params={"name": "Carson C Thoreen"}).status_code == 200  # cached: still answered
    follows.clear_caches()
    pace.EUROPE_PMC.next = time.monotonic() + 30
    r = c.get("/person", params={"name": "Carson C Thoreen"})
    assert r.status_code == 503 and r.headers["Retry-After"]
    pace.EUROPE_PMC.reset()
    up.fail.add("Thoreen")
    assert c.get("/person", params={"name": "Carson C Thoreen"}).status_code == 502
    up.fail.clear()
    assert c.get("/person", params={"name": "Carson C Thoreen"}).status_code == 200  # the failure was not kept


# ---------------------------------------------------------------- follow, unfollow, seen


def test_follow_feed_uses_orcid_linked_papers_only_and_marks_new_until_seen(up):
    c = signed_in()
    assert call(c, "POST", "/follows/people", {"orcid": THOREEN, "display_name": "Carson Thoreen"}).status_code == 201
    assert call(c, "POST", "/follows/people", {"orcid": f"https://orcid.org/{THOREEN}", "display_name": "Carson Thoreen"}).status_code == 200
    assert [f["orcid"] for f in c.get("/follows/people").json()["follows"]] == [THOREEN]

    feed = c.get("/follows/people/updates").json()["people"]
    assert len(feed) == 1 and feed[0]["status"] == "ok" and feed[0]["linked"] == 5
    # Newest paper first (1001 is 2023, 1003 is 2021); the name-only paper's dataset never appears.
    assert [d["accession"] for d in feed[0]["datasets"]] == ["GSE900101", "GSE900103"]
    assert all(d["new"] for d in feed[0]["datasets"]) and feed[0]["new"] == 2
    assert feed[0]["datasets"][0]["paper"]["pmid"] == "1001"

    assert call(c, "POST", "/follows/people/seen", {"orcid": THOREEN, "accessions": ["GSE900101"]}).json()["seen"] == ["GSE900101"]
    feed = c.get("/follows/people/updates").json()["people"]
    assert {d["accession"]: d["new"] for d in feed[0]["datasets"]} == {"GSE900101": False, "GSE900103": True}

    assert call(c, "DELETE", "/follows/people", {"orcid": THOREEN}).json() == {"ok": True}
    assert c.get("/follows/people").json()["follows"] == []
    assert call(c, "DELETE", "/follows/people", {"orcid": THOREEN}).status_code == 404


def test_follow_validates_orcid_and_name_and_needs_session_and_intent(up):
    guest = TestClient(make_app(), base_url="https://testserver", client=LOCAL)
    assert guest.get("/follows/people").status_code == 401
    assert call(guest, "POST", "/follows/people", {"orcid": THOREEN, "display_name": "x"}).status_code == 401
    c = signed_in()
    r = c.post("/follows/people", json={"orcid": THOREEN, "display_name": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "INTENT_REQUIRED"
    assert call(c, "POST", "/follows/people", {"orcid": "0000-0003-1164-7225", "display_name": "x"}).status_code == 422  # bad check digit
    assert call(c, "POST", "/follows/people/seen", {"orcid": THOREEN, "accessions": ["not an accession"]}).status_code == 422


def test_one_account_cannot_see_or_change_anothers_follows(up):
    alice, bob = signed_in("Alice"), signed_in("Bob")
    assert call(alice, "POST", "/follows/people", {"orcid": THOREEN, "display_name": "Carson Thoreen"}).status_code == 201
    assert bob.get("/follows/people").json()["follows"] == []
    assert bob.get("/follows/people/updates").json()["people"] == []
    assert call(bob, "DELETE", "/follows/people", {"orcid": THOREEN}).status_code == 404
    assert call(bob, "POST", "/follows/people/seen", {"orcid": THOREEN, "accessions": ["GSE900101"]}).status_code == 404
    mine = alice.get("/follows/people").json()["follows"]
    assert [f["orcid"] for f in mine] == [THOREEN] and mine[0]["seen"] == []


def test_follow_keeps_the_orcid_records_name_not_the_clients(up):
    c = signed_in()
    up.names[SMITH_A] = ("Jane", "Smith")
    assert call(c, "POST", "/follows/people", {"orcid": SMITH_A, "display_name": "Carson Thoreen"}).json()["display_name"] == "Jane Smith"
    assert c.get("/follows/people").json()["follows"][0]["display_name"] == "Jane Smith"
    up.fail.add("orcid")
    r = call(c, "POST", "/follows/people", {"orcid": SMITH_B})
    assert r.status_code == 503 and r.json()["error"]["transient"] is True
    assert len(c.get("/follows/people").json()["follows"]) == 1


def test_follow_limit(up, monkeypatch):
    monkeypatch.setattr(follows, "MAX_FOLLOWS", 2)
    c = signed_in()
    for orcid in (SMITH_A, SMITH_B):
        assert call(c, "POST", "/follows/people", {"orcid": orcid, "display_name": "Smith"}).status_code == 201
    r = call(c, "POST", "/follows/people", {"orcid": THOREEN, "display_name": "Thoreen"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LIMIT_REACHED"


# ---------------------------------------------------------------- bounded fetch


def orcids(n):
    out, i = [], 0
    while len(out) < n:
        base = f"0000-0001-{6000 + i // 10:04d}-{i % 10:03d}"
        out += [base + ch for ch in "0123456789X" if follows.valid_orcid(base + ch)][:1]
        i += 1
    return out


def test_updates_read_at_most_40_follows_4_at_a_time_and_cache_them(up, monkeypatch):
    monkeypatch.setattr(follows.FOLLOW_LIMIT, "per_ip", 1000)  # following 45 at once is this test's setup, not a flood
    monkeypatch.setattr(follows, "MAX_FOLLOWS", 50)
    c = signed_in()
    many = orcids(41)
    for o in many:
        assert call(c, "POST", "/follows/people", {"orcid": o, "display_name": "Someone"}).status_code == 201
    up.delay = 0.02
    people = c.get("/follows/people/updates").json()["people"]
    statuses = [p["status"] for p in people]
    assert statuses.count("ok") == 40 and statuses[-1] == "not_checked" and people[-1]["orcid"] == many[0]  # oldest follow left out
    assert up.peak <= 4
    n = len(up.calls)
    c.get("/follows/people/updates")
    assert len(up.calls) == n  # all 40 answers kept for 6 hours


def test_updates_stop_at_the_deadline_and_report_failures(up, monkeypatch):
    c = signed_in()
    for o in (SMITH_A, SMITH_B):
        call(c, "POST", "/follows/people", {"orcid": o, "display_name": "Smith"})
    up.fail.add(SMITH_A)
    got = {p["orcid"]: p["status"] for p in c.get("/follows/people/updates").json()["people"]}
    assert got == {SMITH_A: "failed", SMITH_B: "ok"}
    # The failure is kept 5 minutes: the next fetch does not ask Europe PMC about SMITH_A again.
    follows.LAST_UPDATES.clear()
    up.fail.clear()
    n = len(up.calls)
    got = {p["orcid"]: p["status"] for p in c.get("/follows/people/updates").json()["people"]}
    assert got == {SMITH_A: "failed", SMITH_B: "ok"} and len(up.calls) == n

    follows.clear_caches()
    up.fail.clear()
    up.delay = 0.5
    monkeypatch.setattr(follows, "FETCH_SECONDS", 0.1)
    start = time.monotonic()
    got = {p["orcid"]: p["status"] for p in c.get("/follows/people/updates").json()["people"]}
    assert time.monotonic() - start < 0.45
    assert set(got.values()) == {"late"}


def test_updates_are_throttled_per_account_and_share_one_fetch_per_orcid(up):
    alice, bob = signed_in("Alice"), signed_in("Bob")
    for c in (alice, bob):
        assert call(c, "POST", "/follows/people", {"orcid": THOREEN}).status_code == 201
    up.delay = 0.3
    out: dict[str, list] = {}
    threads = [threading.Thread(target=lambda c=c, k=k: out.setdefault(k, c.get("/follows/people/updates").json()["people"])) for k, c in (("a", alice), ("b", bob))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert out["a"][0]["status"] == out["b"][0]["status"] == "ok"
    assert sum("AUTHORID" in x for x in up.calls) == 1  # one fetch for both accounts
    # A second call within UPDATES_EVERY answers from the cache only; a follow not yet read says "wait".
    up.calls.clear()
    assert call(alice, "POST", "/follows/people", {"orcid": SMITH_A}).status_code == 201
    got = {p["orcid"]: p["status"] for p in alice.get("/follows/people/updates").json()["people"]}
    assert got == {THOREEN: "ok", SMITH_A: "wait"} and not any("AUTHORID" in x for x in up.calls)


def test_updates_use_one_shared_pool(up):
    c = signed_in()
    call(c, "POST", "/follows/people", {"orcid": THOREEN})
    before = threading.active_count()
    for _ in range(3):
        follows.LAST_UPDATES.clear()
        follows.WORK.clear()
        c.get("/follows/people/updates")
    assert threading.active_count() <= before + follows.FETCH_WORKERS
    assert follows.POOL._max_workers == follows.FETCH_WORKERS


# ---------------------------------------------------------------- pacing


class FakeClock:
    def __init__(self):
        self.t = 100.0
        self.slept: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 6))
        self.t += s


def test_pace_spaces_calls_one_slot_per_period():
    clock = FakeClock()
    p = pace.Pace(5, clock=clock, sleep=clock.sleep)
    for _ in range(4):
        p.wait()
    assert clock.slept == [0.2, 0.2, 0.2]
    clock.t += 5  # idle time is not banked as a burst
    p.wait()
    p.wait()
    assert clock.slept[-1] == 0.2 and len(clock.slept) == 4


def test_pace_refuses_a_slot_after_the_deadline():
    clock = FakeClock()
    p = pace.Pace(2, clock=clock, sleep=clock.sleep)
    p.wait()
    with pytest.raises(pace.PaceTimeout):
        p.wait(deadline=clock.t + 0.1)  # next slot is 0.5 s away
    p.wait(deadline=clock.t + 0.6)
    assert clock.slept == [0.5]


def test_pace_never_queues_past_max_wait():
    clock = FakeClock()
    p = pace.Pace(5, clock=clock, sleep=clock.sleep)
    p.next = clock.t + pace.MAX_WAIT + 0.1
    with pytest.raises(pace.PaceTimeout):
        p.wait()
    with pytest.raises(pace.PaceTimeout):
        p.wait(deadline=clock.t + 60)  # a later deadline does not lift the cap
    assert clock.slept == [] and isinstance(pace.PaceTimeout("x"), httpx.HTTPError)


def test_pace_is_shared_across_threads():
    p = pace.Pace(50)
    stamps: list[float] = []
    lock = threading.Lock()

    def go():
        p.wait()
        with lock:
            stamps.append(time.monotonic())

    threads = [threading.Thread(target=go) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    assert stamps[-1] - stamps[0] >= 5 * 0.02 - 0.005


def test_every_europe_pmc_and_orcid_call_is_paced(up, monkeypatch):
    taken: list[str] = []

    class Counting(pace.Pace):
        def __init__(self, name):
            super().__init__(10_000)
            self.name = name

        def wait(self, deadline=None, max_wait=None):
            taken.append(self.name)
            super().wait(deadline, max_wait)

    monkeypatch.setattr(pace, "EUROPE_PMC", Counting("epmc"))
    monkeypatch.setattr(pace, "ORCID", Counting("orcid"))
    TestClient(make_app(), client=LOCAL).get("/person/identity", params={"name": "Carson C Thoreen"})
    assert taken.count("epmc") == 2 and taken.count("orcid") == 1 and len(up.calls) == 3


# ---------------------------------------------------------------- fix round 2


def test_the_europe_pmc_form_from_a_paper_page_finds_the_orcid(up):
    # F5-r2-1: paper pages link 'Thoreen CC'; the ORCID record says 'Carson Thoreen' (no middle initial).
    c = TestClient(make_app(), client=LOCAL)
    got = c.get("/person/identity", params={"name": "Thoreen CC"}).json()
    assert got["status"] == "one" and got["orcid"] == THOREEN and got["claimed"] == 5 and got["orcid_name"] == "Carson Thoreen"
    # A record with another middle initial is someone else.
    up.names[THOREEN] = ("Carson J", "Thoreen")
    follows.clear_caches()
    got = c.get("/person/identity", params={"name": "Thoreen CC"}).json()
    assert got["status"] == "unconfirmed" and got["reason"] == "other_name"
    # A record whose first initial differs is someone else too.
    up.names[THOREEN] = ("Kevin", "Thoreen")
    follows.clear_caches()
    assert c.get("/person/identity", params={"name": "Thoreen CC"}).json()["reason"] == "other_name"


def test_the_europe_pmc_form_keeps_the_round_one_refusals(up):
    # 'Thoreen CC' page: a 'Thoreen C' with another ORCID tags 3 papers and even calls itself Carson; Carson CC's tags 2.
    results = [paper(f"11{i}", "2024", [author("Thoreen", "C", YANG)]) for i in range(3)] + [paper(f"12{i}", "2023", [author("Thoreen", "CC", YU)]) for i in range(2)]
    got = identity_of(up, "Thoreen CC", "Thoreen CC", results, 42, {YANG: ("Carson", "Thoreen"), YU: ("Carson", "Thoreen")})
    assert got["status"] == "unconfirmed" and got["reason"] == "few" and got["orcid"] == YU and got["tagged"] == 2
    # 'Zhang Y' with Yang's ORCID on 3 of 5 tagged papers is not common here, and Yang's record spells Yang: the page
    # in Europe PMC's form cannot tell Yu from Yang, so the majority and the 3-paper floor decide; with 120 hits a
    # two-way split under the floor stays unconfirmed.
    results = [paper(f"5{i}", "2024", [author("Zhang", "Y", YANG)]) for i in range(2)] + [paper(f"6{i}", "2023", [author("Zhang", "Y", YU)]) for i in range(2)]
    got = identity_of(up, "Zhang Y", "Zhang Y", results, 120, {YANG: ("Yang", "Zhang"), YU: ("Yu", "Zhang")})
    assert got["status"] == "several" and got["reason"] == "shared"
    results = [paper("801", "2024", [author("Wang", "W", YANG)])] + [paper(f"9{i:02d}", "2023", [author("Wang", "W")]) for i in range(99)]
    got = identity_of(up, "Wang W", "Wang W", results, 48000, {YANG: ("Wei", "Wang")})
    assert got["status"] == "several" and got["reason"] == "common"


def test_following_remembers_the_page_it_was_made_from(up):
    # F5-r2-2: /following links back to the page's name, not the ORCID record's.
    c = signed_in()
    assert call(c, "POST", "/follows/people", {"orcid": THOREEN, "page_name": "Thoreen  CC"}).status_code == 201
    got = c.get("/follows/people").json()["follows"][0]
    assert got["page_name"] == "Thoreen CC" and got["display_name"] == "Carson Thoreen"
    assert c.get("/follows/people/updates").json()["people"][0]["page_name"] == "Thoreen CC"
    assert call(c, "POST", "/follows/people", {"orcid": SMITH_A, "page_name": "x"}).status_code == 201  # not a name: dropped
    assert {f["orcid"]: f["page_name"] for f in c.get("/follows/people").json()["follows"]}[SMITH_A] is None
    assert call(c, "POST", "/follows/people", {"orcid": SMITH_B, "page_name": "y" * 121}).status_code == 422


def test_a_follow_flood_cannot_switch_off_identity(up, monkeypatch):
    # F5-r2-3: one account posting many ORCIDs is limited per account, and the limit and duplicate checks read nothing.
    c = signed_in()
    ids = orcids(follows.FOLLOW_LIMIT.per_ip + 5)
    codes = [call(c, "POST", "/follows/people", {"orcid": o}).status_code for o in ids]
    assert codes[: follows.FOLLOW_LIMIT.per_ip] == [201] * follows.FOLLOW_LIMIT.per_ip and set(codes[follows.FOLLOW_LIMIT.per_ip:]) == {429}
    n = len(up.calls)
    assert call(c, "POST", "/follows/people", {"orcid": ids[0]}).status_code == 200 and len(up.calls) == n  # duplicate: no read
    monkeypatch.setattr(follows, "MAX_FOLLOWS", 2)
    follows.FOLLOW_LIMIT.reset()
    r = call(c, "POST", "/follows/people", {"orcid": THOREEN})
    assert r.status_code == 409 and len(up.calls) == n  # full: no read
    # Another reader's identity still answers.
    assert TestClient(make_app(), client=LOCAL).get("/person/identity", params={"name": "Carson C Thoreen"}).json()["status"] == "one"


def test_a_busy_orcid_pace_is_busy_and_never_kept(up, monkeypatch):
    # F5-r2-3: when locus's own ORCID pace is full, identity answers 503 BUSY and keeps nothing for other readers.
    clock = FakeClock()
    monkeypatch.setattr(pace, "ORCID", pace.Pace(2, clock=clock, sleep=clock.sleep))
    pace.ORCID.next = clock.t + 30
    c = TestClient(make_app(), client=LOCAL)
    r = c.get("/person/identity", params={"name": "Carson C Thoreen"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "BUSY"
    signed = signed_in()
    r = call(signed, "POST", "/follows/people", {"orcid": SMITH_A})
    assert r.status_code == 503 and r.json()["error"]["code"] == "BUSY"
    pace.ORCID.reset()
    clock.t += 31
    assert c.get("/person/identity", params={"name": "Carson C Thoreen"}).json()["status"] == "one"


def test_an_orcid_that_does_not_exist_is_refused_and_kept_briefly(up):
    up.missing.add(SMITH_A)
    c = signed_in()
    r = call(c, "POST", "/follows/people", {"orcid": SMITH_A})
    assert r.status_code == 404 and r.json()["error"]["code"] == "ORCID_NOT_FOUND"
    n = len(up.calls)
    assert call(c, "POST", "/follows/people", {"orcid": SMITH_A}).status_code == 404 and len(up.calls) == n


def test_cached_identity_answers_cost_no_limit_and_ipv6_counts_by_64(up):
    # F5-r2-4: 260 cached hits from distinct addresses leave the limit untouched.
    c = TestClient(make_app(), client=LOCAL)
    for i in range(260):
        r = c.get("/person/identity", params={"name": "Carson C Thoreen"}, headers={"X-Forwarded-For": f"2001:db8:{i:x}::1"})
        assert r.status_code == 200
    # Uncached reads from one /64 share one bucket however the last 64 bits vary.
    follows.clear_caches()
    per = follows.IDENTITY_LIMIT.per_ip
    codes = [c.get("/person/identity", params={"name": f"Ann Person{i:03d}"}, headers={"X-Forwarded-For": f"2001:db8:1:2::{i:x}"}).status_code
             for i in range(per + 2)]
    assert codes[:per] == [200] * per and set(codes[per:]) == {429}
    assert c.get("/person/identity", params={"name": "Ann Other"}, headers={"X-Forwarded-For": "2001:db8:1:3::1"}).status_code == 200
    assert users.limit_key("203.0.113.7") == "203.0.113.7" and users.limit_key("::ffff:203.0.113.7") == "203.0.113.7"
    assert users.limit_key("2001:db8:1:2:aaaa::1") == "2001:db8:1:2::/64" and users.limit_key("account:7") == "account:7"


def test_updates_calls_at_once_are_capped_with_a_fast_503(up, monkeypatch):
    # F5-r2-8
    c = signed_in()
    call(c, "POST", "/follows/people", {"orcid": THOREEN})
    monkeypatch.setattr(follows, "UPDATES_GATE", pace.Gate(1))
    with follows.UPDATES_GATE:
        start = time.monotonic()
        r = c.get("/follows/people/updates")
        assert r.status_code == 503 and r.json()["error"]["code"] == "BUSY" and time.monotonic() - start < 1
    assert c.get("/follows/people/updates").json()["people"][0]["status"] == "ok"  # the refused call did not throttle
    follows.LAST_UPDATES[-1] = time.monotonic() - 2 * follows.UPDATES_EVERY
    follows.LAST_UPDATES.pop(next(k for k in follows.LAST_UPDATES if k != -1))
    c.get("/follows/people/updates")
    assert -1 not in follows.LAST_UPDATES  # old entries are pruned


def test_busy_is_not_mistaken_for_a_failure_on_paper_routes(up, monkeypatch):
    # F5-r2-5: /cite says busy, and a busy moment never keeps empty supplementary sizes.
    from omics_agent import api, paper

    pace.EUROPE_PMC.next = time.monotonic() + 30
    r = TestClient(api.app, client=LOCAL).get("/cite", params={"q": "Thoreen 2012 Nature mTOR"})
    assert r.status_code == 503 and r.headers["Retry-After"]
    pace.EUROPE_PMC.reset()
    paper._zip_sizes.cache_clear()
    answers = iter([pace.PaceTimeout("busy"), {"a.xlsx": 10}])

    def sizes(read, tail=0):
        got = next(answers)
        if isinstance(got, Exception):
            raise got
        return got

    monkeypatch.setattr(paper, "directory_sizes", sizes)
    with pytest.raises(pace.PaceTimeout):
        paper._zip_sizes("PMC1")
    assert paper._zip_sizes("PMC1") == {"a.xlsx": 10}
    paper._zip_sizes.cache_clear()
