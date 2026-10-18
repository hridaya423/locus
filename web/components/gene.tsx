"use client";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { Wordmark } from "@/components/logo";
import { MUTED_LINK } from "@/components/page-kit";
import { datasetPath, foundAll, geneAcross, genePath, type GeneAcross, type GeneRow } from "@/lib/api";

const noSubscription = () => () => {};

const TONE: Record<string, string> = { higher: "bg-signal", lower: "bg-control", "no clear change": "bg-foreground/35" };

function Axis({ max }: { max: number }) {
  return (
    <div aria-hidden className="relative h-4 font-mono text-[10.5px] text-muted-foreground">
      {[-max, -max / 2, 0, max / 2, max].map((v) => (
        <span key={v} className="absolute -translate-x-1/2 tabular" style={{ left: `${((v + max) / (2 * max)) * 100}%` }}>{+v.toFixed(1)}</span>
      ))}
    </div>
  );
}

function Row({ row, max }: { row: GeneRow; max: number }) {
  const measured = row.log2fc != null;
  return (
    <li className="grid grid-cols-1 gap-x-6 gap-y-1.5 border-b border-rule py-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_6.5rem] md:items-center">
      <div className="grid min-w-0 gap-0.5">
        <Link href={`${datasetPath(row.accession)}#first-look`} className="w-fit font-mono text-[12.5px] font-medium underline decoration-rule underline-offset-4 hover:decoration-foreground">{row.accession}</Link>
        <span className="truncate text-[13px] text-muted-foreground" title={row.title}>{row.title}</span>
        {row.case && <span className="text-[12px] text-muted-foreground" title={`Table: ${row.source}, ${row.file}`}>{row.case.join(", ")} ({row.n_case}) vs {row.control?.join(", ")} ({row.n_control})</span>}
      </div>
      {measured ? (
        <div className="relative h-6" role="img" aria-label={`log2 fold change ${row.log2fc}`}>
          <span aria-hidden className="absolute inset-y-0 left-1/2 w-px bg-rule" />
          <span aria-hidden className="absolute top-1/2 h-px bg-foreground/30" style={{ left: `${Math.min(50, ((row.log2fc! + max) / (2 * max)) * 100)}%`, width: `${Math.abs(row.log2fc!) / (2 * max) * 100}%` }} />
          <span aria-hidden className={cn("absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full", TONE[row.status])} style={{ left: `${((row.log2fc! + max) / (2 * max)) * 100}%` }} />
        </div>
      ) : (
        <p className="text-[12.5px] text-muted-foreground">{row.status === "not tested" ? `Not tested: ${row.reason}` : row.reason || row.status}</p>
      )}
      <p className="font-mono text-[12px] tabular md:text-right">
        {measured ? <>{row.log2fc!.toFixed(2)} <span className="text-muted-foreground">q {row.q! >= 0.01 ? row.q!.toFixed(2) : row.q!.toExponential(1)}</span></> : <span className="text-muted-foreground">–</span>}
      </p>
    </li>
  );
}

export function GenePage({ gene }: { gene: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const lastSearch = useSyncExternalStore(noSubscription, () => JSON.stringify(foundAll()), () => "");
  const scope = useMemo(() => {
    if (!lastSearch) return null;
    const listed = params.getAll("in");
    const last: { accessions: string[]; topic: string } = JSON.parse(lastSearch);
    return listed.length ? { accessions: listed, hint: params.get("hint") ?? "" } : { accessions: last.accessions.filter((a) => a.startsWith("GSE")), hint: last.topic };
  }, [params, lastSearch]);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<GeneAcross | null>(null);
  const [failed, setFailed] = useState(false);
  const [next, setNext] = useState("");

  useEffect(() => {
    document.title = `${gene.toUpperCase()} across datasets · locus`;
    if (!scope?.accessions.length) return;
    const ctrl = new AbortController();
    geneAcross(gene, scope.accessions, scope.hint, ctrl.signal).then(setData, () => !ctrl.signal.aborted && setFailed(true));
    return () => ctrl.abort();
  }, [gene, scope, attempt]);

  const rows = data ? [...data.rows].sort((a, b) => Number(b.log2fc != null) - Number(a.log2fc != null) || (b.log2fc ?? 0) - (a.log2fc ?? 0)) : [];
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.log2fc ?? 0))) * 1.1;
  const unclear = data ? data.measured - data.higher - data.lower : 0;

  return (
    <div className="mx-auto grid w-full max-w-6xl grid-cols-1 content-start gap-10">
      <nav className="flex items-center justify-between gap-4">
        <Link href="/" aria-label="locus home" className="leading-none"><Wordmark className="text-[30px]" /></Link>
        <form onSubmit={(e) => { e.preventDefault(); if (next.trim() && scope) router.push(genePath(next.trim(), scope.accessions, scope.hint)); }}>
          <input value={next} onChange={(e) => setNext(e.target.value)} placeholder="Another gene" aria-label="Another gene"
            className="h-9 w-40 rounded-md border border-rule bg-card px-3 text-[16px] outline-none transition-colors duration-150 placeholder:text-muted-foreground focus:border-foreground sm:text-[13px]" />
        </form>
      </nav>
      <header className="grid gap-3">
        <p className="font-mono text-[12.5px] text-muted-foreground">Gene across datasets{scope?.hint && <> · {scope.hint}</>}</p>
        <h1 className="font-display text-[44px] leading-none">{gene.toUpperCase()}</h1>
        {data && <p className="text-[15px] text-muted-foreground">{data.description}</p>}
      </header>
      {scope && !scope.accessions.length ? (
        <p className="text-sm">No datasets to look in. Run a search first, or open this page from a dataset&apos;s first look. <Link href="/" className={MUTED_LINK}>Search</Link></p>
      ) : failed ? (
        <p className="text-sm">The comparison could not be made. <button type="button" onClick={() => { setFailed(false); setAttempt((n) => n + 1); }} className={MUTED_LINK}>Try again</button></p>
      ) : !data ? (
        <p className="text-[13px] text-muted-foreground">Reading the tables of {scope?.accessions.length ?? "the"} datasets and testing {gene.toUpperCase()} in each…</p>
      ) : (
        <section className="grid gap-4">
          <p className="font-mono text-[13px] tabular">
            <span className="text-signal">higher in {data.higher}</span> · <span className="text-control">lower in {data.lower}</span> · {unclear} without a clear change
            <span className="text-muted-foreground"> · of {data.measured} datasets that could answer, {data.rows.length} looked at</span>
          </p>
          <div className="grid gap-1">
            <div className="hidden md:grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_6.5rem] md:gap-x-6">
              <span />
              <Axis max={+max.toFixed(1)} />
              <span className="text-right font-mono text-[11px] text-muted-foreground">log2FC · q</span>
            </div>
            <ul className="grid border-t border-rule">{rows.map((r) => <Row key={r.accession} row={r} max={max} />)}</ul>
          </div>
          <p className="max-w-[80ch] text-[12px] leading-relaxed text-muted-foreground">
            Cases and controls are each dataset&apos;s characteristic with a control-like level. Higher or lower means q &lt; 0.05 and |log2FC| ≥ 1. {data.method}; tables of normalised values use the authors&apos; log scale.
          </p>
        </section>
      )}
    </div>
  );
}
