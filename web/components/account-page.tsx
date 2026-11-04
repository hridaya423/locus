"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowUpRight, KeyRound } from "lucide-react";
import { Wordmark } from "@/components/logo";
import { BackToResults } from "@/components/back-to-results";
import { EmailCode } from "@/components/email-code";
import { Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ACCOUNT_EVENT, createWithPasskey, describe, me, orcidStartHref, safeReturn, signInWithPasskey, signInWithRecoveryCode, signOut, type Me,
} from "@/lib/account";
import { cn } from "@/lib/utils";

export const ORCID_OUTCOME: Record<string, string> = {
  linked: "Your ORCID iD is now linked to this account.",
  "signed-in": "You are signed in with ORCID.",
  "in-use": "That ORCID iD is already linked to another locus account.",
  "confirm-first": "Linking ORCID needs a fresh check that it is you. Confirm in Settings, then link it within five minutes.",
  "already-linked": "This account already has an ORCID iD, and it is the account's only way in, so it stays.",
  cancelled: "ORCID sign-in was cancelled.",
  expired: "That ORCID sign-in took too long. Please start again.",
  failed: "The ORCID step could not be completed in this browser. Please start again.",
};

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div data-fact className="grid gap-1 border-rule pr-4 [&:nth-child(2n)]:border-l [&:nth-child(2n)]:pl-4 sm:[&:not(:first-child)]:border-l sm:[&:not(:first-child)]:pl-4">
      <span className="label text-muted-foreground">{label}</span>
      <span className="font-mono text-[13px] tabular">{children}</span>
    </div>
  );
}

export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <section aria-labelledby="codes" className="grid max-w-xl gap-4">
      <Heading id="codes" count={codes.length}>Your recovery codes</Heading>
      <p className="text-[14px] text-muted-foreground">
        If you lose your passkey, each code signs you in once. locus keeps only a scrambled copy, so this is the only time
        you will see them. Save them in a password manager or print them.
      </p>
      <ol className="grid grid-cols-2 gap-x-6 gap-y-1.5 rounded-lg border border-rule bg-card p-4 font-mono text-[14px] tabular sm:grid-cols-2" data-recovery-codes>
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ol>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" onClick={() => navigator.clipboard.writeText(codes.join("\n")).then(() => setCopied(true), () => setCopied(false))}>
          {copied ? "Copied" : "Copy the codes"}
        </Button>
        <Button onClick={onDone}>I have saved them</Button>
      </div>
    </section>
  );
}

