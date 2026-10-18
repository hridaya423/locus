"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowRight, ArrowUpRight, ChevronDown, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { DesignView } from "@/components/design";
import { EASE_OUT } from "@/lib/springs";
import { SAMPLE_TYPE, datasetPath, repositoryName, samplesheet, type Check, type Facts, type Hit } from "@/lib/api";
import { Evidence, Methods, Ready } from "@/components/row-details";
import { MASS_SPEC, ProtocolLine } from "@/components/assay";

const DATA_TYPE: [RegExp, string][] = [
  [/expression profiling by high throughput sequencing/i, "RNA-seq"],
  [/expression profiling by array/i, "microarray"],
  [/genome binding\/occupancy profiling/i, "ChIP-seq"],
  [/methylation profiling/i, "methylation"],
  [/non-coding RNA profiling by high throughput sequencing/i, "ncRNA-seq"],
  [/non-coding RNA profiling by array/i, "ncRNA array"],
  [/genome variation profiling/i, "DNA variation"],
  [/protein profiling/i, "protein array"],
  [/snp genotyping/i, "SNP genotyping"],
  [/^single-cell/i, "single-cell"],
  [/^proteomics/i, "proteomics"],
];

export function dataType(modality: string) {
  const types = modality.split(";").map((m) => DATA_TYPE.find(([re]) => re.test(m.trim()))?.[1] ?? m.trim());
  return [...new Set(types)].filter(Boolean).join(", ");
}

export function assayOf(hit: Hit) {
  return hit.facts?.assays?.length ? hit.facts.assays.join(" + ") : dataType(hit.modality);
}

export function materialOf(hit: Hit) {
  const f = hit.facts;
  return f ? [f.tissue, SAMPLE_TYPE[f.sample_type]].filter(Boolean).join(", ") : "";
}

export const shortAccession = (hit: Hit) => (hit.source === "CELLxGENE" ? hit.accession.slice(0, 8) : hit.accession);

// Opening and closing animate height, so the rows below glide instead of jumping.
export const unfold = {
  initial: { height: 0, opacity: 0 },
  animate: { height: "auto", opacity: 1 },
  exit: { height: 0, opacity: 0, transition: { duration: 0.18, ease: [0.4, 0, 1, 1] } },
  transition: { height: { type: "spring", duration: 0.32, bounce: 0 }, opacity: { duration: 0.2, delay: 0.05 } },
} as const;

// A no-break space before each dot keeps separators from starting a wrapped line.
export const SEP = "\u00a0·  ";

export const ROW = "border-b border-rule transition-colors duration-150 last:border-b-0 hover:bg-card/60";

export const ACTION =
  "flex items-center gap-1 text-[13px] text-muted-foreground underline decoration-rule underline-offset-4 transition-colors duration-150 hover:text-foreground hover:decoration-foreground";

// Back from a dataset page, the search restores its results; this puts the reader back on the row they opened.
export const SCROLL = "locus:scroll";
export const rememberScroll = () => sessionStorage.setItem(SCROLL, String(window.scrollY));

const TONE = { signal: "text-signal", control: "text-control" } as const;

export function CountCell({ value, tone, pooled, people, href }: { value: number | null | undefined; tone: keyof typeof TONE; pooled?: number; people?: number; href: string }) {
  if (value === null || value === undefined) {
    return (
      <td className="py-3 pl-2 text-right align-top font-mono text-[13px] text-muted-foreground" title="Not counted from sample records">
        –
      </td>
    );
  }
  return (
    <td className="py-3 pl-2 text-right align-top">
      <Link
        href={href}
        onClick={rememberScroll}
        title="Open the sample records"
        className={cn("font-mono text-[13px] font-medium tabular underline decoration-transparent underline-offset-4 transition-colors duration-150 hover:decoration-current", value === 0 ? "text-muted-foreground" : TONE[tone])}
      >
        {value}
      </Link>
      {people != null && people !== value && (
        <div className="mt-0.5 whitespace-nowrap font-mono text-[11px] text-muted-foreground" title={`${value} sample records from ${people} people`}>
          {people} {people === 1 ? "person" : "people"}
        </div>
      )}
      {pooled ? (
        <div className="mt-0.5 whitespace-nowrap font-mono text-[11px] text-muted-foreground" title="Libraries that pool patient and control cells, for example a multiplexed single-cell run">
          +{pooled} pooled
        </div>
      ) : null}
    </td>
  );
}

