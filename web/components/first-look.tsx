"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { size } from "@/components/row-details";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { designCheck, foundAll, genePath, firstLook, paperCheck, pathways, type DesignCheck, type Pathways, type PathwaySide, tableDownload, tableSummary, type FirstLook, type Gene, type PaperCheck, type Pick, type TableSummary } from "@/lib/api";


const H = 360;
const PAD = { l: 44, r: 12, t: 12, b: 36 };
const LABELS = 12;
const LISTED = 10;

function ticks(lo: number, hi: number, n = 5) {
  const step = Math.pow(10, Math.floor(Math.log10((hi - lo) / n)));
  const nice = [1, 2, 5, 10].map((m) => m * step).find((s) => (hi - lo) / s <= n) ?? step * 10;
  const out = [];
  for (let v = Math.ceil(lo / nice) * nice; v <= hi + 1e-9; v += nice) out.push(+v.toFixed(6));
  return out;
}

function Volcano({ look, ringed }: { look: FirstLook; ringed: Set<string> }) {
  const [hover, setHover] = useState<Gene | null>(null);
  const [W, setW] = useState(640);
  const svg = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const el = svg.current?.parentElement;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setW(Math.max(300, Math.round(entry.contentRect.width))));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const { x, y, xs, ys, quiet, up, down, labelled, cut } = useMemo(() => {
    const max = Math.max(...look.genes.map((g) => Math.abs(g[1])), look.lfc + 0.5);
    const top = Math.max(...look.genes.map((g) => g[2]), 2);
    const x = (v: number) => PAD.l + ((v + max) / (2 * max)) * (W - PAD.l - PAD.r);
    const y = (v: number) => H - PAD.b - (v / top) * (H - PAD.t - PAD.b);
    const hit = (g: Gene) => g[3] < look.q && Math.abs(g[1]) >= look.lfc;
    const quiet = look.genes.filter((g) => !hit(g)).map((g) => `M${x(g[1]).toFixed(1)} ${y(g[2]).toFixed(1)}h0`).join("");
    const significant = look.genes.filter((g) => g[3] < look.q);
    const cut = significant.length ? Math.min(...significant.map((g) => g[2])) : null;
    return {
      x, y, quiet, cut,
      xs: ticks(-max, max), ys: ticks(0, top),
      up: look.genes.filter((g) => hit(g) && g[1] > 0),
      down: look.genes.filter((g) => hit(g) && g[1] < 0),
      labelled: look.genes.filter(hit).slice(0, (W < 500 ? LABELS / 2 : LABELS) * 3).reduce<Gene[]>((placed, g) => {
        const clash = placed.some((o) => Math.abs(y(o[2]) - y(g[2])) < 11 && Math.abs(x(o[1]) - x(g[1])) < 56);
        return placed.length < (W < 500 ? LABELS / 2 : LABELS) && !clash ? [...placed, g] : placed;
      }, []),
    };
  }, [look, W]);

  const nearest = (e: React.PointerEvent) => {
    const box = svg.current!.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    const py = ((e.clientY - box.top) / box.height) * H;
    let best: Gene | null = null;
    let d = 100;
    for (const g of look.genes) {
      const dd = (x(g[1]) - px) ** 2 + (y(g[2]) - py) ** 2;
      if (dd < d) [best, d] = [g, dd];
    }
    setHover(best);
  };

  return (
    <figure className="grid content-start gap-2">
      <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="h-auto w-full touch-pan-y select-none" onPointerMove={nearest} onPointerDown={nearest} onPointerLeave={() => setHover(null)} role="img"
        aria-label={`Volcano plot: ${look.up} ${look.feature ?? "gene"}s higher and ${look.down} lower in ${look.case.join(", ")} than ${look.control.join(", ")}`}>
        {xs.map((v) => (
          <g key={`x${v}`}>
            <line x1={x(v)} x2={x(v)} y1={PAD.t} y2={H - PAD.b} className="stroke-rule" strokeWidth={v === 0 ? 1 : 0.5} />
            <text x={x(v)} y={H - PAD.b + 14} textAnchor="middle" className="fill-muted-foreground font-mono text-[10px]">{v}</text>
          </g>
        ))}
        {ys.map((v) => (
          <g key={`y${v}`}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} className="stroke-rule" strokeWidth={0.5} />
            <text x={PAD.l - 6} y={y(v) + 3} textAnchor="end" className="fill-muted-foreground font-mono text-[10px]">{v}</text>
          </g>
        ))}
        {[-look.lfc, look.lfc].map((v) => <line key={v} x1={x(v)} x2={x(v)} y1={PAD.t} y2={H - PAD.b} className="stroke-foreground/40" strokeDasharray="3 3" strokeWidth={0.75} />)}
        {cut != null && <line x1={PAD.l} x2={W - PAD.r} y1={y(cut)} y2={y(cut)} className="stroke-foreground/40" strokeDasharray="3 3" strokeWidth={0.75} />}
        <path d={quiet} className="stroke-foreground/25" strokeWidth={2.4} strokeLinecap="round" />
        {down.map((g) => <circle key={g[0]} cx={x(g[1])} cy={y(g[2])} r={2.2} className="fill-control" />)}
        {up.map((g) => <circle key={g[0]} cx={x(g[1])} cy={y(g[2])} r={2.2} className="fill-signal" />)}
        {labelled.map((g) => {
          const right = x(g[1]) > W - 90 || (x(g[1]) < 90 ? false : g[1] < 0);
          return <text key={`l${g[0]}`} x={x(g[1]) + (right ? -5 : 5)} y={y(g[2]) + 3} textAnchor={right ? "end" : "start"} className="fill-foreground text-[10px] font-medium">{g[0]}</text>;
        })}
        {look.genes.filter((g) => ringed.has(g[0])).map((g) => <circle key={`r${g[0]}`} cx={x(g[1])} cy={y(g[2])} r={4} className="fill-none stroke-foreground" strokeWidth={0.9} />)}
        {hover && <circle cx={x(hover[1])} cy={y(hover[2])} r={4.5} className="fill-none stroke-foreground" strokeWidth={1.25} />}
        <text x={(PAD.l + W - PAD.r) / 2} y={H - 4} textAnchor="middle" className="fill-muted-foreground text-[10.5px]">log2 fold change, {look.case.join(", ")} vs {look.control.join(", ")}</text>
        <text transform={`translate(11 ${(PAD.t + H - PAD.b) / 2}) rotate(-90)`} textAnchor="middle" className="fill-muted-foreground text-[10.5px]">−log10 p</text>
      </svg>
      <figcaption className="min-h-5 font-mono text-[12px] tabular text-muted-foreground">
        {hover ? (
          <><span className="font-medium text-foreground">{hover[0]}</span> log2FC {hover[1].toFixed(2)} · p {(10 ** -hover[2]).toExponential(1)} · q {hover[3] >= 0.001 ? hover[3].toPrecision(2) : hover[3].toExponential(1)}{ringed.has(hover[0]) && " · named in the paper"}</>
        ) : (
          `Hover or tap a dot to name its ${look.feature ?? "gene"}.`
        )}
      </figcaption>
    </figure>
  );
}

