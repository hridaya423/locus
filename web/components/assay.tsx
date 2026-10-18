"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { LINK } from "@/components/page-kit";
import { assays as fetchAssays, samplePath, type Assay, type Assays, type Evidence, type LibraryRow, type Matched, type PairedLibrary } from "@/lib/api";

const SAMPLES_SHOWN = 8;

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

function LibraryRows({ dataset, rows }: { dataset: string; rows: LibraryRow[] }) {
  const [all, setAll] = useState(false);
  return (
    <div className="grid gap-1 pb-3">
      <ul className="grid text-[12.5px]">
        {(all ? rows : rows.slice(0, SAMPLES_SHOWN)).map((r) => (
          <li key={r.sample} className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 border-b border-rule/50 py-1 last:border-b-0 sm:grid-cols-[6.5rem_minmax(0,1fr)_minmax(0,16rem)]">
            <Link href={samplePath(dataset, r.sample)} className={cn("font-mono text-[12px]", LINK)}>{r.sample}</Link>
            <span className="truncate" title={r.title}>{r.title}</span>
            <span className="truncate text-muted-foreground max-sm:col-start-2" title={r.why}>{r.why}</span>
          </li>
        ))}
      </ul>
      {rows.length > SAMPLES_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[12.5px] text-muted-foreground", LINK)}>
          {all ? "Fewer" : `All ${rows.length}`}
        </button>
      )}
    </div>
  );
}

function Row({ dataset, assay }: { dataset: string; assay: Assay }) {
  const samples = assay.samples ?? [];
  const stated = Object.entries(assay.stated ?? {});
  const strategy = Object.entries(assay.strategy ?? {});
  const list = (pairs: [string, number][]) => pairs.map(([label, n]) => `${label} (${n})`).join(", ");
  return (
    <li className="border-b border-rule">
      <details className="group/a" open={assay.mislabelled > 0}>
        <summary className="grid cursor-pointer list-none grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 py-2.5 [&::-webkit-details-marker]:hidden">
          <span className="min-w-0 text-[14px]">
            <span className="font-medium">{assay.assay}</span>
            {assay.terms.length > 0 && <span className="text-muted-foreground"> · {assay.terms.slice(0, 3).join(", ")}</span>}
            {assay.from_paper && <span className="text-muted-foreground"> · from the paper; the record does not say</span>}
          </span>
          <span className="flex items-center gap-3 font-mono text-[12px] tabular text-muted-foreground">
            {samples.length > 0 && <span>{samples.length} {samples.length === 1 ? "sample" : "samples"}</span>}
            {assay.how === "inferred" && <span title="Read from a reagent or step, not named in the methods">inferred</span>}
            <ChevronDown aria-hidden className="size-3.5 transition-transform duration-200 group-open/a:rotate-180" />
          </span>
          {assay.mislabelled > 0 && (
            <span className="col-span-2 text-[12.5px] text-warn">The authors&apos; processing notes call {assay.mislabelled === samples.length ? "these" : `${assay.mislabelled} of these`} {list(stated)}</span>
          )}
        </summary>
        <div className="grid gap-3 pb-4">
          {assay.evidence.map((e) => <Quote key={e.text} dataset={dataset} evidence={e} />)}
          {(stated.length > 0 || strategy.length > 0) && (
            <p className="text-[12.5px] text-muted-foreground">
              {stated.length > 0 && assay.mislabelled === 0 && <>Authors&apos; library strategy: {list(stated)}. </>}
              {strategy.length > 0 && <>GEO library strategy: {list(strategy)}.</>}
            </p>
          )}
          {assay.library_rows && <LibraryRows dataset={dataset} rows={assay.library_rows} />}
        </div>
      </details>
    </li>
  );
}

const short = (assay: string) => assay.replace(/ \(.*\)$/, "");

function Library({ dataset, lib }: { dataset: string; lib: PairedLibrary }) {
  return (
    <span className="grid min-w-0">
      <Link href={samplePath(dataset, lib.sample)} className={cn("w-fit font-mono text-[12px]", LINK)}>{lib.sample}</Link>
      <span className="truncate text-muted-foreground" title={lib.title}>{lib.title}</span>
    </span>
  );
}