const GROUPS = ["case", "control", "mixed", "other"] as const;
const norm = (assay: string) => assay.toLowerCase().replace(/[^a-z0-9]/g, "");

function Libraries({ libraries, matched }: { libraries: NonNullable<Facts["libraries"]>; matched: string[] }) {
  const assays = Object.keys(libraries);
  const paired = assays.filter((a) => matched.some((m) => norm(m) === norm(a)));
  const unmatched = new Map<string, number>();
  if (paired.length > 1) {
    for (const g of GROUPS) {
      const counts = paired.map((a) => libraries[a][g] ?? 0);
      const low = Math.min(...counts);
      paired.forEach((a, i) => counts[i] > low && unmatched.set(a, (unmatched.get(a) ?? 0) + counts[i] - low));
    }
  }
  const total = (a: string) => GROUPS.map((g) => libraries[a][g] ?? 0).filter(Boolean).join(" + ");
  if (assays.length < 2) return null;
  return (
    <span className="grid gap-0.5">
      <span className="label text-muted-foreground">{assays.map((a) => `${a} ${total(a)}`).join("  ·  ")}</span>
      {[...unmatched].map(([assay, n]) => (
        <span key={assay} className="flex items-start gap-1 text-xs text-warn">
          <X aria-hidden className="mt-0.5 size-3 shrink-0" strokeWidth={2.5} />
          {n} {assay} {n === 1 ? "library has" : "libraries have"} no matching {paired.filter((a) => a !== assay).join(" or ")}
        </span>
      ))}
    </span>
  );
}

// A native checkbox, restyled: the box fills with ink and the tick draws itself in.
export function Checkbox({ checked, mixed = false, onChange, label }: { checked: boolean; mixed?: boolean; onChange: () => void; label: string }) {
  return (
    <label className="relative mt-[2px] grid size-4 cursor-pointer place-items-center before:absolute before:-inset-3 before:content-['']">
      <input
        type="checkbox"
        checked={checked}
        ref={(el) => { if (el) el.indeterminate = mixed; }}
        onChange={onChange}
        aria-label={label}
        className="peer size-4 cursor-pointer appearance-none rounded-[4px] border border-foreground/25 bg-card transition-[background-color,border-color,transform] duration-150 ease-out hover:border-foreground/60 active:scale-[0.92] checked:border-foreground checked:bg-foreground indeterminate:border-foreground indeterminate:bg-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground"
      />
      <svg aria-hidden viewBox="0 0 12 12" className="pointer-events-none absolute size-3 text-background peer-checked:[&_path]:[stroke-dashoffset:0] peer-indeterminate:[&_path]:[stroke-dashoffset:0]">
        <path
          d={mixed ? "M3 6h6" : "M2.5 6.4 5 8.8 9.6 3.6"}
          pathLength={1}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="transition-[stroke-dashoffset] duration-200 ease-out [stroke-dasharray:1] [stroke-dashoffset:1]"
        />
      </svg>
    </label>
  );
}

// The study's checkbox sits at x = 20.5. Its datasets indent their checkbox to x = 36, and each branch leaves the
// trunk and bends into its checkbox's centre (y = 22). Each row draws its own piece, so rows can grow when opened.
const TRUNK = 20.5;
// Opaque mixes, so the pieces that meet at a joint never darken where they overlap.
export const tone = (active: boolean) =>
  active
    ? "text-[color-mix(in_oklab,var(--foreground)_70%,var(--card))]"
    : "text-[color-mix(in_oklab,var(--foreground)_20%,var(--card))] group-hover/row:text-[color-mix(in_oklab,var(--foreground)_45%,var(--card))]";
export const draw = (still: boolean | null, delay: number) => ({
  initial: still ? false : { pathLength: 0 },
  animate: { pathLength: 1 },
  transition: { duration: 0.3, ease: EASE_OUT, delay },
});

export function Stem({ active }: { active: boolean }) {
  const still = useReducedMotion();
  return (
    <svg aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[calc(100%+2px)] w-full">
      <motion.line x1={TRUNK} x2={TRUNK} y1={34} y2="100%" stroke="currentColor" className={cn("transition-colors duration-150", tone(active))} {...draw(still, 0)} />
    </svg>
  );
}

type Branch = { index: number; last: boolean; below: boolean };

