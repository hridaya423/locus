"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ArrowUp, Check, LoaderCircle } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import NumberFlow from "@number-flow/react";
import { cn } from "@/lib/utils";
import { motionTier } from "@/lib/springs";
import { search, type Plan, type Result } from "@/lib/api";
import { Results } from "@/components/results";
import { Reticle, Wordmark } from "@/components/logo";

const SHOWN = { opacity: 1, scale: 1, filter: "blur(0px)" };
const HIDDEN = { opacity: 0, scale: 0.9, filter: "blur(4px)" };
const iconSwap = motionTier.micro;

const STEPS = [
  { key: "plan", label: "Understanding the question" },
  { key: "candidates", label: "Searching 18 repositories" },
  { key: "facts", label: "Reading sample records" },
  { key: "done", label: "Grading each dataset" },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

const STEP_COUNT: Partial<Record<StepKey, string>> = { candidates: "candidates", facts: "datasets read" };

function Progress({ reached, counts, seconds }: { reached: StepKey[]; counts: Record<string, number>; seconds: number }) {
  const current = STEPS[Math.min(reached.length, STEPS.length - 1)];
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, transition: motionTier.ui.exit }}
      transition={motionTier.ui}
      className="grid gap-4 rounded-lg border border-rule bg-card p-4"
    >
      <ol className="grid gap-2.5" aria-live="polite">
        {STEPS.map((s) => {
          const done = reached.includes(s.key);
          const active = s.key === current.key && !done;
          const count = STEP_COUNT[s.key] && counts[s.key] !== undefined ? counts[s.key] : undefined;
          return (
            <li key={s.key} className={cn("flex items-center gap-3 text-sm transition-colors duration-200", done || active ? "text-foreground" : "text-muted-foreground")}>
              <span className="grid size-4 place-items-center">
                {done ? <Check className="size-3.5" strokeWidth={2.5} /> : active ? <Reticle scanning className="size-4" /> : <span className="size-1.5 rounded-full bg-current opacity-50" />}
              </span>
              <span className="flex-1">{s.label}</span>
              {count !== undefined && (
                <span className="font-mono text-[13px] tabular">
                  <NumberFlow value={count} /> <span className="text-muted-foreground">{STEP_COUNT[s.key]}</span>
                </span>
              )}
            </li>
          );
        })}
      </ol>
      <div className="grid grid-cols-4 gap-1.5">
        {STEPS.map((s) => (
          <div key={s.key} className="relative h-1 overflow-hidden rounded-[1px] bg-muted">
            {reached.includes(s.key) ? (
              <motion.div className="h-full origin-left bg-foreground" initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={motionTier.ui} />
            ) : s.key === current.key ? (
              <div className="animate-sweep h-full w-2/5 bg-foreground/70" />
            ) : null}
          </div>
        ))}
      </div>
      <p className="flex justify-between text-xs text-muted-foreground">
        <span>A search takes about a minute.</span>
        <span className="font-mono tabular"><NumberFlow value={seconds} suffix=" s" /></span>
      </p>
    </motion.div>
  );
}

