"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowUpRight, Download, KeyRound } from "lucide-react";
import { Wordmark } from "@/components/logo";
import { BackToResults } from "@/components/back-to-results";
import { ORCID_OUTCOME, RecoveryCodes } from "@/components/account-page";
import { EmailCode } from "@/components/email-code";
import { EmptyState, Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ACCOUNT_EVENT, AccountError, describe, me, orcidStartHref, removeEmail, signInHref } from "@/lib/account";
import { listFollows, orcidUrl, unfollow, type Follow } from "@/lib/follows";
import {
  addPasskey, confirmCode, confirmPasskey, deleteAccount, exportHref, getSettings, regenerateCodes, removePasskey, rename,
  renamePasskey, unlinkOrcid, type Passkey, type Settings,
} from "@/lib/settings";
import { PRIVACY_PATH, PRIVACY_SUMMARY } from "@/lib/privacy";
import { setWatch, useWatches } from "@/lib/watches";
import { cn } from "@/lib/utils";

const day = (iso: string | null) => (iso ? iso.slice(0, 10) : "never");
// Whether this session's passkey or recovery-code check is still fresh. The API decides (CONFIRM_REQUIRED); this only
// spares a request that would be refused.
const confirmed = (s: Settings) => !!s.confirmed_until && Date.parse(s.confirmed_until) > Date.now();
const ROW = "flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-b border-rule py-3";
// Text actions in a row: spaced by gap, so a wrapped line never starts with a stray separator.
const ACTIONS = "flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[13px]";
// Confirm's "Add a passkey" asks the Passkeys block to start its ceremony.
const ADD_PASSKEY_EVENT = "locus:add-passkey";

function Nav() {
  return (
    <nav className="flex items-center gap-5">
      <Link href="/" aria-label="locus home" className="leading-none"><Wordmark className="text-[30px]" /></Link>
      <BackToResults />
    </nav>
  );
}

function Section({ id, title, count, children }: { id: string; title: string; count?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="grid gap-5 border-t border-rule pt-8" data-settings-section={id}>
      <Heading id={id} count={count}>{title}</Heading>
      {children}
    </section>
  );
}

