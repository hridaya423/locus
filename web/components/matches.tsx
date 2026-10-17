"use client";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";
import { found, why, type Found, type Hit, type Spot, type Why } from "@/lib/api";

const noSubscription = () => () => {};

// What the search found, read after hydration so the server and the first client render agree.
export function useFound(accession: string): Found | null {
  const known = useSyncExternalStore(noSubscription, () => found(accession) !== null, () => false);
  return useMemo(() => (known ? found(accession) : null), [known, accession]);
}

type Check = keyof Hit["checks"];
export type Group = { check: Check; label: string; terms: string[] };

const PASSED: [Check, string, string][] = [
  ["topic", "Topic", "same"],
  ["patient_material", "Patient material", "yes"],
  ["data_type", "Data type", "yes"],
  ["controls", "Controls", "yes"],
];
const WORDS = { patient_material: ["patient", "donor", "biopsy", "volunteer"], controls: ["healthy", "control", "normal", "non-diseased"] };

export const slug = (term: string) => term.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

function groupsOf(f: Found): Group[] {
  const terms: Record<Check, string[]> = { topic: f.terms, data_type: [...f.assays, ...(f.hit.facts?.assays ?? [])], ...WORDS };
  return PASSED.filter(([check, , pass]) => f.hit.checks[check] === pass).map(([check, label]) => ({ check, label, terms: [...new Set(terms[check])] }));
}

export type Matches = { groups: Group[]; quote: string; why: Why | null };

export function useMatches(accession: string): Matches | null {
  const f = useFound(accession);
  const request = useMemo(() => {
    if (!f) return null;
    const groups = groupsOf(f);
    return { groups, terms: [...new Set(groups.flatMap((g) => g.terms))], quote: f.hit.evidence };
  }, [f]);
  const [answer, setAnswer] = useState<{ request: typeof request; why: Why } | null>(null);
  useEffect(() => {
    if (!request) return;
    let live = true;
    why(accession, request.terms, request.quote).then((w) => live && setAnswer({ request, why: w }), () => {});
    return () => {
      live = false;
    };
  }, [accession, request]);
  return request && { groups: request.groups, quote: request.quote, why: answer?.request === request ? answer.why : null };
}

const rank = (s: Spot) => (s.kind === "title" ? 0 : 1 + s.index) * 1e7 + s.start;

export function firstTerm(m: Matches, group: Group): string | null {
  const onPage = (m.why?.terms ?? []).filter((t) => group.terms.includes(t.term) && t.first && t.first.kind !== "fact");
  return onPage.sort((a, b) => rank(a.first!) - rank(b.first!))[0]?.term ?? null;
}

export const quoteOnPage = (m: Matches) => !!m.why?.quote && m.why.quote.kind !== "fact";

type Span = { start: number; end: number; slugs: string[] };

function marksOf(m: Matches, kind: Spot["kind"], index: number, text: string): { spans: Span[]; quote: [number, number] | null } {
  const astral = /[\ud800-\udfff]/.test(text);
  const unit = (n: number) => (astral ? Array.from(text).slice(0, n).join("").length : n);
  const field = m.why?.fields.find((f) => f.kind === kind && f.index === index);
  const q = m.why?.quote;
  return {
    spans: (field?.matches ?? []).map((s) => ({ start: unit(s.start), end: unit(s.end), slugs: s.terms.map(slug) })),
    quote: q && q.kind === kind && q.index === index ? [unit(q.start), unit(q.end)] : null,
  };
}

export const hasMatch = (m: Matches | null, index: number) =>
  !!m?.why && (m.why.fields.some((f) => f.kind === "text" && f.index === index) || (m.why.quote?.kind === "text" && m.why.quote.index === index));

