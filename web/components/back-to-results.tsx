"use client";
import Link from "next/link";
import { useMemo, useSyncExternalStore } from "react";
import { ArrowLeft } from "lucide-react";
import { MUTED_LINK } from "@/components/page-kit";
import { LAST_SEARCH, type Result } from "@/lib/api";
import { cn } from "@/lib/utils";

const noSubscription = () => () => {};

function lastSearch(): Result | null {
  try {
    return JSON.parse(sessionStorage.getItem(LAST_SEARCH) ?? "null");
  } catch {
    return null;
  }
}

// Back to this tab's last results, from any page. The logo is home; this is the way back to the search. The link carries
// the question, so the search page restores the saved results and the row the reader left from rather than starting over.
export function BackToResults({ className }: { className?: string }) {
  const known = useSyncExternalStore(noSubscription, () => sessionStorage.getItem(LAST_SEARCH), () => null);
  const last = useMemo(() => (known ? lastSearch() : null), [known]);
  if (!last) return null;
  return (
    <Link href={`/?q=${encodeURIComponent(last.question)}`} className={cn("flex min-w-0 items-center gap-1.5 text-[13px]", MUTED_LINK, className)}>
      <ArrowLeft aria-hidden className="size-3.5 shrink-0" />
      <span className="truncate">Results for {last.plan.terms.join(", ")}</span>
    </Link>
  );
}
