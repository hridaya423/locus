"use client";
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { design, subset, type DatasetRecord, type Design, type Filters, type Subset } from "@/lib/api";
import { MUTED_LINK } from "@/components/page-kit";

const LEVELS_SHOWN = 6;
const FACTORS_SHOWN = 6;

// The experiment inside one dataset: which factors vary across samples, how many samples each level has, and
// whether the two main factors are crossed, so a reader sees which comparisons the data can support.
function useDesign(accession: string, source: string, enabled = true) {
  const [state, setState] = useState<{ design?: Design | null; failed?: boolean }>({});
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    design(accession, source).then((d) => live && setState({ design: d }), () => live && setState({ failed: true }));
    return () => {
      live = false;
    };
  }, [accession, source, enabled]);
  return state;
}

// The samples of a dataset page that the chosen factor levels and the text keep. The server does the filtering, so
// the page, the download commands and the MCP tool agree; the previous answer stays on screen while a new one loads.
export function useSelection(rec: DatasetRecord, designed: boolean) {
  const state = useDesign(rec.accession, rec.source, designed);
  const [filters, setFilters] = useState<Filters>({});
  const [text, setText] = useState("");
  const [fetched, setFetched] = useState<{ key: string; data?: Subset } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const active = text.trim() !== "" || Object.keys(filters).length > 0;
  const key = JSON.stringify([filters, text.trim()]);
  useEffect(() => {
    if (!active) return;
    const ctrl = new AbortController();
    const timer = setTimeout(
      () => subset(rec.accession, filters, text.trim(), ctrl.signal).then((data) => setFetched({ key, data }), () => !ctrl.signal.aborted && setFetched({ key })),
      text.trim() ? 200 : 0,
    );
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [rec.accession, filters, text, key, active, attempt]);
  const toggle = (factor: string, level: string) =>
    setFilters((now) => {
      const { [factor]: chosen = [], ...others } = now;
      const next = chosen.includes(level) ? chosen.filter((l) => l !== level) : [...chosen, level];
      return next.length ? { ...others, [factor]: next } : others;
    });
  return {
    design: state.design, failed: state.failed, filters, text, active, toggle, setText,
    clear: () => {
      setFilters({});
      setText("");
      setFetched(null);
    },
    retry: () => setAttempt((n) => n + 1),
    result: active ? fetched?.data ?? null : null,
    pending: active && fetched?.key !== key,
    error: active && fetched?.key === key && !fetched.data,
  };
}
export type Selection = ReturnType<typeof useSelection>;

// The same design, compact, inside an opened result row.
export function DesignView({ accession, source }: { accession: string; source: string }) {
  const state = useDesign(accession, source);
  const [all, setAll] = useState(false);
  if (state.failed || state.design === null) return null;
  if (!state.design) return <p className="label text-muted-foreground">Reading the sample table…</p>;
  const d = state.design;
  const shared = Object.entries(d.shared);
  return (
    <section className="grid gap-2">
      <p className="label flex flex-wrap gap-x-2 text-muted-foreground">
        <span className="text-foreground">Design</span>
        <span>{d.samples} samples</span>
        <span>from {d.source}</span>
      </p>
      {d.factors.length > 0 ? (
        <dl className="grid grid-cols-[minmax(5rem,9rem)_1fr] gap-x-3 gap-y-1.5 text-[13px]">
          {(all ? d.factors : d.factors.slice(0, FACTORS_SHOWN)).map((f) => {
            const levels = Object.entries(f.levels);
            return (
              <div key={f.name} className="contents">
                <dt className="truncate pt-0.5 text-muted-foreground" title={f.aliases ? `${f.name}, also recorded as ${f.aliases.join(", ")}` : f.name}>{f.name}</dt>
                <dd className="flex flex-wrap gap-1">
                  {levels.slice(0, LEVELS_SHOWN).map(([level, n]) => (
                    <span key={level} className="flex items-baseline gap-1.5 rounded-[4px] border border-rule px-1.5 py-px">
                      <span className="max-w-48 truncate" title={level}>{level}</span>
                      <span className="font-mono text-[11px] tabular text-muted-foreground">{n}</span>
                    </span>
                  ))}
                  {levels.length > LEVELS_SHOWN && <span className="px-1 py-px text-muted-foreground">+{levels.length - LEVELS_SHOWN} more</span>}
                </dd>
              </div>
            );
          })}
          {d.factors.length > FACTORS_SHOWN && (
            <button type="button" onClick={() => setAll((v) => !v)} className="col-start-2 w-fit text-[12.5px] text-muted-foreground underline decoration-rule underline-offset-4 hover:text-foreground">
              {all ? "Fewer factors" : `All ${d.factors.length} factors`}
            </button>
          )}
        </dl>
      ) : (
        <p className="text-[13px] text-muted-foreground">Every sample has the same recorded values; the table does not say how samples differ.</p>
      )}
      {d.crossed && <Crossed crossed={d.crossed} />}
      {shared.length > 0 && (
        <p className="text-[12.5px] text-muted-foreground">
          All samples: {shared.slice(0, 4).map(([k, v]) => `${k} ${v}`).join(" · ")}
        </p>
      )}
    </section>
  );
}

export function DesignBars({ rec, selection }: { rec: DatasetRecord; selection: Selection }) {
  const [all, setAll] = useState(false);
  const { design: d, failed, filters, result } = selection;

  if (failed || d === null) return null;
  if (!d) return <p className="text-[13px] text-muted-foreground">Reading the sample table…</p>;
  const shared = Object.entries(d.shared);
  const columns = rec.samples?.columns ?? [];
  const chosen = Object.entries(filters).flatMap(([factor, levels]) => levels.map((level) => [factor, level] as const));
  return (
    <div className="grid gap-6">
      {chosen.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
          {chosen.map(([factor, level]) => (
            <button key={`${factor}\n${level}`} type="button" onClick={() => selection.toggle(factor, level)} aria-label={`Remove ${factor}: ${level}`} className="flex max-w-full items-center gap-1.5 rounded-[4px] border border-foreground px-1.5 py-px text-[13px]">
              <span className="truncate"><span className="text-muted-foreground">{factor}</span> {level}</span>
              <X aria-hidden className="size-3 shrink-0" />
            </button>
          ))}
          <button type="button" onClick={selection.clear} className={cn("text-[13px]", MUTED_LINK)}>Clear</button>
        </div>
      )}
      {d.factors.length > 0 ? (
        <div className="grid gap-x-10 gap-y-6 sm:grid-cols-2">
          {(all ? d.factors : d.factors.slice(0, FACTORS_SHOWN)).map((f) => (
            <Factor key={f.name} factor={f} counts={result?.counts[f.name]} chosen={filters[f.name]} selectable={columns.includes(f.column)} onToggle={(level) => selection.toggle(f.name, level)} />
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-muted-foreground">Every sample has the same recorded values; the table does not say how samples differ.</p>
      )}
      {d.factors.length > FACTORS_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className="w-fit text-[13px] text-muted-foreground underline decoration-rule underline-offset-4 hover:text-foreground hover:decoration-foreground">
          {all ? "Fewer factors" : `All ${d.factors.length} factors`}
        </button>
      )}
      {d.crossed && <Crossed crossed={d.crossed} counts={result?.crossed} />}
      {shared.length > 0 && (
        <dl className="flex flex-wrap gap-x-5 gap-y-1 text-[13px]">
          <dt className="sr-only">Every sample</dt>
          {shared.map(([k, v]) => (
            <dd key={k}><span className="text-muted-foreground">{k}</span> {v}</dd>
          ))}
        </dl>
      )}
      <p className="label text-muted-foreground">Read from {d.source}</p>
    </div>
  );
}

type FactorProps = {
  factor: Design["factors"][number]; counts?: Record<string, number>; chosen?: string[]; selectable: boolean; onToggle: (level: string) => void;
};

function Factor({ factor, counts, chosen = [], selectable, onToggle }: FactorProps) {
  const [open, setOpen] = useState(false);
  const levels = Object.entries(factor.levels);
  const most = Math.max(...levels.map(([, n]) => n));
  const shown = levels.filter(([level], i) => open || i < LEVELS_SHOWN || chosen.includes(level));
  return (
    <figure className="grid content-start gap-2">
      <figcaption className="truncate text-[13px] font-medium" title={factor.aliases ? `${factor.name}, also recorded as ${factor.aliases.join(", ")}` : factor.name}>
        {factor.name}
      </figcaption>
      <ul className="grid gap-0.5">
        {shown.map(([level, total]) => {
          const n = counts?.[level] ?? total;
          const on = chosen.includes(level);
          const row = (
            <>
              <span className={cn("truncate", on && "font-medium", n === 0 && "text-muted-foreground")} title={level}>{level}</span>
              <span className="text-right font-mono text-[12px] tabular text-muted-foreground">{n.toLocaleString()}</span>
              <span aria-hidden className="col-span-2 h-1">
                <span className="block h-full rounded-full bg-rule" style={{ width: `${(total / most) * 100}%` }}>
                  <span className={cn("block h-full rounded-full transition-[width] duration-200 motion-reduce:transition-none", chosen.length && !on ? "bg-foreground/35" : "bg-foreground/75")} style={{ width: `${(n / total) * 100}%` }} />
                </span>
              </span>
            </>
          );
          const grid = "grid w-full grid-cols-[minmax(0,1fr)_2.5rem] items-center gap-x-3 gap-y-0.5 rounded-[4px] border px-1.5 py-1 text-left text-[13px]";
          return (
            <li key={level}>
              {selectable ? (
                <button type="button" aria-pressed={on} onClick={() => onToggle(level)} className={cn(grid, on ? "border-foreground" : "border-transparent hover:border-rule")}>
                  {row}
                </button>
              ) : (
                <div className={cn(grid, "border-transparent")}>{row}</div>
              )}
            </li>
          );
        })}
      </ul>
      {levels.length > LEVELS_SHOWN && (
        <button type="button" onClick={() => setOpen((v) => !v)} className={cn("w-fit text-[12.5px]", MUTED_LINK)}>
          {open ? "Fewer levels" : `+${levels.length - shown.length} more`}
        </button>
      )}
    </figure>
  );
}

// Counts for every combination of the two main factors; an empty combination means that comparison has no samples.
function Crossed({ crossed, counts = crossed.counts }: { crossed: NonNullable<Design["crossed"]>; counts?: [string, string, number][] }) {
  const rows = [...new Set(crossed.counts.map(([r]) => r))];
  const columns = [...new Set(crossed.counts.map(([, c]) => c))];
  if (rows.length > 6 || columns.length > 6) return null;
  const count = (r: string, c: string) => counts.find(([x, y]) => x === r && y === c)?.[2] ?? 0;
  return (
    <div className="grid gap-2 overflow-x-auto">
      <p className="text-[13px] font-medium">{crossed.rows} by {crossed.columns}</p>
      <table className="w-fit border-collapse font-mono text-[12px] tabular">
        <thead>
          <tr>
            <th />
            {columns.map((c) => <th key={c} className="max-w-32 truncate px-3 pb-1 text-right font-sans text-[12.5px] font-normal text-muted-foreground" title={c}>{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r} className="border-t border-rule">
              <td className="max-w-48 truncate py-1 pr-4 font-sans text-[13px]" title={r}>{r}</td>
              {columns.map((c) => {
                const n = count(r, c);
                return <td key={c} className={cn("px-3 text-right", n === 0 ? "text-muted-foreground" : "text-foreground")}>{n || "–"}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