// Asks for a passkey or a recovery code, which marks this session as confirmed for five minutes. A dev sign-in or an
// ORCID sign-in never counts, so deleting, new codes and adding or removing a passkey send everyone else here first.
// An account with neither (one made by ORCID) is told to add a passkey first, with a button that starts it.
function Confirm({ why, s, onConfirmed }: { why: string; s: Settings; onConfirmed: (s: Settings) => void }) {
  const hasPasskey = s.passkeys.length > 0;
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { box.current?.focus(); }, []);
  const run = (kind: string, work: () => Promise<Settings>) => {
    setBusy(kind);
    setError("");
    work().then(onConfirmed, (e) => setError(describe(e))).finally(() => setBusy(""));
  };
  const confirmByEmail = () => getSettings().then(onConfirmed, (e) => setError(describe(e)));
  if (!hasPasskey && s.user.recovery_codes_left === 0 && s.user.email) {
    return (
      <div ref={box} tabIndex={-1} role="group" aria-labelledby="confirm-title" className="grid max-w-xl gap-3 border-l-2 border-foreground pl-4 text-[13px] outline-none" data-confirm="email">
        <p id="confirm-title" className="font-medium">Confirm with a code sent to your email</p>
        <p className="text-muted-foreground">{why} The confirmation lasts five minutes.</p>
        <EmailCode purpose="confirm" idPrefix="confirm-email" sendLabel="Email me a code" onDone={confirmByEmail} />
        {error && <p role="alert" className="text-destructive">{error}</p>}
      </div>
    );
  }
  if (!hasPasskey && s.user.recovery_codes_left === 0) {
    return (
      <div ref={box} tabIndex={-1} role="group" aria-labelledby="confirm-title" className="grid max-w-xl gap-3 border-l-2 border-foreground pl-4 text-[13px] outline-none" data-confirm="add-passkey-first">
        <p id="confirm-title" className="font-medium">Add a passkey first</p>
        <p className="text-muted-foreground">{why} This account has no passkey or recovery codes yet, so there is nothing to confirm with. Add a passkey, sign in with it, then come back here.</p>
        <p><Button onClick={() => window.dispatchEvent(new Event(ADD_PASSKEY_EVENT))} data-confirm-add><KeyRound aria-hidden />Add a passkey</Button></p>
      </div>
    );
  }
  return (
    <div ref={box} tabIndex={-1} role="group" aria-labelledby="confirm-title" className="grid max-w-xl gap-3 border-l-2 border-foreground pl-4 text-[13px] outline-none" data-confirm>
      <p id="confirm-title" className="font-medium">Confirm with your passkey or a recovery code</p>
      <p className="text-muted-foreground">{why} The confirmation lasts five minutes.</p>
      <div className="flex flex-wrap items-center gap-3">
        {hasPasskey && (
          <Button disabled={!!busy} onClick={() => run("passkey", confirmPasskey)}>
            <KeyRound aria-hidden />{busy === "passkey" ? "Waiting for your passkey…" : "Confirm with a passkey"}
          </Button>
        )}
      </div>
      <form className="flex flex-wrap items-center gap-3" onSubmit={(e) => { e.preventDefault(); run("code", () => confirmCode(code.trim())); }}>
        <label htmlFor="confirm-code" className="sr-only">Recovery code</label>
        <Input id="confirm-code" value={code} onChange={(e) => setCode(e.target.value)} maxLength={40} autoComplete="one-time-code" spellCheck={false}
          placeholder="ABCD-EFGH-JKLM" className="h-9 max-w-[14rem] bg-card font-mono" />
        <Button type="submit" variant="outline" disabled={!!busy || !code.trim()}>{busy === "code" ? "Checking…" : "Confirm with a recovery code"}</Button>
      </form>
      {s.user.email && (
        <details className="text-muted-foreground">
          <summary className={cn("cursor-pointer", MUTED_LINK)}>Or confirm with a code sent to your email</summary>
          <div className="mt-3"><EmailCode purpose="confirm" idPrefix="confirm-email" sendLabel="Email me a code" onDone={confirmByEmail} /></div>
        </details>
      )}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- Account

function DisplayName({ s, onChange }: { s: Settings; onChange: (s: Settings) => void }) {
  const [name, setName] = useState(s.user.display_name);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const [error, setError] = useState("");
  const save = (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    setSaid("");
    rename(name.trim()).then((next) => { onChange(next); setName(next.user.display_name); setSaid("Display name saved."); }, (err) => setError(describe(err))).finally(() => setBusy(false));
  };
  return (
    <form className="grid gap-2" onSubmit={save} data-settings-name>
      <label htmlFor="settings-name" className="label text-muted-foreground">Display name</label>
      <div className="flex flex-wrap items-center gap-3">
        <Input id="settings-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} autoComplete="nickname" className="h-9 max-w-xs bg-card" />
        <Button type="submit" variant="outline" disabled={busy || !name.trim() || name.trim() === s.user.display_name}>{busy ? "Saving…" : "Save"}</Button>
        <span role="status" className="text-[13px] text-muted-foreground">{said}</span>
      </div>
      <p className="text-[12.5px] text-muted-foreground">Shown in the header and, if you choose, on a list you share. A shared page keeps the name it was published with until you update it.</p>
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
    </form>
  );
}

function PasskeyRow({ p, only, confirmedNow, onChange, onRemoved, onConfirm }: {
  p: Passkey; only: boolean; confirmedNow: boolean; onChange: (s: Settings) => void; onRemoved: (s: Settings) => void; onConfirm: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [nickname, setNickname] = useState(p.nickname);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const renameButton = useRef<HTMLButtonElement>(null);
  const moved = useRef(false);
  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    if (!editing) renameButton.current?.focus();
  }, [editing]);
  const act = (work: () => Promise<Settings>) => {
    setBusy(true);
    setError("");
    work().then((s) => { moved.current = true; setEditing(false); onChange(s); }, (e) => setError(describe(e))).finally(() => setBusy(false));
  };
  const label = p.nickname || "Passkey";
  return (
    <li className={ROW} data-passkey={p.nickname || p.id} data-passkey-row>
      {editing ? (
        <form className="flex flex-wrap items-center gap-3" onSubmit={(e) => { e.preventDefault(); act(() => renamePasskey(p.id, nickname.trim())); }}>
          <label htmlFor={`nick-${p.id}`} className="sr-only">Name for this passkey</label>
          <Input id={`nick-${p.id}`} autoFocus value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={80} placeholder="Phone, laptop, password manager" className="h-9 max-w-xs bg-card" />
          <Button type="submit" variant="outline" disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
          <button type="button" className={cn("text-[13px]", MUTED_LINK)} onClick={() => { moved.current = true; setNickname(p.nickname); setEditing(false); }}>Cancel</button>
        </form>
      ) : (
        <div className="grid gap-0.5">
          <span className="text-[14.5px]">{label}</span>
          <span className="font-mono text-[11.5px] tabular text-muted-foreground">added {day(p.created_at)} · last used {day(p.last_used_at)}</span>
        </div>
      )}
      {!editing && (
        <span className={ACTIONS}>
          <button ref={renameButton} type="button" className={MUTED_LINK} onClick={() => setEditing(true)} aria-label={`Rename ${label}`}>Rename</button>
          {only ? (
            <span className="text-muted-foreground">Your only passkey stays</span>
          ) : (
            <button type="button" disabled={busy} className={MUTED_LINK} onClick={() => {
              if (!confirmedNow) { onConfirm(); return; }
              setBusy(true);
              setError("");
              removePasskey(p.id).then(onRemoved, (e) => {
                if (e instanceof AccountError && e.code === "CONFIRM_REQUIRED") onConfirm();
                else setError(describe(e));
              }).finally(() => setBusy(false));
            }} aria-label={`Remove ${label}`} data-remove>Remove</button>
          )}
        </span>
      )}
      {error && <p role="alert" className="w-full text-[13px] text-destructive">{error}</p>}
    </li>
  );
}