function Branch({ index, last, below, selected }: Branch & { selected: boolean }) {
  const still = useReducedMotion();
  const delay = 0.1 + index * 0.05;
  const stroke = { stroke: "currentColor", fill: "none" };
  return (
    <svg aria-hidden className="pointer-events-none absolute inset-0 size-full">
      <motion.line x1={TRUNK} x2={TRUNK} y1={0} y2={14} {...stroke} className={cn("transition-colors duration-150", tone(selected || below))} {...draw(still, delay)} />
      <motion.path d={`M${TRUNK} 14 A8 8 0 0 0 ${TRUNK + 8} 22 H33`} {...stroke} strokeLinecap="round" className={cn("transition-colors duration-150", tone(selected))} {...draw(still, delay + 0.06)} />
      {!last && <motion.line x1={TRUNK} x2={TRUNK} y1={14} y2="100%" {...stroke} className={cn("transition-colors duration-150", tone(below))} {...draw(still, delay + 0.06)} />}
    </svg>
  );
}

const WARNING: Record<string, Partial<Record<Check, string>>> = {
  patient_material: { no: "not patient material", unclear: "sample source not confirmed" },
  data_type: { no: "different data type" },
  controls: { no: "no healthy controls", unclear: "controls not confirmed" },
};

type RowProps = {
  hit: Hit;
  matched: string[];
  topic: string;
  selected: boolean;
  onSelect: (accession: string) => void;
  branch?: Branch;
  counts: boolean;
};

