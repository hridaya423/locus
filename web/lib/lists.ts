// Saved datasets and lists. Signed in, they live in the account (/api/lists/*); a guest's "Saved" lives in this browser
// (localStorage `locus:saved`) with the same item shape. One shared store tells every save control on a page what is
// saved, from a single request, and updates them all when anything changes.
import { useEffect, useSyncExternalStore } from "react";
import { API, type DatasetRecord, type Hit } from "@/lib/api";
import { ACCOUNT_EVENT, AccountError, me } from "@/lib/account";

// What the page showed when the dataset was saved, so a list renders without asking a repository again.
export type Snapshot = { title: string; source: string; organism: string; modality: string; samples: number | null };
export type Item = { accession: string; added_at: string; note: string; tags: string[]; snapshot: Snapshot };
// Set while the list is public (F6). stale: the list changed after its public page was last updated.
export type PublicState = { share_id: string; published_at: string; show_owner: boolean; include_notes: boolean; stale: boolean };
export type ListSummary = { id: number; name: string; description: string; builtin: boolean; count: number; created_at: string; updated_at: string; public: PublicState | null };
export type Limits = { public_items?: number; lists: number; items: number; name: number; description: number; note: number; tags: number; tag: number };
export type ListDetail = { list: ListSummary; items: Item[]; limits: Limits };

export const LIMITS: Limits = { lists: 100, items: 500, name: 120, description: 600, note: 10_000, tags: 12, tag: 40 };

// ---------------------------------------------------------------- snapshots from what the page already has

const organisms = (text: string) => text.split(";").map((s) => s.trim()).filter(Boolean).join(", ");

export function hitSnapshot(hit: Hit, dataType: string): Snapshot {
  return { title: hit.title, source: hit.source, organism: organisms(hit.organism ?? ""), modality: dataType, samples: hit.samples ?? null };
}

export function recordSnapshot(rec: DatasetRecord | null, hit: Hit | undefined, fields: { organism: string[]; dataType: string; samples: number | null | undefined }): Snapshot | null {
  const title = rec?.title ?? hit?.title;
  const source = rec?.source ?? hit?.source;
  if (!title || !source) return null;
  return { title, source, organism: fields.organism.join(", "), modality: fields.dataType, samples: fields.samples ?? null };
}

// ---------------------------------------------------------------- API

async function call<T>(method: "GET" | "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  const init: RequestInit = method === "GET"
    ? { credentials: "same-origin", cache: "no-store" }
    : { method, credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Locus-Intent": "1" }, body: JSON.stringify(body ?? {}) };
  const res = await fetch(`${API}${path}`, init);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error;
    throw new AccountError(e?.code ?? `HTTP_${res.status}`, e?.message ?? `locus answered ${res.status}. Please try again.`, e?.transient ?? res.status >= 500);
  }
  return data as T;
}

type Ref = number | "saved";
export const getLists = () => call<{ lists: ListSummary[]; holds: Record<string, number[]>; limits: Limits }>("GET", "/lists");
export const getList = (id: number) => call<ListDetail>("GET", `/lists/${id}`);
export const createList = (name: string, description = "") => call<{ list: ListSummary }>("POST", "/lists", { name, description });
export const editList = (id: number, patch: { name?: string; description?: string }) => call<{ list: ListSummary }>("PATCH", `/lists/${id}`, patch);
export const deleteList = (id: number) => call<{ ok: boolean }>("DELETE", `/lists/${id}`);
export const editItem = (ref: Ref, accession: string, patch: { note?: string; tags?: string[] }) =>
  call<{ item: Item }>("PATCH", `/lists/${ref}/items/${encodeURIComponent(accession)}`, patch);
export const publishList = (id: number, choices: { show_owner: boolean; include_notes: boolean }) => call<{ list: ListSummary }>("POST", `/lists/${id}/publish`, choices);
export const unpublishList = (id: number) => call<{ list: ListSummary }>("DELETE", `/lists/${id}/publish`);
export const shareUrl = (shareId: string) => `${window.location.origin}/s/${shareId}`;
export const exportHref = (id: number, format: "accessions" | "csv") => `${API}/lists/${id}/export?format=${format}`;

// ---------------------------------------------------------------- guest storage

export const GUEST = "locus:saved";

export function guestItems(): Item[] {
  try {
    const items = JSON.parse(localStorage.getItem(GUEST) ?? "[]");
    return Array.isArray(items) ? items.filter((i) => i && typeof i.accession === "string") : [];
  } catch {
    return [];
  }
}

function writeGuest(items: Item[]) {
  localStorage.setItem(GUEST, JSON.stringify(items.slice(0, LIMITS.items)));
}

// ---------------------------------------------------------------- the shared store

export type Saved = {
  status: "loading" | "guest" | "signed-in" | "failed";
  lists: ListSummary[];
  holds: Record<string, number[]>; // accession -> ids of the lists that hold it (signed in)
  guest: Item[];
};

const INITIAL: Saved = { status: "loading", lists: [], holds: {}, guest: [] };
let state: Saved = INITIAL;
const subscribers = new Set<() => void>();
let inflight: Promise<void> | null = null;
let stale = true;

function set(next: Saved) {
  state = next;
  subscribers.forEach((fn) => fn());
}

export const LISTS_EVENT = "locus:lists";