function Passkeys({ s, onChange }: { s: Settings; onChange: (s: Settings) => void }) {
  const [nickname, setNickname] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [asking, setAsking] = useState(false);
  const [needOrcid, setNeedOrcid] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const none = s.passkeys.length === 0;
  // Adding a passkey needs a fresh confirmation, except an account's first one soon after an ORCID sign-in.
  const start = useCallback(() => {
    if (!none && !confirmed(s)) { setAsking(true); return; }
    setBusy(true);
    setError("");
    setNeedOrcid(false);
    addPasskey(field.current?.value.trim() ?? "").then((next) => { onChange(next); setNickname(""); setAsking(false); }, (err) => {
      if (err instanceof AccountError && err.code === "CONFIRM_REQUIRED" && !none) setAsking(true);
      else if (err instanceof AccountError && err.code === "ORCID_SIGN_IN_REQUIRED") setNeedOrcid(true);
      else setError(describe(err));
    }).finally(() => setBusy(false));
  }, [none, onChange, s]);
  useEffect(() => {
    const go = () => { field.current?.scrollIntoView({ block: "center" }); field.current?.focus(); start(); };
    window.addEventListener(ADD_PASSKEY_EVENT, go);
    return () => window.removeEventListener(ADD_PASSKEY_EVENT, go);
  }, [start]);
  const add = (e: React.FormEvent) => { e.preventDefault(); start(); };
  // After a removal, focus moves to the next passkey's Rename (or the last one's), never to the page body. It runs once
  // the list without the removed row has rendered.
  const focusRow = useRef<number | null>(null);
  useEffect(() => {
    if (focusRow.current === null) return;
    const rows = list.current?.querySelectorAll<HTMLElement>("[data-passkey-row]") ?? [];
    const row = rows[Math.min(focusRow.current, rows.length - 1)];
    focusRow.current = null;
    (row?.querySelector<HTMLButtonElement>("button") ?? field.current)?.focus();
  }, [s.passkeys]);
  const removed = (index: number) => (next: Settings) => { focusRow.current = index; onChange(next); };
  return (
    <div ref={list} className="grid gap-3" data-settings-passkeys={s.passkeys.length}>
      <h3 className="label text-muted-foreground">Passkeys</h3>
      {none ? (
        <p className="text-[13px] text-muted-foreground">This account has no passkey yet. It signs in another way (a test sign-in or ORCID).</p>
      ) : (
        <ul className="grid border-t border-rule">
          {s.passkeys.map((p, i) => (
            <PasskeyRow key={p.id} p={p} only={s.passkeys.length === 1} confirmedNow={confirmed(s)} onChange={onChange} onRemoved={removed(i)} onConfirm={() => setAsking(true)} />
          ))}
        </ul>
      )}
      <form className="flex flex-wrap items-center gap-3" onSubmit={add}>
        <label htmlFor="new-passkey" className="sr-only">Name for the new passkey</label>
        <Input ref={field} id="new-passkey" value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={80} placeholder="Name it, e.g. work laptop" className="h-9 max-w-xs bg-card" />
        <Button ref={addButton} type="submit" variant="outline" disabled={busy} data-add-passkey>
          <KeyRound aria-hidden />{busy ? "Waiting for your passkey…" : none ? "Add a passkey" : "Add another passkey"}
        </Button>
      </form>
      {needOrcid && (
        <p role="alert" className="max-w-xl text-[13px]" data-need-orcid>
          An account&apos;s first passkey can be added within five minutes of signing in with ORCID.{" "}
          <a href={orcidStartHref("/settings")} className={LINK}>Sign in with ORCID again</a>, then add it.
        </p>
      )}
      {asking && (
        <Confirm why="Adding or removing a passkey changes how this account is signed in to." s={s}
          onConfirmed={(next) => { onChange(next); setAsking(false); setTimeout(() => addButton.current?.focus()); }} />
      )}
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
    </div>
  );
}

