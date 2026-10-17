"use client";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowUpRight, ChevronDown, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { Wordmark } from "@/components/logo";
import { DesignBars } from "@/components/design";
import { size } from "@/components/row-details";
import { dataType } from "@/components/result-card";
import { datasetRecord, found, repositoryName, samplePath, type DatasetRecord, type Found, type Hit, type RecordFile } from "@/lib/api";

export const LINK = "underline decoration-rule underline-offset-4 transition-colors duration-150 hover:decoration-foreground";
export const MUTED_LINK = "text-muted-foreground underline decoration-rule underline-offset-4 transition-colors duration-150 hover:text-foreground hover:decoration-foreground";

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
          <Header accession={accession} rec={rec} hit={context?.hit} />
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

function Header({ accession, rec, hit }: { accession: string; rec: DatasetRecord | null; hit?: Hit }) {
  const source = rec?.source ?? hit?.source;
  const published = rec?.published ?? hit?.published;
  const samples = rec?.samples?.rows.length || rec?.sample_count || hit?.samples;
  const organism = rec?.facts.find(([label]) => label === "Organism")?.[1] ?? (rec?.organism || hit?.organism || "").split(";").filter(Boolean);
  const bytes = rec?.files.reduce((n, f) => n + (f.bytes ?? 0), 0) ?? 0;
  const processed = rec?.files.filter((f) => f.processed).length ?? 0;
  const unknown = rec || hit ? "not stated" : "…";
  const figures: [string, React.ReactNode][] = [
    ["Data type", dataType(rec?.modality ?? hit?.modality ?? "") || unknown],
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

export function Heading({ id, children, count }: { id?: string; children: React.ReactNode; count?: React.ReactNode }) {
  return (
    <h2 id={id} className="flex scroll-mt-8 items-baseline gap-3 font-display text-[28px] leading-none">
      {children}
      {count != null && <span className="font-mono text-[13px] tabular text-muted-foreground">{count}</span>}
    </h2>
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

const ROWS_SHOWN = 12;
const ROWS_MAX = 2000;

function SampleTable({ dataset, samples }: { dataset: string; samples: NonNullable<DatasetRecord["samples"]> }) {
  const [filter, setFilter] = useState("");
  const [all, setAll] = useState(false);
  const columns = useMemo(() => samples.columns.map((c, i) => [c, i] as const).filter(([, i]) => samples.rows.some((r) => r[i])), [samples]);
  const needle = filter.trim().toLowerCase();
  const rows = needle ? samples.rows.filter((r) => r.some((v) => v.toLowerCase().includes(needle))) : samples.rows;
  const shown = rows.slice(0, all || needle ? ROWS_MAX : ROWS_SHOWN);
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter samples"
          aria-label="Filter samples"
          className="h-9 w-full max-w-64 rounded-md border border-rule bg-card px-3 text-[16px] outline-none transition-colors duration-150 placeholder:text-muted-foreground focus:border-foreground sm:text-[13px]"
        />
        <span className="font-mono text-[12px] tabular text-muted-foreground">
          {needle ? `${rows.length.toLocaleString()} of ${samples.rows.length.toLocaleString()}` : `${samples.rows.length.toLocaleString()} rows`}
        </span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-rule bg-card">
        <table className="w-max min-w-full border-collapse text-[12.5px]">
          <thead>
            <tr className="border-b border-rule">
              {columns.map(([c], n) => (
                <th key={c} className={cn("whitespace-nowrap px-3 py-2 text-left font-normal text-muted-foreground", n === 0 && "sticky left-0 bg-card")}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, k) => (
              <tr key={k} className="border-b border-rule/60 last:border-b-0">
                {columns.map(([c, i], n) => (
                  <td key={c} className={cn("max-w-64 truncate px-3 py-1.5", n === 0 && "sticky left-0 bg-card font-mono text-[12px]")} title={r[i]}>
                    {n === 0 && samples.pages && r[i] ? (
                      <Link href={samplePath(dataset, r[i])} className={LINK}>{r[i]}</Link>
                    ) : n === 0 && samples.link && r[i] ? (
                      <a href={samples.link.replace("{}", r[i])} target="_blank" rel="noreferrer" className={LINK}>{r[i]}</a>
                    ) : (
                      r[i] || <span className="text-muted-foreground">–</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!needle && rows.length > ROWS_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[13px]", MUTED_LINK)}>
          {all ? "Show fewer" : `Show all ${rows.length.toLocaleString()}`}
        </button>
      )}
      {shown.length === ROWS_MAX && rows.length > ROWS_MAX && <p className="text-xs text-muted-foreground">The first {ROWS_MAX.toLocaleString()} rows are shown; filter to find the others.</p>}
    </div>
  );
}

type Group = { name: string; files: RecordFile[]; bytes: number; processed: number };

function groups(files: RecordFile[]): Group[] {
  const by = new Map<string, RecordFile[]>();
  for (const f of files) by.set(f.group, [...(by.get(f.group) ?? []), f]);
  return [...by]
    .map(([name, list]) => ({
      name,
      files: [...list].sort((a, b) => Number(b.processed) - Number(a.processed)),
      bytes: list.reduce((n, f) => n + (f.bytes ?? 0), 0),
      processed: list.filter((f) => f.processed).length,
    }))
    .sort((a, b) => Number(b.processed > 0) - Number(a.processed > 0));
}

export function Files({ rec }: { rec: DatasetRecord }) {
  const list = useMemo(() => groups(rec.files), [rec.files]);
  const total = list.reduce((n, g) => n + g.bytes, 0);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);
  return (
    <section className="grid content-start gap-8">
      <Heading id="files" count={rec.files.length ? `${rec.files.length.toLocaleString()} · ${size(total)}` : undefined}>Files</Heading>
      {list.length === 0 && <p className="text-[13px] text-muted-foreground">{repositoryName(rec.source)} lists no files for this dataset.</p>}
      {total > 0 && list.length > 1 && (
        <figure className="grid gap-3">
          <div aria-hidden className="flex h-2 gap-[2px] overflow-hidden rounded-full">
            {list.filter((g) => g.bytes).map((g) => (
              <span key={g.name} title={`${g.name}: ${size(g.bytes)}`} className={cn("h-full min-w-[3px]", g.processed ? "bg-foreground" : "bg-foreground/25")} style={{ flexGrow: g.bytes }} />
            ))}
          </div>
          <figcaption className="flex flex-wrap gap-x-5 gap-y-1 text-[12.5px]">
            {list.map((g) => (
              <a key={g.name} href={`#files-${g.name}`} className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground">
                <span aria-hidden className={cn("size-2 rounded-full", g.processed ? "bg-foreground" : "bg-foreground/25")} />
                {g.name} <span className="font-mono tabular">{g.bytes ? size(g.bytes) : `${g.files.length}`}</span>
              </a>
            ))}
          </figcaption>
        </figure>
      )}
      {list.map((g) => <FileGroup key={g.name} group={g} />)}
      {rec.download_plan && (
        <details className="group/plan">
          <summary className={cn("flex w-fit cursor-pointer list-none items-center gap-1 text-[13px] [&::-webkit-details-marker]:hidden", MUTED_LINK)}>
            Commands to download everything
            <ChevronDown aria-hidden className="size-3.5 transition-transform duration-200 group-open/plan:rotate-180" />
          </summary>
          <div className="mt-3 grid min-w-0 gap-1.5 border-l-2 border-foreground pl-3">
            <pre className="overflow-x-auto font-mono text-[12px] leading-relaxed">{rec.download_plan}</pre>
            <button type="button" onClick={() => navigator.clipboard.writeText(rec.download_plan).then(() => setCopied(true))} className={cn("w-fit text-xs font-medium", LINK)}>
              {copied ? "copied" : "copy"}
            </button>
          </div>
        </details>
      )}
    </section>
  );
}

const FILES_SHOWN = 6;

function FileGroup({ group }: { group: Group }) {
  const [all, setAll] = useState(false);
  const shown = all ? group.files : group.files.slice(0, FILES_SHOWN);
  return (
    <div id={`files-${group.name}`} className="grid scroll-mt-8 gap-2">
      <h3 className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-foreground pb-2 text-[14px] font-medium">
        <span>
          {group.name}
          {group.processed > 0 && <span className="ml-2 text-[12.5px] font-normal text-muted-foreground">ready to use</span>}
        </span>
        <span className="font-mono text-[12px] font-normal tabular text-muted-foreground">
          {group.files.length.toLocaleString()} {group.files.length === 1 ? "file" : "files"}{group.bytes ? ` · ${size(group.bytes)}` : ""}
        </span>
      </h3>
      <ul className="grid">
        {shown.map((f) => (
          <li key={f.url} className="group/file grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 border-b border-rule/60 py-1.5 text-[13px] last:border-b-0 sm:grid-cols-[minmax(0,1fr)_9rem_4.5rem]">
            <a href={f.url} download className="flex min-w-0 items-baseline gap-1.5 hover:text-foreground" title={f.name}>
              <Download aria-hidden className="size-3 shrink-0 translate-y-[1px] text-muted-foreground group-hover/file:text-foreground" />
              <span className="truncate underline decoration-transparent underline-offset-4 group-hover/file:decoration-foreground">{f.name}</span>
            </a>
            <span className="truncate text-[12.5px] text-muted-foreground max-sm:hidden">{f.kind}</span>
            <span className="text-right font-mono text-[12px] tabular text-muted-foreground">{f.bytes != null ? size(f.bytes) : "–"}</span>
          </li>
        ))}
      </ul>
      {group.files.length > FILES_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[13px]", MUTED_LINK)}>
          {all ? "Show fewer" : `Show all ${group.files.length.toLocaleString()}`}
        </button>
      )}
    </div>
  );
}

const VALUES_SHOWN = 6;

function FactValues({ values }: { values: string[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? values : values.slice(0, VALUES_SHOWN);
  return (
    <dd className="grid gap-0.5 text-[13.5px] leading-snug">
      {shown.map((v) => <span key={v} className="break-words">{v}</span>)}
      {values.length > VALUES_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[12.5px]", MUTED_LINK)}>
          {all ? "fewer" : `+${values.length - VALUES_SHOWN} more`}
        </button>
      )}
    </dd>
  );
}

function AsideSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="grid content-start gap-3">
      <h2 className="label text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

export function Aside({ rec }: { rec: DatasetRecord }) {
  const roles = [...new Set(rec.people.map((p) => p.role))];
  return (
    <aside className="grid content-start gap-10 lg:border-l lg:border-rule lg:pl-8">
      <AsideSection title="Record">
        <dl className="grid gap-3">
          {rec.facts.map(([label, values]) => (
            <div key={label} className="grid gap-0.5">
              <dt className="text-[12px] text-muted-foreground">{label}</dt>
              <FactValues values={values} />
            </div>
          ))}
        </dl>
      </AsideSection>
      {rec.papers.length > 0 && (
        <AsideSection title={rec.papers.length === 1 ? "Paper" : "Papers"}>
          <ul className="grid gap-3">
            {rec.papers.map((p) => (
              <li key={p.url || p.title} className="grid gap-0.5 text-[13.5px] leading-snug">
                {p.url ? <a href={p.url} target="_blank" rel="noreferrer" className={LINK}>{p.title}</a> : <span>{p.title}</span>}
                {(p.journal || p.year) && <span className="text-[12.5px] text-muted-foreground"><span className="italic">{p.journal}</span> {p.year}</span>}
              </li>
            ))}
          </ul>
        </AsideSection>
      )}
      {roles.map((role) => {
        const people = rec.people.filter((p) => p.role === role);
        return (
          <AsideSection key={role} title={people.length > 1 ? `${role}s` : role}>
            <ul className="grid gap-2 text-[13.5px] leading-snug">
              {people.map((p, i) => (
                <li key={`${p.name}${i}`} className="grid gap-0.5">
                  <span>{p.name}</span>
                  {p.affiliation && <span className="text-[12.5px] text-muted-foreground">{p.affiliation}</span>}
                  {p.email && <a href={`mailto:${p.email}`} className={cn("w-fit text-[12.5px] break-all", MUTED_LINK)}>{p.email}</a>}
                  {p.web && <a href={p.web} target="_blank" rel="noreferrer" className={cn("w-fit text-[12.5px] break-all", MUTED_LINK)}>{p.web}</a>}
                </li>
              ))}
            </ul>
          </AsideSection>
        );
      })}
      {rec.links.length > 0 && (
        <AsideSection title="Linked records">
          <ul className="grid gap-1.5 text-[13.5px]">
            {rec.links.map(([label, url]) => (
              <li key={url}>
                <a href={url} target="_blank" rel="noreferrer" className={cn("group/link inline-flex items-center gap-1", LINK)}>
                  {label}
                  <ArrowUpRight aria-hidden className="size-3.5 text-muted-foreground group-hover/link:text-foreground" />
                </a>
              </li>
            ))}
          </ul>
        </AsideSection>
      )}
    </aside>
  );
}
