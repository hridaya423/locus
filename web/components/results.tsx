"use client";
import { Fragment, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import NumberFlow from "@number-flow/react";
import { ArrowDown, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { motionTier } from "@/lib/springs";
import { repositoryName, type Hit, type Result } from "@/lib/api";
import { DatasetRow, assayOf, materialOf } from "@/components/result-card";

type SortKey = "control" | "case" | "samples" | "year";

const SORT_VALUE: Record<SortKey, (h: Hit) => number | null> = {
  control: (h) => h.facts?.control ?? null,
  case: (h) => h.facts?.case ?? null,
  samples: (h) => h.samples,
  year: (h) => (h.published ? Number(h.published.slice(0, 4)) : null),
};

// The resolved paper is canonical: GEO links papers by PubMed ID, PRIDE and CELLxGENE by DOI.
const studyOf = (h: Hit) => h.paper?.url ?? h.papers[0] ?? h.accession;
const counted = (h: Hit) => h.facts?.case != null;

function sortHits(hits: Hit[], key: SortKey) {
  const value = SORT_VALUE[key];
  const sorted = [...hits].sort((a, b) => {
    const [x, y] = [value(a), value(b)];
    if (x !== y) return x === null ? 1 : y === null ? -1 : y - x;
    return (b.facts?.case ?? -1) - (a.facts?.case ?? -1);
  });
  // Keep datasets from the same paper together, at the rank of the group's best dataset.
  const groups = new Map<string, Hit[]>();
  for (const h of sorted) groups.set(studyOf(h), [...(groups.get(studyOf(h)) ?? []), h]);
  return [...groups.values()];
}

function StudyHeader({ hits, columns }: { hits: Hit[]; columns: number }) {
  const paper = hits.find((h) => h.paper)?.paper;
  const types = [...new Set(hits.map((h) => `${assayOf(h)} (${repositoryName(h.source)})`))];
  return (
    <tbody>
      <tr>
        <td colSpan={columns} className="pt-4 pb-1">
          <div className="grid gap-0.5">
            <span className="label text-foreground">
              One study · {hits.length} datasets · {types.join(" + ")}
            </span>
            {paper && (
              <a href={paper.url} target="_blank" rel="noreferrer" className="text-[13px] text-muted-foreground hover:text-foreground">
                <span className="italic">{paper.journal}</span> {paper.year} · {paper.title}
              </a>
            )}
          </div>
        </td>
      </tr>
    </tbody>
  );
}

function csv(hits: Hit[]) {
  const cols = ["accession", "url", "repository", "year", "assay", "material", "case", "control", "pooled", "samples", "counted", "fit", "paper"];
  const cell = (v: unknown) => `"${String(v ?? "").replaceAll('"', '""')}"`;
  const rows = hits.map((h) => [
    h.accession, h.url, h.source, h.published?.slice(0, 4), assayOf(h), materialOf(h),
    h.facts?.case, h.facts?.control, h.facts?.mixed, h.samples, counted(h) ? "yes" : "no", h.fit, h.paper?.url ?? h.papers.join(" "),
  ].map(cell).join(","));
  return [cols.join(","), ...rows].join("\n");
}

function download(name: string, text: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function Tally({ value, label, className }: { value: number; label: string; className?: string }) {
  return (
    <span className={cn("flex items-baseline gap-2", className)}>
      <NumberFlow value={value} className="font-mono text-xl font-medium tabular" />
      <span className="label text-muted-foreground">{label}</span>
    </span>
  );
}

function Toggle({ on, onClick, strike, children }: { on: boolean; onClick: () => void; strike?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "rounded-[4px] border px-2 py-[3px] text-xs transition-colors duration-150",
        on ? "border-foreground/70 bg-card text-foreground" : cn("border-rule text-muted-foreground hover:text-foreground", strike && "line-through decoration-muted-foreground/50"),
      )}
    >
      {children}
    </button>
  );
}

function SortHeader({ label, k, sort, setSort, className }: { label: string; k: SortKey; sort: SortKey; setSort: (k: SortKey) => void; className?: string }) {
  return (
    <th className={cn("py-2 pl-2 text-right font-normal", className)} aria-sort={sort === k ? "descending" : "none"}>
      <button type="button" onClick={() => setSort(k)} className={cn("label inline-flex items-center gap-1 transition-colors duration-150 hover:text-foreground", sort === k ? "text-foreground" : "text-muted-foreground")}>
        {label}
        <ArrowDown aria-hidden className={cn("size-3", sort !== k && "opacity-0")} />
      </button>
    </th>
  );
}

function Table({ hits, matched, topic, sort, setSort, selected, toggle }: { hits: Hit[]; matched: string[]; topic: string; sort: SortKey; setSort: (k: SortKey) => void; selected: Set<string>; toggle: (a: string) => void }) {
  const rows = useMemo(() => sortHits(hits, sort), [hits, sort]);
  // Case and control columns only appear when some dataset in the table was counted.
  const counts = hits.some(counted);
  return (
    <table className="w-full table-fixed border-collapse">
      <colgroup>
        <col className="w-10 sm:w-11" />
        <col />
        {counts && <col className="w-14 sm:w-20" />}
        {counts && <col className="w-16 sm:w-20" />}
        <col className="w-0 sm:w-20" />
        <col className="w-7" />
      </colgroup>
      <thead className="border-b border-foreground">
        <tr>
          <th />
          <th className="py-2 text-left font-normal">
            <button type="button" onClick={() => setSort("year")} className={cn("label inline-flex items-center gap-1 hover:text-foreground", sort === "year" ? "text-foreground" : "text-muted-foreground")}>
              Dataset{sort === "year" && " · newest"}
              <ArrowDown aria-hidden className={cn("size-3", sort !== "year" && "opacity-0")} />
            </button>
          </th>
          {counts && <SortHeader label="Case" k="case" sort={sort} setSort={setSort} />}
          {counts && <SortHeader label="Control" k="control" sort={sort} setSort={setSort} />}
          <SortHeader label="Samples" k="samples" sort={sort} setSort={setSort} className="overflow-hidden max-sm:invisible max-sm:p-0" />
          <th />
        </tr>
      </thead>
      {rows.map((group) => (
        <Fragment key={studyOf(group[0])}>
          {group.length > 1 && <StudyHeader hits={group} columns={counts ? 6 : 4} />}
          {group.map((hit) => (
            <DatasetRow key={hit.accession} hit={hit} matched={matched} topic={topic} selected={selected.has(hit.accession)} onSelect={toggle} sameStudy={group.length > 1} counts={counts} />
          ))}
        </Fragment>
      ))}
    </table>
  );
}

export function Results({ result }: { result: Result }) {
  const [sort, setSort] = useState<SortKey>("control");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [countedOnly, setCountedOnly] = useState(false);
  const [showPartial, setShowPartial] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);

  const sources = [...new Set(result.datasets.map((d) => d.source))];
  const visible = result.datasets.filter((d) => !hidden.has(d.source) && (!countedOnly || counted(d)));
  const strong = visible.filter((d) => d.fit === "strong");
  const partial = visible.filter((d) => d.fit === "partial");
  const picked = result.datasets.filter((d) => selected.has(d.accession));
  const strongCount = result.datasets.filter((d) => d.fit === "strong").length;

  const flip = <T,>(set: Set<T>, v: T) => {
    const next = new Set(set);
    if (next.has(v)) next.delete(v);
    else next.add(v);
    return next;
  };
  const toggle = (a: string) => setSelected((s) => flip(s, a));

  if (result.datasets.length === 0) {
    return <p className="text-sm text-muted-foreground">No dataset matched the question. Try a broader disease name or fewer requirements.</p>;
  }

  return (
    <motion.section initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={motionTier.entrance} className="grid grid-cols-1 gap-5 pb-16">
      <h2 className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        {strongCount > 0 ? (
          <Tally value={strongCount} label="usable as is" className="text-signal" />
        ) : (
          <span className="text-sm font-medium">No dataset meets every requirement</span>
        )}
        {strongCount !== result.datasets.length && <Tally value={result.datasets.length} label="relevant" />}
      </h2>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="basis-full text-xs text-muted-foreground sm:basis-24">Show</span>
        {sources.map((s) => (
          <Toggle key={s} strike on={!hidden.has(s)} onClick={() => setHidden((h) => flip(h, s))}>
            {repositoryName(s)} {result.datasets.filter((d) => d.source === s).length}
          </Toggle>
        ))}
        {result.datasets.some(counted) && (
          <Toggle on={countedOnly} onClick={() => setCountedOnly((v) => !v)}>
            counted only
          </Toggle>
        )}
      </div>

      {strong.length > 0 && <Table hits={strong} matched={result.plan.matched_assays ?? []} topic={result.plan.terms.join(", ")} sort={sort} setSort={setSort} selected={selected} toggle={toggle} />}

      {partial.length > 0 && (
        <div className="grid grid-cols-1 gap-2">
          <button
            type="button"
            onClick={() => setShowPartial((v) => !v)}
            aria-expanded={showPartial}
            className="flex items-center gap-1.5 justify-self-start py-1 text-sm text-muted-foreground underline decoration-rule underline-offset-4 transition-colors duration-150 hover:text-foreground hover:decoration-foreground"
          >
            <ChevronDown className={cn("size-4 transition-transform duration-200", showPartial && "rotate-180")} />
            {showPartial ? "Hide" : "Show"} {partial.length} {partial.length === 1 ? "close match that misses" : "close matches that miss"} a requirement
          </button>
          {showPartial && <Table hits={partial} matched={result.plan.matched_assays ?? []} topic={result.plan.terms.join(", ")} sort={sort} setSort={setSort} selected={selected} toggle={toggle} />}
        </div>
      )}

      <AnimatePresence>
        {picked.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12, transition: motionTier.ui.exit }}
            transition={motionTier.ui}
            className="fixed inset-x-4 bottom-4 z-10 mx-auto flex w-fit max-w-[calc(100%-2rem)] flex-wrap items-center gap-x-4 gap-y-1 rounded-lg bg-foreground px-4 py-2.5 text-sm text-background shadow-[0_12px_32px_-12px_rgb(17_17_16/0.5)]"
          >
            <span className="font-mono tabular">{picked.length} selected</span>
            <button
              type="button"
              onClick={() => navigator.clipboard.writeText(picked.map((h) => h.download_plan).join("\n\n")).then(() => setCopied(true))}
              onBlur={() => setCopied(false)}
              className="underline decoration-background/30 underline-offset-4 hover:decoration-background"
            >
              {copied ? "Copied" : "Copy download commands"}
            </button>
            <button type="button" onClick={() => download("locus-datasets.csv", csv(picked))} className="underline decoration-background/30 underline-offset-4 hover:decoration-background">
              Export CSV
            </button>
            <button type="button" onClick={() => setSelected(new Set())} className="text-background/60 hover:text-background">
              Clear
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}
