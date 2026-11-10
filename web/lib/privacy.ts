// What locus keeps for an account, as the /privacy page and the Privacy section of /settings state it (F7-r1-2).
// This module is the one source of truth for the user-facing facts; docs/accounts.md ("What locus stores") points
// here for the wording users read and keeps the operator detail. Change both when the users DB changes.

export const PRIVACY_PATH = "/privacy";

// One paragraph for /settings.
export const PRIVACY_SUMMARY =
  "For an account, locus keeps your display name, the public half of each passkey, scrambled copies of your recovery codes and sign-in tokens, which browser each sign-in came from, your email address if you give one, your ORCID iD if you link one, your lists with their notes and tags, your watched searches, the people you follow, and a log of account events such as sign-ins, kept until you delete the account. Like most web servers, it also logs each request with your IP address. It runs no analytics. It sets one cookie that keeps you signed in, and a short-lived one during an ORCID sign-in.";

export type PrivacyFact = { id: string; title: string; body: string[] };

export const PRIVACY_FACTS: PrivacyFact[] = [
  {
    id: "without-an-account",
    title: "Without an account",
    body: [
      "Searching and reading dataset pages need no account. Datasets you save and searches you watch without one stay in this browser's local storage and never reach the server until you sign in and choose to bring them into an account.",
      "The browser also keeps your last eight questions for the Go to box, the dataset records you opened from a search, and whether you declined to bring saved items into an account. These stay in this browser and are never sent to the server.",
    ],
  },
  {
    id: "what-is-kept",
    title: "What locus keeps for an account",
    body: [
      "Your display name and when the account was made.",
      "Each passkey's public half, its name, when it was added and last used. The private half stays on your device or in your password manager.",
      "Your recovery codes as SHA-256 hashes only. locus shows the codes once and cannot show them again.",
      "Sessions: a hash of the sign-in token, how you signed in, when, and which browser each sign-in came from (its user-agent string).",
      "Your email address, if you sign in with one or add one. locus uses it only to send sign-in codes, through the email service Brevo, and sends nothing else to it. Each code is kept as a hash for ten minutes; a hash of the address and the time of each code sent are kept for a day, to limit how many codes one address gets.",
      "Your ORCID iD, if you link one.",
      "Your lists with their items, notes and tags, and the public copy of any list you share.",
      "Your watched searches and the people you follow, with the datasets you marked as seen.",
      "A log of account events such as sign-ins, new passkeys and new recovery codes, kept until you delete the account.",
      "The times of your changes in the last minute, so that one account cannot flood the server. Older times are dropped.",
    ],
  },
  {
    id: "cookies",
    title: "Cookies and tracking",
    body: [
      "locus sets one cookie that keeps you signed in, and a short-lived one (five minutes) during an ORCID sign-in. Both are HttpOnly and first-party.",
      "It runs no analytics and shows no adverts. It asks for no email address.",
    ],
  },
  {
    id: "where",
    title: "Where it is kept",
    body: [
      "Account data lives in its own database file on the server that runs locus, apart from the public dataset catalogue. It is not shared or sold.",
      "Like most web servers, the server's request log records your IP address, the time and the address of each page or search you open. How long it is kept depends on how the server is set up; it is not part of the account data and deleting an account does not touch it.",
      "The limits on sign-in attempts and on researcher-page lookups, which apply to guests too, hold your address in memory only and never write it down. An address is dropped the next time that limit is checked after a minute has passed, and every address is forgotten when the server restarts.",
      "An ORCID sign-in asks ORCID only for your iD and name. To show what is new from the people you follow, the server looks up their ORCID iDs in Europe PMC; your own identity is not part of that request.",
    ],
  },
  {
    id: "your-copy",
    title: "Your copy, and deleting it",
    body: [
      "Settings has Download everything as JSON: every row kept about your account, without secrets such as token hashes, code hashes and passkey keys.",
      "Deleting the account in Settings removes all of the above in one step, signs out every device and makes your public links stop opening. One log row stays with the time and \"account deleted\", and nothing in it points at you.",
    ],
  },
];
