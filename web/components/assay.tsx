"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { LINK } from "@/components/page-kit";
import { assays as fetchAssays, samplePath, type Assay, type Assays, type Evidence } from "@/lib/api";

const SAMPLES_SHOWN = 24;

function Marked({ text, term }: { text: string; term?: string }) {
  const at = term ? text.toLowerCase().indexOf(term.toLowerCase()) : -1;
  if (at < 0 || !term) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="bg-transparent font-medium text-signal">{text.slice(at, at + term.length)}</mark>
      {text.slice(at + term.length)}
    </>
  );
}

function Quote({ dataset, evidence }: { dataset: string; evidence: Evidence }) {
  const n = evidence.samples.length;
  return (
    <blockquote className="grid gap-1 border-l-2 border-foreground pl-3">
      <p className="max-w-[72ch] text-[13.5px] leading-relaxed text-pretty">
        <Marked text={evidence.text} term={evidence.term} />
      </p>
      <footer className="font-mono text-[11.5px] text-muted-foreground">
        {evidence.field}
        {n === 1 && <> · <Link href={samplePath(dataset, evidence.samples[0])} className={LINK}>{evidence.samples[0]}</Link></>}
        {n > 1 && ` · ${n} samples`}
      </footer>
    </blockquote>
  );
}

function Row({ dataset, assay }: { dataset: string; assay: Assay }) {
  const [all, setAll] = useState(false);
  const samples = assay.samples ?? [];
  const labels = Object.entries(assay.labels ?? {});
  return (
    <li className="border-b border-rule">
      <details className="group/a" open={assay.mislabelled > 0}>
        <summary className="grid cursor-pointer list-none grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 py-2.5 [&::-webkit-details-marker]:hidden">
          <span className="min-w-0 text-[14px]">
            <span className="font-medium">{assay.assay}</span>
            {assay.terms.length > 0 && <span className="text-muted-foreground"> · {assay.terms.slice(0, 3).join(", ")}</span>}
          </span>
          <span className="flex items-center gap-3 font-mono text-[12px] tabular text-muted-foreground">
            {samples.length > 0 && <span>{samples.length} {samples.length === 1 ? "sample" : "samples"}</span>}
            {assay.how === "inferred" && <span title="Read from a reagent or step, not named in the methods">inferred</span>}
            <ChevronDown aria-hidden className="size-3.5 transition-transform duration-200 group-open/a:rotate-180" />
          </span>
          {assay.mislabelled > 0 && (
            <span className="col-span-2 text-[12.5px] text-warn">Labelled {labels.map(([label, n]) => `${label} (${n})`).join(", ")} by the authors</span>
          )}
        </summary>
        <div className="grid gap-3 pb-4">
          {assay.evidence.map((e) => <Quote key={e.text} dataset={dataset} evidence={e} />)}
          {labels.length > 0 && assay.mislabelled === 0 && (
            <p className="text-[12.5px] text-muted-foreground">
              Author label: {labels.map(([label, n]) => `${label} (${n})`).join(", ")}
            </p>
          )}
          {samples.length > 0 && (
            <p className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[12px]">
              {(all ? samples : samples.slice(0, SAMPLES_SHOWN)).map((g) => <Link key={g} href={samplePath(dataset, g)} className={LINK}>{g}</Link>)}
              {samples.length > SAMPLES_SHOWN && (
                <button type="button" onClick={() => setAll((v) => !v)} className={cn("text-muted-foreground", LINK)}>
                  {all ? "fewer" : `+${samples.length - SAMPLES_SHOWN}`}
                </button>
              )}
            </p>
          )}
        </div>
      </details>
    </li>
  );
}

export function AssayList({ accession }: { accession: string }) {
  const [state, setState] = useState<{ data?: Assays; failed?: boolean }>({});
  useEffect(() => {
    const ctrl = new AbortController();
    fetchAssays(accession, ctrl.signal).then((data) => setState({ data }), () => !ctrl.signal.aborted && setState({ failed: true }));
    return () => ctrl.abort();
  }, [accession]);

  const data = state.data;
  return (
    <section aria-labelledby="measured" className="grid gap-2">
      <h2 id="measured" className="label text-muted-foreground">Measured, read from the methods</h2>
      {state.failed ? (
        <p className="text-[13px] text-muted-foreground">The methods could not be read.</p>
      ) : !data ? (
        <p className="text-[13px] text-muted-foreground">Reading the methods…</p>
      ) : data.assays.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">No method is named in the record{data.read_from.length ? ` (${data.read_from.join(", ")})` : ""}.</p>
      ) : (
        <ul className="grid border-t border-rule">
          {data.assays.map((a) => <Row key={a.assay} dataset={accession} assay={a} />)}
        </ul>
      )}
      {data?.split && (
        <div className="grid gap-2 pt-2">
          <h3 className="text-[13px] font-medium">Where the matched libraries were split</h3>
          <Quote dataset={accession} evidence={data.split} />
        </div>
      )}
    </section>
  );
}
