"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { LINK } from "@/components/page-kit";
import { firstTerm, quoteOnPage, slug, useMatches } from "@/components/matches";
import { datasetPath, readyFiles, type Facts, type Hit, type ReadyFiles } from "@/lib/api";

const METHOD_ORDER = ["acquisition", "labelling", "enrichment", "instrument_family", "search_engine", "fractionation"];

export const size = (bytes: number) => {
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log10(Math.max(bytes, 1)) / 3));
  return `${(bytes / 1000 ** i).toFixed(i > 1 && bytes / 1000 ** i < 10 ? 1 : 0)} ${units[i]}`;
};

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <span className="label text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

// A tag the records state is a plain chip; one a model only inferred is muted and marked, and never decides a grade.
export function Methods({ methods }: { methods: NonNullable<Facts["methods"]> }) {
  const shown = METHOD_ORDER.filter((f) => methods[f] && methods[f].value !== "none" || f === "enrichment" && methods[f]?.trusted);
  if (!shown.length) return null;
  return (
    <Section label="How it was run">
      <span className="flex flex-wrap gap-1.5">
        {shown.map((f) => {
          const m = methods[f];
          return (
            <span
              key={f}
              title={m.trusted ? m.evidence || undefined : "Probably; not stated in the records"}
              className={cn("rounded-[4px] border px-1.5 py-0.5 text-xs", m.trusted ? "border-foreground/40 text-foreground" : "border-dashed border-rule text-muted-foreground")}
            >
              {m.label}{!m.trusted && "?"}
            </span>
          );
        })}
      </span>
    </Section>
  );
}

export function Ready({ accession }: { accession: string }) {
  const [files, setFiles] = useState<ReadyFiles | null | "failed">(null);
  useEffect(() => {
    const ctrl = new AbortController();
    readyFiles(accession, ctrl.signal).then(setFiles, () => !ctrl.signal.aborted && setFiles("failed"));
    return () => ctrl.abort();
  }, [accession]);

  if (files === "failed") return null;
  if (!files) return <Section label="Ready-made results"><span className="text-xs text-muted-foreground">Checking the files in PRIDE…</span></Section>;
  const raw = files.raw.files ? `${files.raw.files} raw files, ${size(files.raw.bytes)}` : "";
  if (!files.processed.length) {
    return <Section label="Ready-made results"><span className="text-[13px] text-muted-foreground">None uploaded; the raw files need processing{raw && ` (${raw})`}.</span></Section>;
  }
  return (
    <Section label="Ready-made results">
      <ul className="grid gap-1 text-[13px]">
        {files.processed.map((f) => (
          <li key={f.url} className="flex min-w-0 items-baseline gap-2">
            <span className="label w-28 shrink-0 whitespace-nowrap text-muted-foreground">{f.kind}</span>
            <a href={f.url} className="min-w-0 truncate underline decoration-rule underline-offset-4 hover:decoration-foreground">{f.name}</a>
            <span className="shrink-0 font-mono text-[12px] tabular text-muted-foreground">{size(f.bytes)}</span>
          </li>
        ))}
      </ul>
      <span className="text-xs text-muted-foreground">{[files.more ? `${files.more} more processed files` : "", raw && `and ${raw}`].filter(Boolean).join(" ")}</span>
    </Section>
  );
}

// Opened from its own toggle in the row header, which already names it, so the list needs no heading.
// Each passed check and the quote lead to the words in the dataset's own text they stand on.
export function Evidence({ hit, onOpen }: { hit: Hit; onOpen: () => void }) {
  const m = useMatches(hit.accession);
  const page = datasetPath(hit.accession);
  const link = (target: string | null, label: React.ReactNode, title: string) =>
    target ? <Link href={`${page}#match-${slug(target)}`} onClick={onOpen} title={title} className={LINK}>{label}</Link> : label;
  const onPage = !!m?.why && quoteOnPage(m);
  return (
    <>
      {m && m.groups.length > 0 && (
        <Section label="Why it matched">
          <span className="flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
            {m.groups.map((g) => {
              const term = firstTerm(m, g);
              return (
                <span key={g.check} className={term ? undefined : "text-muted-foreground"} title={term || !m.why ? undefined : "No matching words in this record's text"}>
                  {link(term, g.label, `Show “${term}” in the record`)}
                </span>
              );
            })}
          </span>
        </Section>
      )}
      {hit.evidence && (
        <p className="border-l-2 border-foreground pl-3 font-mono text-[12.5px] leading-relaxed">
          &quot;{link(onPage ? "quote" : null, hit.evidence, "Show the quote in the record")}&quot;
          {m?.why && !onPage && <span className="label block pt-1.5 text-muted-foreground">from the repository&apos;s search index, not this record&apos;s text</span>}
          {hit.facts?.case != null && (
            // Only the sample count is shown; the full provenance (e.g. which curators grouped the samples) stays on hover.
            <span className="label block pt-1.5 text-muted-foreground" title={hit.facts.source}>
              counts from {hit.facts.source.split(",")[0]}
            </span>
          )}
        </p>
      )}
    </>
  );
}
