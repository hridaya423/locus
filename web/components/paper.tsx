"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { Wordmark } from "@/components/logo";
import { Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { size } from "@/components/row-details";
import { dataType } from "@/components/result-card";
import { paperRecord, repositoryName, type PaperRecord } from "@/lib/api";

const AUTHORS_SHOWN = 8;
const DATASETS_SHOWN = 10;

export function PaperPage({ id }: { id: string }) {
  const [rec, setRec] = useState<PaperRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    paperRecord(id, ctrl.signal).then(
      (r) => {
        setRec(r);
        setError(null);
      },
      (e) => !ctrl.signal.aborted && setError(e instanceof Error ? e.message : String(e)),
    );
    return () => ctrl.abort();
  }, [id, attempt]);

  useEffect(() => {
    document.title = rec ? `${rec.title} · locus` : `${id} · locus`;
  }, [id, rec]);

  const source = rec?.sources.doi ?? rec?.sources.europe_pmc;
  return (
    <div className="mx-auto grid w-full max-w-6xl grid-cols-1 content-start gap-10">
      <nav className="flex items-center justify-between gap-4">
        <Link href="/" aria-label="locus home" className="leading-none">
          <Wordmark className="text-[30px]" />
        </Link>
        {source && (
          <a href={source} target="_blank" rel="noreferrer" className={cn("flex shrink-0 items-center gap-1 text-[13px]", MUTED_LINK)}>
            {rec?.sources.doi ? "Paper at the publisher" : "Paper at Europe PMC"}
            <ArrowUpRight aria-hidden className="size-3.5" />
          </a>
        )}
      </nav>

      {error === "missing" ? (
        <p className="text-sm">Europe PMC has no paper {id}. <Link href={`/?q=${encodeURIComponent(id)}`} className={LINK}>Search instead</Link>.</p>
      ) : error ? (
        <p className="flex flex-wrap items-baseline gap-x-3 text-sm">
          Europe PMC did not send the paper.
          <button type="button" onClick={() => setAttempt((n) => n + 1)} className={LINK}>Try again</button>
        </p>
      ) : !rec ? (
        <p className="text-[13px] text-muted-foreground">Reading the paper from Europe PMC…</p>
      ) : (
        <>
          <Header rec={rec} />
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-16">
            <Datasets rec={rec} />
            <Availability rec={rec} />
            <Abstract rec={rec} />
            <Supplementary rec={rec} />
          </div>
        </>
      )}
    </div>
  );
}