function Recovery({ s, onChange }: { s: Settings; onChange: (s: Settings) => void }) {
  const [codes, setCodes] = useState<string[] | null>(null);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const button = useRef<HTMLButtonElement>(null);
  const regenerate = () => {
    if (!confirmed(s)) { setAsking(true); return; }
    setBusy(true);
    setError("");
    regenerateCodes().then((next) => { onChange(next); setCodes(next.recovery_codes); setAsking(false); }, (e) => {
      if (e instanceof AccountError && e.code === "CONFIRM_REQUIRED") setAsking(true);
      else setError(describe(e));
    }).finally(() => setBusy(false));
  };
  if (codes) return <RecoveryCodes codes={codes} onDone={() => { setCodes(null); setTimeout(() => button.current?.focus()); }} />;
  return (
    <div className="grid gap-3" data-settings-recovery={s.user.recovery_codes_left}>
      <h3 className="label text-muted-foreground">Recovery codes</h3>
      <p className="text-[13px]">
        <span className="font-mono tabular">{s.user.recovery_codes_left}</span> of 10 left. Each signs you in once if you lose your passkeys.
      </p>
      <p className="text-[13px]">
        <button ref={button} type="button" disabled={busy} onClick={regenerate} className={MUTED_LINK} data-regenerate>
          {busy ? "Making new codes…" : "Make ten new codes"}
        </button>
      </p>
      <p className="text-[12.5px] text-muted-foreground">The old ones stop working, and the new ones are shown once.</p>
      {asking && (
        <Confirm why="New recovery codes replace the ones you have." s={s}
          onConfirmed={(next) => { onChange(next); setAsking(false); setTimeout(() => button.current?.focus()); }} />
      )}
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
    </div>
  );
}