export function AccountPage() {
  const router = useRouter();
  const params = useSearchParams();
  const back = safeReturn(params.get("return"));
  const outcome = params.get("orcid");
  const [state, setState] = useState<Me | null>(null);
  const [failed, setFailed] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState<"" | "create" | "passkey" | "code" | "out">("");
  const [error, setError] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);

  const refresh = useCallback(() => {
    me().then((m) => { setState(m); setFailed(false); }, () => setFailed(true));
  }, []);
  useEffect(() => {
    refresh();
    window.addEventListener(ACCOUNT_EVENT, refresh);
    return () => window.removeEventListener(ACCOUNT_EVENT, refresh);
  }, [refresh]);

  const run = (kind: typeof busy, work: () => Promise<unknown>, after?: () => void) => {
    setBusy(kind);
    setError("");
    work().then(() => after?.(), (e) => setError(describe(e))).finally(() => setBusy(""));
  };
  const goBack = () => { if (back) router.push(back); };

  const user = state?.user;
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-10">
      <nav className="flex items-center gap-5"><Link href="/" aria-label="locus home" className="leading-none"><Wordmark className="text-[30px]" /></Link><BackToResults /></nav>
      <header className="grid gap-3">
        <h1 className="font-display text-[34px] leading-[1.08] sm:text-[44px]">{user ? "Your account" : "Sign in to locus"}</h1>
        {!user && (
          <p className="max-w-xl text-[15px] text-muted-foreground">
            Everything in locus works without an account. Signing in keeps what you save on every device you use.
          </p>
        )}
      </header>

      {outcome && ORCID_OUTCOME[outcome] && <p role="status" className="text-[13px]">{ORCID_OUTCOME[outcome]}</p>}
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
      {failed && <p role="alert" className="text-[13px] text-destructive">locus could not check whether you are signed in. Please reload the page.</p>}

      {codes ? (
        <RecoveryCodes codes={codes} onDone={() => { setCodes(null); goBack(); }} />
      ) : !state ? (
        !failed && <p className="text-[13px] text-muted-foreground">Checking whether you are signed in…</p>
      ) : user ? (
        <section aria-labelledby="signed-in" className="grid gap-6" data-account-page="signed-in">
          <p id="signed-in" className="text-[15px]">Signed in as <span className="font-medium">{user.display_name}</span>{user.email && <> with <span className="font-mono text-[14px]">{user.email}</span></>}.</p>
          <div data-account-stats className="grid grid-cols-2 gap-y-3 border-y border-rule py-3 sm:flex sm:flex-wrap">
            <Fact label="Passkeys">{user.passkeys}</Fact>
            <Fact label="Recovery codes left">{user.recovery_codes_left}</Fact>
            <Fact label="ORCID">{user.orcid ?? "not linked"}</Fact>
            <Fact label="Since">{user.created_at.slice(0, 10)}</Fact>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-[13px]">
            {back && <Link href={back} className={LINK}>Back to where you were</Link>}
            {state.orcid_available && !user.orcid && <a href={orcidStartHref("/account")} className={cn("flex items-center gap-1", MUTED_LINK)}>Link your ORCID iD<ArrowUpRight aria-hidden className="size-3.5" /></a>}
            <Button variant="outline" disabled={!!busy} onClick={() => run("out", signOut)}>{busy === "out" ? "Signing out…" : "Sign out"}</Button>
          </div>
        </section>
      ) : (
        <div className="grid gap-10" data-account-page="guest">
          {state.email_available && (
            <section aria-labelledby="by-email" className="grid max-w-xl gap-4">
              <Heading id="by-email">Sign in with email</Heading>
              <p className="text-[14px] text-muted-foreground">
                locus emails you a six-digit code. If no account uses the address yet, the code creates one. There is no
                password, and locus sends nothing else to the address.
              </p>
              <EmailCode purpose="sign-in" idPrefix="sign-in" sendLabel="Email me a code" onDone={() => { refresh(); goBack(); }} />
            </section>
          )}
          <section aria-labelledby="sign-in" className={cn("grid max-w-xl gap-4", state.email_available && "border-t border-rule pt-8")}>
            <Heading id="sign-in">{state.email_available ? "Sign in with a passkey" : "Sign in"}</Heading>
            <div className="flex flex-wrap items-center gap-3">
              <Button disabled={!!busy} onClick={() => run("passkey", signInWithPasskey, goBack)}>
                <KeyRound aria-hidden />{busy === "passkey" ? "Waiting for your passkey…" : "Sign in with a passkey"}
              </Button>
              {state.orcid_available && (
                <a href={orcidStartHref(back ?? "/account")} className={cn("flex items-center gap-1 text-[13px]", MUTED_LINK)}>Sign in with ORCID<ArrowUpRight aria-hidden className="size-3.5" /></a>
              )}
            </div>
          </section>

          <section aria-labelledby="create" className="grid max-w-xl gap-4 border-t border-rule pt-8">
            <Heading id="create">{state.email_available ? "Create an account with a passkey" : "Create an account"}</Heading>
            <p className="text-[14px] text-muted-foreground">
              A passkey is held by your phone, computer or password manager. There is no password to remember
              {state.email_available ? ", and you can add an email address later in Settings." : " and no email address to give."}
            </p>
            <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); run("create", () => createWithPasskey(name.trim()).then((d) => setCodes(d.recovery_codes))); }}>
              <label htmlFor="display-name" className="label text-muted-foreground">Display name</label>
              <div className="flex flex-wrap gap-3">
                <Input id="display-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} autoComplete="nickname"
                  placeholder="How locus should greet you" className="h-9 max-w-xs bg-card" />
                <Button type="submit" size="lg" disabled={!!busy || !name.trim()}>{busy === "create" ? "Waiting for your passkey…" : "Create with a passkey"}</Button>
              </div>
            </form>
          </section>

          <section aria-labelledby="recover" className="grid max-w-xl gap-4 border-t border-rule pt-8">
            <Heading id="recover">Lost your passkey?</Heading>
            <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); run("code", () => signInWithRecoveryCode(code.trim()), goBack); }}>
              <label htmlFor="recovery-code" className="label text-muted-foreground">Recovery code</label>
              <div className="flex flex-wrap gap-3">
                <Input id="recovery-code" value={code} onChange={(e) => setCode(e.target.value)} maxLength={40} autoComplete="one-time-code" spellCheck={false}
                  placeholder="ABCD-EFGH-JKLM" className="h-9 max-w-xs bg-card font-mono" />
                <Button type="submit" size="lg" variant="outline" disabled={!!busy || !code.trim()}>{busy === "code" ? "Checking…" : "Sign in with a recovery code"}</Button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
