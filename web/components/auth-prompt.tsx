"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { LINK } from "@/components/page-kit";
import { signInHref } from "@/lib/account";
import { cn } from "@/lib/utils";

// Shown where an action needs an account: says why, and the sign-in link brings the reader back to this page afterwards.
// Pages using it sit inside a <Suspense> boundary (useSearchParams).
export function AuthPrompt({ reason, className }: { reason: string; className?: string }) {
  const pathname = usePathname();
  const query = useSearchParams().toString();
  return (
    <div role="status" className={cn("grid max-w-xl gap-2 border-l-2 border-foreground pl-4 text-[13px]", className)}>
      <p className="text-muted-foreground">{reason}</p>
      <p>
        <Link href={signInHref(pathname + (query ? `?${query}` : ""))} className={LINK}>Sign in or create an account</Link>
        <span className="text-muted-foreground"> and you will come back here.</span>
      </p>
    </div>
  );
}