function Orcid({ s, onChange }: { s: Settings; onChange: (s: Settings) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [asking, setAsking] = useState(false);
  const outcome = ORCID_OUTCOME[useSearchParams().get("orcid") ?? ""] ?? "";
  const unlink = useRef<HTMLButtonElement>(null);
  const orcid = s.user.orcid;
  return (
    <div className="grid gap-2" data-settings-orcid={orcid ?? "none"}>
      <h3 className="label text-muted-foreground">ORCID</h3>
      {orcid ? (
        <p className={ACTIONS}>
          <span>Linked to <a href={orcidUrl(orcid)} className={cn("font-mono", LINK)}>{orcid}</a></span>
          <button ref={unlink} type="button" disabled={busy} className={MUTED_LINK} onClick={() => {
            if (s.passkeys.length > 0 && !confirmed(s)) { setAsking(true); return; }
            setBusy(true);
            setError("");
            unlinkOrcid().then((next) => { onChange(next); setAsking(false); }, (e) => {
              if (e instanceof AccountError && e.code === "CONFIRM_REQUIRED") setAsking(true);
              else setError(describe(e));
            }).finally(() => setBusy(false));
          }}>{busy ? "Unlinking…" : "Unlink"}</button>
        </p>
      ) : s.orcid_available ? (
        <p className="text-[13px]"><a href={orcidStartHref("/settings")} className={cn("inline-flex items-center gap-1", MUTED_LINK)}>Link your ORCID iD<ArrowUpRight aria-hidden className="size-3.5" /></a></p>
      ) : (
        <p className="text-[13px] text-muted-foreground">Not linked. ORCID sign-in is not switched on for this server yet.</p>
      )}
      {outcome && <p role="status" className="text-[13px] text-muted-foreground">{outcome}</p>}
      {asking && (
        <Confirm why="Unlinking ORCID changes how this account is signed in to." s={s}
          onConfirmed={(next) => { onChange(next); setAsking(false); setTimeout(() => unlink.current?.focus()); }} />
      )}
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
    </div>
  );
}

// The account's email address: sign-in codes go there. Adding or changing it needs a code sent to the new address;
// removing it needs a fresh confirmation, and is refused when the address is the account's only way in.
function Email({ s, onChange }: { s: Settings; onChange: (s: Settings) => void }) {
  const [changing, setChanging] = useState(false);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [said, setSaid] = useState("");
  const email = s.user.email;
  const linked = () => getSettings().then((next) => { onChange(next); setChanging(false); setSaid("Email address saved."); }, (e) => setError(describe(e)));
  const remove = () => {
    if (!confirmed(s)) { setAsking(true); return; }
    setBusy(true);
    setError("");
    removeEmail().then(() => getSettings()).then((next) => { onChange(next); setAsking(false); setSaid("Email address removed."); }, (e) => {
      if (e instanceof AccountError && e.code === "CONFIRM_REQUIRED") setAsking(true);
      else setError(describe(e));
    }).finally(() => setBusy(false));
  };
  if (!s.email_available && !email) {
    return (
      <div className="grid gap-2" data-settings-email="off">
        <h3 className="label text-muted-foreground">Email</h3>
        <p className="text-[13px] text-muted-foreground">Email sign-in is not switched on for this server yet.</p>
      </div>
    );
  }
  return (
    <div className="grid gap-2" data-settings-email={email ? "linked" : "none"}>
      <h3 className="label text-muted-foreground">Email</h3>
      <p className="text-[12.5px] text-muted-foreground">You can sign in with a code sent to this address. locus sends nothing else to it.</p>
      {email && !changing && (
        <p className={ACTIONS}>
          <span className="font-mono">{email}</span>
          {s.email_available && <button type="button" className={MUTED_LINK} onClick={() => { setChanging(true); setSaid(""); }}>Change</button>}
          <button type="button" className={MUTED_LINK} disabled={busy} onClick={remove}>{busy ? "Removing…" : "Remove"}</button>
        </p>
      )}
      {(!email || changing) && s.email_available && (
        <EmailCode purpose="link" idPrefix="settings-email" sendLabel={email ? "Send a code to the new address" : "Send a code"} onDone={linked} />
      )}
      {changing && <p className="text-[13px]"><button type="button" className={MUTED_LINK} onClick={() => setChanging(false)}>Keep {email}</button></p>}
      <span role="status" className="text-[13px] text-muted-foreground">{said}</span>
      {asking && <Confirm why="Removing your email address changes how this account is signed in to." s={s} onConfirmed={(next) => { onChange(next); setAsking(false); }} />}
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- Following

function Following() {
  const w = useWatches();
  const [people, setPeople] = useState<Follow[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { listFollows().then(setPeople, (e) => setError(describe(e))); }, []);
  const drop = (orcid: string) => unfollow(orcid).then(() => setPeople((p) => (p ?? []).filter((x) => x.orcid !== orcid)), (e) => setError(describe(e)));
  const stop = (question: string) => setWatch(question, null).catch((e) => setError(describe(e)));
  return (
    <div className="grid gap-6">
      <div className="grid gap-2" data-settings-people={people?.length ?? "loading"}>
        <h3 className="label text-muted-foreground">People</h3>
        {people === null ? (
          !error && <p className="text-[13px] text-muted-foreground">Reading who you follow…</p>
        ) : people.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">You follow no one yet. A person page offers Follow when their name resolves to one ORCID iD.</p>
        ) : (
          <ul className="grid border-t border-rule">
            {people.map((p) => (
              <li key={p.orcid} className={ROW} data-settings-person={p.orcid}>
                <span className="grid gap-0.5">
                  <span className="text-[14.5px]">{p.display_name}</span>
                  <span className="font-mono text-[11.5px] tabular text-muted-foreground">{p.orcid} · since {day(p.followed_at)}</span>
                </span>
                <button type="button" className={cn("text-[13px]", MUTED_LINK)} onClick={() => drop(p.orcid)} aria-label={`Unfollow ${p.display_name}`}>Unfollow</button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="grid gap-2" data-settings-questions={w.status === "signed-in" ? w.watches.length : w.status}>
        <h3 className="label text-muted-foreground">Watched searches</h3>
        {w.status === "loading" ? (
          <p className="text-[13px] text-muted-foreground">Reading your watched searches…</p>
        ) : w.watches.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">No watched searches. Run a search and choose Watch this search.</p>
        ) : (
          <ul className="grid border-t border-rule">
            {w.watches.map((x) => (
              <li key={x.question} className={ROW} data-settings-question={x.question}>
                <span className="grid gap-0.5">
                  <a href={`/?q=${encodeURIComponent(x.question)}`} className={cn("text-[14.5px]", LINK)}>{x.question}</a>
                  <span className="font-mono text-[11.5px] tabular text-muted-foreground">watching since {x.since}</span>
                </span>
                <button type="button" className={cn("text-[13px]", MUTED_LINK)} onClick={() => stop(x.question)} aria-label={`Stop watching ${x.question}`}>Stop watching</button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <p className="text-[13px]"><Link href="/following" className={MUTED_LINK}>See what is new on the Following page</Link></p>
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- Delete

function DeleteAccount({ s, onChange, onDeleted }: { s: Settings; onChange: (s: Settings) => void; onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const start = useRef<HTMLButtonElement>(null);
  const final = useRef<HTMLButtonElement>(null);
  const moved = useRef(false);
  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    (open ? final : start).current?.focus();
  }, [open]);
  const remove = () => {
    if (!confirmed(s)) { setAsking(true); return; }
    setBusy(true);
    setError("");
    deleteAccount().then(onDeleted, (e) => {
      if (e instanceof AccountError && e.code === "CONFIRM_REQUIRED") setAsking(true);
      else setError(describe(e));
    }).finally(() => setBusy(false));
  };
  return (
    <div className="grid gap-4 text-[14px]">
      <p className="max-w-xl text-muted-foreground">
        Deleting removes the account and everything in it at once: passkeys, recovery codes, the ORCID link, every list with its notes and tags, public links (they stop opening), watched searches and the people you follow. It cannot be undone. Download your data first if you want a copy.
      </p>
      {!open ? (
        <p><Button ref={start} variant="outline" onClick={() => { moved.current = true; setOpen(true); }} data-delete-start>Delete account…</Button></p>
      ) : (
        <div className="grid gap-4" data-delete-open>
          <div className="flex flex-wrap items-center gap-3">
            <Button ref={final} disabled={busy} onClick={remove} data-delete-confirm>{busy ? "Deleting…" : "Delete my account and everything in it"}</Button>
            <Button variant="outline" disabled={busy} onClick={() => { moved.current = true; setAsking(false); setOpen(false); }}>Keep my account</Button>
          </div>
          {asking && (
            <Confirm why="Deleting an account needs a fresh check that it is you." s={s}
              onConfirmed={(next) => { onChange(next); setAsking(false); setTimeout(() => final.current?.focus()); }} />
          )}
          {confirmed(s) && !asking && s.confirmed_until && <p role="status" className="text-[13px] text-muted-foreground">Confirmed. You can delete until {s.confirmed_until.slice(11, 16)} UTC.</p>}
        </div>
      )}
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- page

export function SettingsPage() {
  const [state, setState] = useState<"loading" | "guest" | "failed" | "deleted" | Settings>("loading");
  const load = useCallback(() => {
    me().then((m) => (m.user ? getSettings().then(setState) : setState((s) => (s === "deleted" ? s : "guest"))))
      .catch(() => setState((s) => (s === "deleted" ? s : "failed")));
  }, []);
  useEffect(() => {
    load();
    window.addEventListener(ACCOUNT_EVENT, load);
    return () => window.removeEventListener(ACCOUNT_EVENT, load);
  }, [load]);
  const heading = useRef<HTMLHeadingElement>(null);
  const s = typeof state === "object" ? state : null;
  const status = s ? "signed-in" : state;

  return (
    <div className="mx-auto grid w-full max-w-3xl gap-10" data-settings-page={status}>
      <Nav />
      <header className="grid gap-3">
        <h1 ref={heading} tabIndex={-1} className="font-display text-[34px] leading-[1.08] outline-none sm:text-[44px]">{state === "deleted" ? "Account deleted" : "Settings"}</h1>
        {s && <p className="text-[15px] text-muted-foreground">Signed in as <span className="text-foreground">{s.user.display_name}</span> since {day(s.user.created_at)}.</p>}
      </header>

      {state === "loading" ? (
        <p className="text-[13px] text-muted-foreground">Reading your settings…</p>
      ) : state === "failed" ? (
        <p role="alert" className="text-[13px]">locus could not read your settings. Reload the page to try again.</p>
      ) : state === "guest" ? (
        <EmptyState
          id="settings-signed-out"
          title="Settings belong to an account"
          ways={[{ href: signInHref("/settings"), label: "Sign in or create an account" }, { href: "/privacy", label: "What locus keeps" }]}
        >
          Sign in to change your name, passkeys and recovery codes, or to download or delete your data.
        </EmptyState>
      ) : state === "deleted" ? (
        <div role="status" className="grid max-w-xl gap-2 text-[14px]">
          <p>Your account and everything in it are gone, and this browser is signed out.</p>
          <p><Link href="/" className={LINK}>Back to search</Link></p>
        </div>
      ) : (
        <>
          <nav aria-label="Settings sections" className={cn(ACTIONS, "-mt-4")}>
            {[["account", "Account"], ["following", "Following"], ["privacy", "Privacy"], ["data", "Your data"], ["delete", "Delete account"]].map(([id, label]) => (
              <a key={id} href={`#${id}`} className={MUTED_LINK}>{label}</a>
            ))}
          </nav>
          <Section id="account" title="Account">
            <DisplayName s={state} onChange={setState} />
            <Email s={state} onChange={setState} />
            <Passkeys s={state} onChange={setState} />
            <Recovery s={state} onChange={setState} />
            <Orcid s={state} onChange={setState} />
          </Section>
          <Section id="following" title="Following">
            <Following />
          </Section>
          <Section id="privacy" title="Privacy">
            <p className="max-w-xl text-[14px] leading-relaxed">{PRIVACY_SUMMARY}</p>
            <p className="text-[13px]"><Link href={PRIVACY_PATH} className={MUTED_LINK} data-privacy-link>How accounts work</Link></p>
          </Section>
          <Section id="data" title="Your data">
            <p className="max-w-xl text-[14px] text-muted-foreground">One JSON file with everything above: your lists and items, notes and tags, watched searches, follows, passkey names, sign-in history and the account log. It leaves out secrets such as passkey keys and code hashes.</p>
            <p><a href={exportHref} download className={cn("inline-flex items-center gap-1.5 text-[13px]", LINK)} data-export><Download aria-hidden className="size-3.5" />Download everything as JSON</a></p>
          </Section>
          <Section id="delete" title="Delete account">
            <DeleteAccount s={state} onChange={setState} onDeleted={() => { setState("deleted"); setTimeout(() => heading.current?.focus()); }} />
          </Section>
        </>
      )}
    </div>
  );
}