export function DatasetRow({ hit, matched, topic, selected, onSelect, branch, counts }: RowProps) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [sheet, setSheet] = useState<"idle" | "writing" | "failed">("idle");
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);
  const facts = hit.facts;
  const plan = hit.download_plan;
  const page = datasetPath(hit.accession);
  const riboseq = hit.source === "GEO" && (facts?.assays ?? []).some((a) => /^(riboseq|tisseq|ribosomeprofiling)$/.test(norm(a)));

  async function exportSamplesheet() {
    setSheet("writing");
    try {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await samplesheet(hit.accession, topic));
      a.download = `${hit.accession}-riboseq.zip`;
      a.click();
      URL.revokeObjectURL(a.href);
      setSheet("idle");
    } catch {
      setSheet("failed");
    }
  }
  const reason = hit.fit === "partial" ? hit.reason : "";
  const warnings = Object.entries(WARNING).map(([k, text]) => text[hit.checks[k as keyof Hit["checks"]]]).filter(Boolean);
  const meta = [repositoryName(hit.source), hit.published?.slice(0, 4), assayOf(hit), materialOf(hit)].filter(Boolean).join(SEP);
  const toggle = () => setExpanded((v) => !v);

  return (
    <tbody data-accession={hit.accession} className={cn(ROW, (selected || expanded) && "bg-card hover:bg-card")}>
      <tr className="group/row">
        <td className={cn("py-3 align-top", branch ? "relative pl-9" : "pl-3")}>
          {branch && <Branch {...branch} selected={selected} />}
          <Checkbox checked={selected} onChange={() => onSelect(hit.accession)} label={`Select ${hit.accession}`} />
        </td>
        <td className="min-w-0 py-3 pr-2 align-top">
          <div className="grid min-w-0 gap-1">
            <Link href={page} onClick={rememberScroll} className="w-fit text-sm leading-snug text-foreground underline decoration-transparent underline-offset-4 transition-colors duration-150 hover:decoration-foreground">
              {hit.title}
            </Link>
            <button type="button" onClick={toggle} aria-expanded={expanded} aria-label={`Details of ${hit.accession}`} className="grid w-full min-w-0 cursor-pointer gap-1 text-left">
              <span className="flex min-w-0 flex-wrap items-baseline gap-x-2" title={meta}>
                <span className="shrink-0 font-mono text-[12px] font-medium text-foreground/80">{shortAccession(hit)}</span>
                <span className="label line-clamp-2 min-w-0 basis-full text-muted-foreground sm:line-clamp-1 sm:basis-0 sm:grow">{meta}</span>
              </span>
              {!branch && hit.paper && (
                <span className="text-[12.5px] leading-snug text-muted-foreground">
                  <span className="italic">{hit.paper.journal}</span> {hit.paper.year}
                </span>
              )}
              {facts?.libraries && Object.keys(facts.libraries).length > 0 && <Libraries libraries={facts.libraries} matched={matched} />}
            </button>
          </div>
        </td>
        {counts && <CountCell value={facts?.case} tone="signal" people={facts?.donors?.case} href={`${page}#samples`} />}
        {counts && <CountCell value={facts?.control} tone="control" pooled={facts?.mixed} people={facts?.donors?.control} href={`${page}#samples`} />}
        <td className="overflow-hidden py-3 pl-2 text-right align-top font-mono text-[13px] tabular text-muted-foreground max-sm:invisible max-sm:p-0">{hit.samples ?? "–"}</td>
        <td className="py-3 pl-1 align-top">
          <button type="button" onClick={toggle} aria-expanded={expanded} aria-label={`${expanded ? "Hide" : "Show"} details of ${hit.accession}`} className="relative grid cursor-pointer place-items-center before:absolute before:-inset-2 before:content-['']">
            <ChevronDown aria-hidden className={cn("mt-[2px] size-4 text-muted-foreground transition-transform duration-200", expanded && "rotate-180")} />
          </button>
        </td>
      </tr>
      <AnimatePresence initial={false}>
        {expanded && (
          <tr>
            <td />
            <td colSpan={counts ? 5 : 3} className="pr-2">
              <motion.div {...unfold} className="overflow-hidden">
                <div className="grid gap-3 pb-4">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
                  <Link href={page} onClick={rememberScroll} className="group/link flex items-center gap-1 font-medium underline decoration-rule underline-offset-4 hover:decoration-foreground">
                    Open dataset
                    <ArrowRight aria-hidden className="size-3.5 text-muted-foreground transition-transform duration-150 group-hover/link:translate-x-0.5 group-hover/link:text-foreground" />
                  </Link>
                  {hit.paper && (
                    <a href={hit.paper.url} target="_blank" rel="noreferrer" className="group/link flex items-center gap-1 text-muted-foreground underline decoration-rule underline-offset-4 hover:text-foreground hover:decoration-foreground">
                      Open paper
                      <ArrowUpRight aria-hidden className="size-3.5 group-hover/link:text-foreground" />
                    </a>
                  )}
                </div>
                {reason && <p className="text-sm text-muted-foreground">{reason}</p>}
                {!reason && warnings.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {warnings.map((w) => (
                      <span key={w} className="flex items-center gap-1 rounded-[4px] bg-warn-soft px-1.5 py-0.5 text-xs text-warn"><X aria-hidden className="size-3" strokeWidth={2.5} />{w}</span>
                    ))}
                  </div>
                )}
                <Evidence hit={hit} onOpen={rememberScroll} />
                {facts?.methods && <Methods methods={facts.methods} />}
                {MASS_SPEC.has(hit.source) && <ProtocolLine accession={hit.accession} />}
                {hit.source === "PRIDE" && <Ready accession={hit.accession} />}
                <DesignView accession={hit.accession} source={hit.source} />
                <details className="group/plan">
                  <summary className={cn(ACTION, "w-fit cursor-pointer list-none")}>
                    Download data
                    <ChevronDown aria-hidden className="size-3.5 transition-transform duration-200 group-open/plan:rotate-180" />
                  </summary>
                  <div className="mt-2 grid min-w-0 gap-1.5 border-l-2 border-foreground pl-3">
                    <pre className="overflow-x-auto font-mono text-[12px] leading-relaxed">{plan}</pre>
                    <button
                      type="button"
                      onClick={() => navigator.clipboard.writeText(plan).then(() => setCopied(true))}
                      className="w-fit text-xs font-medium text-foreground underline decoration-rule underline-offset-4 hover:decoration-foreground"
                    >
                      {copied ? "copied" : "copy"}
                    </button>
                  </div>
                </details>
                {riboseq && (
                  <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <button type="button" onClick={exportSamplesheet} disabled={sheet === "writing"} className={cn(ACTION, "w-fit disabled:cursor-wait disabled:no-underline")}>
                      Samplesheet for nf-core/riboseq
                    </button>
                    <span role="status" className={cn("text-xs", sheet === "failed" ? "text-warn" : "text-muted-foreground")}>
                      {sheet === "failed"
                        ? "The samplesheet could not be written. Try again."
                        : sheet === "writing"
                          ? "Writing…"
                          : "zip, with contrasts and a README"}
                    </span>
                  </span>
                )}
                </div>
              </motion.div>
            </td>
          </tr>
        )}
      </AnimatePresence>
    </tbody>
  );
}
