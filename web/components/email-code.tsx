"use client";
import { useEffect, useRef, useState } from "react";
import { Mail } from "lucide-react";
import { MUTED_LINK } from "@/components/page-kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { describe, emailCode, verifyEmailCode, type Account, type EmailPurpose } from "@/lib/account";

// Two steps in one place: an address (skipped for "confirm", which mails the account's own address), then the six-digit
// code from the email. Used to sign in or create an account, to add an address in Settings, and to confirm it is you.
export function EmailCode({ purpose, idPrefix, sendLabel, onDone }: {
  purpose: EmailPurpose; idPrefix: string; sendLabel: string; onDone: (r: { user: Account; created?: boolean }) => void;
}) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<{ challenge_id: string; sent_to: string } | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState<"" | "send" | "check">("");
  const [error, setError] = useState("");
  const codeField = useRef<HTMLInputElement>(null);
  useEffect(() => { if (sent) codeField.current?.focus(); }, [sent]);

  const ask = (e?: React.FormEvent) => {
    e?.preventDefault();
    setBusy("send");
    setError("");
    emailCode(purpose, email.trim()).then((s) => { setSent(s); setCode(""); }, (err) => setError(describe(err))).finally(() => setBusy(""));
  };
  const check = (e: React.FormEvent) => {
    e.preventDefault();
    if (!sent) return;
    setBusy("check");
    setError("");
    verifyEmailCode(sent.challenge_id, code).then(onDone, (err) => {
      setError(describe(err));
      if (err?.code === "CHALLENGE_EXPIRED") setSent(null);
    }).finally(() => setBusy(""));
  };

  return (
    <div className="grid gap-3" data-email-code={purpose}>
      {!sent ? (
        <form className="grid gap-3" onSubmit={ask}>
          {purpose !== "confirm" && <label htmlFor={`${idPrefix}-email`} className="label text-muted-foreground">Email address</label>}
          <div className="flex flex-wrap gap-3">
            {purpose !== "confirm" && (
              <Input id={`${idPrefix}-email`} type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} autoComplete="email"
                placeholder="you@university.ac.uk" className="h-9 max-w-xs bg-card" />
            )}
            <Button type="submit" size="lg" variant={purpose === "sign-in" ? "default" : "outline"} disabled={!!busy || (purpose !== "confirm" && !email.trim())}>
              <Mail aria-hidden />{busy === "send" ? "Sending…" : sendLabel}
            </Button>
          </div>
        </form>
      ) : (
        <form className="grid gap-3" onSubmit={check}>
          <p role="status" className="text-[13px]">We sent a six-digit code to <span className="font-medium">{sent.sent_to}</span>. It works for ten minutes.</p>
          <label htmlFor={`${idPrefix}-code`} className="label text-muted-foreground">Code from the email</label>
          <div className="flex flex-wrap items-center gap-3">
            <Input ref={codeField} id={`${idPrefix}-code`} value={code} onChange={(e) => setCode(e.target.value)} maxLength={12} inputMode="numeric"
              autoComplete="one-time-code" spellCheck={false} placeholder="123456" className="h-9 max-w-[10rem] bg-card font-mono tabular" />
            <Button type="submit" size="lg" disabled={!!busy || code.replace(/\D/g, "").length !== 6}>{busy === "check" ? "Checking…" : "Continue"}</Button>
            <button type="button" className={MUTED_LINK} disabled={!!busy} onClick={() => ask()}>Send a new code</button>
            {purpose !== "confirm" && <button type="button" className={MUTED_LINK} disabled={!!busy} onClick={() => { setSent(null); setError(""); }}>Use another address</button>}
          </div>
        </form>
      )}
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
    </div>
  );
}
