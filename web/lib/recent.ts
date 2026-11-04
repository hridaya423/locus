// The last few questions searched in this browser, for the command palette (F8). They stay in local storage, are never
// sent to the server, and /privacy says so. A question is stored in the same trimmed form as the address (?q=).
export const RECENT = "locus:recent";
export const RECENT_LIMIT = 8;

export function recentSearches(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT) ?? "[]");
    return Array.isArray(raw) ? raw.filter((q): q is string => typeof q === "string" && q.trim() !== "").slice(0, RECENT_LIMIT) : [];
  } catch {
    return [];
  }
}

export function rememberSearch(question: string): void {
  const q = question.trim();
  if (!q) return;
  try {
    localStorage.setItem(RECENT, JSON.stringify([q, ...recentSearches().filter((r) => r !== q)].slice(0, RECENT_LIMIT)));
  } catch {}
}

// The palette asks the mounted search page to run a question; any other page navigates to /?q=, which runs it on load.
export const SEARCH_EVENT = "locus:search";
export const askSearch = (question: string) => window.dispatchEvent(new CustomEvent<string>(SEARCH_EVENT, { detail: question }));
// The header's Search link asks a mounted search page to clear itself, as the logo does.
export const HOME_EVENT = "locus:home";
