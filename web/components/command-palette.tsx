"use client";
import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ArrowRight, CornerDownLeft } from "lucide-react";
import { looksLikeIdentifier, personPath, resolve } from "@/lib/api";
import { listFollows, type Follow } from "@/lib/follows";
import { useSaved } from "@/lib/lists";
import { askSearch, recentSearches } from "@/lib/recent";
import { cn } from "@/lib/utils";

// The command palette (F8 a, after papertok's keyboard shortcuts): "/" or Ctrl/Cmd+K opens it from any page. It jumps to
// an accession, PMID or DOI (through the existing /resolve, on Enter only), a researcher, one of your lists, or a recent
// search. Typing never calls the model: only choosing "Search for …" (the default for free text) runs the normal search.
// It is a combobox over a listbox, so a screen reader hears the active option and the number of options.

let isOpen = false;
const listeners = new Set<() => void>();
const setOpen = (v: boolean) => {
  isOpen = v;
  listeners.forEach((l) => l());
};
export const openPalette = () => setOpen(true);
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

const KBD = "rounded border border-rule px-1 font-mono text-[11px] leading-[1.4] text-muted-foreground";

export function PaletteButton() {
  return (
    <button
      type="button"
      onClick={openPalette}
      aria-keyshortcuts="/ Control+K Meta+K"
      data-palette-button
      className="hidden items-baseline gap-1.5 text-muted-foreground transition-colors duration-150 hover:text-foreground sm:flex"
    >
      Go to <kbd className={KBD}>/</kbd>
    </button>
  );
}

const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

export function CommandPalette() {
  const open = useSyncExternalStore(subscribe, () => isOpen, () => false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey) {
        e.preventDefault();
        setOpen(!isOpen);
      } else if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey && !typing(e.target) && !isOpen) {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return open ? <Palette onClose={() => setOpen(false)} /> : null;
}

type Option = { id: string; group: string; label: string; hint?: string; mono?: boolean; run: () => void | Promise<void> };

