"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { Download, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { LINK, MUTED_LINK } from "@/components/page-kit";
import { ROLE_TEXT, roleOf, type Selection } from "@/components/design";
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

// A value of a charted factor filters the samples to it, as its bar does; cases and controls keep their colour.
function Valued({ role, value, onFilter }: { role?: "case" | "control"; value: string; onFilter?: () => void }) {
  const text = role ? <span className={cn("font-medium", ROLE_TEXT[role])} title={`${role}: ${value}`}>{value}</span> : value;
  return onFilter ? (
    <button type="button" onClick={onFilter} title={`Keep only samples with ${value}`} className="cursor-pointer underline decoration-transparent underline-offset-4 transition-colors duration-150 hover:decoration-current">{text}</button>
  ) : text;
}

export function SampleTable({ dataset, samples, selection }: { dataset: string; samples: NonNullable<DatasetRecord["samples"]>; selection: Selection }) {
  const [all, setAll] = useState(false);
  const { active, rows, pending, error } = selection;
  const columns = useMemo(() => samples.columns.map((c, i) => [c, i] as const).filter(([, i]) => samples.rows.some((r) => r[i])), [samples]);
  const factorOf = new Map((selection.design?.factors ?? []).map((f) => [f.column, f]));
  const filterOf = (column: string, value: string) => {
    const f = factorOf.get(column);
    return f && value in f.levels && !selection.filters[f.name]?.includes(value) ? () => selection.toggle(f.name, value) : undefined;
  };
  const shown = rows.slice(0, all || active ? ROWS_MAX : ROWS_SHOWN);
  return (
    <div className="grid gap-3">
      <input
        type="search"
        value={selection.text}
        onChange={(e) => selection.setText(e.target.value)}
        placeholder="Filter samples"
        aria-label="Filter samples"
        className="h-9 w-full max-w-64 rounded-md border border-rule bg-card px-3 text-[16px] outline-none transition-colors duration-150 placeholder:text-muted-foreground focus:border-foreground sm:text-[13px]"
      />
      <div aria-busy={pending} className={cn("overflow-x-auto rounded-lg border border-rule bg-card transition-opacity duration-150 motion-reduce:transition-none", (pending || error) && "opacity-60")}>
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
                      r[i] ? <Valued role={roleOf(selection.design?.comparison, c, r[i])} value={r[i]} onFilter={filterOf(c, r[i])} /> : <span className="text-muted-foreground">–</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {active && !pending && !error && rows.length === 0 && (
        <p className="flex flex-wrap items-baseline gap-x-3 text-[13px]">
          No sample has all of these.
          <button type="button" onClick={selection.clear} className={LINK}>Clear filters</button>
        </p>
      )}
      {!active && rows.length > ROWS_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[13px]", MUTED_LINK)}>
          {all ? "Show fewer" : `Show all ${rows.length.toLocaleString()}`}
        </button>
      )}
      {shown.length === ROWS_MAX && rows.length > ROWS_MAX && (
        <p className="text-xs text-muted-foreground">
          The first {ROWS_MAX.toLocaleString()} of {rows.length.toLocaleString()} rows are shown; the sample sheet{active ? " and the commands hold" : " holds"} all {rows.length.toLocaleString()}{active ? "" : ", or filter to find the others"}.
        </p>
      )}
    </div>
  );
}

// What is selected and what it can be taken as, kept in view while the charts are used.
export function SelectionBar({ rec, selection }: { rec: DatasetRecord; selection: Selection }) {
  const samples = rec.samples!;
  const { active, result, rows, pending, error, filters, design } = selection;
  const unit = rec.source === "ENA" ? "runs" : "samples";
  const chosen = Object.entries(filters).flatMap(([factor, levels]) => levels.map((level) => [factor, level] as const));
  const none = active && !!result && rows.length === 0;
  const total = (result?.total ?? design?.samples ?? samples.rows.length).toLocaleString();
  const focusAfterRemoving = (at: number) => {
    const chips = [...document.querySelectorAll<HTMLElement>("[data-chip]")];
    (chips[at + 1] ?? chips[at - 1] ?? document.querySelector<HTMLElement>("figure button[aria-pressed]"))?.focus();
  };
  const toCommands = () => {
    const commands = document.getElementById("download-commands") as HTMLDetailsElement | null;
    if (commands) commands.open = true;
    commands?.scrollIntoView({ block: "center" });
    commands?.querySelector("summary")?.focus();
  };
  const narrowed = !!result?.downloads?.commands;
  const stale = pending || error;
  return (
    <div className="sticky top-0 z-10 -mx-1 grid gap-1.5 border-b border-rule bg-background px-1 py-2 text-[13px]">
      <div className="flex items-center gap-x-3 whitespace-nowrap">
        {error ? (
          <span className="flex items-baseline gap-x-2">
            The filter did not load.
            <button type="button" onClick={selection.retry} className={LINK}>Try again</button>
          </span>
        ) : (
          <span className={cn("font-mono text-[12px] tabular text-muted-foreground transition-opacity duration-150 motion-reduce:transition-none", pending && "opacity-60")} aria-live="polite">
            {result ? `${result.samples.toLocaleString()} of ${total} ${unit}` : `${total} ${unit}`}
          </span>
        )}
        {active && (
          <button type="button" className={MUTED_LINK} onClick={() => {
            document.querySelector<HTMLElement>("figure button[aria-pressed]")?.focus();
            selection.clear();
          }}>Clear</button>
        )}
        <button type="button" disabled={stale || none} onClick={() => saveCsv(`${rec.accession}-samples${active ? "-selected" : ""}.csv`, samples.columns, rows)} className={cn("flex items-center gap-1 disabled:pointer-events-none disabled:opacity-50", MUTED_LINK)}>
          <Download aria-hidden className="size-3" />
          <span className="max-sm:hidden">Sample sheet </span>(CSV)
        </button>
        {rec.download_plan && active && !none && !stale && (
          <button type="button" onClick={toCommands} className={MUTED_LINK} title={narrowed ? undefined : result?.downloads?.note ?? undefined}>
            Commands<span className="max-sm:hidden">{narrowed ? ` for these ${result!.samples.toLocaleString()}` : " (whole dataset)"}</span>
          </button>
        )}
      </div>
      {chosen.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {chosen.map(([factor, level], at) => (
            <button key={`${factor}\n${level}`} data-chip type="button" aria-label={`Remove ${factor}: ${level}`} className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[4px] border border-foreground px-1.5 py-px"
              onClick={() => {
                focusAfterRemoving(at);
                selection.toggle(factor, level);
              }}>
              <span><span className="text-muted-foreground">{factor}</span> {level}</span>
              <X aria-hidden className="size-3 shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
