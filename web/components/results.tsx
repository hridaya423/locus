"use client";
import { useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import NumberFlow from "@number-flow/react";
import { ArrowDown, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { motionTier } from "@/lib/springs";
import { useRouter } from "next/navigation";
import { datasetPath, genePath, repositoryName, type Hit, type Result } from "@/lib/api";
import { LINK as LINK_CLASS } from "@/components/page-kit";
import { CompareDialog, Connector } from "@/components/compare";
import { Checkbox, CountCell, DatasetRow, ROW, SEP, Stem, assayOf, materialOf, rememberScroll, unfold } from "@/components/result-card";
import Link from "next/link";

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

function Cols({ counts, nested = false }: { counts: boolean; nested?: boolean }) {
  return (
    <colgroup>
      <col className={nested ? "w-14" : "w-10 sm:w-11"} />
      <col />
      {counts && <col className="w-14 sm:w-20" />}
      {counts && <col className="w-16 sm:w-20" />}
      <col className="w-0 sm:w-20" />
      <col className="w-7" />
    </colgroup>
  );
}

type GroupProps = { hits: Hit[]; counts: boolean; matched: string[]; topic: string; selected: Set<string>; toggle: (a: string) => void; select: (ids: string[], on: boolean) => void };

// Datasets from one paper collapse into a single row; opening it slides the datasets out beneath.
function StudyRow({ hits, counts, matched, topic, selected, toggle, select }: GroupProps) {
  const [open, setOpen] = useState(false);
  const paper = hits.find((h) => h.paper)?.paper;
  const repositories = [...new Set(hits.map((h) => repositoryName(h.source)))];
  const assays = [...new Set(hits.map(assayOf).filter(Boolean))];
  const best = hits.filter(counted).sort((a, b) => b.facts!.case! + (b.facts!.control ?? 0) - a.facts!.case! - (a.facts!.control ?? 0))[0];
  const samples = hits.reduce((n, h) => n + (h.samples ?? 0), 0);
  const picked = hits.filter((h) => selected.has(h.accession)).length;
  const href = `${datasetPath((best ?? hits[0]).accession)}#samples`;
  return (
    <>
      <tbody data-accession={hits.map((h) => h.accession).join(" ")} className={cn(ROW, (open || picked > 0) && "bg-card hover:bg-card", open && "border-b-0")}>
        <tr>
          <td className="relative py-3 pl-3 align-top">
            {open && <Stem active={picked > 0} />}
            <Checkbox
              checked={picked === hits.length}
              mixed={picked > 0 && picked < hits.length}
              onChange={() => select(hits.map((h) => h.accession), picked < hits.length)}
              label={`Select all ${hits.length} datasets of this study`}
            />
          </td>
          <td className="min-w-0 py-3 pr-2 align-top">
            <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="grid w-full min-w-0 cursor-pointer gap-1 text-left">
              <span className="text-sm leading-snug text-foreground">{paper?.title ?? hits[0].title}</span>
              <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="shrink-0 rounded-[3px] bg-foreground px-1.5 py-px font-mono text-[11px] font-medium text-background tabular">{hits.length} datasets</span>
                <span className="label line-clamp-2 min-w-0 basis-full text-muted-foreground sm:line-clamp-1 sm:basis-0 sm:grow">{repositories.join(" + ")}{SEP}{assays.join(" + ")}</span>
              </span>
              {paper && (
                <span className="text-[12.5px] text-muted-foreground">
                  <span className="italic">{paper.journal}</span> {paper.year}
                </span>
              )}
            </button>
          </td>
          {counts && <CountCell value={best?.facts?.case} tone="signal" href={href} />}
          {counts && <CountCell value={best?.facts?.control} tone="control" pooled={best?.facts?.mixed} href={href} />}
          <td className="overflow-hidden py-3 pl-2 text-right align-top font-mono text-[13px] tabular text-muted-foreground max-sm:invisible max-sm:p-0">{samples || "–"}</td>
          <td className="py-3 pl-1 align-top">
            <ChevronDown aria-hidden className={cn("mt-[2px] size-4 text-muted-foreground transition-transform duration-200", open && "rotate-180")} />
          </td>
        </tr>
      </tbody>
      <AnimatePresence initial={false}>
        {open && (
          <tbody className="border-b border-rule bg-card last:border-b-0">
            <tr>
              <td colSpan={counts ? 6 : 4} className="p-0">
                <motion.div {...unfold} className="overflow-hidden">
                  <table className="mb-1 w-full table-fixed border-collapse">
                    <Cols counts={counts} nested />
                    {hits.map((hit, i) => (
                      <DatasetRow
                        key={hit.accession}
                        hit={hit}
                        matched={matched}
                        topic={topic}
                        selected={selected.has(hit.accession)}
                        onSelect={toggle}
                        branch={{ index: i, last: i === hits.length - 1, below: hits.slice(i + 1).some((h) => selected.has(h.accession)) }}
                        counts={counts}
                      />
                    ))}
                  </table>
                </motion.div>
              </td>
            </tr>
          </tbody>
        )}
      </AnimatePresence>
    </>
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

const KIND: Record<string, string> = { matched: "Best matched assays", cohort: "Largest counted comparison", ready: "Ready to analyse" };

function StartWith({ answer }: { answer: NonNullable<Result["answer"]> }) {
  return (
    <section aria-labelledby="start-with" className="grid gap-3 border-y border-foreground py-4">
      <h2 id="start-with" className="label text-muted-foreground">Start with</h2>
      <ol className="grid gap-3">
        {answer.map((a) => (
          <li key={a.accession} className="grid gap-0.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-x-4">
            <span className="label pt-0.5 text-muted-foreground">{KIND[a.kind]}</span>
            <div className="grid min-w-0 gap-0.5">
              <Link href={`${datasetPath(a.accession)}#${a.anchor}`} onClick={rememberScroll} className="w-fit text-[15px] leading-snug underline decoration-rule underline-offset-4 transition-colors duration-150 hover:decoration-foreground">{a.title}</Link>
              <p className="text-[13px] text-muted-foreground"><span className="font-mono text-[12px] text-foreground/80">{a.accession}</span> · {a.fact}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Table({ hits, matched, topic, sort, setSort, selected, toggle, select }: { hits: Hit[]; matched: string[]; topic: string; sort: SortKey; setSort: (k: SortKey) => void; selected: Set<string>; toggle: (a: string) => void; select: (ids: string[], on: boolean) => void }) {
  const rows = useMemo(() => sortHits(hits, sort), [hits, sort]);
  // Case and control columns only appear when some dataset in the table was counted.
  const counts = hits.some(counted);
  return (
    <table className="w-full table-fixed border-collapse">
      <Cols counts={counts} />
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
      {rows.map((group) =>
        group.length > 1 ? (
          <StudyRow key={studyOf(group[0])} hits={group} counts={counts} matched={matched} topic={topic} selected={selected} toggle={toggle} select={select} />
        ) : (
          <DatasetRow key={group[0].accession} hit={group[0]} matched={matched} topic={topic} selected={selected.has(group[0].accession)} onSelect={toggle} counts={counts} />
        ),
      )}
    </table>
  );
}

export function Results({ result }: { result: Result }) {
  const [sort, setSort] = useState<SortKey>("control");
  const router = useRouter();
  const [gene, setGene] = useState("");
  const [showPartial, setShowPartial] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);
  const [comparing, setComparing] = useState(false);
  const section = useRef<HTMLElement>(null);

  const visible = result.datasets;
  const geo = result.datasets.filter((d) => d.source === "GEO" && d.fit === "strong").map((d) => d.accession);
  const strong = visible.filter((d) => d.fit === "strong");
  const partial = visible.filter((d) => d.fit === "partial");
  const picked = result.datasets.filter((d) => selected.has(d.accession));
  // Datasets from one paper are parts of one study, so there is nothing to decide about combining them.
  const pair = picked.length === 2 && studyOf(picked[0]) !== studyOf(picked[1]) ? picked : null;
  const strongCount = result.datasets.filter((d) => d.fit === "strong").length;

  const flip = <T,>(set: Set<T>, v: T) => {
    const next = new Set(set);
    if (next.has(v)) next.delete(v);
    else next.add(v);
    return next;
  };
  const toggle = (a: string) => setSelected((s) => flip(s, a));
  const select = (ids: string[], on: boolean) =>
    setSelected((s) => {
      const next = new Set(s);
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
      return next;
    });

  if (result.datasets.length === 0) {
    return <p className="text-sm text-muted-foreground">No dataset matched the question. Try a broader disease name or fewer requirements.</p>;
  }

  return (
    <motion.section ref={section} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={motionTier.entrance} className="relative grid grid-cols-1 gap-5 pb-16">
      <h2 className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        {strongCount > 0 ? (
          <Tally value={strongCount} label="usable as is" className="text-signal" />
        ) : (
          <span className="text-sm font-medium">No dataset meets every requirement</span>
        )}
        {strongCount !== result.datasets.length && <Tally value={result.datasets.length} label="relevant" />}
      </h2>

      {!!result.answer?.length && <StartWith answer={result.answer} />}

      {geo.length > 0 && (
        <form onSubmit={(e) => { e.preventDefault(); if (gene.trim()) router.push(genePath(gene.trim(), geo, result.plan.terms.join(", "))); }} className="flex flex-wrap items-center gap-2 text-[13px]">
          <label htmlFor="gene-across" className="text-muted-foreground">Your gene across the {geo.length} usable GEO datasets</label>
          <input id="gene-across" value={gene} onChange={(e) => setGene(e.target.value)} placeholder="e.g. SPP1" autoComplete="off" spellCheck={false}
            className="h-8 w-32 rounded-md border border-rule bg-card px-2 font-mono text-[16px] uppercase outline-none transition-colors duration-150 placeholder:normal-case placeholder:text-muted-foreground focus:border-foreground sm:text-[13px]" />
          <button type="submit" className={cn("font-medium", LINK_CLASS)}>Show</button>
        </form>
      )}

      {strong.length > 0 && <Table hits={strong} matched={result.plan.matched_assays ?? []} topic={result.plan.terms.join(", ")} sort={sort} setSort={setSort} selected={selected} toggle={toggle} select={select} />}

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
          {showPartial && <Table hits={partial} matched={result.plan.matched_assays ?? []} topic={result.plan.terms.join(", ")} sort={sort} setSort={setSort} selected={selected} toggle={toggle} select={select} />}
        </div>
      )}

      <Connector section={section} accessions={pair ? pair.map((h) => h.accession) : null} onCompare={() => setComparing(true)} />
      {comparing && pair && <CompareDialog a={pair[0]} b={pair[1]} topic={result.plan.terms.join(", ")} onClose={() => setComparing(false)} />}

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
            {pair && (
              <button type="button" onClick={() => setComparing(true)} className="font-medium underline decoration-background/30 underline-offset-4 hover:decoration-background">
                Compare
              </button>
            )}
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