function MatchedLibraries({ dataset, matched }: { dataset: string; matched: Matched }) {
  const tis = matched.pairs.some((p) => p.tis);
  const kinds = [...new Set(matched.pairs.map((p) => short(p.footprint.assay)))].join(" or ");
  return (
    <details className="group/m">
      <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-3 py-1 text-[13px] [&::-webkit-details-marker]:hidden">
        <span className="font-medium">Matched libraries</span>
        <span className="font-mono text-[12px] tabular text-muted-foreground">
          {matched.pairs.length} {kinds || "footprint"}/RNA-seq pairs by title{matched.unpaired.length > 0 && ` · ${matched.unpaired.length} without a partner`}{matched.top_ups.length > 0 && ` · ${matched.top_ups.length} re-sequencing top-ups`}
        </span>
        <ChevronDown aria-hidden className="size-3.5 self-center text-muted-foreground transition-transform duration-200 group-open/m:rotate-180" />
      </summary>
      <div className="grid gap-3 pt-2 text-[12.5px]">
        {matched.pairs.length > 0 && (
          <ul className="grid">
            <li className={cn("grid gap-x-4 border-b border-rule pb-1 text-muted-foreground", tis ? "grid-cols-3" : "grid-cols-2")}>
              <span>Footprints</span><span>RNA-seq</span>{tis && <span>TIS-seq, same sample</span>}
            </li>
            {matched.pairs.map((p) => (
              <li key={p.key} className={cn("grid gap-x-4 border-b border-rule/50 py-1", tis ? "grid-cols-3" : "grid-cols-2")}>
                <Library dataset={dataset} lib={p.footprint} />
                <Library dataset={dataset} lib={p.rna} />
                {tis && (p.tis ? <Library dataset={dataset} lib={p.tis} /> : <span className="text-muted-foreground">–</span>)}
              </li>
            ))}
          </ul>
        )}
        {matched.unpaired.length > 0 && (
          <p className="text-muted-foreground">Without a partner: {matched.unpaired.map((u) => `${u.sample} (${short(u.assay)})`).join(", ")}</p>
        )}
        {matched.top_ups.length > 0 && <p className="text-muted-foreground">Re-sequencing top-ups, not separate samples: {matched.top_ups.map((u) => u.sample).join(", ")}</p>}
      </div>
    </details>
  );
}

export type AssayState = { data?: Assays; failed?: boolean; slow?: boolean };

export function useAssays(accession: string, enabled: boolean): AssayState {
  const [state, setState] = useState<AssayState>({});
  useEffect(() => {
    if (!enabled) return;
    const ctrl = new AbortController();
    const slow = setTimeout(() => setState((s) => (s.data || s.failed ? s : { slow: true })), 8000);
    fetchAssays(accession, ctrl.signal).then((data) => setState({ data }), () => !ctrl.signal.aborted && setState({ failed: true }));
    return () => {
      clearTimeout(slow);
      ctrl.abort();
    };
  }, [accession, enabled]);
  return state;
}

const MASS_SPEC = new Set(["PRIDE", "MassIVE", "iProX", "jPOST", "PanoramaPublic", "PeptideAtlas"]);
// Acquisition and quantification modes describe how, not what: PXD008373 is phosphoproteomics, acquired by DDA.
const MODE = /^(Data-(in)?dependent acquisition|Label-free quantification)/;

// Assays with libraries assigned to them; else what the record's text names (for mass spectrometry, the experiment
// type it names or implies, without acquisition modes).
export const assayNames = (data?: Assays) => {
  const assigned = data?.assays.filter((a) => a.samples?.length) ?? [];
  const named = !data ? [] : MASS_SPEC.has(data.source) ? data.assays.filter((a) => !MODE.test(a.assay)) : data.assays.filter((a) => a.how === "named" && !a.from_paper);
  return (assigned.length ? assigned : named).map((a) => a.assay.replace(/ \(.*\)$/, ""));
};

export function AssayList({ accession, state }: { accession: string; state: AssayState }) {
  const data = state.data;
  return (
    <section aria-labelledby="measured" className="grid gap-2">
      <h2 id="measured" className="label text-muted-foreground">Measured, read from the methods</h2>
      {state.failed ? (
        <p className="text-[13px] text-muted-foreground">The methods could not be read.</p>
      ) : !data ? (
        <p className="text-[13px] text-muted-foreground">{state.slow ? "Still reading the methods; a series with thousands of samples can take up to three minutes the first time." : "Reading the methods…"}</p>
      ) : data.assays.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">No method is named in the record{data.read_from.length ? ` (${data.read_from.join(", ")})` : ""}.</p>
      ) : (
        <ul className="grid border-t border-rule">
          {data.assays.map((a) => <Row key={a.assay} dataset={accession} assay={a} />)}
        </ul>
      )}
      {data && data.unassigned_samples.length > 0 && (
        <details className="group/u border-b border-rule">
          <summary className="flex cursor-pointer list-none items-baseline justify-between gap-4 py-2.5 text-[14px] [&::-webkit-details-marker]:hidden">
            <span className="text-muted-foreground">Library type not determined</span>
            <span className="font-mono text-[12px] tabular text-muted-foreground">{data.unassigned_samples.length} samples</span>
          </summary>
          <LibraryRows dataset={accession} rows={data.unassigned_samples} />
        </details>
      )}
      {data?.matched && <MatchedLibraries dataset={accession} matched={data.matched} />}
      {data?.split && (
        <div className="grid gap-2 pt-2">
          <h3 className="text-[13px] font-medium">Where the matched libraries were split</h3>
          <Quote dataset={accession} evidence={data.split} />
        </div>
      )}
    </section>
  );
}
