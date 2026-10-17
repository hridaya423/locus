"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { quality, samplePath, type DepthRow, type Quality } from "@/lib/api";

const QUOTES = 5;
const millions = (n: number) => `${(n / 1e6).toFixed(n < 1e7 ? 1 : 0)} M`;

function Strip({ dataset, name, rows, median, lo, hi }: { dataset: string; name: string; rows: DepthRow[]; median: number; lo: number; hi: number }) {
  const x = (n: number) => ((Math.log10(Math.max(n, 1)) - lo) / (hi - lo)) * 100;
  const out = rows.filter((r) => r.outlier);
  return (
    <div className="grid gap-1.5">
      <p className="flex flex-wrap items-baseline gap-x-3 text-[13px]">
        <span className="font-medium">{name}</span>
        <span className="font-mono text-[12px] tabular text-muted-foreground">{rows.length} samples · median {millions(median)} reads</span>
      </p>
      <div className="relative h-7 rounded-md border border-rule bg-card" role="img" aria-label={`${name}: reads per sample, median ${millions(median)}`}>
        <span aria-hidden className="absolute inset-y-1 w-px bg-foreground/50" style={{ left: `${x(median)}%` }} />
        {rows.map((r) => (
          <span key={r.sample} title={`${r.sample} ${r.title}: ${r.reads.toLocaleString()} reads${r.outlier ? ` (${r.outlier})` : ""}`}
            className={cn("absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full", r.outlier ? "bg-signal" : "bg-foreground/40")}
            style={{ left: `${x(r.reads)}%` }} />
        ))}
      </div>
      {out.length > 0 && (
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px]">
          {out.map((r) => (
            <span key={r.sample} className="text-signal">
              {r.sample.startsWith("GSM") ? <Link href={samplePath(dataset, r.sample)} className={LINK}>{r.sample}</Link> : r.sample}{" "}
              <span className="text-muted-foreground">{r.title}</span> {millions(r.reads)} · {r.outlier}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

export function QualitySection({ accession }: { accession: string }) {
  const [data, setData] = useState<Quality | null>(null);
  const [failed, setFailed] = useState(false);
  const [all, setAll] = useState(false);
  useEffect(() => {
    const ctrl = new AbortController();
    quality(accession, ctrl.signal).then(setData, () => !ctrl.signal.aborted && setFailed(true));
    return () => ctrl.abort();
  }, [accession]);

  if (failed) return null;
  if (!data) return <p className="text-[13px] text-muted-foreground">Reading run tables and methods for quality…</p>;
  const { depth, criteria } = data;
  if (!depth.available && criteria.quotes.length === 0) return null;
  const reads = depth.available ? depth.rows.map((r) => r.reads) : [];
  const lo = Math.floor(Math.log10(Math.max(1, Math.min(...reads))) * 4) / 4 - 0.1;
  const hi = Math.ceil(Math.log10(Math.max(1, ...reads)) * 4) / 4 + 0.1;
  const quotes = all ? criteria.quotes : criteria.quotes.slice(0, QUOTES);
  return (
    <section className="grid content-start gap-6">
      <Heading id="quality">Quality</Heading>
      {depth.available ? (
        <div className="grid gap-4">
          {Object.entries(depth.groups).map(([name, g]) => (
            <Strip key={name} dataset={accession} name={name} rows={depth.rows.filter((r) => r.library === name)} median={g.median_reads} lo={lo} hi={hi} />
          ))}
          <p className="text-[12px] text-muted-foreground">
            Reads per sample on a log scale, {millions(10 ** lo)} to {millions(10 ** hi)}, from the {depth.source}. Orange: {depth.rule}.
          </p>
        </div>
      ) : (
        <p className="text-[13px] text-muted-foreground">Depth per sample: {depth.reason}.</p>
      )}
      {criteria.quotes.length > 0 && (
        <div className="grid gap-3">
          <h3 className="text-[13px] font-medium">The authors&apos; QC, in their words</h3>
          {quotes.map((q) => (
            <blockquote key={q.text} className="grid gap-1 border-l-2 border-foreground pl-3">
              <p className="max-w-[72ch] text-[13.5px] leading-relaxed">{q.text}</p>
              <footer className="font-mono text-[11.5px] text-muted-foreground">{q.field}</footer>
            </blockquote>
          ))}
          {criteria.quotes.length > QUOTES && (
            <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[13px]", MUTED_LINK)}>
              {all ? "Fewer" : `${criteria.quotes.length - QUOTES} more`}
            </button>
          )}
          <p className="text-[12px] text-muted-foreground">Sentences that state a filter or threshold with a number, read from: {criteria.read.join("; ")}.</p>
        </div>
      )}
    </section>
  );
}