function Authors({ names }: { names: string[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? names : names.slice(0, AUTHORS_SHOWN);
  return (
    <p className="max-w-4xl text-[15px] leading-relaxed text-pretty">
      {shown.join(", ")}
      {names.length > AUTHORS_SHOWN && (
        <>
          {" "}
          <button type="button" onClick={() => setAll((v) => !v)} className={cn("text-[13px]", MUTED_LINK)}>
            {all ? "fewer" : `+${names.length - AUTHORS_SHOWN} more`}
          </button>
        </>
      )}
    </p>
  );
}

function Header({ rec }: { rec: PaperRecord }) {
  return (
    <header className="grid gap-4">
      <p className="flex flex-wrap items-baseline gap-x-3 font-mono text-[12.5px] text-muted-foreground">
        {rec.pmid && <span className="font-medium text-foreground">PMID {rec.pmid}</span>}
        {rec.pmcid && <span>{rec.pmcid}</span>}
        {rec.journal && <span className="font-sans italic">{rec.journal}</span>}
        {rec.year && <span className="tabular">{rec.year}</span>}
      </p>
      <h1 className="max-w-4xl text-balance break-words font-display text-[34px] leading-[1.08] sm:text-[44px]">{rec.title}</h1>
      {rec.authors.length > 0 && <Authors names={rec.authors} />}
    </header>
  );
}

function Datasets({ rec }: { rec: PaperRecord }) {
  const [all, setAll] = useState(false);
  const shown = all ? rec.datasets : rec.datasets.slice(0, DATASETS_SHOWN);
  return (
    <section className="grid content-start gap-6">
      <Heading id="datasets" count={rec.datasets.length || undefined}>Datasets in locus</Heading>
      {rec.datasets.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">No dataset in locus cites this paper.</p>
      ) : (
        <ul className="grid border-t border-rule">
          {shown.map((d) => (
            <li key={d.accession} className="border-b border-rule">
              <Link href={d.path} className="group/row grid gap-x-6 gap-y-1 py-3.5 sm:grid-cols-[11rem_minmax(0,1fr)_auto]">
                <span className="grid content-start gap-0.5">
                  <span className="font-mono text-[13px] font-medium underline decoration-transparent underline-offset-4 transition-colors duration-150 group-hover/row:decoration-foreground">{d.accession}</span>
                  <span className="text-[12.5px] text-muted-foreground">{repositoryName(d.source)}</span>
                </span>
                <span className="min-w-0 break-words text-[14.5px] leading-snug">{d.title}</span>
                <span className="text-[12.5px] text-muted-foreground sm:text-right">
                  {dataType(d.modality) || "data type not stated"}
                  <span className="tabular"> · {d.samples ? `${d.samples.toLocaleString()} ${d.samples === 1 ? "sample" : "samples"}` : "samples not stated"}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {rec.datasets.length > DATASETS_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[13px]", MUTED_LINK)}>
          {all ? "fewer" : `+${rec.datasets.length - DATASETS_SHOWN} more`}
        </button>
      )}
    </section>
  );
}

function Availability({ rec }: { rec: PaperRecord }) {
  const a = rec.data_availability;
  return (
    <section className="grid content-start gap-6">
      <Heading id="availability">Data availability</Heading>
      {a.status === "stated" ? (
        <figure className="grid max-w-[68ch] gap-3">
          <blockquote className="grid gap-2 [overflow-wrap:anywhere] border-l-2 border-foreground pl-4 text-[15px] leading-relaxed">
            {a.text?.split("\n").map((line, i) => <p key={i}>{line}</p>)}
          </blockquote>
          <figcaption className="text-[12.5px] text-muted-foreground">{/availab/i.test(a.section ?? "") ? "Quoted" : `${a.section}, quoted`} from the open-access full text at Europe PMC</figcaption>
        </figure>
      ) : (
        <p className="text-[13px] text-muted-foreground">{a.note && a.note[0].toUpperCase() + a.note.slice(1)}.</p>
      )}
    </section>
  );
}

function Abstract({ rec }: { rec: PaperRecord }) {
  return (
    <section className="grid content-start gap-6">
      <Heading id="abstract">Abstract</Heading>
      {rec.abstract.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">Europe PMC has no abstract for this paper.</p>
      ) : (
        <div className="grid max-w-[68ch] gap-3 text-[15px] leading-relaxed text-pretty">
          {rec.abstract.map(([label, text], i) => (
            <p key={i}>
              {label && <span className="font-medium">{label}. </span>}
              {text}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

function Supplementary({ rec }: { rec: PaperRecord }) {
  const s = rec.supplementary;
  return (
    <section className="grid content-start gap-6">
      <Heading id="supplementary" count={s?.files.length || undefined}>Supplementary files</Heading>
      {!s ? (
        <p className="text-[13px] text-muted-foreground">Europe PMC lists none: the full text is not open access.</p>
      ) : s.files.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">The open-access full text lists no supplementary files.</p>
      ) : (
        <>
          <ul className="grid border-t border-rule">
            {s.files.map((f) => (
              <li key={f.url} className="grid gap-x-6 gap-y-0.5 border-b border-rule py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-baseline">
                <span className="grid min-w-0 gap-0.5">
                  <a href={f.url} target="_blank" rel="noreferrer" className={cn("w-fit max-w-full break-all font-mono text-[13px]", LINK)}>{f.name}</a>
                  {f.caption && <span className="break-words text-[12.5px] text-muted-foreground">{f.caption}</span>}
                </span>
                <span className="whitespace-nowrap font-mono text-[12.5px] tabular text-muted-foreground sm:text-right">{f.bytes ? size(f.bytes) : "size not stated"}</span>
              </li>
            ))}
          </ul>
          <a href={s.zip} className={cn("w-fit text-[13px]", LINK)}>All files as one zip, from Europe PMC</a>
        </>
      )}
    </section>
  );
}
