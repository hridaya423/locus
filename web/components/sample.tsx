"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, ArrowUpRight, ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { Wordmark } from "@/components/logo";
import { About } from "@/components/dataset";
import { Aside } from "@/components/aside";
import { Files } from "@/components/files";
import { Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { size } from "@/components/row-details";
import { datasetPath, repositoryName, samplePath, sampleRecord, type SampleRecord } from "@/lib/api";

const fact = (rec: SampleRecord, ...labels: string[]) => labels.map((l) => rec.facts.find(([label]) => label === l)?.[1][0]).find(Boolean);

export function SamplePage({ dataset, accession }: { dataset: string; accession: string }) {
  const router = useRouter();
  const [rec, setRec] = useState<SampleRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    sampleRecord(dataset, accession, ctrl.signal).then(
      (r) => {
        setRec(r);
        setError(null);
      },
      (e) => !ctrl.signal.aborted && setError(e instanceof Error ? e.message : String(e)),
    );
    return () => ctrl.abort();
  }, [dataset, accession, attempt]);

  useEffect(() => {
    document.title = rec ? `${accession} · ${rec.title} · locus` : `${accession} · locus`;
  }, [accession, rec]);

  // Arrow keys step through the dataset's samples, as the previous and next links do.
  useEffect(() => {
    const step = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || (e.target as HTMLElement).closest("input, textarea")) return;
      const to = e.key === "ArrowLeft" ? rec?.position.previous : e.key === "ArrowRight" ? rec?.position.next : null;
      if (to) router.push(samplePath(dataset, to));
    };
    window.addEventListener("keydown", step);
    return () => window.removeEventListener("keydown", step);
  }, [rec, dataset, router]);

  const characteristics = rec?.samples?.rows ?? [];
  const bytes = rec?.files.reduce((n, f) => n + (f.bytes ?? 0), 0) ?? 0;
  const figures: [string, React.ReactNode][] = rec
    ? [
        ["Organism", fact(rec, "Organism", "Organism (channel 1)") ?? "not stated"],
        ["Source", fact(rec, "Source", "Source (channel 1)") ?? characteristics.find(([k]) => /tissue|cell type/i.test(k))?.[1] ?? "not stated"],
        ["Measured on", fact(rec, "Instrument", "Platform") ?? "not stated"],
        ["Files", rec.files.length ? <span className="tabular">{rec.files.length} <span className="text-muted-foreground">· {bytes ? size(bytes) : "size not stated"}</span></span> : "none listed"],
      ]
    : [];

  return (
    <div className="mx-auto grid w-full max-w-6xl grid-cols-1 content-start gap-10">
      <nav className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-5">
          <Link href="/" aria-label="locus home" className="leading-none">
            <Wordmark className="text-[30px]" />
          </Link>
          <Link href={datasetPath(dataset)} className={cn("flex min-w-0 items-center gap-1.5 text-[13px]", MUTED_LINK)}>
            <ChevronLeft aria-hidden className="size-3.5 shrink-0" />
            <span className="font-mono">{dataset}</span>
            {rec && <span className="truncate max-sm:hidden">{rec.dataset.title}</span>}
          </Link>
        </div>
        {rec && (
          <a href={rec.url} target="_blank" rel="noreferrer" className={cn("flex shrink-0 items-center gap-1 text-[13px]", MUTED_LINK)}>
            {repositoryName(rec.source)} record
            <ArrowUpRight aria-hidden className="size-3.5" />
          </a>
        )}
      </nav>

      {error === "missing" ? (
        <p className="text-sm">
          {accession} is not a sample locus can show for {dataset}. <Link href={datasetPath(dataset)} className={LINK}>Back to the dataset</Link>.
        </p>
      ) : error ? (
        <p className="flex flex-wrap items-baseline gap-x-3 text-sm">
          The repository did not send the sample record.
          <button type="button" onClick={() => setAttempt((n) => n + 1)} className={LINK}>Try again</button>
        </p>
      ) : (
        <>
          <header className="grid gap-6">
            <div className="grid gap-3">
              <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
                <p className="flex flex-wrap items-baseline gap-x-3 font-mono text-[12.5px]">
                  <span className="font-medium">{accession}</span>
                  {rec && rec.position.index >= 0 && (
                    <span className="text-muted-foreground tabular">sample {rec.position.index + 1} of {rec.position.total.toLocaleString()}</span>
                  )}
                </p>
                {rec && rec.position.index >= 0 && (
                  <span className="flex items-center gap-4 text-[13px]">
                    <Step to={rec.position.previous && samplePath(dataset, rec.position.previous)} label="Previous" icon={<ArrowLeft aria-hidden className="size-3.5" />} />
                    <Step to={rec.position.next && samplePath(dataset, rec.position.next)} label="Next" icon={<ArrowRight aria-hidden className="size-3.5" />} after />
                  </span>
                )}
              </div>
              <h1 className="max-w-4xl font-display text-[34px] leading-[1.08] break-words sm:text-[44px]">{rec?.title ?? accession}</h1>
            </div>
            {rec && (
              <dl className="grid grid-cols-2 border-y border-rule sm:grid-cols-4">
                {figures.map(([label, value], i) => (
                  <div key={label} className={cn("grid min-w-0 content-start gap-1 py-3 pr-4", i % 2 === 1 && "pl-4 max-sm:border-l max-sm:border-rule", i > 0 && "sm:border-l sm:border-rule sm:pl-4", i > 1 && "max-sm:border-t max-sm:border-rule")}>
                    <dt className="label text-muted-foreground">{label}</dt>
                    <dd className="truncate text-[15px] font-medium" title={typeof value === "string" ? value : undefined}>{value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </header>

          {!rec ? (
            <p className="text-[13px] text-muted-foreground">Reading the sample record…</p>
          ) : (
            <div className="grid grid-cols-1 gap-14 lg:grid-cols-[minmax(0,1fr)_17rem] lg:gap-16">
              <div className="grid min-w-0 content-start gap-16">
                <section className="grid content-start gap-6">
                  <Heading id="characteristics" count={characteristics.length || undefined}>Characteristics</Heading>
                  {characteristics.length ? (
                    <dl className="grid gap-x-8 sm:grid-cols-2">
                      {characteristics.map(([name, value], i) => (
                        <div key={`${name}${i}`} className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] items-baseline gap-x-4 border-b border-rule py-2.5">
                          <dt className="text-[13px] text-muted-foreground break-words">{name}</dt>
                          <dd className="text-[15px] break-words">{value}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p className="text-[13px] text-muted-foreground">{repositoryName(rec.source)} records no characteristics for this sample.</p>
                  )}
                </section>
                {rec.texts.length > 0 && <About rec={rec} />}
                <Files rec={rec} />
              </div>
              <Aside rec={rec} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Step({ to, label, icon, after = false }: { to: string | null; label: string; icon: React.ReactNode; after?: boolean }) {
  const body = after ? <>{label}{icon}</> : <>{icon}{label}</>;
  if (!to) return <span aria-disabled className="flex items-center gap-1.5 text-muted-foreground/50">{body}</span>;
  return <Link href={to} className={cn("flex items-center gap-1.5", MUTED_LINK)}>{body}</Link>;
}