function PlanChips({ plan }: { plan: Plan }) {
  const filters = [
    ...(plan.organism ? [plan.organism] : []),
    ...plan.assays,
    ...(plan.wants_controls ? ["with controls"] : []),
  ];
  const groups = [
    { caption: "Searched for", items: plan.terms, strong: true },
    { caption: "Filters", items: filters, strong: false },
  ].filter((g) => g.items.length > 0);
  let order = 0;
  return (
    <div className="grid gap-3">
      {groups.map((g) => (
        <div key={g.caption} className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="basis-full shrink-0 text-muted-foreground sm:basis-24">{g.caption}</span>
          {g.items.map((label) => (
            <motion.span
              key={label}
              initial={{ opacity: 0, filter: "blur(4px)" }}
              animate={{ opacity: 1, filter: "blur(0px)" }}
              transition={{ ...motionTier.ui, delay: order++ * 0.03 }}
              className={cn(
                "rounded-[4px] border px-2 py-[3px]",
                g.strong ? "border-foreground/70 bg-card text-foreground" : "border-rule text-muted-foreground",
              )}
            >
              {label}
            </motion.span>
          ))}
        </div>
      ))}
      {plan.method_notes.length > 0 && (
        <ul className="grid gap-1 border-l-2 border-foreground pl-3 text-sm text-muted-foreground">
          {plan.method_notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
    </div>
  );
}

export function Search() {
  const [q, setQ] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [reached, setReached] = useState<StepKey[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const field = useRef<HTMLTextAreaElement>(null);
  const current = useRef<AbortController | null>(null);

  // Grow the field so the whole question stays readable after a search.
  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    // An empty field is sized to its example text, which wraps on phones.
    if (!q) el.value = el.placeholder;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
    el.value = q;
  }, [q]);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [running]);

  async function run(question: string) {
    if (!question.trim()) return;
    // A new search replaces the one in flight, so a stalled stream can never lock the page.
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    const reset = () => {
      setQ(question);
      setPlan(null); setResult(null); setError(null); setReached([]); setCounts({}); setSeconds(0);
      setRunning(true);
    };
    // The bar glides from the centre to the top instead of jumping.
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (document.startViewTransition && !still) document.startViewTransition(() => flushSync(reset));
    else reset();
    try {
      await search(question, (s) => {
        if (controller.signal.aborted) return;
        if (s.stage === "error") return setError(s.data);
        setReached((r) => [...r, s.stage]);
        if (s.stage === "plan") setPlan(s.data);
        if (s.stage === "candidates" || s.stage === "facts") setCounts((c) => ({ ...c, [s.stage]: s.data.count }));
        if (s.stage === "done") setResult(s.data);
      }, controller.signal);
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (current.current === controller) setRunning(false);
    }
  }

  const idle = !running && !result && !error && !plan;

  return (
    <div className={cn("mx-auto w-full max-w-3xl grid grid-cols-1 content-start gap-6", idle && "min-h-[calc(100dvh-10rem)] content-center")}>
      {idle && (
        <div className="grid justify-items-center gap-5 text-center animate-in fade-in slide-in-from-bottom-2 duration-700">
          <Wordmark className="text-[88px] sm:text-[120px]" />
          <h1 className="text-xl sm:text-2xl font-medium">
            Ask in plain English. <span className="text-muted-foreground">Land on the exact dataset.</span>
          </h1>
          <Bands />
        </div>
      )}
      <form onSubmit={(e) => { e.preventDefault(); run(q); }} className="relative [view-transition-name:search-bar]">
        <textarea
          ref={field}
          rows={1}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); run(q); }
          }}
          aria-label="Describe your research"
          placeholder="Lung fibrosis in humans, single-cell and proteomics, patients and controls"
          className="block min-h-14 w-full resize-none overflow-hidden rounded-lg border border-rule bg-card py-[15px] pl-5 pr-16 text-[15px] leading-relaxed text-foreground placeholder:text-muted-foreground outline-none transition-colors duration-150 focus:border-foreground"
        />
        <button
          type="submit"
          disabled={!q.trim()}
          aria-label="Search"
          className="absolute bottom-2 right-2 grid size-10 place-items-center rounded-md bg-foreground text-background transition-[transform,opacity,background-color] duration-150 hover:bg-foreground/85 active:scale-[0.96] disabled:opacity-25"
        >
          <span className="grid">
            <motion.span className="col-start-1 row-start-1 flex" initial={false} animate={running ? HIDDEN : SHOWN} transition={iconSwap}>
              <ArrowUp className="size-4" strokeWidth={2} />
            </motion.span>
            <motion.span className="col-start-1 row-start-1 flex" initial={false} animate={running ? SHOWN : HIDDEN} transition={iconSwap}>
              <LoaderCircle className="size-4 animate-spin [animation-duration:.65s]" strokeWidth={2} />
            </motion.span>
          </span>
        </button>
      </form>

      {plan && <PlanChips plan={plan} />}
      <AnimatePresence>{running && <Progress key="progress" reached={reached} counts={counts} seconds={seconds} />}</AnimatePresence>
      {error && <p className="rounded-lg border border-foreground/30 bg-card p-4 text-sm text-foreground">{error}</p>}

      {result && <Results result={result} />}
    </div>
  );
}

// A chromosome ideogram: one lit band is the dataset the question lands on.
const BANDS = [3, 8, 2, 14, 5, 2, 9, 3, 20, 4, 6, 2, 11, 3, 7, 2, 16, 4, 3, 10, 2, 6, 13, 3, 5, 2, 8, 18, 3, 4, 7, 2, 12, 5, 3, 9];

function Bands() {
  return (
    <div aria-hidden className="mt-3 flex h-2 w-full max-w-xl gap-[2px]">
      {BANDS.map((w, i) => (
        <span key={i} style={{ flex: w }} className={i === 27 ? "rounded-[1px] bg-signal" : "rounded-[1px] bg-foreground/12"} />
      ))}
    </div>
  );
}
