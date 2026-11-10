import type { Metadata } from "next";
import Link from "next/link";
import { Wordmark } from "@/components/logo";
import { Heading, MUTED_LINK } from "@/components/page-kit";
import { PRIVACY_FACTS } from "@/lib/privacy";

export const metadata: Metadata = { title: "Privacy · locus" };

// How accounts work, for the people who have one (F7-r1-2). Static: the facts come from lib/privacy.ts.
export default function Page() {
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-10" data-privacy-page>
      <nav className="flex items-center gap-5">
        <Link href="/" aria-label="locus home" className="leading-none"><Wordmark className="text-[30px]" /></Link>
      </nav>
      <header className="grid gap-3">
        <h1 className="font-display text-[34px] leading-[1.08] sm:text-[44px]">Privacy</h1>
        <p className="max-w-xl text-[15px] text-muted-foreground">What locus keeps when you make an account, and how to take it with you or delete it.</p>
      </header>
      {PRIVACY_FACTS.map((f) => (
        <section key={f.id} aria-labelledby={f.id} className="grid gap-4 border-t border-rule pt-8" data-privacy-section={f.id}>
          <Heading id={f.id}>{f.title}</Heading>
          {f.body.length > 2 ? (
            <ul className="grid max-w-xl list-disc gap-1.5 pl-5 text-[14px] leading-relaxed">
              {f.body.map((line) => <li key={line}>{line}</li>)}
            </ul>
          ) : (
            f.body.map((line) => <p key={line} className="max-w-xl text-[14px] leading-relaxed">{line}</p>)
          )}
        </section>
      ))}
      <p className="text-[13px]"><Link href="/settings" className={MUTED_LINK}>Open Settings</Link></p>
    </div>
  );
}
