"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown } from "lucide-react";
import { MUTED_LINK } from "@/components/page-kit";
import { ACCOUNT_EVENT, me, signInHref, signOut, type Account } from "@/lib/account";
import { cn } from "@/lib/utils";
import { HOME_EVENT } from "@/lib/recent";
import { PaletteButton } from "@/components/command-palette";

// The account menu holds what belongs to the account alone; Search, Following and Lists sit in the site navigation.
const ITEMS = [{ href: "/settings", label: "Settings" }];

// Site navigation (F8 d): Search · Following · Lists, the current one marked. Lists is there for guests too, since a
// guest's saved datasets live on /lists (F2-r1-1); Following needs an account, so a guest is not sent to it.
const NAV = [
  { href: "/", label: "Search", current: (p: string) => p === "/", guest: true },
  { href: "/following", label: "Following", current: (p: string) => p.startsWith("/following"), guest: false },
  { href: "/lists", label: "Lists", current: (p: string) => p.startsWith("/lists"), guest: true },
];

const NAV_LINK = "transition-colors duration-150 hover:text-foreground";
const NAV_ON = "text-foreground underline decoration-signal decoration-2 underline-offset-[6px]";

function SiteNav({ pathname, signedIn }: { pathname: string; signedIn: boolean }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const items = NAV.filter((n) => signedIn || n.guest);
  const here = items.find((n) => n.current(pathname));

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", escape); };
  }, [open]);

  const link = (n: (typeof NAV)[number], extra = "") => (
    <Link
      href={n.href}
      prefetch={false}
      aria-current={n.current(pathname) ? "page" : undefined}
      onClick={() => {
        setOpen(false);
        // The search page stays mounted when only the address changes; this tells it to go back to its home state.
        if (n.href === "/") window.dispatchEvent(new Event(HOME_EVENT));
      }}
      className={cn(NAV_LINK, n.current(pathname) ? NAV_ON : "text-muted-foreground", extra)}
    >
      {n.label}
    </Link>
  );

  return (
    <nav aria-label="Main" data-site-nav>
      <ul className="hidden items-baseline gap-4 sm:flex">
        {items.map((n) => <li key={n.href}>{link(n)}</li>)}
      </ul>
      <div ref={box} className="relative sm:hidden">
        <button
          ref={button}
          type="button"
          aria-expanded={open}
          aria-controls="site-menu"
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1 text-muted-foreground transition-colors duration-150 hover:text-foreground"
        >
          <span>{here?.label ?? "Menu"}</span>
          <ChevronDown aria-hidden className={cn("size-3.5 shrink-0 transition-transform duration-150", open && "rotate-180")} />
        </button>
        {open && (
          <ul id="site-menu" className="absolute right-0 mt-2 grid min-w-36 gap-0.5 rounded-lg border border-rule bg-popover p-1.5 shadow-sm">
            {items.map((n) => <li key={n.href}>{link(n, "block rounded px-2.5 py-1.5 no-underline hover:bg-muted")}</li>)}
          </ul>
        )}
      </div>
    </nav>
  );
}

// The top corner of every page: the site navigation, the command palette's button, then "Sign in" for a guest or the
// account's name opening a short menu.
export function AccountMenu() {
  const pathname = usePathname();
  const [state, setState] = useState<{ known: boolean; user: Account | null }>({ known: false, user: null });
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  const refresh = useCallback(() => {
    me().then((m) => setState({ known: true, user: m.user }), () => setState({ known: true, user: null }));
  }, []);

  useEffect(() => {
    refresh();
    window.addEventListener(ACCOUNT_EVENT, refresh);
    return () => window.removeEventListener(ACCOUNT_EVENT, refresh);
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", escape); };
  }, [open]);

  const leave = () => {
    setBusy(true);
    signOut().finally(() => { setBusy(false); setOpen(false); });
  };

  return (
    <header className="absolute right-5 top-4 z-30 flex items-baseline gap-4 text-[13px]">
      {state.known && <SiteNav pathname={pathname} signedIn={!!state.user} />}
      <PaletteButton />
      {!(state.known && !state.user && pathname === "/account") && <span aria-hidden className="h-3 w-px self-center bg-rule" />}
      {!state.known ? (
        <span aria-hidden className="block h-5" />
      ) : !state.user ? (
        pathname === "/account" ? null : (
          <Link href={signInHref(pathname + (typeof window === "undefined" ? "" : window.location.search))} data-account="guest" className={MUTED_LINK}>
            Sign in
          </Link>
        )
      ) : (
        <div ref={box} className="relative" data-account="signed-in">
          <button
            ref={button}
            type="button"
            aria-expanded={open}
            aria-controls="account-menu"
            onClick={() => setOpen((o) => !o)}
            className="flex max-w-[14rem] items-center gap-1 text-muted-foreground transition-colors duration-150 hover:text-foreground"
          >
            <span className="truncate">{state.user.display_name}</span>
            <ChevronDown aria-hidden className={cn("size-3.5 shrink-0 transition-transform duration-150", open && "rotate-180")} />
          </button>
          {open && (
            <ul id="account-menu" className="absolute right-0 mt-2 grid min-w-40 gap-0.5 rounded-lg border border-rule bg-popover p-1.5 shadow-sm">
              {ITEMS.map((item) => (
                <li key={item.href}>
                  <Link href={item.href} prefetch={false} onClick={() => setOpen(false)} className="block rounded px-2.5 py-1.5 hover:bg-muted">
                    {item.label}
                  </Link>
                </li>
              ))}
              <li className="mt-0.5 border-t border-rule pt-0.5">
                <button type="button" disabled={busy} onClick={leave} className="block w-full rounded px-2.5 py-1.5 text-left hover:bg-muted disabled:opacity-60">
                  {busy ? "Signing out…" : "Sign out"}
                </button>
              </li>
            </ul>
          )}
        </div>
      )}
    </header>
  );
}
