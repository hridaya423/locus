"use client";
import { useEffect, useState } from "react";
import { Check, Download, LoaderCircle, X } from "lucide-react";
import { CartesianGrid, ReferenceLine, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { cn } from "@/lib/utils";
import {
  PROCESS_STAGES, processFile, processJson, processStatus, startProcess,
  type PcaPoint, type ProcessResult, type ProcessStatus,
} from "@/lib/api";
import { ACTION } from "@/components/result-card";

const STEPS: Record<(typeof PROCESS_STAGES)[number], string> = {
  plan: "Choosing the contrast from the sample records",
  reference: "GENCODE transcripts and salmon index",
  fetch: "Streaming the first reads of each FASTQ from ENA",
  quantify: "Quantifying with salmon",
  count: "Gene counts: counts.tsv and one .count file per sample",
  test: "DESeq2 with apeglm shrinkage, PCA, volcano and MA plots",
  done: "Done",
};

const size = (bytes: number) => (bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`);
const sig = (value: number) => (value === 0 ? "0" : value < 1e-3 ? value.toExponential(1) : value.toFixed(3));

// Polls the job every two seconds until it is done, then loads the three plot files.
function useJob(accession: string, topic: string) {
  const [status, setStatus] = useState<ProcessStatus | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await processStatus(accession, controller.signal);
        setStatus(next);
        if (next.stage !== "done" && next.stage !== "error") timer = setTimeout(poll, 2000);
      } catch (error) {
        if (!controller.signal.aborted) setFailed(error instanceof Error ? error.message : String(error));
      }
    };
    startProcess(accession, topic).then(poll, (error) => setFailed(error instanceof Error ? error.message : String(error)));
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [accession, topic]);
  return { status, failed };
}

function Stages({ status }: { status: ProcessStatus }) {
  const reached = PROCESS_STAGES.indexOf(status.stage === "error" ? "plan" : (status.stage ?? "plan"));
  return (
    <ol className="grid gap-1.5" aria-live="polite">
      {PROCESS_STAGES.filter((s) => s !== "done").map((s, i) => {
        const done = i < reached || status.stage === "done";
        const active = i === reached && status.stage !== "done" && status.stage !== "error";
        const counts = status.stages[s];
        return (
          <li key={s} className={cn("flex items-center gap-2 text-[13px]", done ? "text-muted-foreground" : active ? "text-foreground" : "text-muted-foreground/60")}>
            {done ? <Check aria-hidden className="size-3.5" strokeWidth={2.5} /> : active ? <LoaderCircle aria-hidden className="size-3.5 animate-spin" /> : <span className="size-3.5" />}
            {STEPS[s]}
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

const COLOURS = ["var(--control)", "var(--signal)"];
const dot = (fill: string) => ({ fill, fillOpacity: 0.75, stroke: "none" });

function Pca({ accession, result }: { accession: string; result: ProcessResult }) {
  const [points, setPoints] = useState<PcaPoint[] | null>(null);
  useEffect(() => {
    processJson<{ points: PcaPoint[] }>(accession, "pca.json").then((d) => setPoints(d.points)).catch(() => setPoints([]));
  }, [accession]);
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

function Genes({ accession, file, title, x, y, xLabel, yLabel, zero }: {
  accession: string; file: string; title: string; x: string; y: string; xLabel: string; yLabel: string; zero?: boolean;
}) {
  const [points, setPoints] = useState<GenePoint[] | null>(null);
  useEffect(() => {
    processJson<GenePoint[]>(accession, file).then(setPoints).catch(() => setPoints([]));
  }, [accession, file]);
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
        <Scatter name="padj < 0.05" data={hits} {...dot("var(--signal)")} />
      </ScatterChart>
      <span className="max-w-[300px] text-[11px] leading-snug text-muted-foreground">{xLabel} vs {yLabel}; orange: padj &lt; 0.05</span>
    </Panel>
  );
}

function Results({ accession, result }: { accession: string; result: ProcessResult }) {
  const c = result.contrast;
  const downloads = result.files.filter((f) => /\.(count|tsv|json|png)$/.test(f.name) && !/^(samples|result)\./.test(f.name));
  return (
    <div className="grid gap-3">
      <p className="text-sm">
        <span className="font-medium">{c.target}</span> vs <span className="font-medium">{c.reference}</span> from the field &lsquo;{c.field}&rsquo;, {result.samples.length} samples
        {SEP}{result.genes.toLocaleString()} genes counted, {result.genes_tested.toLocaleString()} tested
        {SEP}<span className="font-medium text-signal">{result.significant}</span> with padj &lt; 0.05 ({result.up} up, {result.down} down)
      </p>
      <div className="grid gap-2 sm:grid-cols-3">
        <Pca accession={accession} result={result} />
        <Genes accession={accession} file="volcano.json" title="Volcano" x="log2fc" y="neglog10p" xLabel="log2 fold change" yLabel="-log10 p" />
        <Genes accession={accession} file="ma.json" title="MA" x="log10_mean" y="log2fc" xLabel="log10 mean count" yLabel="log2 fold change" zero />
      </div>
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
      <div className="grid gap-1.5">
        <span className="label text-muted-foreground">Download</span>
        <span className="flex flex-wrap gap-x-3 gap-y-1">
          {downloads.map((f) => (
            <a key={f.name} href={processFile(accession, f.name)} download className={ACTION}>
              <Download aria-hidden className="size-3" />{f.name}<span className="font-mono text-[11px]">{size(f.bytes)}</span>
            </a>
          ))}
        </span>
      </div>
      <p className="text-[12px] text-muted-foreground">
        Subsampled: the first {result.reads_per_fastq.toLocaleString()} reads of each FASTQ, salmon {result.tools.salmon} on {result.reference.source} {result.reference.release} ({result.reference.index}),
        DESeq2 {result.tools.DESeq2} with apeglm {result.tools.apeglm}; {Math.round(result.seconds / 60)} min. manifest.json records the samples, runs and versions
        {result.skipped.length > 0 && `; ${result.skipped.length} samples left out`}.
      </p>
    </div>
  );
}

const SEP = " ·  ";

// The results panel under a GEO RNA-seq row: starts the job, shows each stage, then the plots, top genes and downloads.
export function ProcessPanel({ accession, topic }: { accession: string; topic: string }) {
  const { status, failed } = useJob(accession, topic);
  const error = failed ?? status?.error ?? null;
  return (
    <div className="grid gap-3 border-l-2 border-foreground pl-3" data-process={accession}>
      {status && status.stage !== "done" && !error && <Stages status={status} />}
      {status && status.stage !== "done" && !error && status.log.length > 0 && (
        <pre className="max-h-16 overflow-hidden font-mono text-[11px] leading-relaxed text-muted-foreground">{status.log.slice(-3).join("\n")}</pre>
      )}
      {!status && !error && <span className="flex items-center gap-2 text-[13px] text-muted-foreground"><LoaderCircle aria-hidden className="size-3.5 animate-spin" />Starting…</span>}
      {error && <span className="flex items-start gap-1 text-[13px] text-warn"><X aria-hidden className="mt-0.5 size-3.5 shrink-0" strokeWidth={2.5} />{error}</span>}
      {status?.stage === "done" && status.result && <Results accession={accession} result={status.result} />}
    </div>
  );
}