function TopList({ accession, title, genes, tone, feature = "gene" }: { accession: string; title: string; genes: Gene[]; tone: "signal" | "control"; feature?: string }) {
  const router = useRouter();
  const across = (gene: string) => {
    const last = foundAll();
    router.push(genePath(gene, [...new Set([accession, ...last.accessions.filter((a) => a.startsWith("GSE"))])], last.topic));
  };
  return (
    <div className="grid content-start gap-2">
      <h3 className="flex items-center gap-2 text-[13px] font-medium">
        <span aria-hidden className={cn("size-2 rounded-full", tone === "signal" ? "bg-signal" : "bg-control")} />
        {title}
      </h3>
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="border-b border-rule text-left text-muted-foreground">
            <th className="py-1 font-normal capitalize">{feature}</th>
            <th className="py-1 text-right font-normal">log2FC</th>
            <th className="py-1 text-right font-normal">q</th>
          </tr>
        </thead>
        <tbody>
          {genes.slice(0, LISTED).map((g) => (
            <tr key={g[0]} className="border-b border-rule/60 last:border-b-0">
              <td className="py-1 font-medium">
                {feature === "gene" ? <button type="button" onClick={() => across(g[0])} title={`${g[0]} in every dataset of the search`} className={cn("cursor-pointer", LINK)}>{g[0]}</button> : g[0]}
              </td>
              <td className="py-1 text-right font-mono tabular">{g[1].toFixed(2)}</td>
              <td className="py-1 text-right font-mono tabular text-muted-foreground">{g[3] >= 0.001 ? g[3].toPrecision(2) : g[3].toExponential(1)}</td>
            </tr>
          ))}
          {genes.length === 0 && <tr><td colSpan={3} className="py-1 text-muted-foreground">none at these cut-offs</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function PaperLine({ check, ringOn, onRing }: { check: PaperCheck; ringOn: boolean; onRing: () => void }) {
  if (!check.available) return <p className="text-[12.5px] text-muted-foreground">Paper check: {check.reason ?? "not available"}.</p>;
  if (!check.named) return <p className="text-[12.5px] text-muted-foreground">The paper names none of the tested genes.</p>;
  return (
    <details className="group/p grid gap-2">
      <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-3 gap-y-1 text-[13px] [&::-webkit-details-marker]:hidden">
        <span>
          The paper mentions <span className="font-medium">{check.named}</span> of the tested genes; <span className="font-medium">{check.significant}</span> are among the coloured genes here <span className="text-muted-foreground">(about {check.by_chance} by chance)</span>.
        </span>
        <button type="button" aria-pressed={ringOn} onClick={(e) => { e.preventDefault(); onRing(); }} className={cn("text-[12.5px]", MUTED_LINK)}>
          {ringOn ? "Hide rings" : "Ring them on the plot"}
        </button>
        <span className={cn("text-[12.5px]", MUTED_LINK)}>Show the genes</span>
      </summary>
      <div className="grid gap-2 pt-2">
        <p className="flex flex-wrap gap-x-3 gap-y-1 text-[12.5px]">
          {check.genes.map((g) => (
            <span key={g.gene} title={g.sentence ? `${g.where}: “${g.sentence}”` : `Named in the paper (${g.where})`}
              className={cn("font-medium", !g.significant ? "text-muted-foreground" : g.log2fc > 0 ? "text-signal" : "text-control")}>
              {g.gene}
            </span>
          ))}
        </p>
        <p className="text-[12px] text-muted-foreground">
          Read from {check.read}: <a href={check.url} className={MUTED_LINK}>{check.title}</a> <span className="italic">{check.journal}</span> {check.year}. Coloured as on the plot.
        </p>
      </div>
    </details>
  );
}

function DesignChecks({ check }: { check: DesignCheck }) {
  if (!check.available) return null;
  return (
    <div className="grid gap-2 border-l-2 border-foreground pl-3 text-[13px]">
      <p className="font-medium">Design check</p>
      {check.traps.length === 0 && <p className="text-muted-foreground">No batch-like characteristic goes with the comparison, and no characteristic is unbalanced by 30 points or more.</p>}
      {check.traps.map((t) => (
        <details key={t.title} className="group/t">
          <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-2 [&::-webkit-details-marker]:hidden">
            <span className="flex items-center gap-1.5"><span aria-hidden className="size-2 rounded-full bg-signal" />{t.title}</span>
            <span className="text-muted-foreground">{t.detail}</span>
          </summary>
          {t.table && (
            <table className="mt-1 text-[12px]">
              <thead><tr className="text-muted-foreground"><th className="pr-4 text-left font-normal">{t.factor}</th><th className="pr-4 text-right font-normal">cases</th><th className="text-right font-normal">controls</th></tr></thead>
              <tbody>{t.table.map(([lv, a, b]) => <tr key={lv}><td className="pr-4">{lv}</td><td className="pr-4 text-right font-mono tabular">{a}</td><td className="text-right font-mono tabular">{b}</td></tr>)}</tbody>
            </table>
          )}
        </details>
      ))}
      {check.balanced.length > 0 && <p className="text-muted-foreground">Balanced: {check.balanced.map((b) => `${b.factor} (V ${b.v})`).join(", ")}</p>}
      {check.power && (
        <p>
          With {check.power.n_case} and {check.power.n_control} {check.power.unit ?? "samples"}, a {check.power.fold}× change (log2 {check.power.detectable_log2fc}) in a typical gene is detectable.
          <span className="text-muted-foreground"> {check.power.method}.</span>
        </p>
      )}
    </div>
  );
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: [string, string][]; onChange: (v: string) => void }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}
      className="h-8 max-w-56 truncate rounded-md border border-rule bg-card px-2 text-[16px] outline-none transition-colors duration-150 focus:border-foreground sm:text-[13px]">
      {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
    </select>
  );
}

const qText = (q: number) => (q >= 0.001 ? q.toPrecision(2) : q.toExponential(1));

function PathwayList({ title, side, tone }: { title: string; side?: PathwaySide; tone: "signal" | "control" }) {
  return (
    <div className="grid content-start gap-2">
      <h3 className="flex items-center gap-2 text-[13px] font-medium">
        <span aria-hidden className={cn("size-2 rounded-full", tone === "signal" ? "bg-signal" : "bg-control")} />
        {title}
      </h3>
      {!side ? (
        <p className="text-[12.5px] text-muted-foreground">Asking Enrichr…</p>
      ) : side.terms.length === 0 ? (
        <p className="text-[12.5px] text-muted-foreground">{side.reason ?? `No Reactome pathway reaches q < 0.05 among the top ${side.genes} genes`}.</p>
      ) : (
        <ul className="grid gap-1.5 text-[12.5px]">
          {side.terms.map((t) => (
            <li key={t.term} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3">
              <a href={`https://reactome.org/content/detail/${t.id}`} target="_blank" rel="noreferrer" title={t.genes.join(", ")} className={cn("w-fit", LINK)}>{t.term}</a>
              <span className="font-mono tabular text-muted-foreground">{t.genes.length} genes · q {qText(t.q)}</span>
            </li>
          ))}
          {(side.significant ?? 0) > side.terms.length && <li className="text-muted-foreground">+{side.significant! - side.terms.length} more at q &lt; 0.05</li>}
        </ul>
      )}
    </div>
  );
}

export function FirstLookSection({ accession }: { accession: string }) {
  const [summary, setSummary] = useState<TableSummary | null>(null);
  const [look, setLook] = useState<FirstLook | null>(null);
  const [pick, setPick] = useState<Pick | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [check, setCheck] = useState<PaperCheck | null>(null);
  const [design, setDesign] = useState<DesignCheck | null>(null);
  const [ringOn, setRingOn] = useState(true);
  const [answered, setAnswered] = useState<{ look: FirstLook; data: Pathways } | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    tableSummary(accession, ctrl.signal).then(setSummary, () => !ctrl.signal.aborted && setFailed(true));
    return () => ctrl.abort();
  }, [accession]);

  useEffect(() => {
    if (!summary?.available) return;
    const ctrl = new AbortController();
    firstLook(accession, pick, ctrl.signal).then(
      (r) => { setLook(r); setBusy(false); },
      () => { if (!ctrl.signal.aborted) { setFailed(true); setBusy(false); } },
    );
    return () => ctrl.abort();
  }, [accession, summary, pick]);

  useEffect(() => {
    if (!look?.available) return;
    const ctrl = new AbortController();
    designCheck(accession, { factor: look.factor, case: look.case, control: look.control }, ctrl.signal).then(setDesign, () => {});
    // The paper's genes and Reactome pathways are about genes; a metabolite table has neither.
    if (look.feature === "metabolite") return () => ctrl.abort();
    paperCheck(accession, { factor: look.factor, case: look.case, control: look.control }, ctrl.signal).then(setCheck, () => {});
    pathways(accession, { factor: look.factor, case: look.case, control: look.control, within: look.within }, ctrl.signal).then(
      (data) => setAnswered({ look, data }),
      () => !ctrl.signal.aborted && setAnswered({ look, data: { available: false, reason: "Enrichr did not answer" } }),
    );
    return () => ctrl.abort();
  }, [accession, look]);
  const paths = answered?.look === look ? answered.data : null;
  const unit = look?.feature ?? (accession.startsWith("ST") ? "metabolite" : "gene");
  const ringed = useMemo(() => new Set(ringOn && check?.available ? check.genes.map((g) => g.gene) : []), [check, ringOn]);

  if (!summary && !failed) return null;
  if (summary && !summary.available) return null;
  const factors = look?.groups?.factors ?? [];
  const starter = factors.find((f) => !f.nuisance) ?? factors[0];
  const current: Pick | null = look?.available
    ? { factor: look.factor, case: look.case, control: look.control, within: look.within }
    : pick ?? (starter ? { factor: starter.name, case: [Object.keys(starter.levels)[0]], control: [Object.keys(starter.levels)[1]] } : null);
  const factor = factors.find((f) => f.name === current?.factor);
  const levels: [string, string][] = factor ? Object.entries(factor.levels).map(([lv, n]) => [lv, `${lv} (${n})`]) : [];
  const choose = (next: Partial<Pick>) => {
    if (!current) return;
    const base: Pick = { ...current, ...next };
    if (next.factor) {
      const lv = Object.keys(factors.find((f) => f.name === next.factor)?.levels ?? {});
      Object.assign(base, { case: [lv[0]], control: [lv[1]], within: null });
    }
    setBusy(true);
    setPick(base);
  };
  const hits = (g: Gene) => g[3] < (look?.q ?? 0) && Math.abs(g[1]) >= (look?.lfc ?? 0);
  const pooled = look?.available ? look.pooled[0] : undefined;

  return (
    <section className="grid content-start gap-6">
      <Heading id="first-look">First look</Heading>
      {failed ? (
        <p className="text-[13px] text-muted-foreground">locus could not compute the comparison; its server failed.</p>
      ) : !look ? (
        <p className="text-[13px] text-muted-foreground">Reading {summary?.genes?.toLocaleString()} {unit}s × {summary?.samples} samples…</p>
      ) : (
        <>
          {current && factors.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-[13px]">
              <span className="text-muted-foreground">Compare</span>
              <Select label="Sample characteristic" value={current.factor} options={factors.map((f) => [f.name, f.name])} onChange={(v) => choose({ factor: v })} />
              <Select label="Case group" value={current.case[0]} options={levels} onChange={(v) => choose({ case: [v] })} />
              <span className="text-muted-foreground">against</span>
              <Select label="Control group" value={current.control[0]} options={levels} onChange={(v) => choose({ control: [v] })} />
              {(pooled || look.within) && (
                <>
                  <span className="text-muted-foreground">within</span>
                  <Select label="Within one level of" value={look.within?.[1] ?? ""} options={[["", `all ${pooled?.factor ?? look.within?.[0]}`], ...((pooled?.levels ?? (look.within ? [look.within[1]] : [])).map((l) => [l, l] as [string, string]))]}
                    onChange={(v) => choose({ within: v ? [pooled?.factor ?? look.within![0], v] : null })} />
                </>
              )}
              {!look.available && <button type="button" onClick={() => choose({})} className={cn("font-medium", LINK)}>Compare</button>}
              {busy && <span className="font-mono text-[12px] text-muted-foreground">testing…</span>}
            </div>
          )}
          {!look.available ? (
            <p className="text-[13px] text-muted-foreground">
              No comparison shown: {look.reason}.{look.samples_with_data < look.record_samples && ` The table covers ${look.samples_with_data} of the ${look.record_samples} samples.`}
            </p>
          ) : (
            <>
              <p className="font-mono text-[12.5px] tabular">
                <span className="text-signal">{look.up.toLocaleString()} higher</span> · <span className="text-control">{look.down.toLocaleString()} lower</span> in {look.n_case} {look.case.join(", ")} than {look.n_control} {look.control.join(", ")}
                <span className="text-muted-foreground"> · {look.tested.toLocaleString()} {unit}s tested · q &lt; {look.q}, |log2FC| ≥ {look.lfc}{look.samples_with_data < look.record_samples && ` · data for ${look.samples_with_data} of ${look.record_samples} samples`}</span>
              </p>
              {look.warnings.length > 0 && (
                <ul className="grid gap-0.5 text-[12.5px] text-warn">
                  {look.warnings.map((w) => <li key={w}>Caution: {w}</li>)}
                </ul>
              )}
              {design && <DesignChecks check={design} />}
              {check && <PaperLine check={check} ringOn={ringOn} onRing={() => setRingOn((v) => !v)} />}
              <div className={cn("grid gap-8 transition-opacity duration-200", busy && "opacity-50")}>
                <Volcano look={look} ringed={ringed} />
                <div className="grid content-start gap-6 sm:grid-cols-2 sm:gap-10">
                  <TopList accession={accession} title={`Higher in ${look.case.join(", ")}`} genes={look.genes.filter((g) => hits(g) && g[1] > 0)} tone="signal" feature={unit} />
                  <TopList accession={accession} title={`Higher in ${look.control.join(", ")}`} genes={look.genes.filter((g) => hits(g) && g[1] < 0)} tone="control" feature={unit} />
                </div>
                {unit !== "gene" ? null : paths?.available === false ? (
                  <p className="text-[12.5px] text-muted-foreground">Pathways: {paths.reason}.</p>
                ) : (
                  <div className="grid gap-3">
                    <div className="grid content-start gap-6 sm:grid-cols-2 sm:gap-10">
                      <PathwayList title={`Pathways higher in ${look.case.join(", ")}`} side={paths?.sides?.up} tone="signal" />
                      <PathwayList title={`Pathways higher in ${look.control.join(", ")}`} side={paths?.sides?.down} tone="control" />
                    </div>
                    {paths?.method && <p className="max-w-[80ch] text-[12px] text-muted-foreground">{paths.method}. <a href={paths.source} className={MUTED_LINK}>Enrichr</a>, {paths.library?.replace("_", " ")}.</p>}
                  </div>
                )}
              </div>
              <p className="max-w-[80ch] text-[12px] leading-relaxed text-muted-foreground">
                {look.method}. Table: {look.source.pipeline}, {look.source.build} (<a href={look.source.url} className={MUTED_LINK}>{look.source.file}</a>). A screen for direction, not a replacement for {unit === "gene" ? "DESeq2 or limma" : "the authors' statistics"}.
              </p>
            </>
          )}
        </>
      )}
      {look?.available && unit === "gene" && <Link href={`/list?in=${accession}`} className={cn("w-fit text-[13px]", MUTED_LINK)}>Check your own gene list in this comparison</Link>}
      {summary?.available && summary.source && (
        <a href={tableDownload(accession)} download className={cn("flex w-fit items-center gap-1.5 text-[13px] font-medium", LINK)}>
          <Download aria-hidden className="size-3.5" />
          Get the table: {summary.genes?.toLocaleString()} {unit}s × {summary.samples} samples, with sample characteristics{unit === "gene" && " and gene names"}
          <span className="font-mono text-[12px] font-normal text-muted-foreground">zip, from {size(summary.source.bytes)}</span>
        </a>
      )}
    </section>
  );
}
