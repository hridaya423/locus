"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { LINK, MUTED_LINK } from "@/components/page-kit";
import { samplePath, type DatasetRecord } from "@/lib/api";

const ROWS_SHOWN = 12;
const ROWS_MAX = 2000;

export function SampleTable({ dataset, samples }: { dataset: string; samples: NonNullable<DatasetRecord["samples"]> }) {
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
