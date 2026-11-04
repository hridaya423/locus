import Link from "next/link";
import { Wordmark } from "@/components/logo";
import { LINK } from "@/components/page-kit";

// A share link that never existed, was withdrawn, or belongs to a deleted list: all look the same.
export default function NotShared() {
  return (
    <div className="mx-auto grid w-full max-w-4xl content-start gap-10" data-public-list="missing">
      <nav className="flex items-center gap-5">
        <Link href="/" aria-label="locus home" className="leading-none"><Wordmark className="text-[30px]" /></Link>
      </nav>
      <div className="grid gap-3">
        <h1 className="font-display text-[34px] leading-[1.08] sm:text-[44px]">This list is not shared</h1>
        <p className="max-w-xl text-[15px] text-muted-foreground">
          The link may be mistyped, or its owner stopped sharing the list. <Link href="/" className={LINK}>Search locus</Link> for datasets instead.
        </p>
      </div>
    </div>
  );
}
