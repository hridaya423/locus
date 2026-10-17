"use client";
import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUpRight, ChevronDown, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { motionTier } from "@/lib/springs";
import { SAMPLE_TYPE, repositoryName, samplesheet, type Check, type Facts, type Hit } from "@/lib/api";

const WARNING: Record<string, Partial<Record<Check, string>>> = {
  patient_material: { no: "not patient material", unclear: "sample source not confirmed" },
  data_type: { no: "different data type" },
  controls: { no: "no healthy controls", unclear: "controls not confirmed" },
};

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

const ACTION =
  "flex items-center gap-1 text-[13px] text-muted-foreground underline decoration-rule underline-offset-4 transition-colors duration-150 hover:text-foreground hover:decoration-foreground";

const reveal = {
  initial: { opacity: 0, y: -4 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, transition: motionTier.micro.exit },
  transition: motionTier.ui,
};

const TONE = { signal: "text-signal", control: "text-control" } as const;

function CountCell({ value, tone, pooled, href }: { value: number | null | undefined; tone: keyof typeof TONE; pooled?: number; href?: string }) {
  if (value === null || value === undefined) {
    return (
      <td className="py-3 pl-2 text-right align-top font-mono text-[13px] text-muted-foreground" title="Not counted from sample records">
        –
      </td>
    );
  }
  return (
    <td className="py-3 pl-2 text-right align-top">
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        title="Open the sample records"
        className={cn("font-mono text-[13px] font-medium tabular underline decoration-transparent underline-offset-4 transition-colors duration-150 hover:decoration-current", value === 0 ? "text-muted-foreground" : TONE[tone])}
      >
        {value}
      </a>
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
function Checkbox({ checked, onChange, label }: { checked: boolean; onChange: () => void; label: string }) {
  return (
    <label className="relative mt-[2px] grid size-4 cursor-pointer place-items-center before:absolute before:-inset-3 before:content-['']">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        aria-label={label}
        className="peer size-4 cursor-pointer appearance-none rounded-[4px] border border-foreground/25 bg-card transition-[background-color,border-color,transform] duration-150 ease-out hover:border-foreground/60 active:scale-[0.92] checked:border-foreground checked:bg-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground"
      />
      <svg aria-hidden viewBox="0 0 12 12" className="pointer-events-none absolute size-3 text-background peer-checked:[&_path]:[stroke-dashoffset:0]">
        <path
          d="M2.5 6.4 5 8.8 9.6 3.6"
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

type RowProps = {
  hit: Hit;
  matched: string[];
  topic: string;
  selected: boolean;
  onSelect: (accession: string) => void;
  sameStudy: boolean;
  counts: boolean;
};

export function DatasetRow({ hit, matched, topic, selected, onSelect, sameStudy, counts }: RowProps) {
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
  const samplesUrl = hit.source === "GEO" ? `https://www.ncbi.nlm.nih.gov/geo/browse/?view=samples&series=${hit.accession.slice(3)}` : hit.url;
  const warnings = Object.entries(WARNING).map(([k, text]) => text[hit.checks[k as keyof Hit["checks"]]]).filter(Boolean);
  // Assay and material move into the expanded row on phones.
  const meta = [
    { text: repositoryName(hit.source), phone: true },
    { text: hit.published?.slice(0, 4), phone: true },
    { text: assayOf(hit), phone: false },
    { text: materialOf(hit), phone: false },
  ].filter((m) => m.text);

  return (
    <tbody className={cn("border-b border-rule transition-colors duration-150 last:border-b-0", selected && "bg-card", expanded && "bg-card")}>
      <tr className="group/row">
        <td className="py-3 pl-3 align-top">
          <Checkbox checked={selected} onChange={() => onSelect(hit.accession)} label={`Select ${hit.accession}`} />
        </td>
        <td className="min-w-0 py-3 pr-2 align-top">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="grid w-full min-w-0 cursor-pointer gap-1 text-left"
          >
            <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
              {sameStudy && <span className="label shrink-0 text-muted-foreground" title="Part of the study above">↳</span>}
              <span className="shrink-0 font-mono text-[13px] font-medium">{shortAccession(hit)}</span>
              {meta.map((m, i) => (
                <span key={m.text} className={cn("label text-muted-foreground", i > 0 && "before:mr-2 before:content-['·']", !m.phone && "max-sm:hidden")}>
                  {m.text}
                </span>
              ))}
              {warnings.length > 0 && <span className="label shrink-0 text-warn">✕ {warnings.length}</span>}
            </span>
            <span className="text-sm leading-snug text-foreground/90">{hit.title}</span>
            {facts?.libraries && Object.keys(facts.libraries).length > 0 && <Libraries libraries={facts.libraries} matched={matched} />}
          </button>
        </td>
        {counts && <CountCell value={facts?.case} tone="signal" href={samplesUrl} />}
        {counts && <CountCell value={facts?.control} tone="control" pooled={facts?.mixed} href={samplesUrl} />}
        <td className="overflow-hidden py-3 pl-2 text-right align-top font-mono text-[13px] tabular text-muted-foreground max-sm:invisible max-sm:p-0">{hit.samples ?? "–"}</td>
        <td className="py-3 pl-1 align-top">
          <ChevronDown aria-hidden className={cn("mt-[2px] size-4 text-muted-foreground transition-transform duration-200", expanded && "rotate-180")} />
        </td>
      </tr>
      <AnimatePresence initial={false}>
        {expanded && (
          <tr>
            <td />
            <td colSpan={counts ? 5 : 3} className="pb-4 pr-2">
              <motion.div {...reveal} className="grid gap-3">
                <p className="label text-muted-foreground sm:hidden">{[assayOf(hit), materialOf(hit)].filter(Boolean).join("  ·  ")}</p>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
                  <a href={hit.url} target="_blank" rel="noreferrer" className="group/link flex items-center gap-1 font-medium underline decoration-rule underline-offset-4 hover:decoration-foreground">
                    Open in {repositoryName(hit.source)}
                    <ArrowUpRight aria-hidden className="size-3.5 text-muted-foreground group-hover/link:text-foreground" />
                  </a>
                  {hit.paper && (
                    <a href={hit.paper.url} target="_blank" rel="noreferrer" className="min-w-0 text-muted-foreground hover:text-foreground">
                      <span className="italic">{hit.paper.journal}</span> {hit.paper.year} · {hit.paper.title}
                    </a>
                  )}
                </div>
                {hit.fit === "partial" && <p className="text-sm text-muted-foreground">{hit.reason}</p>}
                {warnings.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {warnings.map((w) => (
                      <span key={w} className="flex items-center gap-1 rounded-[4px] bg-warn-soft px-1.5 py-0.5 text-xs text-warn"><X aria-hidden className="size-3" strokeWidth={2.5} />{w}</span>
                    ))}
                  </div>
                )}
                {hit.evidence && (
                  <p className="border-l-2 border-foreground pl-3 font-mono text-[12.5px] leading-relaxed">
                    &quot;{hit.evidence}&quot;
                    {facts && (
                      <span className="label block pt-1.5 text-muted-foreground">
                        counts from {facts.source}
                        {facts.library && Object.keys(facts.library).length > 0 && ` · library: ${Object.entries(facts.library).map(([k, v]) => `${k} ${v}`).join(", ")}`}
                      </span>
                    )}
                  </p>
                )}
                <details className="group/plan">
                  <summary className={cn(ACTION, "w-fit cursor-pointer list-none")}>
                    Download data
                    <ChevronDown aria-hidden className="size-3.5 transition-transform duration-200 group-open/plan:rotate-180" />
                  </summary>
                  <div className="mt-2 grid min-w-0 gap-1.5 border-l-2 border-foreground pl-3">
                    <pre className="overflow-x-auto font-mono text-[12px] leading-relaxed">{plan}</pre>
                    <span className="flex gap-3 text-xs text-muted-foreground">
                      <button
                        type="button"
                        onClick={() => navigator.clipboard.writeText(plan).then(() => setCopied(true))}
                        className="font-medium text-foreground underline decoration-rule underline-offset-4 hover:decoration-foreground"
                      >
                        {copied ? "copied" : "copy"}
                      </button>
                      <span>review before running; nothing runs from here</span>
                    </span>
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
                          ? "Reading the sample records and ENA runs…"
                          : "zip with samplesheet, contrasts and a README of what to check"}
                    </span>
                  </span>
                )}
              </motion.div>
            </td>
          </tr>
        )}
      </AnimatePresence>
    </tbody>
  );
}
