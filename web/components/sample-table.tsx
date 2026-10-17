"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { LINK, MUTED_LINK } from "@/components/page-kit";
import type { Selection } from "@/components/design";
import { samplePath, type DatasetRecord } from "@/lib/api";

const ROWS_SHOWN = 12;
const ROWS_MAX = 2000;

const quoted = (v: string) => (/[",\r\n]/.test(v) ? `"${v.replaceAll('"', '""')}"` : v);

function saveCsv(name: string, header: string[], rows: string[][]) {
  const url = URL.createObjectURL(new Blob([[header, ...rows].map((r) => r.map(quoted).join(",")).join("\r\n") + "\r\n"], { type: "text/csv" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  link.click();
  URL.revokeObjectURL(url);
}

export function SampleTable({ dataset, samples, selection }: { dataset: string; samples: NonNullable<DatasetRecord["samples"]>; selection: Selection }) {
  const [all, setAll] = useState(false);
  const { active, result, pending, error } = selection;
  const columns = useMemo(() => samples.columns.map((c, i) => [c, i] as const).filter(([, i]) => samples.rows.some((r) => r[i])), [samples]);
  const kept = useMemo(() => (result ? result.rows.map((i) => samples.rows[i]) : samples.rows), [result, samples]);
  const rows = active && !result ? [] : kept;
  const shown = rows.slice(0, all || active ? ROWS_MAX : ROWS_SHOWN);
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <input
          type="search"
          value={selection.text}
          onChange={(e) => selection.setText(e.target.value)}
          placeholder="Filter samples"
          aria-label="Filter samples"
          className="h-9 w-full max-w-64 rounded-md border border-rule bg-card px-3 text-[16px] outline-none transition-colors duration-150 placeholder:text-muted-foreground focus:border-foreground sm:text-[13px]"
        />
        <span className="flex items-baseline gap-4">
          <span className="font-mono text-[12px] tabular text-muted-foreground" aria-live="polite">
            {result ? `${result.samples.toLocaleString()} of ${result.total.toLocaleString()} samples` : `${samples.rows.length.toLocaleString()} rows`}
          </span>
          <button type="button" disabled={pending || error} onClick={() => saveCsv(`${dataset}-samples${active ? "-selected" : ""}.csv`, samples.columns, rows)} className={cn("flex items-center gap-1 text-[13px] disabled:pointer-events-none disabled:opacity-50", MUTED_LINK)}>
            <Download aria-hidden className="size-3" />
            Sample sheet (CSV)
          </button>
        </span>
      </div>
      <div aria-busy={pending} className={cn("overflow-x-auto rounded-lg border border-rule bg-card transition-opacity duration-150 motion-reduce:transition-none", pending && "opacity-60")}>
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
      {error ? (
        <p className="flex flex-wrap items-baseline gap-x-3 text-[13px]">
          The filter did not load.
          <button type="button" onClick={selection.retry} className={LINK}>Try again</button>
        </p>
      ) : active && !pending && rows.length === 0 ? (
        <p className="flex flex-wrap items-baseline gap-x-3 text-[13px]">
          No sample has all of these.
          <button type="button" onClick={selection.clear} className={LINK}>Clear filters</button>
        </p>
      ) : active && !result && <p className="text-[13px] text-muted-foreground">Filtering…</p>}
      {!active && rows.length > ROWS_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[13px]", MUTED_LINK)}>
          {all ? "Show fewer" : `Show all ${rows.length.toLocaleString()}`}
        </button>
      )}
      {shown.length === ROWS_MAX && rows.length > ROWS_MAX && <p className="text-xs text-muted-foreground">The first {ROWS_MAX.toLocaleString()} rows are shown; filter to find the others.</p>}
    </div>
  );
}
