"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { Wordmark } from "@/components/logo";
import { LINK, MUTED_LINK } from "@/components/page-kit";
import { browseValue, datasetPath, repositoryName, type Browse } from "@/lib/api";

export function BrowsePage() {
  const params = useSearchParams();
  const field = params.get("field") ?? "";
  const value = params.get("value") ?? "";
  const [source, setSource] = useState("");
  const [pages, setPages] = useState<Browse[]>([]);
  const [failed, setFailed] = useState(false);
  const [more, setMore] = useState(0);

  useEffect(() => {
    document.title = `${value} · locus`;
    const ctrl = new AbortController();
    browseValue(field, value, source, more * 50, ctrl.signal).then(
      (page) => setPages((p) => (more === 0 ? [page] : [...p, page])),
      () => !ctrl.signal.aborted && setFailed(true),
    );
    return () => ctrl.abort();
  }, [field, value, source, more]);

  const first = pages[0];
  const rows = pages.flatMap((p) => p.datasets);
  const pick = (s: string) => {
    setMore(0);
    setSource(s);
  };
  return (
    <div className="mx-auto grid w-full max-w-6xl grid-cols-1 content-start gap-10">
      <nav><Link href="/" aria-label="locus home" className="leading-none"><Wordmark className="text-[30px]" /></Link></nav>
      <header className="grid gap-3">
        <p className="font-mono text-[12.5px] text-muted-foreground">{field}</p>
        <h1 className="max-w-4xl font-display text-[34px] leading-[1.08] sm:text-[44px]">{value}</h1>
        {first && (
          <p className="font-mono text-[13px] tabular">
            {first.total.toLocaleString()} {first.total === 1 ? "dataset" : "datasets"} in locus
            <span className="text-muted-foreground"> · matched “{first.phrase}” in {first.matched_in}</span>
          </p>
        )}
      </header>
      {failed ? (
        <p className="text-sm">locus could not read its index. <button type="button" onClick={() => { setFailed(false); pick(source); }} className={LINK}>Try again</button></p>
      ) : !first ? (
        <p className="text-[13px] text-muted-foreground">Reading the index…</p>
      ) : first.total === 0 && !source ? (
        <p className="text-[13px] text-muted-foreground">No other locus dataset states this value.</p>
      ) : (
        <section className="grid gap-4">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
            <button type="button" aria-pressed={!source} onClick={() => pick("")} className={cn(!source ? "font-medium text-foreground" : MUTED_LINK)}>All</button>
            {Object.entries(first.by_source).map(([s, n]) => (
              <button key={s} type="button" aria-pressed={source === s} onClick={() => pick(s)} className={cn(source === s ? "font-medium text-foreground" : MUTED_LINK)}>
                {repositoryName(s)} <span className="font-mono text-[12px] tabular">{n.toLocaleString()}</span>
              </button>
            ))}
          </div>
          <ul className="grid border-t border-rule">
            {rows.map((d) => (
              <li key={d.accession} className="grid gap-0.5 border-b border-rule py-2.5">
                <Link href={datasetPath(d.accession)} className={cn("w-fit text-[14.5px] leading-snug", LINK)}>{d.title}</Link>
                <p className="flex flex-wrap gap-x-2 font-mono text-[12px] text-muted-foreground">
                  <span className="text-foreground/80">{d.accession}</span>
                  <span>{repositoryName(d.source)}</span>
                  {d.published && <span className="tabular">{d.published.slice(0, 4)}</span>}
                  {d.samples ? <span className="tabular">{d.samples.toLocaleString()} samples</span> : null}
                </p>
              </li>
            ))}
          </ul>
          {rows.length < (source ? first.by_source[source] ?? 0 : first.total) && (
            <button type="button" onClick={() => setMore((n) => n + 1)} className={cn("w-fit text-[13px]", MUTED_LINK)}>Show 50 more</button>
          )}
        </section>
      )}
    </div>
  );
}
