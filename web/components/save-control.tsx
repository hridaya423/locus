"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bookmark, ChevronDown, Plus } from "lucide-react";
import { Checkbox } from "@/components/result-card";
import { LINK, MUTED_LINK } from "@/components/page-kit";
import { signInHref } from "@/lib/account";
import { addTo, describeError, isSaved, newList, removeFrom, savedList, useSaved, type Snapshot } from "@/lib/lists";
import { cn } from "@/lib/utils";
import { toast, type Toast } from "@/components/toast";

// Save on a result row or a dataset page: one click keeps the dataset in "Saved"; the arrow opens the list picker.
// `snapshot` comes from what the page already shows (the search hit or the dataset record); null until it is known.
export function SaveControl({ accession, snapshot, compact = false }: { accession: string; snapshot: Snapshot | null; compact?: boolean }) {
  const saved = useSaved();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const picker = useRef<HTMLButtonElement>(null);
  const on = isSaved(saved, accession);
  const ready = !!snapshot && (saved.status === "guest" || saved.status === "signed-in");

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); picker.current?.focus(); } };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", escape); };
  }, [open]);

  async function run(work: () => Promise<void>, done?: Toast) {
    setBusy(true);
    try {
      await work();
      if (done) toast(done);
    } catch (e) {
      toast({ text: describeError(e), error: true });
    } finally {
      setBusy(false);
    }
  }

  const where = saved.status === "guest" ? "Saved in this browser" : "Saved";
  // After a save the toast offers the list picker and, for a guest, the way to what this browser has saved (F2-r1-1).
  const picks = [
    { label: "Add to a list", onClick: () => setOpen(true) },
    ...(saved.status === "guest" ? [{ label: "See saved", href: "/lists" }] : []),
  ];
  function toggleSaved() {
    if (!snapshot) return;
    if (on) run(() => removeFrom("saved", accession), { text: "Removed from Saved", undo: () => run(() => addTo("saved", accession, snapshot)) });
    else run(() => addTo("saved", accession, snapshot), { text: where, actions: picks, undo: () => run(() => removeFrom("saved", accession)) });
  }

  function toggleList(id: number, held: boolean, listName: string) {
    if (!snapshot) return;
    run(() => (held ? removeFrom(id, accession) : addTo(id, accession, snapshot)), { text: held ? `Removed from ${listName}` : `Added to ${listName}` });
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const text = name.trim();
    if (!text || !snapshot) return;
    await run(async () => {
      const list = await newList(text);
      await addTo(list.id, accession, snapshot);
      setName("");
    }, { text: `Added to ${text}` });
  }

  const label = on ? `Remove ${accession} from ${where}` : `Save ${accession}`;
  const why = !snapshot ? "Available once the record has loaded" : saved.status === "failed" ? "locus could not reach your lists" : undefined;
  const holds = saved.holds[accession] ?? [];
  const named = saved.lists.filter((l) => !l.builtin);
  const builtin = savedList(saved);

  return (
    <div ref={box} className="relative flex shrink-0 items-center" data-save-control={accession} data-saved={on ? "true" : "false"}>
      <button
        type="button"
        onClick={toggleSaved}
        disabled={!ready || busy}
        aria-pressed={on}
        aria-label={compact ? label : undefined}
        title={why ?? label}
        className={cn(
          "flex items-center gap-1 rounded-l px-1 py-0.5 text-[13px] text-muted-foreground transition-colors duration-150 hover:text-foreground disabled:cursor-default disabled:opacity-50",
          on && "text-foreground",
        )}
      >
        <Bookmark aria-hidden className={cn("size-3.5", on && "fill-current")} />
        {!compact && <span>{on ? "Saved" : "Save"}</span>}
      </button>
      <button
        ref={picker}
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={!ready}
        aria-expanded={open}
        aria-label={`Choose lists for ${accession}`}
        title={why ?? "Choose lists"}
        className="grid place-items-center rounded-r px-0.5 py-0.5 text-muted-foreground transition-colors duration-150 hover:text-foreground disabled:cursor-default disabled:opacity-50"
      >
        <ChevronDown aria-hidden className={cn("size-3.5 transition-transform duration-150", open && "rotate-180")} />
      </button>
      {open && (
        <div role="group" aria-label={`Lists for ${accession}`} data-list-picker className="absolute right-0 top-full z-30 mt-1.5 grid w-64 gap-2 rounded-lg border border-rule bg-popover p-3 text-left text-[13px] shadow-sm">
          {saved.status === "guest" ? (
            <>
              <div className="flex items-start gap-2.5">
                <Checkbox checked={on} onChange={toggleSaved} label={`Saved in this browser: ${accession}`} />
                <span>Saved in this browser</span>
              </div>
              <p className="text-[12px] leading-snug text-muted-foreground">
                Named lists, notes and tags need an account. <Link href={signInHref(pathname)} className={LINK}>Sign in</Link> to keep them on every device.
              </p>
              <Link href="/lists" className={cn("w-fit text-[12px]", MUTED_LINK)} data-see-saved>See what this browser saved</Link>
            </>
          ) : (
            <>
              <ul className="grid max-h-60 gap-1.5 overflow-y-auto">
                {builtin && (
                  <li className="flex items-start gap-2.5">
                    <Checkbox checked={on} onChange={toggleSaved} label={`Saved: ${accession}`} />
                    <span>Saved</span>
                  </li>
                )}
                {named.map((l) => {
                  const held = holds.includes(l.id);
                  return (
                    <li key={l.id} className="flex items-start gap-2.5">
                      <Checkbox checked={held} onChange={() => toggleList(l.id, held, l.name)} label={`${l.name}: ${accession}`} />
                      <span className="min-w-0 break-words">{l.name} <span className="font-mono text-[11.5px] tabular text-muted-foreground">{l.count}</span></span>
                    </li>
                  );
                })}
              </ul>
              <form onSubmit={create} className="flex items-center gap-1.5 border-t border-rule pt-2">
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={120}
                  placeholder="New list"
                  aria-label="Name of a new list"
                  className="h-7 min-w-0 flex-1 rounded border border-rule bg-card px-2 text-[13px] outline-none focus-visible:border-foreground"
                />
                <button type="submit" disabled={busy || !name.trim()} aria-label="Create the list and add this dataset" className="grid size-7 place-items-center rounded bg-foreground text-background disabled:opacity-40">
                  <Plus aria-hidden className="size-3.5" />
                </button>
              </form>
              <Link href="/lists" className={cn("w-fit text-[12px]", MUTED_LINK)}>All lists</Link>
            </>
          )}
        </div>
      )}
    </div>
  );
}
