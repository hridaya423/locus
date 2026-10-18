"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { quality, samplePath, type DepthRow, type Quality } from "@/lib/api";

const QUOTES = 5;
const BARS = 40;
const OUTLIERS = 10;
const millions = (n: number) => `${(n / 1e6).toFixed(n < 1e7 ? 1 : 0)} M`;

function SampleLink({ dataset, sample }: { dataset: string; sample: string }) {
  return sample.startsWith("GSM") ? <Link href={samplePath(dataset, sample)} className={cn("font-mono text-[12px]", LINK)}>{sample}</Link> : <span className="font-mono text-[12px]">{sample}</span>;
}

function Bars({ dataset, rows, max }: { dataset: string; rows: DepthRow[]; max: number }) {
  return (
    <ul className="grid gap-0.5 text-[12.5px]">
      {rows.map((r) => (
        <li key={r.sample} className="grid grid-cols-[6.5rem_minmax(0,1fr)_4rem] items-center gap-x-3 sm:grid-cols-[6.5rem_minmax(0,14rem)_minmax(0,1fr)_4rem]">
          <SampleLink dataset={dataset} sample={r.sample} />
          <span className="truncate text-muted-foreground max-sm:hidden" title={r.title}>{r.title}</span>
          <span aria-hidden className="relative h-2 rounded-full bg-foreground/10">
            <span className={cn("absolute inset-y-0 left-0 rounded-full", r.outlier ? "bg-signal" : "bg-foreground/50")} style={{ width: `${(r.reads / max) * 100}%` }} />
          </span>
          <span className="text-right font-mono tabular">{millions(r.reads)}</span>
        </li>
      ))}
    </ul>
  );
}

function Group({ dataset, name, rows, group }: { dataset: string; name: string; rows: DepthRow[]; group: Quality["depth"]["groups"][string] }) {
  const [all, setAll] = useState(false);
  const outliers = rows.filter((r) => r.outlier);
  return (
    <div className="grid gap-2">
      <p className="flex flex-wrap items-baseline gap-x-3 text-[13px]">
        <span className="font-medium">{name}</span>
        <span className="font-mono text-[12px] tabular text-muted-foreground">
          {group.samples} samples · {millions(group.min_reads)} to {millions(group.max_reads)} reads, median {millions(group.median_reads)}
          {!group.flagged && " · not flagged"}
        </span>
      </p>
      {rows.length <= BARS ? (
        <Bars dataset={dataset} rows={rows} max={group.max_reads} />
      ) : (
        outliers.length > 0 && <Bars dataset={dataset} rows={all ? outliers : outliers.slice(0, OUTLIERS)} max={group.max_reads} />
      )}
      {outliers.length > 0 && (
        <p className="flex flex-wrap items-center gap-x-3 text-[12.5px]">
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="size-2 rounded-full bg-signal" />
            {outliers.length} far from the median: {outliers.slice(0, 3).map((r) => `${r.sample} ${r.outlier}`).join(", ")}{outliers.length > 3 && "…"}
          </span>
          {rows.length > BARS && outliers.length > OUTLIERS && (
            <button type="button" onClick={() => setAll((v) => !v)} className={MUTED_LINK}>{all ? "Fewer" : `All ${outliers.length}`}</button>
          )}
        </p>
      )}
    </div>
  );
}

export function QualitySection({ accession }: { accession: string }) {
  const [data, setData] = useState<Quality | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [all, setAll] = useState(false);
  useEffect(() => {
    const ctrl = new AbortController();
    quality(accession, ctrl.signal).then((d) => { setData(d); setFailed(false); }, () => !ctrl.signal.aborted && setFailed(true));
    return () => ctrl.abort();
  }, [accession, attempt]);

  if (failed)
    return (
      <section className="grid content-start gap-3">
        <Heading id="quality">Quality</Heading>
        <p className="flex flex-wrap gap-x-3 text-[13px] text-muted-foreground">
          locus could not read the run table and methods.
          <button type="button" onClick={() => setAttempt((n) => n + 1)} className={LINK}>Try again</button>
        </p>
      </section>
    );
  if (!data) return <p className="text-[13px] text-muted-foreground">Reading run tables and methods for quality…</p>;
  const { depth, criteria } = data;
  const sequencing = depth.sequencing !== false;
  if (!depth.available && criteria.quotes.length === 0 && !criteria.checklist) return null;
  const quotes = all ? criteria.quotes : criteria.quotes.slice(0, QUOTES);
  const topUps = depth.available ? depth.rows.filter((r) => r.top_up_of) : [];
  return (
    <section className="grid content-start gap-6">
      <Heading id="quality">Quality</Heading>
      {depth.available ? (
        <div className="grid gap-5">
          {Object.entries(depth.groups).map(([name, g]) => (
            <Group key={name} dataset={accession} name={name} group={g} rows={depth.rows.filter((r) => r.library === name && !r.top_up_of)} />
          ))}
          {topUps.length > 0 && (
            <div className="grid gap-1 text-[12.5px]">
              <p className="font-medium">Re-sequencing top-ups, counted apart</p>
              {topUps.map((r) => (
                <p key={r.sample} className="flex flex-wrap gap-x-2 text-muted-foreground">
                  <SampleLink dataset={accession} sample={r.sample} /> {millions(r.reads)} reads, a top-up of{" "}
                  {r.top_up_of?.startsWith("GSM") ? <SampleLink dataset={accession} sample={r.top_up_of} /> : r.top_up_of}
                </p>
              ))}
            </div>
          )}
          <p className="text-[12px] text-muted-foreground">Reads per sample from the {depth.source}. Flagged: {depth.rule}.</p>
        </div>
      ) : (
        sequencing && <p className="text-[13px] text-muted-foreground">Depth per sample: {depth.reason}.</p>
      )}
      {criteria.checklist && (
        <div className="grid gap-2">
          <h3 className="text-[13px] font-medium">Ribo-seq checks the methods state</h3>
          <dl className="grid border-t border-rule text-[12.5px]">
            {criteria.checklist.map((c) => (
              <div key={c.check} className="grid gap-x-6 gap-y-0.5 border-b border-rule py-2 sm:grid-cols-[13rem_minmax(0,1fr)]">
                <dt className={cn("font-medium", !c.stated && "text-muted-foreground")}>{c.check}</dt>
                <dd className="min-w-0">
                  {c.stated ? (
                    <>
                      <span className="line-clamp-2" title={c.text}>{c.text}</span>
                      <span className="font-mono text-[11.5px] text-muted-foreground">{c.field}</span>
                    </>
                  ) : (
                    <span className="text-warn">not stated</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
          {criteria.quotes.length === 0 && <p className="text-[12px] text-muted-foreground">Looked for in: {criteria.read.join("; ")}.</p>}
        </div>
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
          <p className="text-[12px] text-muted-foreground">Read from: {criteria.read.join("; ")}.</p>
        </div>
      )}
    </section>
  );
}
