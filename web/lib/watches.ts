// Watched searches. A watch remembers a question, the day watching started and the datasets the search has shown so
// far; when the search runs again, results outside that set are marked new and then added to it. Signed in, watches
// live in the account (/api/follows/questions); a guest's live in this browser (localStorage `locus:watched`) with
// the same shape. One shared store serves the home page, the results and the import panel.
import { useEffect, useSyncExternalStore } from "react";
import { API } from "@/lib/api";
import { ACCOUNT_EVENT, AccountError, me } from "@/lib/account";
import { ACCESSION } from "@/lib/lists";

export type Watch = { question: string; since: string; seen: string[] };
export type WatchImportResult = { added: string[]; already: string[]; left_out: string[]; held: string[]; skipped: number };

export const WATCH_LIMITS = { watches: 200, question: 500, seen: 500 };

// The key a watch is kept under: the question trimmed, as the API keeps it (watches.py _question). Every lookup and
// every write uses it, so "polysome profiling " typed with a trailing space finds the same watch.
export const watchKey = (question: string) => question.trim();
export const findWatch = (all: Watch[], question: string) => all.find((w) => watchKey(w.question) === watchKey(question)) ?? null;
export const TOO_LONG = `Questions over ${WATCH_LIMITS.question} characters cannot be watched.`;

// ---------------------------------------------------------------- this browser (guests)

export const WATCHED = "locus:watched";
const today = () => new Date().toISOString().slice(0, 10);

export function guestWatches(): Watch[] {
  try {
    const all = JSON.parse(localStorage.getItem(WATCHED) ?? "[]");
    return Array.isArray(all) ? all.filter((w) => w && typeof w.question === "string" && Array.isArray(w.seen)) : [];
  } catch {
    return [];
  }
}

function writeGuest(all: Watch[]) {
  localStorage.setItem(WATCHED, JSON.stringify(all));
}

// Everything shown so far, oldest first, keeping the newest 500 (the API's rule).
const mergeSeen = (old: string[], next: string[]) => [...old, ...next.filter((a) => !old.includes(a))].slice(-WATCH_LIMITS.seen);

// ---------------------------------------------------------------- API

async function call<T>(method: "GET" | "POST" | "DELETE", path: string, body?: unknown): Promise<T> {
  const init: RequestInit = method === "GET"
    ? { credentials: "same-origin", cache: "no-store" }
    : { method, credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Locus-Intent": "1" }, body: JSON.stringify(body ?? {}) };
  const res = await fetch(`${API}/follows/questions${path}`, init);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error;
    throw new AccountError(e?.code ?? `HTTP_${res.status}`, e?.message ?? `locus answered ${res.status}. Please try again.`, e?.transient ?? res.status >= 500);
  }
  return data as T;
}

// ---------------------------------------------------------------- the shared store

// "guest" also covers a browser whose session check failed: its own watches still show and Watch still works there,
// and the next mount asks again. "failed" means only that a signed-in account's watches could not be read.
export type Watches = { status: "loading" | "guest" | "signed-in" | "failed"; watches: Watch[] };

const INITIAL: Watches = { status: "loading", watches: [] };
let state: Watches = INITIAL;
const subscribers = new Set<() => void>();
let inflight: Promise<void> | null = null;
let stale = true;

function set(next: Watches) {
  state = next;
  subscribers.forEach((fn) => fn());
}