// Re-reads the lists (deduplicated: many controls on one page share one request).
export function reload(): Promise<void> {
  if (inflight) return inflight;
  stale = false;
  inflight = (async () => {
    try {
      const who = await me();
      if (!who.user) {
        set({ status: "guest", lists: [], holds: {}, guest: guestItems() });
        return;
      }
      const all = await getLists();
      set({ status: "signed-in", lists: all.lists, holds: all.holds, guest: [] });
    } catch {
      set({ ...state, status: "failed" });
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

function onAccount() {
  stale = true;
  reload();
}

function subscribe(fn: () => void) {
  if (subscribers.size === 0) window.addEventListener(ACCOUNT_EVENT, onAccount);
  subscribers.add(fn);
  return () => {
    subscribers.delete(fn);
    if (subscribers.size === 0) {
      window.removeEventListener(ACCOUNT_EVENT, onAccount);
      stale = true; // the next page asks again, since lists may have changed elsewhere
    }
  };
}

export function useSaved(): Saved {
  const value = useSyncExternalStore(subscribe, () => state, () => INITIAL);
  useEffect(() => {
    if (stale) reload();
  }, []);
  return value;
}

export const savedList = (s: Saved) => s.lists.find((l) => l.builtin) ?? null;

export function isSaved(s: Saved, accession: string): boolean {
  if (s.status === "guest") return s.guest.some((i) => i.accession === accession);
  const saved = savedList(s);
  return !!saved && (s.holds[accession] ?? []).includes(saved.id);
}

// Adds a dataset to a list ("saved" is the built-in one); for a guest, to this browser's Saved.
export async function addTo(ref: Ref, accession: string, snapshot: Snapshot): Promise<void> {
  if (state.status === "guest") {
    const items = guestItems();
    if (!items.some((i) => i.accession === accession)) {
      if (items.length >= LIMITS.items) throw new AccountError("LIMIT_REACHED", `This browser keeps at most ${LIMITS.items} saved datasets.`);
      writeGuest([...items, { accession, added_at: new Date().toISOString().replace(/\.\d+Z$/, "Z"), note: "", tags: [], snapshot }]);
    }
    set({ ...state, guest: guestItems() });
    return;
  }
  const done = await call<{ list_id: number }>("POST", `/lists/${ref}/items`, { accession, snapshot });
  const held = state.holds[accession] ?? [];
  set({ ...state, holds: { ...state.holds, [accession]: held.includes(done.list_id) ? held : [...held, done.list_id] } });
  await reload();
}

export async function removeFrom(ref: Ref, accession: string): Promise<void> {
  if (state.status === "guest") {
    writeGuest(guestItems().filter((i) => i.accession !== accession));
    set({ ...state, guest: guestItems() });
    return;
  }
  const done = await call<{ list_id: number }>("DELETE", `/lists/${ref}/items/${encodeURIComponent(accession)}`);
  set({ ...state, holds: { ...state.holds, [accession]: (state.holds[accession] ?? []).filter((id) => id !== done.list_id) } });
  await reload();
}

export async function newList(name: string): Promise<ListSummary> {
  const done = await createList(name);
  await reload();
  return done.list;
}

// ---------------------------------------------------------------- bringing guest saves into the account (F3)

export type ImportResult = { list_id: number; added: string[]; already: string[]; left_out: string[]; held: string[]; skipped: number };

// The API's accession rule (saved.py ACCESSION); an entry outside it would refuse the whole batch, so it is not sent.
export const ACCESSION = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$/;

const text = (v: unknown, max: number) => (typeof v === "string" ? v.slice(0, max) : "");

// Only the fields the API keeps, trimmed to its limits, so one odd entry in localStorage cannot refuse the whole batch.
function importable(i: Item) {
  const s = (i.snapshot ?? {}) as Partial<Snapshot>;
  const samples = typeof s.samples === "number" && Number.isInteger(s.samples) && s.samples >= 0 ? s.samples : null;
  const tags = Array.isArray(i.tags) ? [...new Set(i.tags.map((t) => text(t, LIMITS.tag).trim()).filter(Boolean))].slice(0, LIMITS.tags) : [];
  return {
    accession: i.accession.trim(),
    note: text(i.note, LIMITS.note),
    tags,
    snapshot: { title: text(s.title, 1000), source: text(s.source, 60), organism: text(s.organism, 500), modality: text(s.modality, 500), samples },
  };
}

// Sends this browser's Saved to the account's Saved in one request. Local copies are removed only for the accessions
// the server says it now holds; anything it could not take stays in this browser.
// Entries locus cannot read (an accession outside the API's rule) are not sent; they stay and are counted as skipped.
export async function importGuestSaved(): Promise<ImportResult> {
  const items = guestItems().map(importable);
  const good = items.filter((i) => ACCESSION.test(i.accession));
  const done = await call<Omit<ImportResult, "skipped">>("POST", "/lists/saved/import", { items: good });
  const held = new Set(done.held);
  writeGuest(guestItems().filter((i) => !held.has(i.accession.trim())));
  stale = true;
  await reload();
  return { ...done, skipped: items.length - good.length };
}

// Tags typed as "HEK293, riboseq" become ["HEK293", "riboseq"].
export const parseTags = (text: string) => [...new Set(text.split(",").map((t) => t.trim()).filter(Boolean))];

export function describeError(error: unknown): string {
  if (error instanceof AccountError) return error.message;
  return "locus could not reach your lists. Please try again.";
}
