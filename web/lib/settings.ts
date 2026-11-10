// Settings (F7): the account as /settings shows it, and every change it can make. The API is /api/account/* (settings.py).
// Deleting the account and regenerating recovery codes need a passkey or recovery-code check within five minutes;
// the API answers CONFIRM_REQUIRED otherwise, and confirmPasskey / confirmCode record one on this session.
import { API } from "@/lib/api";
import { AccountError, announce, type Account } from "@/lib/account";

export type Passkey = { id: string; nickname: string; created_at: string; last_used_at: string | null };
export type Settings = {
  user: Account; passkeys: Passkey[]; orcid_available: boolean; email_available: boolean; session_method: string; confirmed_until: string | null;
};

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

export const getSettings = () => call<Settings>("GET", "/account/settings");
export const rename = async (display_name: string) => {
  const s = await call<Settings>("PATCH", "/account/profile", { display_name });
  announce();
  return s;
};
export const renamePasskey = (id: string, nickname: string) => call<Settings>("PATCH", `/account/passkeys/${encodeURIComponent(id)}`, { nickname });
export const removePasskey = (id: string) => call<Settings>("DELETE", `/account/passkeys/${encodeURIComponent(id)}`);
export const unlinkOrcid = () => call<Settings>("DELETE", "/account/orcid");
export const regenerateCodes = () => call<Settings & { recovery_codes: string[] }>("POST", "/account/recovery-codes");
export const exportHref = `${API}/account/export`;

type Options<T> = { challenge_id: string; options: T };

// Adds another passkey with the same ceremony as creating an account (F1), for the signed-in account.
export async function addPasskey(nickname: string): Promise<Settings> {
  const { startRegistration } = await import("@simplewebauthn/browser");
  const start = await call<Options<Parameters<typeof startRegistration>[0]["optionsJSON"]>>("POST", "/account/passkeys/options");
  const credential = await startRegistration({ optionsJSON: start.options });
  return call<Settings>("POST", "/account/passkeys/verify", { challenge_id: start.challenge_id, credential, nickname });
}

// A passkey check for the account already signed in: only its own passkeys are offered, and the session is confirmed
// for five minutes.
export async function confirmPasskey(): Promise<Settings> {
  const { startAuthentication } = await import("@simplewebauthn/browser");
  const start = await call<Options<Parameters<typeof startAuthentication>[0]["optionsJSON"]>>("POST", "/account/confirm/options");
  const credential = await startAuthentication({ optionsJSON: start.options });
  return call<Settings>("POST", "/account/confirm/verify", { challenge_id: start.challenge_id, credential });
}

export const confirmCode = (code: string) => call<Settings>("POST", "/account/confirm/recovery", { code });

export async function deleteAccount(): Promise<void> {
  await call("DELETE", "/account");
  announce();
}

export const PRIVACY_DOC = "https://github.com/jurilw/locus/blob/accounts/docs/accounts.md";