const matches = (text: string, q: string) => text.toLowerCase().includes(q.toLowerCase());
// A researcher's page is offered for text that reads like a name: letters only, two to five words.
const nameLike = (q: string) => /^[\p{L}][\p{L}' .-]*$/u.test(q) && q.split(/\s+/).length >= 2 && q.split(/\s+/).length <= 5;

function Palette({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const saved = useSaved();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [people, setPeople] = useState<Follow[]>([]);
  const [recent] = useState(recentSearches);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const before = useRef<Element | null>(null);
  const base = useId();
  const signedIn = saved.status === "signed-in";

  // Focus moves into the palette and goes back to where it was on close.
  useEffect(() => {
    before.current = document.activeElement;
    input.current?.focus();
    return () => {
      if (before.current instanceof HTMLElement && before.current.isConnected) before.current.focus();
    };
  }, []);

  // The people you follow, read once when the palette opens (signed in only).
  useEffect(() => {
    if (!signedIn) return;
    let live = true;
    listFollows().then((f) => live && setPeople(f), () => {});
    return () => {
      live = false;
    };
  }, [signedIn]);

  const go = (path: string) => {
    onClose();
    router.push(path);
  };
  const runSearch = (text: string) => {
    onClose();
    if (pathname === "/") askSearch(text);
    else router.push(`/?q=${encodeURIComponent(text)}`);
  };

  const options = ((): Option[] => {
    const text = q.trim();
    const out: Option[] = [];
    if (text && looksLikeIdentifier(text)) {
      out.push({
        id: "open", group: "Go to", label: `Open ${text}`, mono: true, hint: "accession, PMID or DOI",
        run: async () => {
          setBusy(true);
          setProblem("");
          try {
            const found = await resolve(text);
            if (found) go(found.path);
            else setProblem(`locus has no record for ${text}. Choose Search to look for it in the catalogue.`);
          } catch (e) {
            setProblem(`locus could not look up ${text} (${e instanceof Error ? e.message : String(e)}).`);
          } finally {
            setBusy(false);
          }
        },
      });
    }
    if (text) out.push({ id: "search", group: "Search", label: `Search for “${text}”`, hint: "runs the full search", run: () => runSearch(text) });
    for (const r of recent.filter((r) => !text || (matches(r, text) && r !== text)).slice(0, text ? 4 : 5)) {
      out.push({ id: `recent-${r}`, group: "Recent searches", label: r, run: () => runSearch(r) });
    }
    if (signedIn) {
      for (const l of saved.lists.filter((l) => !text || matches(l.name, text)).slice(0, 6)) {
        out.push({ id: `list-${l.id}`, group: "Your lists", label: l.name, hint: `${l.count.toLocaleString()} ${l.count === 1 ? "dataset" : "datasets"}`, run: () => go(`/lists/${l.id}`) });
      }
    } else if (saved.status === "guest" && (!text || matches("saved in this browser", text))) {
      out.push({ id: "list-guest", group: "Your lists", label: "Saved in this browser", hint: `${saved.guest.length.toLocaleString()} ${saved.guest.length === 1 ? "dataset" : "datasets"}`, run: () => go("/lists") });
    }
    for (const p of people.filter((p) => !text || matches(p.display_name, text)).slice(0, 5)) {
      out.push({ id: `person-${p.orcid}`, group: "People", label: p.display_name, hint: "followed", run: () => go(personPath(p.page_name ?? p.display_name)) });
    }
    if (text && nameLike(text) && !people.some((p) => p.display_name.toLowerCase() === text.toLowerCase())) {
      out.push({ id: "person", group: "People", label: `Researcher page for ${text}`, hint: "papers in Europe PMC", run: () => go(personPath(text)) });
    }
    const pages = [
      { href: "/", label: "Search" },
      ...(signedIn ? [{ href: "/following", label: "Following" }] : []),
      { href: "/lists", label: "Lists" },
      ...(signedIn ? [{ href: "/settings", label: "Settings" }] : []),
      { href: "/privacy", label: "Privacy" },
    ];
    for (const p of pages.filter((p) => !text || matches(p.label, text))) {
      out.push({ id: `page-${p.href}`, group: "Pages", label: p.label, run: () => go(p.href) });
    }
    return out;
  })();

  const at = Math.min(active, Math.max(options.length - 1, 0));
  const optionId = (i: number) => `${base}-option-${i}`;

  useEffect(() => {
    list.current?.querySelector(`[data-index="${at}"]`)?.scrollIntoView({ block: "nearest" });
  }, [at]);

  const choose = (i: number) => {
    const o = options[i];
    if (o && !busy) void o.run();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((at + 1) % Math.max(options.length, 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((at - 1 + options.length) % Math.max(options.length, 1));
    } else if (e.key === "Home" && e.ctrlKey) {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End" && e.ctrlKey) {
      e.preventDefault();
      setActive(options.length - 1);
    } else if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      e.preventDefault();
      choose(at);
    } else if (e.key === "Tab") {
      // Focus stays in the palette while it is open (the options are reached with the arrow keys).
      e.preventDefault();
    }
  };

  let group = "";
  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-foreground/20 px-4 pt-[12vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Go to"
        data-palette
        onKeyDown={onKey}
        className="grid w-full max-w-xl overflow-hidden rounded-lg border border-rule bg-popover text-[13px] motion-safe:animate-in motion-safe:fade-in motion-safe:duration-150"
      >
        <div className="flex items-center gap-2 border-b border-rule px-4">
          <ArrowRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
          <input
            ref={input}
            value={q}
            onChange={(e) => { setQ(e.target.value); setActive(0); setProblem(""); }}
            role="combobox"
            aria-expanded="true"
            aria-controls={`${base}-list`}
            aria-activedescendant={options.length ? optionId(at) : undefined}
            aria-autocomplete="list"
            aria-label="Go to an accession, a researcher, a list or a search"
            placeholder="GSE185023, a researcher, a list, or a question"
            className="h-12 min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none placeholder:text-muted-foreground"
          />
          <kbd className={KBD}>Esc</kbd>
        </div>
        {problem && <p role="alert" className="border-b border-rule px-4 py-2.5 text-destructive">{problem}</p>}
        <ul ref={list} id={`${base}-list`} role="listbox" aria-label="Places to go" className="max-h-[50vh] overflow-y-auto py-1.5">
          {options.map((o, i) => {
            const heading = o.group !== group ? (group = o.group) : null;
            return (
              <li key={o.id} role="presentation">
                {heading && <p aria-hidden className="label px-4 pb-1 pt-2.5 text-muted-foreground">{heading}</p>}
                <div
                  id={optionId(i)}
                  role="option"
                  aria-selected={i === at}
                  data-index={i}
                  data-option={o.id}
                  onMouseMove={() => i !== at && setActive(i)}
                  onClick={() => choose(i)}
                  className={cn("mx-1.5 flex cursor-pointer items-baseline gap-3 rounded px-2.5 py-1.5", i === at && "bg-muted")}
                >
                  <span className={cn("min-w-0 flex-1 truncate", o.mono && "font-mono text-[12.5px]")}>
                    <span className="sr-only">{o.group}: </span>
                    {o.label}
                  </span>
                  {o.hint && <span className="shrink-0 text-[12px] text-muted-foreground">{o.hint}</span>}
                  {i === at && <CornerDownLeft aria-hidden className="size-3.5 shrink-0 self-center text-muted-foreground" />}
                </div>
              </li>
            );
          })}
        </ul>
        {options.length === 0 && <p className="px-4 py-3 text-muted-foreground">Nothing to go to yet. Type an accession or a question.</p>}
        <p className="flex justify-between border-t border-rule px-4 py-2 text-[12px] text-muted-foreground">
          <span>{busy ? "Looking it up…" : "Arrow keys to move, Enter to go"}</span>
          <span aria-live="polite" className="tabular">{options.length} {options.length === 1 ? "option" : "options"}</span>
        </p>
      </div>
    </div>
  );
}