export function reloadWatches(): Promise<void> {
  if (inflight) return inflight;
  stale = false;
  inflight = (async () => {
    try {
      let who;
      try {
        who = await me();
      } catch {
        // Who is signed in is unknown: keep serving this browser's watches and ask again on the next mount.
        set({ status: "guest", watches: guestWatches() });
        stale = true;
        return;
      }
      if (!who.user) {
        set({ status: "guest", watches: guestWatches() });
        return;
      }
      const all = await call<{ watches: Watch[] }>("GET", "");
      set({ status: "signed-in", watches: all.watches.map(({ question, since, seen }) => ({ question, since, seen })) });
    } catch {
      set({ status: "failed", watches: [] });
      stale = true;
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

function onAccount() {
  stale = true;
  reloadWatches();
}

function subscribe(fn: () => void) {
  if (subscribers.size === 0) window.addEventListener(ACCOUNT_EVENT, onAccount);
  subscribers.add(fn);
  return () => {
    subscribers.delete(fn);
    if (subscribers.size === 0) {
      window.removeEventListener(ACCOUNT_EVENT, onAccount);
      stale = true;
    }
  };
}

export function useWatches(): Watches {
  const value = useSyncExternalStore(subscribe, () => state, () => INITIAL);
  useEffect(() => {
    if (stale) reloadWatches();
  }, []);
  return value;
}

// The store once it knows who is signed in.
async function ready(): Promise<Watches> {
  if (stale || state.status === "loading" || inflight) await reloadWatches();
  return state;
}

// Starts watching a question (accessions: what the search shows now), or stops when accessions is null.
export async function setWatch(raw: string, accessions: string[] | null): Promise<void> {
  const question = watchKey(raw);
  if (accessions && question.length > WATCH_LIMITS.question) throw new AccountError("TOO_LONG", TOO_LONG, false);
  const s = await ready();
  if (s.status === "signed-in") {
    if (accessions) await call("POST", "", { question, seen: accessions.slice(-WATCH_LIMITS.seen) });
    else await call("DELETE", "", { question });
    await reloadWatches();
    return;
  }
  if (s.status !== "guest") throw new AccountError("UNAVAILABLE", "locus could not reach your watched searches. Please try again.", true);
  const rest = guestWatches().filter((w) => watchKey(w.question) !== question);
  writeGuest(accessions ? [{ question, since: today(), seen: accessions.slice(-WATCH_LIMITS.seen) }, ...rest] : rest);
  set({ status: "guest", watches: guestWatches() });
}

// A new run of a search: if it is watched, tells `show` which results are new since the last run (before anything
// changes, so the page marks them without a flicker), then records them as seen for the next run.
export async function markSeen(raw: string, accessions: string[], show: (n: { since: string; fresh: string[] }) => void): Promise<void> {
  const question = watchKey(raw);
  const s = await ready();
  const watch = findWatch(s.watches, question);
  if (!watch) return;
  const fresh = accessions.filter((a) => !watch.seen.includes(a));
  if (fresh.length === 0) return;
  show({ since: watch.since, fresh });
  try {
    if (s.status === "signed-in") {
      await call("POST", "", { question, seen: accessions.slice(-WATCH_LIMITS.seen) });
      await reloadWatches();
    } else {
      writeGuest(guestWatches().map((w) => (watchKey(w.question) === question ? { ...w, seen: mergeSeen(w.seen, accessions) } : w)));
      set({ status: "guest", watches: guestWatches() });
    }
  } catch {
    // The marks still show; the next run marks the same datasets again.
  }
}

// ---------------------------------------------------------------- bringing a guest's watches into the account (F4)

// Only what the API accepts: a question of at most 500 characters, a real past day, accessions it can keep.
function importable(w: Watch): Watch | null {
  const question = watchKey(w.question);
  if (!question || question.length > WATCH_LIMITS.question) return null;
  const real = typeof w.since === "string" && /^\d{4}-\d{2}-\d{2}$/.test(w.since) && !Number.isNaN(Date.parse(w.since)) && new Date(w.since).toISOString().slice(0, 10) === w.since;
  const day = real && w.since <= today() ? w.since : today();
  const seen = [...new Set(w.seen.filter((a): a is string => typeof a === "string").map((a) => a.trim()).filter((a) => ACCESSION.test(a)))].slice(-WATCH_LIMITS.seen);
  return { question, since: day, seen };
}

// Sends this browser's watches to the account in one request. Local copies are removed only for the questions the
// server says it now watches; anything it could not take (or could not read: `skipped`) stays in this browser.
export async function importGuestWatches(): Promise<WatchImportResult> {
  const local = guestWatches();
  const batch = local.map(importable).filter((w): w is Watch => w !== null).slice(0, WATCH_LIMITS.watches);
  const done = await call<Omit<WatchImportResult, "skipped">>("POST", "/import", { watches: batch });
  const held = new Set(done.held);
  writeGuest(guestWatches().filter((w) => !held.has(watchKey(w.question))));
  stale = true;
  await reloadWatches();
  return { ...done, skipped: local.length - batch.length };
}
