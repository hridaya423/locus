"use client";
import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { Wordmark } from "@/components/logo";
import { LINK, MUTED_LINK } from "@/components/page-kit";
import { checkList, datasetPath, type ListCheck } from "@/lib/api";

const ROWS = 30;
const percent = (x: number) => `${(x * 100).toFixed(0)}%`;

export function ListPage() {
  const params = useSearchParams();
  const [text, setText] = useState("");
  const [accession, setAccession] = useState(params.get("in") ?? "");
  const [result, setResult] = useState<ListCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [all, setAll] = useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await checkList(text, accession.trim().toUpperCase()));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  const rows = result ? [...result.rows].sort((a, b) => Number(!!b.mitocarta) - Number(!!a.mitocarta) || (a.dataset?.rank ?? 1e9) - (b.dataset?.rank ?? 1e9)) : [];
  const ds = result?.dataset;
  return (
    <div className="mx-auto grid w-full max-w-6xl grid-cols-1 content-start gap-10">
      <nav><Link href="/" aria-label="locus home" className="leading-none"><Wordmark className="text-[30px]" /></Link></nav>
      <header className="grid gap-3">
        <h1 className="font-display text-[34px] leading-[1.08] sm:text-[44px]">Your list</h1>
        <p className="max-w-[68ch] text-[15px] text-muted-foreground">Paste the proteins or genes from your experiment: gene symbols, UniProt accessions or FASTA headers.</p>
      </header>
      <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) run(); }} className="grid gap-3">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={7} aria-label="Gene or protein list" placeholder={"TOMM20\nP08574\nsp|O94826|TOM70_HUMAN\nSDHB …"}
          className="w-full max-w-3xl rounded-md border border-rule bg-card p-3 font-mono text-[16px] outline-none transition-colors duration-150 placeholder:text-muted-foreground focus:border-foreground sm:text-[13px]" />
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <label htmlFor="list-dataset" className="text-muted-foreground">Also rank them in a GEO dataset (optional)</label>
          <input id="list-dataset" value={accession} onChange={(e) => setAccession(e.target.value)} placeholder="GSE124685" spellCheck={false}
            className="h-8 w-32 rounded-md border border-rule bg-card px-2 font-mono text-[16px] outline-none focus:border-foreground sm:text-[13px]" />
          <button type="submit" disabled={busy || !text.trim()} className={cn("font-medium disabled:opacity-50", LINK)}>{busy ? "Checking…" : "Check"}</button>
        </div>
      </form>
      {error && <p className="text-[13px] text-muted-foreground">The list could not be checked: {error}.</p>}
      {result && (
        <section className="grid gap-5">
          <p className="font-mono text-[13px] tabular">
            <span className="font-medium">{result.mitocarta}</span> of {result.items} are MitoCarta 3.0 mitochondrial proteins
            {result.recovery != null && <span className="text-muted-foreground"> · recovery {percent(result.recovery)}</span>}
          </p>
          {result.mitocarta > 0 && (
            <p className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-muted-foreground">
              {Object.entries(result.compartments).map(([c, n]) => <span key={c}>{c} <span className="font-mono tabular text-foreground">{n}</span></span>)}
            </p>
          )}
          {ds && (
            ds.reason ? (
              <p className="text-[13px] text-muted-foreground">{ds.accession}: {ds.reason}.</p>
            ) : (
              <p className="text-[13px]">
                In <Link href={`${datasetPath(ds.accession)}#first-look`} className={cn("font-mono text-[12.5px]", LINK)}>{ds.accession}</Link> ({ds.case?.join(", ")} vs {ds.control?.join(", ")}):{" "}
                {ds.in_table} of your {result.items} are in the table and {ds.coloured} are among its significant genes
                <span className="text-muted-foreground"> (about {ds.expected} by chance{ds.p != null && `, p = ${ds.p < 0.001 ? ds.p.toExponential(1) : ds.p.toFixed(3)}`})</span>.
              </p>
            )
          )}
          <table className="w-full max-w-5xl text-[12.5px]">
            <thead>
              <tr className="border-b border-rule text-left text-muted-foreground">
                <th className="py-1 font-normal">Item</th>
                <th className="py-1 font-normal">MitoCarta 3.0</th>
                <th className="py-1 font-normal max-sm:hidden">Evidence</th>
                {ds && !ds.reason && <th className="py-1 text-right font-normal">log2FC · q · rank</th>}
              </tr>
            </thead>
            <tbody>
              {(all ? rows : rows.slice(0, ROWS)).map((r) => (
                <tr key={r.item} className="border-b border-rule/50 align-top">
                  <td className="py-1 font-mono">{r.item}{r.mitocarta && r.mitocarta.symbol.toUpperCase() !== r.item.toUpperCase() && <span className="text-muted-foreground"> {r.mitocarta.symbol}</span>}</td>
                  <td className="py-1">{r.mitocarta ? <span title={r.mitocarta.pathways}>{r.mitocarta.compartment || "mitochondrial"}</span> : <span className="text-muted-foreground">not in MitoCarta</span>}</td>
                  <td className="max-w-80 truncate py-1 text-muted-foreground max-sm:hidden" title={r.mitocarta?.evidence}>{r.mitocarta?.evidence}</td>
                  {ds && !ds.reason && (
                    <td className={cn("py-1 text-right font-mono tabular", r.dataset?.coloured ? (r.dataset.log2fc > 0 ? "text-signal" : "text-control") : "text-muted-foreground")}>
                      {r.dataset ? `${r.dataset.log2fc.toFixed(2)} · ${r.dataset.q < 0.001 ? r.dataset.q.toExponential(1) : r.dataset.q.toFixed(3)} · ${r.dataset.rank.toLocaleString()}` : "not tested"}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > ROWS && <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[13px]", MUTED_LINK)}>{all ? "Fewer" : `All ${rows.length}`}</button>}
          <p className="max-w-[80ch] text-[12px] text-muted-foreground">
            MitoCarta 3.0, {result.source.genes.toLocaleString()} human genes: <a href={result.source.url} className={MUTED_LINK}>{result.source.citation}</a>.
            {ds?.method && ` Dataset ranks from locus's first look: ${ds.method}.`}
          </p>
        </section>
      )}
    </div>
  );
}
