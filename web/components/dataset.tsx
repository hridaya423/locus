"use client";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowUpRight, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Wordmark } from "@/components/logo";
import { DesignBars } from "@/components/design";
import { size } from "@/components/row-details";
import { Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { SampleTable } from "@/components/sample-table";
import { Files } from "@/components/files";
import { Aside } from "@/components/aside";
import { AssayList, assayNames, useAssays, type AssayState } from "@/components/assay";
import { dataType } from "@/components/result-card";
import { datasetRecord, found, repositoryName, type DatasetRecord, type Found, type Hit } from "@/lib/api";

const noSubscription = () => () => {};

// What the search found, read after hydration so the server and the first client render agree.
function useFound(accession: string): Found | null {
  const known = useSyncExternalStore(noSubscription, () => found(accession) !== null, () => false);
  return useMemo(() => (known ? found(accession) : null), [known, accession]);
}

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
              {source ? repositoryName(source) : "The repository"} did not send the record.
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
    ["Files", rec ? (rec.files.length ? <span className="tabular">{rec.files.length.toLocaleString()} <span className="text-muted-foreground">· {bytes ? size(bytes) : "size not stated"}</span></span> : "none listed") : "…"],
  ];
  return (
    <header className="grid gap-6">
      <div className="grid gap-3">
        <p className="flex flex-wrap items-baseline gap-x-3 font-mono text-[12.5px]">
          <span className="font-medium">{accession}</span>
          {source && <span className="text-muted-foreground">{repositoryName(source)}</span>}
          {published && <span className="text-muted-foreground tabular">{published.slice(0, 10)}</span>}
        </p>
        <h1 className="max-w-4xl font-display text-[34px] leading-[1.08] sm:text-[44px]">{rec?.title ?? hit?.title ?? accession}</h1>
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

function Body({ rec }: { rec: DatasetRecord }) {
  return (
    <div className="grid grid-cols-1 gap-14 lg:grid-cols-[minmax(0,1fr)_17rem] lg:gap-16">
      <div className="grid min-w-0 content-start gap-16">
        <About rec={rec} />
        <Samples rec={rec} />
        <Files rec={rec} />
      </div>
      <Aside rec={rec} />
    </div>
  );
}

const PROTOCOL = /protocol|processing/i;

function Text({ text }: { text: string }) {
  return (
    <div className="grid max-w-[68ch] gap-3 text-[15px] leading-relaxed text-pretty">
      {text.split(/\n\s*\n/).map((p, i) => <p key={i} className="whitespace-pre-line">{p.trim()}</p>)}
    </div>
  );
}

export function About({ rec }: { rec: DatasetRecord }) {
  const main = rec.texts.filter(([label]) => !PROTOCOL.test(label));
  const protocols = rec.texts.filter(([label]) => PROTOCOL.test(label));
  return (
    <section className="grid content-start gap-6">
      <Heading id="about">About</Heading>
      {main.length === 0 && protocols.length === 0 && <p className="text-[13px] text-muted-foreground">{repositoryName(rec.source)} gives no description.</p>}
      {main.map(([label, text], i) => (
        <div key={label} className="grid gap-2">
          {i > 0 && <h3 className="text-[13px] font-medium">{label}</h3>}
          <Text text={text} />
        </div>
      ))}
      {protocols.length > 0 && (
        <div className="grid border-t border-rule">
          {protocols.map(([label, text]) => (
            <details key={label} className="group/p border-b border-rule">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-3 text-[14px] [&::-webkit-details-marker]:hidden">
                {label.replace(/^Protocol: /, "")}
                <ChevronDown aria-hidden className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-open/p:rotate-180" />
              </summary>
              <div className="pb-4"><Text text={text} /></div>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}

const DESIGNED = new Set(["GEO", "PRIDE", "iProX", "jPOST", "PanoramaPublic", "ENA", "ArrayExpress"]);

function Samples({ rec }: { rec: DatasetRecord }) {
  const designed = DESIGNED.has(rec.source) && (rec.source !== "PRIDE" || rec.accession.startsWith("PXD"));
  return (
    <section className="grid content-start gap-8">
      <Heading id="samples" count={rec.samples ? rec.samples.rows.length.toLocaleString() : undefined}>Samples</Heading>
      {designed && <DesignBars accession={rec.accession} source={rec.source} />}
      {rec.samples ? (
        <SampleTable dataset={rec.accession} samples={rec.samples} />
      ) : (
        <p className="text-[13px] text-muted-foreground">{repositoryName(rec.source)} does not list individual samples{rec.files.some((f) => f.kind === "sample design") ? "; the sample design file is under Files" : ""}.</p>
      )}
    </section>
  );
}
