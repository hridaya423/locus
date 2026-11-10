"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { LINK } from "@/components/page-kit";
import { ACCOUNT_EVENT, AccountError, me } from "@/lib/account";
import { GUEST as GUEST_SAVED, describeError, guestItems, importGuestSaved, type ImportResult } from "@/lib/lists";
import { WATCHED as GUEST_WATCHED, guestWatches, importGuestWatches, type WatchImportResult } from "@/lib/watches";

// "Not now" is remembered per browser and per account: another account signing in here is still asked.
const DECLINED = "locus:import-declined";

function declined(): number[] {
  try {
    const ids = JSON.parse(localStorage.getItem(DECLINED) ?? "[]");
    return Array.isArray(ids) ? ids.filter((i) => typeof i === "number") : [];
  } catch {
    return [];
  }
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function savedSummary(r: ImportResult): string {
  const parts: string[] = [];
  if (r.added.length) parts.push(`${plural(r.added.length, "dataset", "datasets")} added to Saved.`);
  if (r.already.length) parts.push(r.added.length ? `${r.already.length} ${r.already.length === 1 ? "was" : "were"} already there.` : "Saved already held these datasets.");
  if (r.left_out.length) parts.push(`${plural(r.left_out.length, "dataset", "datasets")} did not fit, since a list holds at most 500, and stayed in this browser.`);
  if (r.skipped) parts.push(`${plural(r.skipped, "saved entry", "saved entries")} could not be read, so ${r.skipped === 1 ? "it" : "they"} stayed in this browser.`);
  return parts.join(" ");
}

function watchSummary(r: WatchImportResult): string {
  const parts: string[] = [];
  if (r.added.length) parts.push(`${plural(r.added.length, "watched search", "watched searches")} added.`);
  if (r.already.length) parts.push(r.added.length ? `Your account already watched ${r.already.length} of them.` : "Your account already watched these searches.");
  if (r.left_out.length) parts.push(`${plural(r.left_out.length, "watched search", "watched searches")} did not fit, since an account watches at most 200, and stayed in this browser.`);
  if (r.skipped) parts.push(`${plural(r.skipped, "watched search", "watched searches")} could not be read and stayed in this browser.`);
  return parts.join(" ");
}

type Done = { saved: ImportResult | null; watched: WatchImportResult | null };
type Offer = { user: number; saved: number; watched: number; titles: string[] };

// What this browser holds, named, so on a shared computer the person signing in can tell whose saves these are.
function held(): Omit<Offer, "user"> {
  const items = guestItems();
  const watched = guestWatches();
  const titles = [...items.map((i) => i.snapshot?.title || i.accession), ...watched.map((w) => `“${w.question}”`)];
  return { saved: items.length, watched: watched.length, titles: titles.slice(0, 3) };
}

// A 422 means something this browser kept could not be read; say so plainly rather than show the validator's words.
function plainError(e: unknown): string {
  if (e instanceof AccountError && e.code === "INVALID_REQUEST") return "locus could not read what this browser kept, so nothing more was added. Your saves are still here.";
  return describeError(e);
}

// Sends focus somewhere sensible once the panel goes away: the page's main heading, else the main region.
function focusPage() {
  const target = document.querySelector<HTMLElement>("main h1") ?? document.querySelector<HTMLElement>("main");
  if (!target) return;
  if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}

// Shown once after signing in when this browser still holds a guest's saved datasets or watched searches (papertok's
// guest merge, D6). Add sends the datasets to the account's Saved and the watches to the account, one request each;
// each part clears only what the server confirms. The panel docks to the bottom edge of the window, ruled off by a
// hairline, so it never pushes the page's header or the home page's search down.
export function GuestImport() {
  const [offer, setOffer] = useState<Offer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<Done | null>(null);
  const [clearing, setClearing] = useState(false);
  const [said, setSaid] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLElement>(null);
  const moved = useRef(false); // set when Clear or Keep them swaps the action rows, so focus follows the swap

  const check = useCallback(() => {
    // With nothing to offer there is no need to ask who is signed in.
    const now = held();
    const who = now.saved + now.watched === 0 ? Promise.resolve(null) : me().then((m) => m.user, () => null);
    who.then((user) => {
      const h = held();
      if (!user || h.saved + h.watched === 0 || declined().includes(user.id)) {
        setOffer(null);
        return;
      }
      setOffer({ user: user.id, ...h });
      setSaid(`This browser has ${[h.saved > 0 && plural(h.saved, "saved dataset", "saved datasets"), h.watched > 0 && plural(h.watched, "watched search", "watched searches")].filter(Boolean).join(" and ")}. Add them to your account? The choice is at the bottom of the page.`);
      setDone(null);
      setError("");
      setClearing(false);
    });
  }, []);

  useEffect(() => {
    check();
    window.addEventListener(ACCOUNT_EVENT, check);
    return () => window.removeEventListener(ACCOUNT_EVENT, check);
  }, [check]);

  useEffect(() => {
    if (done) heading.current?.focus({ preventScroll: true });
  }, [done]);

  // The panel is fixed to the bottom edge. Its real height goes into --dock on <html>, so the page's bottom padding and
  // the results' selection bar (Compare, copy) sit above it instead of under it.
  const shown = !!(offer || done);
  useEffect(() => {
    const root = document.documentElement;
    const el = panel.current;
    if (!shown || !el) {
      root.style.removeProperty("--dock");
      return;
    }
    const measure = () => root.style.setProperty("--dock", `${Math.ceil(el.getBoundingClientRect().height)}px`);
    measure();
    const watcher = new ResizeObserver(measure);
    watcher.observe(el);
    return () => {
      watcher.disconnect();
      root.style.removeProperty("--dock");
    };
  }, [shown]);

  // Clear asks to confirm in place: focus goes to the confirming button, and back to "Clear from this browser" after
  // "Keep them", rather than dropping to the page.
  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    panel.current?.querySelector<HTMLElement>(clearing ? "[data-clear-confirm]" : "[data-clear-local]")?.focus();
  }, [clearing]);

  const remember = (user: number) => localStorage.setItem(DECLINED, JSON.stringify([...new Set([...declined(), user])]));

  const add = async () => {
    if (!offer) return;
    setBusy(true);
    setError("");
    const result: Done = { saved: null, watched: null };
    try {
      if (offer.saved > 0) result.saved = await importGuestSaved();
      if (offer.watched > 0) result.watched = await importGuestWatches();
      // Whatever did not fit or could not be read stays in this browser; say so once rather than ask on every page.
      const left = (result.saved ? result.saved.left_out.length + result.saved.skipped : 0) + (result.watched ? result.watched.left_out.length + result.watched.skipped : 0);
      if (left > 0) remember(offer.user);
      setSaid([result.saved && savedSummary(result.saved), result.watched && watchSummary(result.watched)].filter(Boolean).join(" "));
      setDone(result);
      setOffer(null);
    } catch (e) {
      if (result.saved) {
        setDone(result);
        setOffer(null);
      }
      setError(plainError(e));
    } finally {
      setBusy(false);
    }
  };

  const close = (message: string) => {
    setOffer(null);
    setDone(null);
    setError("");
    setClearing(false);
    setSaid(message);
    focusPage();
  };

  const notNow = () => {
    if (offer) remember(offer.user);
    close("Your saves stay in this browser.");
  };

  const clear = () => {
    localStorage.removeItem(GUEST_SAVED);
    localStorage.removeItem(GUEST_WATCHED);
    close("Cleared from this browser.");
  };

  // One persistent live region (never remounted) carries every announcement: the offer, the result, the close.
  const live = <p className="sr-only" role="status" aria-live="polite">{said}</p>;

  return (
    <>
      {live}
      {shown && (
      <section ref={panel} aria-labelledby="guest-import" data-guest-import={done ? "done" : "offer"}
        className="fixed inset-x-0 bottom-0 z-40 border-t border-rule bg-background/95 px-5 py-3 text-[13px] backdrop-blur-sm sm:py-4 sm:text-[14px]">
        <div className="mx-auto grid w-full max-w-4xl gap-2">
          <h2 id="guest-import" ref={heading} tabIndex={-1} className="font-display text-[18px] leading-tight outline-none sm:text-[22px]">
            {done ? "Added to your account" : "Bring this browser’s saves into your account?"}
          </h2>
          {done ? (
            <>
              <p className="text-muted-foreground" data-import-result>
                {[done.saved && savedSummary(done.saved), done.watched && watchSummary(done.watched)].filter(Boolean).join(" ")}
              </p>
              {error && <p role="alert" className="text-destructive">{error} The watched searches stayed in this browser.</p>}
              <p className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                {done.saved && <Link href={`/lists/${done.saved.list_id}`} className={LINK} onClick={() => setDone(null)}>Open Saved</Link>}
                {done.watched && done.watched.held.length > 0 && <Link href="/" className={LINK} onClick={() => setDone(null)}>See watched searches</Link>}
                <button type="button" className={LINK} onClick={() => close("")}>Close</button>
              </p>
            </>
          ) : offer && (
            <>
              <p className="text-muted-foreground" data-import-counts={`${offer.saved},${offer.watched}`}>
                This browser has <span className="tabular-nums">{[offer.saved > 0 && plural(offer.saved, "saved dataset", "saved datasets"), offer.watched > 0 && plural(offer.watched, "watched search", "watched searches")].filter(Boolean).join(" and ")}</span>.
                {" "}{offer.saved + offer.watched === 1 ? "Add it to your account?" : "Add them to your account?"}
                {offer.saved > 0 && <span className="hidden sm:inline"> Datasets go to your Saved list.</span>}
              </p>
              <p className="truncate text-muted-foreground sm:whitespace-normal" data-import-titles>
                {offer.titles.join(" · ")}{offer.saved + offer.watched > offer.titles.length && ` and ${offer.saved + offer.watched - offer.titles.length} more`}
              </p>
              {error && <p role="alert" className="text-destructive">{error}</p>}
              {clearing ? (
                <p className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <span>Remove these from this browser? Your account keeps what it has.</span>
                  <Button data-clear-confirm type="button" size="sm" variant="outline" onClick={clear}>Clear</Button>
                  <button type="button" className={LINK} onClick={() => { moved.current = true; setClearing(false); }}>Keep them</button>
                </p>
              ) : (
                <p className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <Button type="button" size="sm" disabled={busy} onClick={add}>{busy ? "Adding…" : "Add"}</Button>
                  <Button type="button" size="sm" variant="outline" disabled={busy} onClick={notNow}>Not now</Button>
                  <button type="button" disabled={busy} className={`${LINK} text-muted-foreground`} onClick={() => { moved.current = true; setClearing(true); }} data-clear-local>Clear from this browser</button>
                </p>
              )}
            </>
          )}
        </div>
      </section>
      )}
    </>
  );
}
