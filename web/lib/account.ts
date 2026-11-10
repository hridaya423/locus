// Accounts: who is signed in, passkey and recovery-code sign-in, sign out. The API is reached through the web app's own
// /api rewrite, so the HttpOnly session cookie is first-party and the browser sends it by itself.
import { API } from "@/lib/api";

export type Account = { id: number; display_name: string; created_at: string; orcid: string | null; email: string | null; passkeys: number; recovery_codes_left: number };
export type Me = { user: Account | null; orcid_available: boolean; email_available: boolean };

// The API's shared error shape: {"error": {"code", "message", "transient"}}.
export class AccountError extends Error {
  constructor(public code: string, message: string, public transient = false) {
    super(message);
  }
}

// Every account change goes out as JSON with X-Locus-Intent: 1; the API refuses state-changing requests without both.
export async function send<T>(path: string, body: unknown = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Locus-Intent": "1" },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error;
    throw new AccountError(e?.code ?? `HTTP_${res.status}`, e?.message ?? `locus answered ${res.status}. Please try again.`, e?.transient ?? res.status >= 500);
  }
  return data as T;
}

export async function me(): Promise<Me> {
  const res = await fetch(`${API}/account/me`, { credentials: "same-origin", cache: "no-store" });
  if (!res.ok) throw new AccountError(`HTTP_${res.status}`, "locus could not check whether you are signed in.", true);
  return res.json();
}

// Tells every account-aware component (the header menu, the account page) that sign-in state changed.
export const ACCOUNT_EVENT = "locus:account";
export const announce = () => window.dispatchEvent(new Event(ACCOUNT_EVENT));

export async function signOut(): Promise<void> {
  await send("/account/sign-out");
  announce();
}

type Options<T> = { challenge_id: string; options: T };

export async function createWithPasskey(displayName: string): Promise<{ user: Account; recovery_codes: string[] }> {
  const { startRegistration } = await import("@simplewebauthn/browser");
  const start = await send<Options<Parameters<typeof startRegistration>[0]["optionsJSON"]>>("/account/register/options", { display_name: displayName });
  const credential = await startRegistration({ optionsJSON: start.options });
  const done = await send<{ user: Account; recovery_codes: string[] }>("/account/register/verify", { challenge_id: start.challenge_id, credential });
  announce();
  return done;
}

export async function signInWithPasskey(): Promise<Account> {
  const { startAuthentication } = await import("@simplewebauthn/browser");
  const start = await send<Options<Parameters<typeof startAuthentication>[0]["optionsJSON"]>>("/account/login/options");
  const credential = await startAuthentication({ optionsJSON: start.options });
  const done = await send<{ user: Account }>("/account/login/verify", { challenge_id: start.challenge_id, credential });
  announce();
  return done.user;
}

export async function signInWithRecoveryCode(code: string): Promise<Account> {
  const done = await send<{ user: Account }>("/account/recovery", { code });
  announce();
  return done.user;
}

// Email codes: ask for a six-digit code, then type it back. "sign-in" signs in or creates an account; "link" adds the
// address to the signed-in account; "confirm" sends to the account's own address and marks this session as confirmed.
export type EmailPurpose = "sign-in" | "link" | "confirm";
export async function emailCode(purpose: EmailPurpose, email = ""): Promise<{ challenge_id: string; sent_to: string }> {
  return send("/account/email/start", { purpose, email });
}

export async function verifyEmailCode(challengeId: string, code: string): Promise<{ user: Account; created?: boolean }> {
  const done = await send<{ user: Account; created?: boolean }>("/account/email/verify", { challenge_id: challengeId, code });
  announce();
  return done;
}

export async function removeEmail(): Promise<Account> {
  const done = await send<{ user: Account }>("/account/email/unlink");
  announce();
  return done.user;
}

// Where to go after signing in: only a path on this site, never another origin.
export function safeReturn(path: string | null | undefined): string | null {
  return path && path.startsWith("/") && !path.startsWith("//") && !path.includes("\\") && path.length <= 500 ? path : null;
}

// The sign-in page, remembering where the reader was (papertok's auth-return idea).
export function signInHref(returnTo: string): string {
  const back = safeReturn(returnTo);
  return back && back !== "/account" && !back.startsWith("/account?") ? `/account?return=${encodeURIComponent(back)}` : "/account";
}

export const orcidStartHref = (returnTo: string) => `${API}/account/orcid/start?to=${encodeURIComponent(safeReturn(returnTo) ?? "/account")}`;

// A browser's own refusal (the user closed the passkey dialog) reads as a cancellation, not a failure.
export function describe(error: unknown): string {
  if (error instanceof AccountError) return error.message;
  if (error instanceof Error && (error.name === "NotAllowedError" || error.name === "AbortError")) return "The passkey request was cancelled or timed out.";
  // Browsers allow passkeys only on https or localhost; anywhere else the request fails before any dialog shows.
  if (error instanceof Error && (error.name === "SecurityError" || !window.isSecureContext)) return "Passkeys only work on a secure (https) address. Sign in with an email code instead.";
  if (error instanceof Error && error.name === "InvalidStateError") return "This device already holds a passkey for this account.";
  return "Something went wrong. Please try again.";
}
