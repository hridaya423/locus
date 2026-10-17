"use client";
import { useEffect, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { readyFiles, repositoryName, type Facts, type Hit, type ReadyFiles } from "@/lib/api";

const METHOD_ORDER = ["acquisition", "labelling", "enrichment", "instrument_family", "search_engine", "fractionation"];

const size = (bytes: number) => {
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

export function Partners({ hit }: { hit: Hit }) {
  if (!hit.partners?.length) return null;
  return (
    <Section label={hit.source === "PRIDE" ? "Gene data on the same tissue" : "Protein data on the same tissue"}>
      <ul className="grid gap-1 text-[13px]">
        {hit.partners.map((p) => (
          <li key={p.accession} className="flex min-w-0 items-baseline gap-2">
            <a href={p.url} target="_blank" rel="noreferrer" className="group/link flex shrink-0 items-center gap-1 font-mono text-[12px] font-medium underline decoration-rule underline-offset-4 hover:decoration-foreground">
              {p.accession}
              <ArrowUpRight aria-hidden className="size-3 text-muted-foreground group-hover/link:text-foreground" />
            </a>
            <span className="min-w-0 truncate text-muted-foreground" title={p.title}>
              {[repositoryName(p.source), p.assay, p.tissue].filter(Boolean).join(" · ")}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}
