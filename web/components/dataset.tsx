"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowUpRight, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Wordmark } from "@/components/logo";
import { DesignBars, useSelection, type Selection } from "@/components/design";
import { size } from "@/components/row-details";
import { Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { SampleTable, SelectionBar } from "@/components/sample-table";
import { CONTROLLED, Files } from "@/components/files";
import { Aside } from "@/components/aside";
import { AssayList, assayNames, useAssays, type AssayState } from "@/components/assay";
import { QualitySection } from "@/components/qc";
import { FirstLookSection } from "@/components/first-look";
import { dataType } from "@/components/result-card";
import { MarkedText, MarkedTitle, MatchedLine, goToMatch, hasMatch, useFound, useMatches, type Matches } from "@/components/matches";
import { datasetRecord, filePreview, repositoryName, type DatasetRecord, type FilePreview, type Hit } from "@/lib/api";

export function DatasetPage({ accession }: { accession: string }) {
  const router = useRouter();
  const [rec, setRec] = useState<DatasetRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const context = useFound(accession);
  const assays = useAssays(accession, rec !== null);

  useEffect(() => {
    const ctrl = new AbortController();
    datasetRecord(accession, ctrl.signal).then(
      (r) => {
        setRec(r);
        setError(null);
      },
      (e) => !ctrl.signal.aborted && setError(e instanceof Error ? e.message : String(e)),
    );
    return () => ctrl.abort();
  }, [accession, attempt]);

  const title = rec?.title ?? context?.hit.title;
  useEffect(() => {
    document.title = title ? `${accession} · ${title} · locus` : `${accession} · locus`;
  }, [accession, title]);

  const source = rec?.source ?? context?.hit.source;
  return (
    <div className="mx-auto grid w-full max-w-6xl grid-cols-1 content-start gap-10">
      <nav className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-5">
          <Link href="/" aria-label="locus home" className="leading-none">
            <Wordmark className="text-[30px]" />
          </Link>
          {context && (
            <button type="button" onClick={() => (history.length > 1 ? router.back() : router.push("/"))} className={cn("flex items-center gap-1.5 text-[13px]", MUTED_LINK)}>
              <ArrowLeft aria-hidden className="size-3.5" />
              Results for {context.topic}
            </button>
          )}
        </div>
        {(rec?.url || context?.hit.url) && source && (
          <a href={rec?.url ?? context?.hit.url} target="_blank" rel="noreferrer" className={cn("group/link flex shrink-0 items-center gap-1 text-[13px]", MUTED_LINK)}>
            {repositoryName(source)} record
            <ArrowUpRight aria-hidden className="size-3.5" />
          </a>
        )}
      </nav>

      {error === "missing" ? (
        <p className="text-sm">locus has no dataset {accession}. <Link href="/" className={LINK}>Search instead</Link>.</p>
      ) : (
        <>
          <Header accession={accession} rec={rec} hit={context?.hit} assays={assays} />
          {error ? (
            <p className="flex flex-wrap items-baseline gap-x-3 text-sm">
              {error === "502" ? `${source ? repositoryName(source) : "The repository"} did not send the record.` : "locus could not read this record; its server failed."}
              <button type="button" onClick={() => setAttempt((n) => n + 1)} className={LINK}>Try again</button>
            </p>
          ) : !rec ? (
            <p className="text-[13px] text-muted-foreground">Reading the record from {source ? repositoryName(source) : "the repository"}…</p>
          ) : (
            <Body rec={rec} />
          )}
        </>
      )}
    </div>
  );
}

function Header({ accession, rec, hit, assays }: { accession: string; rec: DatasetRecord | null; hit?: Hit; assays: AssayState }) {
  const measured = assayNames(assays.data);
  const source = rec?.source ?? hit?.source;
  const published = rec?.published ?? hit?.published;
  const samples = rec?.samples?.rows.length || rec?.sample_count || hit?.samples;
  const organism = rec?.facts.find(([label]) => label === "Organism")?.[1] ?? (rec?.organism || hit?.organism || "").split(";").filter(Boolean);
  const bytes = rec?.files.reduce((n, f) => n + (f.bytes ?? 0), 0) ?? 0;
  const processed = rec?.files.filter((f) => f.processed).length ?? 0;
  const unknown = rec || hit ? "not stated" : "…";
  const figures: [string, React.ReactNode][] = [
    ["Data type", measured.length ? <span title={`Read from the methods: ${measured.join(", ")}`}>{measured.slice(0, 2).join(", ")}{measured.length > 2 && <span className="text-muted-foreground"> +{measured.length - 2}</span>}</span> : dataType(rec?.modality ?? hit?.modality ?? "") || unknown],
    ["Organism", organism.length ? <span title={organism.join(", ")}>{organism[0]}{organism.length > 1 && <span className="text-muted-foreground"> +{organism.length - 1}</span>}</span> : unknown],
    ["Samples", samples ? <span className="tabular">{samples.toLocaleString()}</span> : unknown],
    ["Files", rec ? (rec.files.length ? <span className="tabular">{rec.files.length.toLocaleString()} <span className="text-muted-foreground">· {bytes ? size(bytes) : "size not stated"}</span></span> : CONTROLLED.has(rec.source) ? "controlled access" : "none listed") : "…"],
  ];
  return (
    <header className="grid gap-6">
      <div className="grid gap-3">
        <p className="flex flex-wrap items-baseline gap-x-3 font-mono text-[12.5px]">
          <span className="font-medium">{accession}</span>
          {source && <span className="text-muted-foreground">{repositoryName(source)}</span>}
          {published && <span className="text-muted-foreground tabular">{published.slice(0, 10)}</span>}
        </p>
        <h1 className="max-w-4xl font-display text-[34px] leading-[1.08] sm:text-[44px]">{rec ? <MarkedTitle accession={accession} title={rec.title} /> : (hit?.title ?? accession)}</h1>
      </div>
      <dl className="grid grid-cols-2 border-y border-rule sm:grid-cols-4">
        {figures.map(([label, value], i) => (
          <div key={label} className={cn("grid min-w-0 content-start gap-1 py-3 pr-4", i % 2 === 1 && "pl-4 max-sm:border-l max-sm:border-rule", i > 0 && "sm:border-l sm:border-rule sm:pl-4", i > 1 && "max-sm:border-t max-sm:border-rule")}>
            <dt className="label text-muted-foreground">{label}</dt>
            <dd className="truncate text-[15px] font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      {rec && <AssayList accession={accession} state={assays} />}
      {rec && (
        <nav aria-label="Sections" className="flex flex-wrap gap-x-5 gap-y-1 text-[13px]">
          {[["about", "About"], ["samples", "Samples"], ["files", processed ? `Files · ${processed} ready to use` : "Files"]].map(([id, label]) => (
            <a key={id} href={`#${id}`} className={MUTED_LINK}>{label}</a>
          ))}
        </nav>
      )}
    </header>
  );
}

const DESIGNED = new Set(["GEO", "PRIDE", "iProX", "jPOST", "PanoramaPublic", "ENA", "ArrayExpress", "MetabolomicsWorkbench"]);

function Body({ rec }: { rec: DatasetRecord }) {
  const designed = DESIGNED.has(rec.source) && (rec.source !== "PRIDE" || rec.accession.startsWith("PXD"));
  const selection = useSelection(rec, designed);
  return (
    <div className="grid grid-cols-1 gap-14 lg:grid-cols-[minmax(0,1fr)_17rem] lg:gap-16">
      <div className="grid min-w-0 content-start gap-16">
        <About rec={rec} />
        <Samples rec={rec} designed={designed} selection={selection} />
        <QualitySection accession={rec.accession} />
        {(rec.source === "GEO" || rec.source === "MetabolomicsWorkbench") && <FirstLookSection accession={rec.accession} />}
        <Files rec={rec} selection={selection} />
      </div>
      <Aside rec={rec} />
    </div>
  );
}

const PROTOCOL = /protocol|processing/i;

function Text({ text, index, m }: { text: string; index: number; m: Matches | null }) {
  return (
    <div className="grid max-w-[68ch] gap-3 text-[15px] leading-relaxed text-pretty">
      <MarkedText text={text} index={index} m={m} />
    </div>
  );
}

export function About({ rec }: { rec: DatasetRecord }) {
  const m = useMatches(rec.accession);
  useEffect(() => {
    if (m?.why && location.hash.startsWith("#match-")) goToMatch(location.hash.slice(7));
  }, [m?.why]);
  const texts = rec.texts.map(([label, text], index) => ({ label, text, index }));
  const main = texts.filter(({ label }) => !PROTOCOL.test(label));
  const protocols = texts.filter(({ label }) => PROTOCOL.test(label));
  return (
    <section className="grid content-start gap-6">
      <Heading id="about">About</Heading>
      {m && <MatchedLine m={m} />}
      {main.length === 0 && protocols.length === 0 && <p className="text-[13px] text-muted-foreground">{repositoryName(rec.source)} gives no description.</p>}
      {main.map(({ label, text, index }, i) => (
        <div key={index} className="grid gap-2">
          {i > 0 && <h3 className="text-[13px] font-medium">{label}</h3>}
          <Text text={text} index={index} m={m} />
        </div>
      ))}
      {protocols.length > 0 && (
        <div className="grid border-t border-rule">
          {protocols.map(({ label, text, index }) => (
            <details key={index} open={hasMatch(m, index)} className="group/p border-b border-rule">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-3 text-[14px] [&::-webkit-details-marker]:hidden">
                {label.replace(/^Protocol: /, "")}
                <ChevronDown aria-hidden className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-open/p:rotate-180" />
              </summary>
              <div className="pb-4"><Text text={text} index={index} m={m} /></div>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}

function Samples({ rec, designed, selection }: { rec: DatasetRecord; designed: boolean; selection: Selection }) {
  return (
    <section className="grid content-start gap-8">
      <Heading id="samples" count={rec.samples ? rec.samples.rows.length.toLocaleString() : undefined}>Samples</Heading>
      {rec.samples && <SelectionBar rec={rec} selection={selection} />}
      {designed && <DesignBars rec={rec} selection={selection} />}
      {rec.samples ? (
        <SampleTable dataset={rec.accession} samples={rec.samples} selection={selection} />
      ) : (
        <>
          <p className="text-[13px] text-muted-foreground">{repositoryName(rec.source)} does not list individual samples{rec.files.some((f) => f.kind === "sample design") ? "; the sample design file is under Files" : ""}.</p>
          <TableSamples rec={rec} />
        </>
      )}
    </section>
  );
}

const NAMES_SHOWN = 48;

// Without a sample list, the authors' search-engine table still names what it measured: one column per sample or channel.
function TableSamples({ rec }: { rec: DatasetRecord }) {
  const zip = rec.files.find((f) => f.preview && /\.zip$/i.test(f.name));
  const [found, setFound] = useState<FilePreview | null>(null);
  useEffect(() => {
    if (!zip) return;
    const ctrl = new AbortController();
    filePreview(rec.accession, zip.name, ctrl.signal).then(setFound, () => {});
    return () => ctrl.abort();
  }, [rec.accession, zip]);
  const e = found?.experiments;
  if (!found || !e) return null;
  const runs = e.names.length;
  return (
    <div className="grid gap-2 text-[13px]">
      <p>
        {runs > 1 ? <>The authors&apos; protein table names <span className="font-medium">{runs} samples</span></> : <>The authors&apos; protein table holds one run</>}
        {e.channels && <>, {runs > 1 ? "each" : ""} with <span className="font-medium">{e.channels} isobaric channels</span></>}
        {e.groups && <>: {Object.entries(e.groups).map(([g, n], i) => <span key={g}>{i > 0 && ", "}<span className="font-mono text-[12.5px]">{g}</span> {n}</span>)}</>}.
      </p>
      {runs > 1 && (
        <p className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[12px] text-muted-foreground">
          {e.names.slice(0, NAMES_SHOWN).map((n) => <span key={n}>{n}</span>)}
          {runs > NAMES_SHOWN && <span>+{runs - NAMES_SHOWN} more</span>}
        </p>
      )}
      <p className="text-[12px] text-muted-foreground">Read from the column names of {found.member?.path ?? found.file} in {found.file}, not downloaded.</p>
    </div>
  );
}
