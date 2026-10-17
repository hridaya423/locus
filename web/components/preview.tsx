"use client";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { MUTED_LINK } from "@/components/page-kit";
import { size } from "@/components/row-details";
import { filePreview, type FilePreview, type PreviewColumn } from "@/lib/api";

const LEVELS_SHOWN = 6;
const NUMERIC = new Set(["integer", "number"]);

function detail(c: PreviewColumn): string {
  const range = c.min === undefined ? "" : c.min === c.max ? c.min : `${c.min} to ${c.max}`;
  const extra = c.type === "text" ? `${c.distinct?.toLocaleString()} distinct` : range;
  return [c.type, extra, c.missing && c.type !== "empty" ? `${c.missing.toLocaleString()} missing` : ""].filter(Boolean).join(" · ");
}

function source(p: FilePreview): string {
  const covered = p.rows_read > p.rows.length ? `; types and ranges cover the ${p.rows_read.toLocaleString()} rows read` : "";
  const where = p.format === "xlsx" ? `Downloaded the whole file (${size(p.size ?? p.bytes_read)})` : p.complete ? `Read the whole file (${size(p.bytes_read)})` : `Read the first ${size(p.bytes_read)}${p.size ? ` of ${size(p.size)}` : "; file size not stated"}`;
  return where + covered;
}

function Summary({ p }: { p: FilePreview }) {
  const rows = p.complete ? (p.rows.length === p.total_rows ? `All ${p.total_rows.toLocaleString()} rows` : `First ${p.rows.length} of ${p.total_rows?.toLocaleString()} rows`) : `First ${p.rows.length.toLocaleString()} rows of an unknown total`;
  const columns = p.columns.length < p.column_count ? `first ${p.columns.length.toLocaleString()} of ${p.column_count.toLocaleString()} columns` : `${p.column_count.toLocaleString()} columns`;
  const levels = p.samples ? Object.entries(p.samples.levels) : [];
  return (
    <div className="grid gap-1 text-[12.5px]">
      <p className="font-mono tabular">{[rows, columns, p.format + (p.sheet ? ` · sheet ${p.sheet}` : "")].join(" · ")}</p>
      <p className="text-muted-foreground">{source(p)}.</p>
      {p.samples && (
        <p className="text-muted-foreground">
          <span className="font-mono tabular">{p.samples.matched.toLocaleString()} of {p.samples.of.toLocaleString()}</span> columns are in the sample table, by {p.samples.by}
          {p.samples.factor && <>; grouped by {p.samples.factor}: {levels.slice(0, LEVELS_SHOWN).map(([name, n]) => `${name} (${n.toLocaleString()})`).join("; ")}{levels.length > LEVELS_SHOWN && `; ${levels.length - LEVELS_SHOWN} more`}</>}
        </p>
      )}
    </div>
  );
}

function PreviewTable({ p }: { p: FilePreview }) {
  const grouped = p.samples?.factor ? p.columns.some((c) => c.group) : false;
  const sticky = "sticky left-0 bg-card";
  return (
    <div className="max-w-full overflow-x-auto rounded-lg border border-rule bg-card">
      <table className="w-max min-w-full border-collapse text-[12.5px]">
        <thead>
          <tr className="border-b border-rule align-top">
            {p.columns.map((c, n) => (
              <th key={n} title={`${c.name || "row name"}: ${detail(c)}`} className={cn("max-w-64 px-3 py-2 text-left font-normal", NUMERIC.has(c.type) && "text-right", n === 0 && sticky)}>
                <span className="block truncate">{c.name || <span className="text-muted-foreground">row name</span>}</span>
                <span className="block whitespace-nowrap font-mono text-[11px] tabular text-muted-foreground">{detail(c)}</span>
              </th>
            ))}
          </tr>
          {grouped && (
            <tr className="border-b border-rule">
              {p.columns.map((c, n) => (
                <th key={n} title={c.group ?? undefined} className={cn("max-w-64 truncate whitespace-nowrap px-3 py-1.5 text-[12px] font-normal text-muted-foreground", NUMERIC.has(c.type) ? "text-right" : "text-left", n === 0 && sticky)}>
                  {n === 0 ? p.samples?.factor : c.group ?? "–"}
                </th>
              ))}
            </tr>
          )}
        </thead>
        <tbody>
          {p.rows.map((r, k) => (
            <tr key={k} className="border-b border-rule/60 last:border-b-0">
              {r.map((v, n) => (
                <td key={n} title={v} className={cn("max-w-64 truncate px-3 py-1.5", NUMERIC.has(p.columns[n]?.type) && "text-right font-mono text-[12px] tabular", n === 0 && sticky)}>
                  {v || <span className="text-muted-foreground">–</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Preview({ accession, file }: { accession: string; file: string }) {
  const [state, setState] = useState<{ p: FilePreview } | { error: string; retry: boolean } | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    filePreview(accession, file, abort.signal).then((p) => setState({ p }), (e: Error & { retry?: boolean }) => !abort.signal.aborted && setState({ error: e.message, retry: e.retry ?? true }));
    return () => abort.abort();
  }, [accession, file, attempt]);
  if (!state) {
    return (
      <div className="grid gap-2" role="status">
        <p className="text-[13px] text-muted-foreground">Reading the start of the file…</p>
        <div aria-hidden className="h-32 animate-pulse rounded-lg border border-rule bg-card motion-reduce:animate-none" />
      </div>
    );
  }
  if ("error" in state) {
    return (
      <p className="text-[13px] text-muted-foreground" role="alert">
        {state.error}{" "}
        {state.retry && <button type="button" onClick={() => { setState(null); setAttempt((n) => n + 1); }} className={cn("text-[13px]", MUTED_LINK)}>Try again</button>}
      </p>
    );
  }
  return (
    <div className="grid min-w-0 gap-3">
      <Summary p={state.p} />
      <PreviewTable p={state.p} />
    </div>
  );
}
