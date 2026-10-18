"use client";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { MUTED_LINK } from "@/components/page-kit";
import { size } from "@/components/row-details";
import { filePreview, type FilePreview, type PreviewColumn } from "@/lib/api";

const LEVELS_SHOWN = 6;
const MAX_RUNS = 30;
const NUMERIC = new Set(["integer", "number"]);

function detail(c: PreviewColumn, rows: number): string {
  const range = c.min === undefined ? "" : c.min === c.max ? c.min : `${c.min} to ${c.max}`;
  const extra = c.type === "text" ? (c.distinct === rows ? "unique" : `${c.distinct?.toLocaleString()} distinct`) : range;
  return [c.type, extra, c.missing && c.type !== "empty" ? `${c.missing.toLocaleString()} missing` : ""].filter(Boolean).join(" · ");
}

function source(p: FilePreview): string {
  const covered = p.rows_read > p.rows.length ? `; types and ranges cover the ${p.rows_read.toLocaleString()} rows read` : "";
  const above = p.skipped ? `; ${p.skipped.toLocaleString()} ${p.format === "xlsx" ? "rows" : "comment lines"} above the header skipped` : "";
  const where = p.format === "xlsx" ? "Downloaded the whole file" : p.complete ? "Read the whole file" : `Read the first ${size(p.bytes_read)}`;
  const inside = p.member ? `${p.member.path} inside the zip (one of ${p.member.files} files), not downloaded. ` : "";
  return inside + where + covered + above;
}

function runs(columns: PreviewColumn[]): { group: string; count: number }[] {
  const out: { group: string; count: number }[] = [];
  for (const c of columns.slice(1)) {
    const group = c.group ?? "not in the sample table";
    if (out.at(-1)?.group === group) out[out.length - 1].count++;
    else out.push({ group, count: 1 });
  }
  return out;
}

function SampleLine({ s }: { s: NonNullable<FilePreview["samples"]> }) {
  const levels = Object.entries(s.levels);
  if (s.by === null) {
    return (
      <p className="text-muted-foreground">
        {s.keys?.length
          ? `Columns are not the dataset's samples: none matches the sample table's ${s.keys.join(" or ")}${s.looks_like ? `; they look like ${s.looks_like} accessions` : ""}.`
          : "The sample table has no accession or title column to match these columns against."}
      </p>
    );
  }
  return (
    <p className="text-muted-foreground">
      <span className="font-mono tabular">{s.matched.toLocaleString()} of {s.of.toLocaleString()}</span> columns are in the sample table, by {s.by}
      {s.factor && <>; grouped by {s.factor}: {levels.slice(0, LEVELS_SHOWN).map(([name, n]) => `${name} (${n.toLocaleString()})`).join("; ")}{levels.length > LEVELS_SHOWN && `; ${levels.length - LEVELS_SHOWN} more`}</>}
    </p>
  );
}

function Summary({ p }: { p: FilePreview }) {
  const rows = p.complete ? (p.rows.length === p.total_rows ? `All ${p.total_rows.toLocaleString()} rows` : `First ${p.rows.length} of ${p.total_rows?.toLocaleString()} rows`) : `First ${p.rows.length.toLocaleString()} rows of an unknown total`;
  const columns = p.columns.length < p.column_count ? `first ${p.columns.length.toLocaleString()} of ${p.column_count.toLocaleString()} columns` : `${p.column_count.toLocaleString()} columns`;
  return (
    <div className="grid gap-1 text-[12.5px]">
      <p className="font-mono tabular">{[rows, columns, p.format + (p.sheet ? ` · sheet ${p.sheet}` : "")].join(" · ")}</p>
      <p className="text-muted-foreground">{source(p)}.</p>
      {p.samples && <SampleLine s={p.samples} />}
    </div>
  );
}

function GroupStrip({ p }: { p: FilePreview }) {
  const list = runs(p.columns);
  if (!p.samples?.factor || list.length < 2) return null;
  if (list.length > MAX_RUNS) return <p className="text-[12.5px] text-muted-foreground">The groups alternate in <span className="font-mono tabular">{list.length.toLocaleString()}</span> runs along the columns.</p>;
  return (
    <div role="img" aria-label={`Groups along the columns: ${list.map((r) => `${r.group} ${r.count}`).join(", ")}`} className="flex h-7 overflow-hidden rounded-md border border-rule text-[11px] text-muted-foreground">
      {list.map((r, i) => (
        <span key={i} title={`${r.group}: ${r.count.toLocaleString()} ${r.count === 1 ? "column" : "columns"}`} style={{ flex: `${r.count} 1 0`, minWidth: 3 }} className={cn("truncate px-1.5 leading-[26px]", i > 0 && "border-l border-rule")}>
          {r.group}
        </span>
      ))}
    </div>
  );
}

function PreviewTable({ p }: { p: FilePreview }) {
  const grouped = p.samples?.factor ? p.columns.some((c) => c.group) : false;
  const sticky = "sticky left-0 bg-card max-sm:max-w-[7.5rem]";
  return (
    <div className="max-w-full overflow-x-auto rounded-lg border border-rule bg-card">
      <table className="w-max min-w-full border-collapse text-[12.5px]">
        <thead>
          <tr className="border-b border-rule align-top">
            {p.columns.map((c, n) => (
              <th key={n} title={`${c.name || "row name"}: ${detail(c, p.rows_read)}`} className={cn("max-w-64 px-3 py-2 text-left font-normal", NUMERIC.has(c.type) && "text-right", n === 0 && sticky)}>
                <span className="block truncate">{c.name || <span className="text-muted-foreground">row name</span>}</span>
                <span className="block whitespace-nowrap font-mono text-[11px] tabular text-muted-foreground">{detail(c, p.rows_read)}</span>
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
      <GroupStrip p={state.p} />
      <PreviewTable p={state.p} />
    </div>
  );
}
