"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronLeft, Download } from "lucide-react";
import { Wordmark } from "@/components/logo";
import { BackToResults } from "@/components/back-to-results";
import { AuthPrompt } from "@/components/auth-prompt";
import { EmptyState, Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { Checkbox, SEP } from "@/components/result-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { datasetPath, repositoryName } from "@/lib/api";
import { AccountError, signInHref } from "@/lib/account";
import {
  LIMITS, addTo, deleteList, describeError, editItem, editList, exportHref, getList, newList, parseTags, publishList, reload, removeFrom,
  shareUrl, unpublishList, useSaved, type Item, type ListDetail, type ListSummary,
} from "@/lib/lists";
import { cn } from "@/lib/utils";
import { toast } from "@/components/toast";

const day = (iso: string) => iso.slice(0, 10);
const datasets = (n: number) => `${n.toLocaleString()} ${n === 1 ? "dataset" : "datasets"}`;

function Nav({ back }: { back?: boolean }) {
  return (
    <nav className="flex items-center gap-5">
      <Link href="/" aria-label="locus home" className="leading-none"><Wordmark className="text-[30px]" /></Link>
      {back ? (
        <Link href="/lists" className={cn("flex items-center gap-1 text-[13px]", MUTED_LINK)}>
          <ChevronLeft aria-hidden className="size-3.5" />All lists
        </Link>
      ) : (
        <BackToResults />
      )}
    </nav>
  );
}

// One saved dataset: its snapshot as saved, with a link to the live dataset page.
function ItemHead({ item }: { item: Item }) {
  const s = item.snapshot;
  const meta = [s.source && repositoryName(s.source), s.organism, s.modality, s.samples != null && `${s.samples.toLocaleString()} samples`].filter(Boolean).join(SEP);
  return (
    <div className="grid min-w-0 gap-1">
      <Link href={datasetPath(item.accession)} className={cn("w-fit text-[15px] leading-snug", LINK)}>{s.title || item.accession}</Link>
      <p className="flex min-w-0 flex-wrap items-baseline gap-x-2">
        <span className="font-mono text-[12px] font-medium text-foreground/80">{item.accession}</span>
        {meta && <span className="label min-w-0 text-muted-foreground">{meta}</span>}
      </p>
      <p className="font-mono text-[11.5px] tabular text-muted-foreground">added {day(item.added_at)}</p>
    </div>
  );
}

// ---------------------------------------------------------------- /lists

export function ListsPage() {
  const saved = useSaved();
  const router = useRouter();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const list = await newList(name.trim());
      router.push(`/lists/${list.id}`);
    } catch (err) {
      setError(describeError(err));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto grid w-full max-w-4xl content-start gap-10">
      <Nav />
      <header className="grid gap-3">
        <h1 className="font-display text-[34px] leading-[1.08] sm:text-[44px]">Lists</h1>
        <p className="max-w-xl text-[15px] text-muted-foreground">Datasets you saved, in the order you added them, with your notes and tags.</p>
      </header>
      {saved.status === "loading" ? (
        <p className="text-[13px] text-muted-foreground">Reading your lists…</p>
      ) : saved.status === "failed" ? (
        <p role="alert" className="flex flex-wrap items-baseline gap-x-3 text-[13px]">locus could not read your lists. <button type="button" onClick={() => reload()} className={LINK}>Try again</button></p>
      ) : saved.status === "guest" ? (
        <GuestSaved />
      ) : (
        <div className="grid gap-10" data-lists-page="signed-in">
          {saved.lists.every((l) => l.builtin && l.count === 0) ? (
            <EmptyState id="no-lists" title="No lists yet" ways={[{ href: "/", label: "Search for datasets" }]}>
              Saved is empty and you have made no named lists. Save a dataset from a search result, or name a new list below.
            </EmptyState>
          ) : (
          <table className="w-full border-collapse text-[14px]">
            <thead className="border-b border-foreground">
              <tr className="label text-muted-foreground">
                <th className="py-2 text-left font-normal">List</th>
                <th className="py-2 pl-3 text-right font-normal">Datasets</th>
                <th className="py-2 pl-3 text-right font-normal max-sm:hidden">Updated</th>
              </tr>
            </thead>
            <tbody>
              {saved.lists.map((l) => (
                <tr key={l.id} className="border-b border-rule" data-list-row={l.name}>
                  <td className="py-3 align-top">
                    <Link href={`/lists/${l.id}`} className={cn("font-medium", LINK)}>{l.name}</Link>
                    {l.description && <p className="mt-0.5 line-clamp-1 text-[13px] text-muted-foreground">{l.description}</p>}
                  </td>
                  <td className="py-3 pl-3 text-right align-top font-mono text-[13px] tabular">{l.count.toLocaleString()}</td>
                  <td className="py-3 pl-3 text-right align-top font-mono text-[13px] tabular text-muted-foreground max-sm:hidden">{day(l.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          )}
          <section aria-labelledby="new-list" className="grid max-w-xl gap-3">
            <Heading id="new-list">New list</Heading>
            <form onSubmit={create} className="flex flex-wrap gap-3">
              <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={LIMITS.name} aria-label="Name of the new list"
                placeholder="Ribo-seq in HEK293" className="h-9 max-w-xs bg-card" />
              <Button type="submit" size="lg" disabled={busy || !name.trim() || saved.lists.length >= LIMITS.lists}>{busy ? "Creating…" : "Create list"}</Button>
            </form>
            {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
            <p className="text-[12px] text-muted-foreground">
              Up to {LIMITS.lists} lists of {LIMITS.items} datasets each. Save from any search result or dataset page; the arrow beside Save picks the list.
            </p>
          </section>
        </div>
      )}
    </div>
  );
}

function GuestSaved() {
  const saved = useSaved();
  const [error, setError] = useState("");
  const items = saved.guest;
  return (
    <section aria-labelledby="this-browser" className="grid gap-6" data-lists-page="guest">
      <Heading id="this-browser" count={items.length || undefined}>Saved in this browser</Heading>
      <AuthPrompt reason="This list lives only in this browser. With an account, saved datasets, named lists, notes and tags follow you to every device." />
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
      {items.length === 0 ? (
        <EmptyState id="nothing-saved" title="Nothing saved yet" ways={[{ href: "/", label: "Search for datasets" }]}>
          Use Save on a search result or a dataset page and it appears here.
        </EmptyState>
      ) : (
        <ul className="grid border-t border-rule">
          {items.map((item) => (
            <li key={item.accession} data-item={item.accession} className="flex items-start justify-between gap-4 border-b border-rule py-4">
              <ItemHead item={item} />
              <button
                type="button"
                onClick={() => removeFrom("saved", item.accession).then(
                  () => toast({ text: `Removed ${item.accession}`, undo: () => { addTo("saved", item.accession, item.snapshot).catch((e) => toast({ text: describeError(e), error: true })); } }),
                  (e) => setError(describeError(e)),
                )}
                className={cn("shrink-0 text-[13px]", MUTED_LINK)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- /lists/[id]

export function ListPage({ id }: { id: string }) {
  const saved = useSaved();
  const numeric = /^\d+$/.test(id) ? Number(id) : null;
  const [detail, setDetail] = useState<ListDetail | null>(null);
  const [problem, setProblem] = useState<"" | "missing" | "failed">("");
  const [attempt, setAttempt] = useState(0);
  const signedIn = saved.status === "signed-in";

  useEffect(() => {
    if (!signedIn || numeric === null) return;
    let live = true;
    getList(numeric).then(
      (d) => { if (live) { setDetail(d); setProblem(""); } },
      (e) => { if (live) setProblem(e instanceof AccountError && e.code === "LIST_NOT_FOUND" ? "missing" : "failed"); },
    );
    return () => { live = false; };
  }, [signedIn, numeric, attempt]);

  useEffect(() => {
    document.title = detail ? `${detail.list.name} · locus` : "List · locus";
  }, [detail]);

  const missing = numeric === null || problem === "missing";
  return (
    <div className="mx-auto grid w-full max-w-4xl content-start gap-10">
      <Nav back />
      {saved.status === "loading" ? (
        <p className="text-[13px] text-muted-foreground">Reading the list…</p>
      ) : saved.status === "guest" ? (
        <EmptyState
          id="list-signed-out"
          title="Sign in to open this list"
          ways={[{ href: signInHref(`/lists/${id}`), label: "Sign in or create an account" }, { href: "/lists", label: "See what this browser saved" }]}
        >
          Lists are kept in an account. Sign in to open this one, and you will come back here.
        </EmptyState>
      ) : missing ? (
        <p className="text-[14px]">There is no such list in your account. <Link href="/lists" className={LINK}>See all your lists</Link>.</p>
      ) : problem === "failed" || saved.status === "failed" ? (
        <p role="alert" className="flex flex-wrap items-baseline gap-x-3 text-[13px]">locus could not read this list. <button type="button" onClick={() => setAttempt((n) => n + 1)} className={LINK}>Try again</button></p>
      ) : !detail ? (
        <p className="text-[13px] text-muted-foreground">Reading the list…</p>
      ) : (
        <ListBody detail={detail} onChange={setDetail} />
      )}
    </div>
  );
}

function ListBody({ detail, onChange }: { detail: ListDetail; onChange: (d: ListDetail) => void }) {
  const router = useRouter();
  const { list, items } = detail;
  const [mode, setMode] = useState<"" | "rename" | "delete">("");
  const [name, setName] = useState(list.name);
  const [description, setDescription] = useState(list.description);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(describeError(e));
    } finally {
      setBusy(false);
    }
  }

  const rename = (e: React.FormEvent) => {
    e.preventDefault();
    act(async () => {
      const done = await editList(list.id, { name: name.trim(), description: description.trim() });
      onChange({ ...detail, list: done.list });
      setMode("");
      await reload();
    });
  };

  const remove = () => act(async () => {
    await deleteList(list.id);
    await reload();
    router.push("/lists");
  });

  // Any change to the list makes its public page out of date until the owner updates it (the server says the same).
  const changed = (l: ListSummary): ListSummary => (l.public ? { ...l, public: { ...l.public, stale: true } } : l);

  const dropItem = (accession: string) => act(async () => {
    await removeFrom(list.id, accession);
    onChange({ ...detail, list: changed({ ...list, count: list.count - 1 }), items: items.filter((i) => i.accession !== accession) });
  });

  const putItem = useCallback((item: Item) => {
    onChange({ ...detail, list: changed(detail.list), items: detail.items.map((i) => (i.accession === item.accession ? item : i)) });
  }, [detail, onChange]);

  return (
    <div className="grid gap-10" data-list-page={list.name}>
      <header className="grid gap-4">
        <p className="label text-muted-foreground">{list.builtin ? "Built-in list" : "List"}</p>
        {mode === "rename" ? (
          <form onSubmit={rename} className="grid max-w-xl gap-3" data-rename>
            <label htmlFor="list-name" className="label text-muted-foreground">Name</label>
            <Input id="list-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={LIMITS.name} className="h-9 bg-card" />
            <label htmlFor="list-description" className="label text-muted-foreground">Description</label>
            <Textarea id="list-description" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={LIMITS.description} rows={2} className="bg-card" />
            <div className="flex gap-3">
              <Button type="submit" disabled={busy || !name.trim()}>{busy ? "Saving…" : "Save"}</Button>
              <Button type="button" variant="outline" onClick={() => { setMode(""); setName(list.name); setDescription(list.description); }}>Cancel</Button>
            </div>
          </form>
        ) : (
          <>
            <h1 className="max-w-4xl font-display text-[34px] leading-[1.08] break-words sm:text-[44px]">{list.name}</h1>
            {list.description && <p className="max-w-2xl text-[15px] text-muted-foreground">{list.description}</p>}
          </>
        )}
        <div className="flex flex-wrap items-baseline gap-x-5 gap-y-2 border-y border-rule py-3 text-[13px]">
          <span className="font-mono tabular" data-count={list.count}>{datasets(list.count)}</span>
          <span className="font-mono tabular text-muted-foreground">updated {day(list.updated_at)}</span>
          {items.length > 0 && (
            <>
              <a href={exportHref(list.id, "accessions")} download className={cn("flex items-center gap-1", MUTED_LINK)}><Download aria-hidden className="size-3.5" />Accessions</a>
              <a href={exportHref(list.id, "csv")} download className={cn("flex items-center gap-1", MUTED_LINK)}><Download aria-hidden className="size-3.5" />CSV</a>
            </>
          )}
          {!list.builtin && mode === "" && (
            <>
              <button type="button" onClick={() => setMode("rename")} className={MUTED_LINK}>Rename</button>
              <button type="button" onClick={() => setMode("delete")} className={MUTED_LINK}>Delete</button>
            </>
          )}
        </div>
        {mode === "delete" && (
          <div role="alertdialog" aria-labelledby="delete-question" className="grid max-w-xl gap-3 border-l-2 border-destructive pl-4 text-[14px]" data-delete-confirm>
            <p id="delete-question">Delete {list.name} and the {datasets(list.count)} in it? Your notes and tags on them go too. This cannot be undone.</p>
            <div className="flex gap-3">
              <Button variant="destructive" disabled={busy} onClick={remove}>{busy ? "Deleting…" : "Delete list"}</Button>
              <Button variant="outline" onClick={() => setMode("")}>Keep it</Button>
            </div>
          </div>
        )}
        {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
        <Sharing list={list} onChange={(l) => onChange({ ...detail, list: l })} />
      </header>

      {items.length === 0 ? (
        <EmptyState id="empty-list" title="This list is empty" ways={[{ href: "/", label: "Search for datasets" }, { href: "/lists", label: "All lists" }]}>
          Save datasets from a search result or a dataset page, and choose this list with the arrow beside Save.
        </EmptyState>
      ) : (
        <ol className="-mt-10 grid">
          {items.map((item) => (
            <ItemRow key={item.accession} listId={list.id} item={item} onSaved={putItem} onRemove={() => dropItem(item.accession)} />
          ))}
        </ol>
      )}
    </div>
  );
}

// Public link (papertok's public lists): publish a frozen copy at /s/<id>, update it, or stop sharing (the link then
// answers 404). Showing the owner's name and including notes are both off unless ticked; tags are never published.
function Sharing({ list, onChange }: { list: ListSummary; onChange: (l: ListSummary) => void }) {
  const pub = list.public;
  const [open, setOpen] = useState(false);
  const [showOwner, setShowOwner] = useState(pub?.show_owner ?? false);
  const [includeNotes, setIncludeNotes] = useState(pub?.include_notes ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [said, setSaid] = useState("");
  const max = LIMITS.public_items ?? 50;
  // Keyboard focus after the controls swap (F6-r1-2): into the form when it opens; to the share link after Publish,
  // Update or Cancel; to "Share a public link" after Stop sharing. Set just before the swap, used once after it.
  const focusNext = useRef<"" | "form" | "link" | "open">("");
  const box = useRef<HTMLElement>(null);
  useEffect(() => {
    const target = focusNext.current;
    if (!target) return;
    focusNext.current = "";
    const sel = target === "form" ? "[data-share-form] input[type=checkbox]" : target === "link" ? "[data-share-link]" : "[data-share-open]";
    box.current?.querySelector<HTMLElement>(sel)?.focus();
  });

  async function act(work: () => Promise<{ list: ListSummary }>, message: string) {
    setBusy(true);
    setError("");
    try {
      const done = await work();
      focusNext.current = done.list.public ? "link" : "open";
      onChange(done.list);
      setOpen(false);
      setSaid(message);
      await reload();
    } catch (e) {
      setError(describeError(e));
    } finally {
      setBusy(false);
    }
  }
  const publish = () => act(() => publishList(list.id, { show_owner: showOwner, include_notes: includeNotes }), pub ? "The public page now shows the list as it is." : "The list is public. Anyone with the link can open it.");
  const stop = () => act(() => unpublishList(list.id), "The list is private again. Its link no longer opens.");
  const url = pub ? shareUrl(pub.share_id) : "";
  const copy = () => navigator.clipboard.writeText(url).then(() => setCopied(true), () => setError("The link could not be copied. Select it and copy it by hand."));

  const choices = (
    <div className="grid max-w-xl gap-3 border-l-2 border-foreground pl-4 text-[14px]" data-share-form>
      <p className="text-muted-foreground">
        Anyone with the link can see this list’s name, description and {list.count > max ? `the first ${max} of its datasets` : "its datasets"}, as they are when you publish. Tags stay private. The link cannot be guessed and is listed nowhere.
      </p>
      {/* The words toggle the box too (F6-r1-3): each is a <label> for the checkbox's id. */}
      <span className="flex items-start gap-3">
        <Checkbox id={`share-owner-${list.id}`} checked={showOwner} onChange={() => setShowOwner((v) => !v)} label="Show my display name" />
        <label htmlFor={`share-owner-${list.id}`} className="cursor-pointer" data-share-choice="owner">Show my display name</label>
      </span>
      <span className="flex items-start gap-3">
        <Checkbox id={`share-notes-${list.id}`} checked={includeNotes} onChange={() => setIncludeNotes((v) => !v)} label="Include my notes" />
        <label htmlFor={`share-notes-${list.id}`} className="cursor-pointer" data-share-choice="notes">Include my notes</label>
      </span>
      <div className="flex gap-3">
        <Button disabled={busy} onClick={publish}>{busy ? "Publishing…" : pub ? "Update public page" : "Publish"}</Button>
        <Button variant="outline" disabled={busy} onClick={() => { focusNext.current = pub ? "link" : "open"; setOpen(false); }}>Cancel</Button>
      </div>
    </div>
  );

  return (
    <section ref={box} aria-label="Sharing" className="grid gap-3 text-[13px]" data-sharing={pub ? "public" : "private"}>
      <p className="sr-only" role="status" aria-live="polite">{said}</p>
      {pub ? (
        <>
          {/* Spaced by gap rather than "·" text, so a wrapped line never starts with a stray separator (F6-r1-4). */}
          <p className="flex min-w-0 flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="label text-muted-foreground">Public</span>
            <a href={url} className={cn("min-w-0 max-w-full truncate font-mono text-[12px]", LINK)} data-share-link>{url}</a>
            <button type="button" onClick={copy} onBlur={() => setCopied(false)} className={MUTED_LINK}>{copied ? "Copied" : "Copy"}</button>
            <button type="button" disabled={busy} onClick={stop} className={MUTED_LINK} data-unpublish>Stop sharing</button>
            {!open && (
              <button type="button" onClick={() => { focusNext.current = "form"; setOpen(true); }} className={MUTED_LINK} data-share-change>Change what it shows</button>
            )}
          </p>
          <p className="font-mono text-[12px] tabular text-muted-foreground">
            published {day(pub.published_at)}{pub.show_owner ? " · with your name" : ""}{pub.include_notes ? " · with your notes" : ""}
          </p>
          {pub.stale && !open && (
            <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-warn" data-share-stale>
              You changed this list after publishing, so the public page still shows the earlier version.
              <button type="button" disabled={busy} onClick={publish} className={LINK}>{busy ? "Updating…" : "Update public page"}</button>
            </p>
          )}
        </>
      ) : !open && (
        <p>
          <button type="button" onClick={() => { focusNext.current = "form"; setOpen(true); }} className={MUTED_LINK} data-share-open>Share a public link</button>
        </p>
      )}
      {open && choices}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </section>
  );
}

function ItemRow({ listId, item, onSaved, onRemove }: { listId: number; item: Item; onSaved: (item: Item) => void; onRemove: () => void }) {
  const [note, setNote] = useState(item.note);
  const [tags, setTags] = useState(item.tags.join(", "));
  const [state, setState] = useState<"" | "saving" | "saved">("");
  const [error, setError] = useState("");
  const parsed = parseTags(tags);
  const dirty = note !== item.note || parsed.join("\n") !== item.tags.join("\n");
  const tooMany = parsed.length > LIMITS.tags || parsed.some((t) => t.length > LIMITS.tag);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setState("saving");
    setError("");
    try {
      const done = await editItem(listId, item.accession, { note, tags: parsed });
      onSaved(done.item);
      setTags(done.item.tags.join(", "));
      setState("saved");
    } catch (err) {
      setError(describeError(err));
      setState("");
    }
  }

  const id = `item-${item.accession}`;
  return (
    <li className="grid gap-3 border-b border-rule py-5" data-item={item.accession}>
      <div className="flex items-start justify-between gap-4">
        <ItemHead item={item} />
        <button type="button" onClick={onRemove} className={cn("shrink-0 text-[13px]", MUTED_LINK)} aria-label={`Remove ${item.accession} from this list`}>Remove</button>
      </div>
      <form onSubmit={save} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_16rem] sm:gap-4">
        <div className="grid content-start gap-1">
          <label htmlFor={`${id}-note`} className="label text-muted-foreground">Note</label>
          <Textarea id={`${id}-note`} value={note} onChange={(e) => { setNote(e.target.value); setState(""); }} maxLength={LIMITS.note} rows={2} className="min-h-0 bg-card text-[14px]" />
        </div>
        <div className="grid content-start gap-1">
          <label htmlFor={`${id}-tags`} className="label text-muted-foreground">Tags, separated by commas</label>
          <Input id={`${id}-tags`} value={tags} onChange={(e) => { setTags(e.target.value); setState(""); }} className="h-9 bg-card" aria-invalid={tooMany || undefined} />
          {tooMany && <p className="text-[12px] text-warn">At most {LIMITS.tags} tags of {LIMITS.tag} characters each.</p>}
          <div className="mt-1 flex items-baseline gap-3">
            <Button type="submit" variant="outline" size="sm" disabled={!dirty || tooMany || state === "saving"}>{state === "saving" ? "Saving…" : "Save"}</Button>
            <span role="status" className="text-[12px] text-muted-foreground">{state === "saved" && !dirty ? "Saved" : ""}</span>
          </div>
          {error && <p role="alert" className="text-[12px] text-destructive">{error}</p>}
        </div>
      </form>
    </li>
  );
}