function Segments({ text, from = 0, to = text.length, marks }: { text: string; from?: number; to?: number; marks: ReturnType<typeof marksOf> }) {
  const { spans, quote } = marks;
  const cuts = [...new Set([from, to, ...spans.flatMap((s) => [s.start, s.end]), ...(quote ?? [])].filter((c) => c >= from && c <= to))].sort((a, b) => a - b);
  return cuts.slice(0, -1).map((a, i) => {
    const b = cuts[i + 1];
    const span = spans.find((s) => s.start <= a && b <= s.end);
    const quoted = !!quote && quote[0] <= a && b <= quote[1];
    if (!span && !quoted) return text.slice(a, b);
    return (
      <mark
        key={a}
        data-match={[...(span?.slugs ?? []), ...(quoted ? ["quote"] : [])].join(" ")}
        className={cn("bg-transparent text-inherit", span && "bg-signal/20", quoted && "underline decoration-signal decoration-2 underline-offset-4")}
      >
        {text.slice(a, b)}
      </mark>
    );
  });
}

// Paragraphs are split at blank lines and trimmed, so the matches' offsets are read in the full text.
export function MarkedText({ text, index, m }: { text: string; index: number; m: Matches | null }) {
  const marks = m?.why ? marksOf(m, "text", index, text) : null;
  return [...text.matchAll(/\S[\s\S]*?(?=\s*(?:\n\s*\n|$))/g)].map((p) => (
    <p key={p.index} className="whitespace-pre-line">
      {marks ? <Segments text={text} from={p.index} to={p.index + p[0].length} marks={marks} /> : p[0]}
    </p>
  ));
}

export function MarkedTitle({ accession, title }: { accession: string; title: string }) {
  const m = useMatches(accession);
  return m?.why ? <Segments text={title} marks={marksOf(m, "title", 0, title)} /> : title;
}

export function goToMatch(match: string) {
  const marks = [...document.querySelectorAll<HTMLElement>(`[data-match~="${slug(match)}"]`)];
  if (!marks.length) return;
  marks[0].closest("details")?.setAttribute("open", "");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  marks[0].scrollIntoView({ block: "center", behavior: still ? "auto" : "smooth" });
  if (!still) for (const el of marks) el.animate([{ backgroundColor: "color-mix(in oklab, var(--signal) 60%, transparent)" }, {}], { duration: 1400, easing: "ease-out" });
}

const CHIP = "flex items-baseline gap-1 rounded-[4px] border border-foreground/70 bg-card px-2 py-[3px] text-xs";

export function MatchedLine({ m }: { m: Matches }) {
  if (!m.why) return null;
  const shown = m.groups.map((g) => ({ ...g, found: m.why!.terms.filter((t) => g.terms.includes(t.term) && t.count > 0) })).filter((g) => g.found.length > 0);
  const onPage = quoteOnPage(m);
  if (!shown.length && !m.why.quote) {
    return (
      <p className="max-w-[68ch] border-l-2 border-foreground/30 pl-3 text-[13px] leading-relaxed text-muted-foreground">
        Matched only in the repository&apos;s search index; none of the search terms appear in this record&apos;s text.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-baseline gap-x-5 gap-y-2 border-l-2 border-signal pl-3 text-[13px]">
      <span className="label text-muted-foreground">Matched for</span>
      {shown.map((g) => (
        <span key={g.check} className="flex flex-wrap items-baseline gap-1.5">
          <span className="text-muted-foreground">{g.label}</span>
          {g.found.map((t) => {
            const body = (
              <>
                <span className="bg-signal/20">{t.term}</span>
                {t.count > 1 && <span className="font-mono text-[11px] tabular text-muted-foreground">×{t.count}</span>}
              </>
            );
            return t.first?.kind === "fact" ? (
              <span key={t.term} title="In the record's details, not its text" className={cn(CHIP, "border-rule")}>{body}</span>
            ) : (
              <button key={t.term} type="button" onClick={() => goToMatch(t.term)} className={cn(CHIP, "cursor-pointer transition-colors duration-150 hover:bg-secondary")}>{body}</button>
            );
          })}
        </span>
      ))}
      {onPage && (
        <span className="flex min-w-0 items-baseline gap-1.5">
          <span className="text-muted-foreground">Evidence</span>
          <button type="button" onClick={() => goToMatch("quote")} className={cn(CHIP, "max-w-[28ch] cursor-pointer transition-colors duration-150 hover:bg-secondary")}>
            <span className="truncate underline decoration-signal decoration-2 underline-offset-4">{m.quote}</span>
          </button>
        </span>
      )}
    </div>
  );
}
