"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { Wordmark } from "@/components/logo";
import { Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { dataType } from "@/components/result-card";
import { datasetPath, person, repositoryName, type Person, type PersonPaper } from "@/lib/api";

const PAPERS_SHOWN = 15;
const JOURNALS_SHOWN = 8;
const COMMON_NAME = 300;

export function PersonPage({ name }: { name: string }) {
  const [rec, setRec] = useState<Person | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    person(name, ctrl.signal).then(
      (r) => {
        setRec(r);
        setError(null);
      },
      (e) => !ctrl.signal.aborted && setError(e instanceof Error ? e.message : String(e)),
    );
    return () => ctrl.abort();
  }, [name, attempt]);

  useEffect(() => {
    document.title = `${name} · locus`;
  }, [name]);

  return (
    <div className="mx-auto grid w-full max-w-6xl grid-cols-1 content-start gap-10">
      <nav className="flex items-center justify-between gap-4">
        <Link href="/" aria-label="locus home" className="leading-none">
          <Wordmark className="text-[30px]" />
        </Link>
        {rec?.search && (
          <a href={rec.search} target="_blank" rel="noreferrer" className={cn("flex shrink-0 items-center gap-1 text-[13px]", MUTED_LINK)}>
            Author search at Europe PMC
            <ArrowUpRight aria-hidden className="size-3.5" />
          </a>
        )}
      </nav>
      <header className="grid gap-3">
        <p className="label text-muted-foreground">Contributor</p>
        <h1 className="font-display text-[34px] leading-[1.08] sm:text-[44px]">{name}</h1>
        {rec?.available && (
          <p className="max-w-[80ch] text-[13px] text-muted-foreground">
            Europe PMC finds <span className="font-mono tabular text-foreground">{rec.matched!.toLocaleString()}</span> papers by{" "}
            <span className="font-mono">{rec.query}</span>
            {rec.matched! > rec.shown! && `; the newest ${rec.shown} are here`}.
            {rec.matched! > COMMON_NAME && " A name this common belongs to several people, so these papers are not all theirs."}
          </p>
        )}
      </header>
      {error ? (
        <p className="flex flex-wrap items-baseline gap-x-3 text-sm">
          {error === "502" ? "Europe PMC did not answer." : "locus could not read this contributor."}
          <button type="button" onClick={() => setAttempt((n) => n + 1)} className={LINK}>Try again</button>
        </p>
      ) : !rec ? (
        <p className="text-[13px] text-muted-foreground">Reading their papers from Europe PMC…</p>
      ) : !rec.available ? (
        <p className="text-[13px] text-muted-foreground">locus cannot search for this name: {rec.reason}.</p>
      ) : (
        <>
          <Record rec={rec} />
          <Datasets papers={rec.papers!} count={rec.counts!.datasets} />
          <Papers papers={rec.papers!} />
        </>
      )}
    </div>
  );
}

function Record({ rec }: { rec: Person }) {
  const c = rec.counts!;
  const shown = rec.shown!;
  const facts: [string, number][] = [["last author", c.last_author], ["with supplementary files", c.supplementary], ["open access", c.open_access], ["preprints", c.preprints], ["with datasets in locus", c.with_datasets]];
  const journals = Object.entries(rec.journals!);
  return (
    <section className="grid gap-5">
      <dl className="grid grid-cols-2 border-y border-rule sm:grid-cols-5">
        {facts.map(([label, n], i) => (
          <div key={label} className={cn("grid content-start gap-1 py-3 pr-4", i > 0 && "sm:border-l sm:border-rule sm:pl-4", i % 2 === 1 && "max-sm:border-l max-sm:border-rule max-sm:pl-4", i > 1 && "max-sm:border-t max-sm:border-rule")}>
            <dt className="label text-muted-foreground">{label}</dt>
            <dd className="font-mono text-[15px] tabular">{n} <span className="text-[12px] text-muted-foreground">of {shown}</span></dd>
          </div>
        ))}
      </dl>
      {journals.length > 0 && (
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
          <span className="text-muted-foreground">Journals</span>
          {journals.slice(0, JOURNALS_SHOWN).map(([j, n]) => (
            <span key={j}><span className="italic">{j}</span> <span className="font-mono text-[12px] tabular text-muted-foreground">{n}</span></span>
          ))}
          {journals.length > JOURNALS_SHOWN && <span className="text-muted-foreground">+{journals.length - JOURNALS_SHOWN} more</span>}
        </p>
      )}
    </section>
  );
}

