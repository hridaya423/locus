"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Download, LoaderCircle, X } from "lucide-react";
import { CartesianGrid, ReferenceLine, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { cn } from "@/lib/utils";
import {
  kitUrl, processOptions, rowFile, rowStatus, startRow,
  type PcaPoint, type ProcessOptions, type ProcessResult, type ProcessRow, type ProcessRowId, type RowResult, type RowStatus,
} from "@/lib/api";
import { ACTION } from "@/components/result-card";

// What each stage means, for every data type's pipeline; a stage the server names that is not here shows its own name.
const STEPS: Record<string, string> = {
  plan: "Choosing the samples and the contrast from the sample records",
  reference: "Reference: GENCODE transcripts and an index, built once",
  fetch: "Fetching: the first reads of each FASTQ from ENA, or the authors' processed files from GEO",
  quantify: "Quantifying with salmon",
  count: "Counting per gene",
  test: "DESeq2 with apeglm shrinkage, PCA, volcano and MA plots",
  explain: "The model writes a paragraph from the numbers; code checks every number",
  qc: "QC: cells with too few genes or too much mitochondrial RNA removed",
  cluster: "Normalising, PCA, neighbours, Leiden clusters and UMAP",
  markers: "Marker genes per cluster",
  pseudobulk: "Pseudobulk per sample and cluster, DESeq2 per cluster",
  clean: "Trimming adapters with fastp",
  align: "bowtie2: rRNA removed, then the transcriptome",
  psite: "P-site offsets, metagene and footprint lengths",
  deltate: "ΔTE: DESeq2 with an interaction term, classes and the Δ RNA vs Δ Ribo scatter",
  done: "Done",
};
const ORDER: Record<string, string[]> = {
  bulk_rnaseq: ["plan", "reference", "fetch", "quantify", "count", "test", "explain"],
  scrnaseq: ["plan", "fetch", "qc", "cluster", "markers", "pseudobulk"],
  "riboseq:here": ["plan", "fetch", "deltate"],
  "riboseq:laptop": ["plan", "reference", "fetch", "clean", "align", "psite", "count", "deltate"],
};

const size = (bytes: number) => (bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`);
const sig = (value: number) => (value === 0 ? "0" : value < 1e-3 ? value.toExponential(1) : value.toFixed(3));
const SEP = " ·  ";

// ---------------------------------------------------------------- the three rows

function Requirements({ row }: { row: ProcessRow }) {
  if (!row.requirements) return null;
  const r = row.requirements;
  return (
    <span className="font-mono text-[11px] tabular text-muted-foreground">
      {r.time}{SEP}memory {r.memory}{SEP}disk {r.disk}
    </span>
  );
}

function Row({ row, accession, topic, active, onRun }: { row: ProcessRow; accession: string; topic: string; active: boolean; onRun: () => void }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);
  const grey = !row.available;
  return (
    <div className={cn("grid gap-1 py-2", grey && "opacity-60")} aria-disabled={grey}>
      <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className={cn("label", grey ? "text-muted-foreground" : "text-foreground")}>{row.label}</span>
        {row.what && <span className="text-[13px]">{row.what}</span>}
      </span>
      {row.detail && !grey && <span className="text-[12px] text-muted-foreground">{row.detail}</span>}
      {grey ? (
        <span className="flex items-start gap-1 text-[12px] text-muted-foreground"><X aria-hidden className="mt-0.5 size-3 shrink-0" />cannot run for this dataset: {row.reason}</span>
      ) : (
        <Requirements row={row} />
      )}
      {!grey && row.why_not_laptop && <span className="text-[12px] text-muted-foreground">not a laptop job: {row.why_not_laptop}</span>}
      {!grey && row.fidelity && <span className="text-[12px] text-muted-foreground">{row.fidelity}</span>}
      {!grey && (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {(row.action === "run" || row.action === "cached") && !active && (
            <button type="button" onClick={onRun} className={cn(ACTION, "w-fit")}>{row.action === "cached" || row.state === "done" ? "Show the results" : "Run"}</button>
          )}
          {row.action === "link" && row.href && <Link href={row.href} className={cn(ACTION, "w-fit")}>Open the First look</Link>}
          {(row.action === "kit" || row.action === "command" || row.kit) && (
            <a href={kitUrl(accession, row.id, topic)} download className={cn(ACTION, "w-fit")}><Download aria-hidden className="size-3" />{row.action === "kit" ? "Download the kit (zip)" : "Download as a zip"}</a>
          )}
          {row.command && (
            <span className="flex items-center gap-2">
              <code className="font-mono text-[11.5px]">{row.command}</code>
              <button type="button" onClick={() => navigator.clipboard.writeText(row.command!).then(() => setCopied(true))} className="text-xs font-medium underline decoration-rule underline-offset-4 hover:decoration-foreground">
                {copied ? "copied" : "copy"}
              </button>
            </span>
          )}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- a run: stages, then results

function useRow(accession: string, row: ProcessRowId | null, topic: string, start: boolean) {
  const [status, setStatus] = useState<RowStatus | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    if (!row) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setStatus(null);
    setFailed(null);
    const poll = async () => {
      try {
        const next = await rowStatus(accession, row, topic, controller.signal);
        setStatus(next);
        if (next.stage !== "done" && next.stage !== "error") timer = setTimeout(poll, 2000);
      } catch (error) {
        if (!controller.signal.aborted) setFailed(error instanceof Error ? error.message : String(error));
      }
    };
    (start ? startRow(accession, row, topic) : Promise.resolve()).then(poll, (error) => setFailed(error instanceof Error ? error.message : String(error)));
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [accession, row, topic, start]);
  return { status, failed };
}

function Stages({ status, order }: { status: RowStatus; order: string[] }) {
  const steps = order.includes(status.stage ?? "") || !status.stage ? order : [...order, status.stage];
  const reached = steps.indexOf(status.stage === "error" ? "plan" : (status.stage ?? "plan"));
  return (
    <ol className="grid gap-1.5" aria-live="polite">
      {steps.filter((s) => s !== "done").map((s, i) => {
        const done = i < reached || status.stage === "done";
        const active = i === reached && status.stage !== "done" && status.stage !== "error";
        const counts = status.stages[s];
        return (
          <li key={s} className={cn("flex items-center gap-2 text-[13px]", done ? "text-muted-foreground" : active ? "text-foreground" : "text-muted-foreground/60")}>
            {done ? <Check aria-hidden className="size-3.5" strokeWidth={2.5} /> : active ? <LoaderCircle aria-hidden className="size-3.5 animate-spin" /> : <span className="size-3.5" />}
            {STEPS[s] ?? s}
            {counts?.count !== undefined && (active || done) && (
              <span className="font-mono text-[11px] tabular text-muted-foreground">{counts.done !== undefined ? `${counts.done}/${counts.count}` : `${counts.count} samples`}</span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <figure className="grid gap-1 rounded-md border border-rule bg-background/60 p-2">
      <figcaption className="label text-muted-foreground">{title}</figcaption>
      {children}
    </figure>
  );
}

// The same blue/orange pair as the R figures (validated colourblind-safe categorical slots 1 and 2).
const COLOURS = ["#2a78d6", "#eb6834"];
const dot = (fill: string) => ({ fill, fillOpacity: 0.75, stroke: "none" });

async function json<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

function Pca({ file, result }: { file: (name: string) => string; result: ProcessResult }) {
  const [points, setPoints] = useState<PcaPoint[] | null>(null);
  useEffect(() => {
    json<{ points: PcaPoint[] }>(file("pca.json")).then((d) => setPoints(d.points)).catch(() => setPoints([]));
  }, [file]);
  const conditions = [result.contrast.reference, result.contrast.target];
  return (
    <Panel title={`PCA · PC1 ${result.pca.variance[0]}%, PC2 ${result.pca.variance[1]}%`}>
      <ScatterChart width={300} height={220} margin={{ top: 8, right: 8, bottom: 4, left: -16 }}>
        <CartesianGrid stroke="var(--rule)" strokeDasharray="2 4" />
        <XAxis type="number" dataKey="PC1" name="PC1" tick={{ fontSize: 10 }} stroke="var(--muted-foreground)" />
        <YAxis type="number" dataKey="PC2" name="PC2" tick={{ fontSize: 10 }} stroke="var(--muted-foreground)" />
        <Tooltip cursor={false} contentStyle={{ fontSize: 11 }} formatter={(v) => (typeof v === "number" ? v.toFixed(2) : String(v ?? ""))} labelFormatter={() => ""} />
        {conditions.map((c, i) => (
          <Scatter key={c} name={c} data={(points ?? []).filter((p) => p.condition === c)} {...dot(COLOURS[i])} />
        ))}
      </ScatterChart>
      <span className="flex gap-3 text-[11px] text-muted-foreground">
        {conditions.map((c, i) => (
          <span key={c} className="flex items-center gap-1"><span className="size-2 rounded-full" style={{ background: COLOURS[i] }} />{c}</span>
        ))}
      </span>
    </Panel>
  );
}

type GenePoint = { gene: string; significant: boolean; [key: string]: number | string | boolean };

function Genes({ file, name, title, x, y, xLabel, yLabel, zero }: {
  file: (name: string) => string; name: string; title: string; x: string; y: string; xLabel: string; yLabel: string; zero?: boolean;
}) {
  const [points, setPoints] = useState<GenePoint[] | null>(null);
  useEffect(() => {
    json<GenePoint[]>(file(name)).then(setPoints).catch(() => setPoints([]));
  }, [file, name]);
  const rest = (points ?? []).filter((p) => !p.significant);
  const hits = (points ?? []).filter((p) => p.significant);
  return (
    <Panel title={title}>
      <ScatterChart width={300} height={220} margin={{ top: 8, right: 8, bottom: 4, left: -16 }}>
        <CartesianGrid stroke="var(--rule)" strokeDasharray="2 4" />
        <XAxis type="number" dataKey={x} name={xLabel} tick={{ fontSize: 10 }} stroke="var(--muted-foreground)" />
        <YAxis type="number" dataKey={y} name={yLabel} tick={{ fontSize: 10 }} stroke="var(--muted-foreground)" />
        {zero && <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeDasharray="3 3" />}
        <Tooltip
          cursor={false}
          content={({ payload }) => (payload?.[0] ? <div className="rounded border border-rule bg-card px-2 py-1 text-[11px]">{(payload[0].payload as GenePoint).gene}</div> : null)}
        />
        <Scatter name="other" data={rest} {...dot("var(--muted-foreground)")} fillOpacity={0.35} />
        <Scatter name="padj < 0.05" data={hits} {...dot("#eb6834")} />
      </ScatterChart>
      <span className="block w-[300px] whitespace-normal text-[11px] leading-snug text-muted-foreground">{xLabel} vs {yLabel}; orange: padj &lt; 0.05</span>
    </Panel>
  );
}

function Downloads({ files, file }: { files: { name: string; bytes: number }[]; file: (name: string) => string }) {
  return (
    <div className="grid gap-1.5">
      <span className="label text-muted-foreground">Download</span>
      <span className="flex flex-wrap gap-x-3 gap-y-1">
        {files.map((f) => (
          <a key={f.name} href={file(f.name)} download className={ACTION}>
            <Download aria-hidden className="size-3" />{f.name}<span className="font-mono text-[11px]">{size(f.bytes)}</span>
          </a>
        ))}
      </span>
    </div>
  );
}

// Bulk RNA-seq: the PCA, volcano and MA from the JSON files, the model's paragraph, the top genes and the downloads.
function BulkResults({ result, file }: { result: ProcessResult; file: (name: string) => string }) {
  const c = result.contrast;
  const downloads = result.files.filter((f) => /\.(count|tsv|json|png|pdf|md)$/.test(f.name) && !/^(samples|result)\./.test(f.name));
  return (
    <div className="grid gap-3">
      <p className="text-sm">
        <span className="font-medium">{c.target}</span> vs <span className="font-medium">{c.reference}</span> from the field &lsquo;{c.field}&rsquo;, {result.samples.length} samples
        {SEP}{result.genes.toLocaleString()} genes counted, {result.genes_tested.toLocaleString()} tested
        {SEP}<span className="font-medium text-signal">{result.significant}</span> with padj &lt; 0.05 ({result.up} up, {result.down} down)
      </p>
      <div className="grid gap-2 sm:grid-cols-3">
        <Pca file={file} result={result} />
        <Genes file={file} name="volcano.json" title="Volcano" x="log2fc" y="neglog10p" xLabel="log2 fold change" yLabel="-log10 p" />
        <Genes file={file} name="ma.json" title="MA" x="log10_mean" y="log2fc" xLabel="log10 mean count" yLabel="log2 fold change" zero />
      </div>
      {(result.explanation || result.note) && (
        <div className="grid gap-1 border-l-2 border-rule pl-3">
          <span className="label text-muted-foreground">{result.explanation ? "Written by the model from the numbers above" : "No explanation"}</span>
          <p className="text-[13px] leading-relaxed">{result.explanation ?? result.note}</p>
          {result.explanation && <span className="text-[11px] text-muted-foreground">{result.note}</span>}
        </div>
      )}
      <div className="grid gap-1.5">
        <span className="label text-muted-foreground">Top genes by adjusted p-value ({c.target} vs {c.reference}, apeglm shrinkage)</span>
        <table className="w-full text-[12.5px]">
          <thead className="text-left text-[11px] text-muted-foreground"><tr><th className="font-normal">Gene</th><th className="text-right font-normal">base mean</th><th className="text-right font-normal">log2 FC</th><th className="text-right font-normal">padj</th></tr></thead>
          <tbody>
            {result.top_genes.slice(0, 12).map((g) => (
              <tr key={g.gene_id} className="border-t border-rule">
                <td className="py-0.5 font-mono">{g.gene_name || g.gene_id}</td>
                <td className="py-0.5 text-right font-mono tabular">{g.base_mean.toFixed(0)}</td>
                <td className={cn("py-0.5 text-right font-mono tabular", g.log2fc > 0 ? "text-signal" : "text-control")}>{g.log2fc > 0 ? "+" : ""}{g.log2fc.toFixed(2)}</td>
                <td className="py-0.5 text-right font-mono tabular">{sig(g.padj)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Downloads files={downloads} file={file} />
      <p className="text-[12px] text-muted-foreground">
        Subsampled: the first {result.reads_per_fastq.toLocaleString()} reads of each FASTQ, salmon {result.tools.salmon} on {result.reference.source} {result.reference.release} ({result.reference.index}),
        DESeq2 {result.tools.DESeq2} with apeglm {result.tools.apeglm}; {result.seconds < 90 ? `${result.seconds} s` : `${Math.round(result.seconds / 60)} min`}. manifest.json records the samples, runs and versions
        {result.skipped.length > 0 && `; ${result.skipped.length} samples left out`}.
      </p>
    </div>
  );
}

// Single-cell and Ribo-seq: the figures as images with their captions, the summary sentences, warnings and downloads.
function FigureResults({ result, file }: { result: RowResult; file: (name: string) => string }) {
  const downloads = result.files.filter((f) => /\.(tsv|csv|json|png|pdf|md|h5ad|txt)$/.test(f.name) && !/^(result)\./.test(f.name));
  return (
    <div className="grid gap-3">
      <p className="text-sm font-medium">{result.title}</p>
      {result.summary.length > 0 && <p className="text-[13px] leading-relaxed">{result.summary.join(" ")}</p>}
      <div className="grid gap-2 sm:grid-cols-2">
        {result.figures.map((f) => (
          <figure key={f.file} className="grid gap-1 rounded-md border border-rule bg-background/60 p-2">
            <figcaption className="label text-muted-foreground">{f.title}</figcaption>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={file(f.file)} alt={f.caption} className="w-full rounded bg-white" loading="lazy" />
            <span className="text-[11.5px] leading-snug text-muted-foreground">{f.caption}</span>
          </figure>
        ))}
      </div>
      {(result.warnings ?? []).length > 0 && (
        <ul className="grid gap-1 border-l-2 border-rule pl-3">
          {result.warnings!.map((w) => <li key={w} className="text-[12.5px] text-warn">{w}</li>)}
        </ul>
      )}
      <Downloads files={downloads} file={file} />
      <p className="text-[12px] text-muted-foreground">
        {result.tier === "here" ? "Computed from the authors' processed files" : "Computed from subsampled reads"}
        {result.tools && `; ${Object.entries(result.tools).slice(0, 4).map(([k, v]) => `${k} ${v}`).join(", ")}`}
        ; {result.seconds < 90 ? `${result.seconds} s` : `${Math.round(result.seconds / 60)} min`}. manifest.json records the files, samples and versions
        {(result.skipped ?? []).length > 0 && `; ${result.skipped!.length} samples left out`}.
      </p>
    </div>
  );
}

const isBulk = (result: ProcessResult | RowResult): result is ProcessResult => "top_genes" in result;

function Run({ accession, topic, row, dataType, start }: { accession: string; topic: string; row: ProcessRowId; dataType: string; start: boolean }) {
  const { status, failed } = useRow(accession, row, topic, start);
  const error = failed ?? status?.error ?? null;
  const order = ORDER[`${dataType}:${row}`] ?? ORDER[dataType] ?? [];
  const file = (name: string) => rowFile(accession, row, name, topic);
  return (
    <div className="grid gap-3 border-l-2 border-foreground pl-3" data-process={accession} data-run={row}>
      {status && status.stage !== "done" && !error && <Stages status={status} order={order} />}
      {status && status.stage !== "done" && !error && status.log.length > 0 && (
        <pre className="max-h-16 overflow-hidden font-mono text-[11px] leading-relaxed text-muted-foreground">{status.log.slice(-3).join("\n")}</pre>
      )}
      {!status && !error && <span className="flex items-center gap-2 text-[13px] text-muted-foreground"><LoaderCircle aria-hidden className="size-3.5 animate-spin" />Starting…</span>}
      {error && <span className="flex items-start gap-1 text-[13px] text-warn"><X aria-hidden className="mt-0.5 size-3.5 shrink-0" strokeWidth={2.5} />{error}</span>}
      {status?.stage === "done" && status.result && (isBulk(status.result) ? <BulkResults result={status.result} file={file} /> : <FigureResults result={status.result} file={file} />)}
    </div>
  );
}

// ---------------------------------------------------------------- the panel

// Under a GEO row: the three rows (here, now / on your laptop / on a cluster) with what each costs for this dataset,
// greyed with the reason when one cannot work; a run's stages and results open under the row that started it.
export function ProcessPanel({ accession, topic }: { accession: string; topic: string }) {
  const [opts, setOpts] = useState<ProcessOptions | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [active, setActive] = useState<{ row: ProcessRowId; start: boolean } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    processOptions(accession, topic, controller.signal).then(setOpts, (error) => {
      if (!controller.signal.aborted) setFailed(error instanceof Error ? error.message : String(error));
    });
    return () => controller.abort();
  }, [accession, topic]);
  if (failed) return <span className="flex items-start gap-1 text-[13px] text-warn"><X aria-hidden className="mt-0.5 size-3.5 shrink-0" strokeWidth={2.5} />{failed}</span>;
  if (!opts) return <span className="flex items-center gap-2 text-[13px] text-muted-foreground"><LoaderCircle aria-hidden className="size-3.5 animate-spin" />Reading the sample records and ENA's run table…</span>;
  if (!opts.data_type) return <span className="text-[13px] text-muted-foreground">Not processed here: {opts.reason}</span>;
  return (
    <div className="grid gap-2 border-l-2 border-foreground pl-3" data-options={accession}>
      <span className="text-[13px]">
        <span className="font-medium">{opts.data_type_label}</span>, {opts.organism}, {opts.samples} samples{SEP}where it can run, and what it costs for this dataset
        {opts.reason && <span className="text-warn"> {SEP}{opts.reason}</span>}
      </span>
      <ol className="divide-y divide-rule">
        {opts.rows.map((row) => (
          <li key={row.id} className="grid gap-2" data-row={row.id}>
            <Row row={row} accession={accession} topic={topic} active={active?.row === row.id} onRun={() => setActive({ row: row.id, start: row.action !== "cached" && row.state !== "done" })} />
            {active?.row === row.id && <div className="pb-3"><Run accession={accession} topic={topic} row={row.id} dataType={opts.data_type!} start={active.start} /></div>}
          </li>
        ))}
      </ol>
    </div>
  );
}
