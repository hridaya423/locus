"""App-wide pacing for the public services locus reads on a reader's behalf: Europe PMC (at most 5 requests a second)
and the ORCID public API (at most 2 a second). Every call to them in this process takes the next free slot of one
shared clock per service, so a busy page or a /following fetch cannot burst past what the service asks of clients.

No caller queues for long: a slot more than MAX_WAIT seconds away is refused at once with PaceTimeout (a transient
error the routes answer with 503 and Retry-After), so a flood of requests cannot build a backlog that every other
reader then waits behind, nor park the server's threads in sleep. UPSTREAM caps how many requests at a time may be
reading a person or an identity from upstream at all, for the same reason.

The idea (one slot per period for each upstream, shared by the whole app) comes from papertok's
worker/upstream-pace.ts; this is a fresh Python version, not a copy. Where papertok refuses at once with Retry-After,
locus waits up to MAX_WAIT (2 s) for its slot, or less when the caller's deadline is sooner, and refuses past that.

The base URLs come from the environment (LOCUS_EPMC_BASE, LOCUS_ORCID_BASE) so page checks can point the API at a
local fixture server; unset, they are the real services.
"""

import os
import threading
import time

import httpx

EPMC_DEFAULT = "https://www.ebi.ac.uk/europepmc/webservices/rest"
ORCID_DEFAULT = "https://pub.orcid.org/v3.0"


MAX_WAIT = 2.0
RETRY_AFTER = 5


class PaceTimeout(httpx.HTTPError):
    """The next free slot is further away than the caller may wait, or too many reads are under way. A subclass of
    httpx.HTTPError, so every caller that already handles an upstream failure handles this too."""


class Gate:
    """At most `size` callers inside at once; one more is refused at once (PaceTimeout) rather than queued."""

    def __init__(self, size: int):
        self.size = size
        self.sem = threading.BoundedSemaphore(size)

    def __enter__(self):
        if not self.sem.acquire(blocking=False):
            raise PaceTimeout("too many upstream reads under way")
        return self

    def __exit__(self, *_):
        self.sem.release()


class Pace:
    """One request slot every 1/per_second seconds, shared by every thread of the process."""

    def __init__(self, per_second: float, clock=time.monotonic, sleep=time.sleep):
        self.period = 1.0 / per_second
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        self.next = 0.0

    def reset(self) -> None:
        with self.lock:
            self.next = 0.0

    def wait(self, deadline: float | None = None, max_wait: float | None = None) -> None:
        """Takes the next free slot and sleeps until it comes. Raises PaceTimeout (taking nothing) when that slot lies
        after `deadline` (a time on this pace's clock) or more than `max_wait` (default MAX_WAIT) seconds away."""
        with self.lock:
            t = self.clock()
            slot = max(t, self.next)
            limit = t + (MAX_WAIT if max_wait is None else max_wait)
            if deadline is not None:
                limit = min(limit, deadline)
            if slot > limit:
                raise PaceTimeout(f"no slot before the deadline ({slot - t:.1f} s away)")
            self.next = slot + self.period
        if slot > t:
            self.sleep(slot - t)


EUROPE_PMC = Pace(5)
ORCID = Pace(2)
# Uncached person and identity reads under way at once, app-wide (the sync threadpool has about 40 threads).
UPSTREAM = Gate(8)


class TtlCache:
    """Answers kept per key for a time given at put() (so failures can be kept briefly and answers for hours)."""

    def __init__(self, seconds: float, size: int = 2000):
        self.seconds, self.size = seconds, size
        self.lock = threading.Lock()
        self.items: dict = {}

    def get(self, key):
        with self.lock:
            hit = self.items.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            return None

    def put(self, key, value, seconds: float | None = None) -> None:
        with self.lock:
            self.items.pop(key, None)
            if len(self.items) >= self.size:
                self.items.pop(next(iter(self.items)))
            self.items[key] = (time.monotonic() + (self.seconds if seconds is None else seconds), value)

    def clear(self) -> None:
        with self.lock:
            self.items.clear()


def epmc_base() -> str:
    return os.environ.get("LOCUS_EPMC_BASE", EPMC_DEFAULT).rstrip("/")


def orcid_base() -> str:
    return os.environ.get("LOCUS_ORCID_BASE", ORCID_DEFAULT).rstrip("/")


def _timeout(timeout: float, deadline: float | None) -> float:
    if deadline is None:
        return timeout
    left = deadline - time.monotonic()
    if left <= 0:
        raise PaceTimeout("the deadline has passed")
    return min(timeout, left)


def epmc_get(path: str, params: dict, timeout: float = 30, deadline: float | None = None) -> dict:
    """GET a Europe PMC REST path (e.g. "/search") as JSON, in its pacing slot. httpx errors pass through."""
    EUROPE_PMC.wait(deadline)
    return httpx.get(f"{epmc_base()}{path}", params=params, timeout=_timeout(timeout, deadline)).raise_for_status().json()


def orcid_get(path: str, timeout: float = 15, deadline: float | None = None) -> dict:
    """GET an ORCID public API path (e.g. "/0000-0003-1164-7224/person") as JSON, in its pacing slot."""
    ORCID.wait(deadline)
    return httpx.get(f"{orcid_base()}{path}", headers={"Accept": "application/json"}, timeout=_timeout(timeout, deadline)).raise_for_status().json()