function Datasets({ papers, count }: { papers: PersonPaper[]; count: number }) {
  const rows = papers.flatMap((p) => p.datasets.map((d) => ({ ...d, paper: p })));
  const seen = new Set<string>();
  const unique = rows.filter((r) => !seen.has(r.accession) && seen.add(r.accession));
  return (
    <section className="grid content-start gap-5">
      <Heading id="datasets" count={count}>Datasets in locus</Heading>
      {unique.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">No locus dataset cites these papers.</p>
      ) : (
        <ul className="grid border-t border-rule">
          {unique.map((d) => (
            <li key={d.accession} className="border-b border-rule">
              <Link href={datasetPath(d.accession)} className="group/row grid gap-x-6 gap-y-1 py-3.5 sm:grid-cols-[11rem_minmax(0,1fr)_auto]">
                <span className="grid content-start gap-0.5">
                  <span className="font-mono text-[13px] font-medium underline decoration-transparent underline-offset-4 transition-colors duration-150 group-hover/row:decoration-foreground">{d.accession}</span>
                  <span className="text-[12.5px] text-muted-foreground">{repositoryName(d.source)}</span>
                </span>
                <span className="grid min-w-0 gap-0.5">
                  <span className="break-words text-[14.5px] leading-snug">{d.title}</span>
                  <span className="truncate text-[12.5px] text-muted-foreground">from {d.paper.title} ({d.paper.year})</span>
                </span>
                <span className="text-[12.5px] text-muted-foreground sm:text-right">{dataType(d.modality) || "data type not stated"}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Papers({ papers }: { papers: PersonPaper[] }) {
  const [all, setAll] = useState(false);
  return (
    <section className="grid content-start gap-5">
      <Heading id="papers" count={papers.length}>Papers</Heading>
      <ul className="grid border-t border-rule">
        {(all ? papers : papers.slice(0, PAPERS_SHOWN)).map((p) => {
          const href = p.pmid ? `/p/${p.pmid}` : p.doi ? `/p/${p.doi}` : null;
          return (
            <li key={p.key} className="grid gap-x-6 gap-y-1 border-b border-rule py-3 sm:grid-cols-[3.5rem_minmax(0,1fr)_auto]">
              <span className="font-mono text-[12.5px] tabular text-muted-foreground">{p.year}</span>
              <span className="grid min-w-0 gap-0.5">
                {href ? <Link href={href} className={cn("w-fit text-[14.5px] leading-snug", LINK)}>{p.title}</Link> : <span className="text-[14.5px] leading-snug">{p.title}</span>}
                <span className="text-[12.5px] text-muted-foreground">
                  <span className="italic">{p.journal || "journal not stated"}</span>
                  {p.preprint && " · preprint"}
                  {p.last_author && " · last author"}
                  {p.datasets.length > 0 && " · "}
                  {p.datasets.map((d, i) => (
                    <span key={d.accession}>{i > 0 && ", "}<Link href={datasetPath(d.accession)} className={cn("font-mono text-[12px]", MUTED_LINK)}>{d.accession}</Link></span>
                  ))}
                </span>
              </span>
              <span className="flex gap-x-3 font-mono text-[12px] tabular text-muted-foreground sm:justify-end">
                {p.supplementary && <span className="text-foreground">supplementary</span>}
                <span>{p.cited_by.toLocaleString()} cited</span>
              </span>
            </li>
          );
        })}
      </ul>
      {papers.length > PAPERS_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[13px]", MUTED_LINK)}>
          {all ? "Fewer papers" : `All ${papers.length} papers`}
        </button>
      )}
    </section>
  );
}
