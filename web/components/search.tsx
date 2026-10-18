"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { flushSync } from "react-dom";
import { ArrowUp, Check, LoaderCircle } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import NumberFlow from "@number-flow/react";
import { cn } from "@/lib/utils";
import { motionTier } from "@/lib/springs";
import { LAST_SEARCH, cite, datasetPath, looksLikeCitation, looksLikeIdentifier, rememberFound, resolve, search, watches, type Cited, type Plan, type Result, type Watch } from "@/lib/api";
import { LINK, MUTED_LINK } from "@/components/page-kit";
import { MicButton, useDictation } from "@/components/dictation";
import { SCROLL } from "@/components/result-card";
import { Results } from "@/components/results";
import { Reticle, Wordmark } from "@/components/logo";

const SHOWN = { opacity: 1, scale: 1, filter: "blur(0px)" };
const HIDDEN = { opacity: 0, scale: 0.9, filter: "blur(4px)" };
const iconSwap = motionTier.micro;
const LAST = LAST_SEARCH;

const STEPS = [
  { key: "plan", label: "Understanding the question" },
  { key: "candidates", label: "Searching 18 repositories" },
  { key: "facts", label: "Reading sample records" },
  { key: "done", label: "Grading each dataset" },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

const STEP_COUNT: Partial<Record<StepKey, string>> = { facts: "datasets read" };

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
          {plan.method_notes.slice(0, 2).map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
    </div>
  );
}

export function Search() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [looking, setLooking] = useState(false);
  const [miss, setMiss] = useState<string | null>(null);
  const voice = useDictation(q, setQ);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [reached, setReached] = useState<StepKey[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [result, setResult] = useState<Result | null>(null);
  const [cited, setCited] = useState<{ question: string; paper: Cited } | null>(null);
  const [watched, setWatched] = useState<Watch[]>([]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setWatched(watches()), []);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const field = useRef<HTMLTextAreaElement>(null);
  const current = useRef<AbortController | null>(null);

  // A search is kept for the tab's session, so coming back from a dataset page lands on the same results and row.
  useLayoutEffect(() => {
    const asked = new URLSearchParams(location.search).get("q")?.trim();
    const saved = sessionStorage.getItem(LAST);
    const last: Result | null = saved ? JSON.parse(saved) : null;
    if (asked && asked !== last?.question) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setQ(asked);
      open(asked, true);
      return;
    }
    if (!last) return;
    setQ(last.question);
    setPlan(last.plan);
    setResult(last);
    if (!asked) history.replaceState(null, "", `/?q=${encodeURIComponent(last.question)}`);
    const y = Number(sessionStorage.getItem(SCROLL));
    sessionStorage.removeItem(SCROLL);
    if (y) requestAnimationFrame(() => window.scrollTo(0, y));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Grow the field so the whole question stays readable after a search.
  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    // An empty field is sized to its example text, which wraps on phones; the web font changes the wrap once loaded.
    const fit = () => {
      if (!q) el.value = el.placeholder;
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight}px`;
      el.value = q;
    };
    fit();
    let live = true;
    document.fonts.ready.then(() => live && fit());
    return () => {
      live = false;
    };
  }, [q]);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [running]);

  // A pasted accession, PMID or DOI opens the page it names; anything else, or an identifier locus lacks, is offered as a search.
  async function open(text: string, fromUrl = false) {
    setMiss(null);
    voice.stop();
    if (!looksLikeIdentifier(text)) return run(text, !fromUrl);
    current.current?.abort();
    setLooking(true);
    try {
      const found = await resolve(text);
      if (!found) return fromUrl ? undefined : run(text);
      if (fromUrl) router.replace(found.path);
      else router.push(found.path);
    } catch (e) {
      setMiss(e instanceof Error ? e.message : String(e));
    } finally {
      setLooking(false);
    }
  }

  async function run(question: string, animate = true) {
    if (!question.trim()) return;
    setMiss(null);
    history.replaceState(null, "", `/?q=${encodeURIComponent(question.trim())}`);
    // A new search replaces the one in flight, so a stalled stream can never lock the page.
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    if (looksLikeCitation(question)) cite(question, controller.signal).then((paper) => paper && setCited({ question, paper }), () => {});
    const reset = () => {
      setQ(question);
      setPlan(null); setResult(null); setError(null); setReached([]); setCounts({}); setSeconds(0);
      setRunning(true);
    };
    // The bar glides from the centre to the top instead of jumping.
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (document.startViewTransition && animate && !still) document.startViewTransition(() => flushSync(reset));
    else reset();
    try {
      await search(question, (s) => {
        if (controller.signal.aborted) return;
        if (s.stage === "error") return setError(s.data);
        setReached((r) => [...r, s.stage]);
        if (s.stage === "plan") setPlan(s.data);
        if (s.stage === "facts") setCounts((c) => ({ ...c, facts: s.data.count }));
        if (s.stage === "done") {
          setResult(s.data);
          rememberFound(s.data);
          try {
            sessionStorage.setItem(LAST, JSON.stringify(s.data));
          } catch {}
        }
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
      <form onSubmit={(e) => { e.preventDefault(); open(q); }} className="relative [view-transition-name:search-bar]">
        <textarea
          ref={field}
          rows={1}
          value={q}
          onChange={(e) => { setQ(e.target.value); setMiss(null); }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); open(q); }
          }}
          aria-label="Describe your research"
          placeholder="Lung fibrosis in humans, single-cell and proteomics, patients and controls"
          className={cn("block min-h-14 w-full resize-none overflow-hidden rounded-lg border border-rule bg-card py-[15px] pl-5 text-[15px] leading-relaxed text-foreground placeholder:text-muted-foreground outline-none transition-colors duration-150 focus:border-foreground", "pr-24")}
        />
        <MicButton listening={voice.listening} blocked={voice.blocked} onClick={voice.toggle} />
        <button
          type="submit"
          disabled={!q.trim()}
          aria-label="Search"
          className="absolute bottom-2 right-2 grid size-10 place-items-center rounded-md bg-foreground text-background transition-[transform,opacity,background-color] duration-150 hover:bg-foreground/85 active:scale-[0.96] disabled:opacity-25"
        >
          <span className="grid">
            <motion.span className="col-start-1 row-start-1 flex" initial={false} animate={running || looking ? HIDDEN : SHOWN} transition={iconSwap}>
              <ArrowUp className="size-4" strokeWidth={2} />
            </motion.span>
            <motion.span className="col-start-1 row-start-1 flex" initial={false} animate={running || looking ? SHOWN : HIDDEN} transition={iconSwap}>
              <LoaderCircle className="size-4 animate-spin [animation-duration:.65s]" strokeWidth={2} />
            </motion.span>
          </span>
        </button>
      </form>

      {idle && !voice.listening && !voice.problem && (
        <p className="text-center text-[13px] text-muted-foreground">
          Or paste a GSE, PXD, SRR, PMID or DOI to open its page, or{" "}
          <Link href="/list" className={MUTED_LINK}>check your own gene or protein list</Link>.
        </p>
      )}
      {idle && watched.length > 0 && (
        <ul className="grid justify-items-center gap-1 text-[13px]">
          {watched.slice(0, 3).map((w) => (
            <li key={w.question}>
              <span className="text-muted-foreground">Watching since {w.since}: </span>
              <a href={`/?q=${encodeURIComponent(w.question)}`} className={LINK}>{w.question}</a>
            </li>
          ))}
        </ul>
      )}

      {(voice.listening || voice.problem) && (
        <p className="text-sm text-muted-foreground" role="status">
          {voice.listening ? "Listening. Speak your question, then select the microphone to stop." : voice.problem}
        </p>
      )}
      {miss && (
        <p className="flex flex-wrap items-baseline gap-x-3 text-sm" role="status">
          {miss}
          <button type="button" onClick={() => run(q)} className={LINK}>Search for “{q.trim()}” instead</button>
        </p>
      )}
      {plan && <PlanChips plan={plan} />}
      <AnimatePresence>{running && <Progress key="progress" reached={reached} counts={counts} seconds={seconds} />}</AnimatePresence>
      {error && <p className="rounded-lg border border-foreground/30 bg-card p-4 text-sm text-foreground">{error}</p>}

      {cited?.question === q && <CitedPaper paper={cited.paper} />}
      {result && <Results result={result} />}
    </div>
  );
}

// A chromosome ideogram that passes a signal along like a Newton's cradle. Orange marks one locus. When it fires,
// a knock travels band to band toward the next locus: each band jolts, stretches, and snaps back in turn. The
// band at the end takes the hit and the orange wipes into it from the side the knock arrived on.
const BANDS = [3, 8, 2, 14, 5, 2, 9, 3, 20, 4, 6, 2, 11, 3, 7, 2, 16, 4, 3, 10, 2, 6, 13, 3, 5, 2, 8, 18, 3, 4, 7, 2, 12, 5, 3, 9];
const LOCI = [27, 8, 21, 33, 14, 3];
const RIPPLE = 45;
const HOLD = 1700;
const SNAP = "cubic-bezier(0.22, 1, 0.36, 1)";
const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));
const visible = () => new Promise<void>((r) => {
  if (!document.hidden) return r();
  document.addEventListener("visibilitychange", () => r(), { once: true });
});

function Bands() {
  const bands = useRef<(HTMLSpanElement | null)[]>([]);
  const inks = useRef<(HTMLSpanElement | null)[]>([]);
  const lights = useRef<(HTMLSpanElement | null)[]>([]);
  const still = useReducedMotion();

  useEffect(() => {
    if (still) return;
    let stopped = false;
    const running: Animation[] = [];
    const play = (el: HTMLElement | null, frames: Keyframe[], timing: KeyframeAnimationOptions) => {
      const a = el?.animate(frames, { fill: "both", ...timing });
      if (a) running.push(a);
    };
    (async () => {
      await pause(700);
      for (let n = 0; !stopped; n++) {
        await visible();
        running.splice(0).forEach((a) => a.cancel());
        const from = LOCI[n % LOCI.length];
        const to = LOCI[(n + 1) % LOCI.length];
        const dir = Math.sign(to - from);
        const near = dir > 0 ? "left" : "right";
        // Finished animations are cancelled, so the resting orange is written down explicitly.
        lights.current.forEach((el, i) => el && (el.style.clipPath = i === from ? "inset(0 0 0 0)" : "inset(0 100% 0 0)"));

        // The source kicks and cools.
        play(bands.current[from], [{ transform: "none" }, { transform: `translateX(${dir * 3}px) scaleX(1.35)`, offset: 0.3 }, { transform: "none" }], { duration: 420, easing: SNAP });
        play(lights.current[from], [{ clipPath: "inset(0 0 0 0)" }, { clipPath: `inset(0 ${dir > 0 ? "0 0 100%" : "100% 0 0"})` }], { duration: 320, delay: 60, easing: "cubic-bezier(0.4, 0, 1, 1)" });

        // The knock travels: each band jolts toward the target, stretches, darkens, and snaps back.
        for (let k = from + dir; k !== to; k += dir) {
          const delay = Math.abs(k - from) * RIPPLE;
          play(bands.current[k], [{ transform: "none" }, { transform: `translateX(${dir * 2.5}px) scaleX(1.18)`, offset: 0.3 }, { transform: "none" }], { duration: 340, delay, easing: SNAP });
          play(inks.current[k], [{ opacity: 0 }, { opacity: 1, offset: 0.3 }, { opacity: 0 }], { duration: 380, delay, easing: "ease-out" });
        }

        // The target takes the hit; the orange wipes in from the side the knock arrived on.
        const arrive = Math.abs(to - from) * RIPPLE;
        play(bands.current[to], [{ transform: "none" }, { transform: `translateX(${dir * 3}px) scaleX(1.4) scaleY(1.35)`, offset: 0.25 }, { transform: "none" }], { duration: 560, delay: arrive, easing: SNAP });
        play(lights.current[to], [{ clipPath: `inset(0 ${near === "left" ? "100% 0 0" : "0 0 100%"})` }, { clipPath: "inset(0 0 0 0)" }], { duration: 260, delay: arrive, easing: SNAP });

        await pause(arrive + HOLD);
      }
    })();
    return () => {
      stopped = true;
      running.forEach((a) => a.cancel());
    };
  }, [still]);

  return (
    <motion.div
      aria-hidden
      initial={still ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ ...motionTier.entrance, delay: 0.15 }}
      className="mt-3 flex h-2 w-full max-w-xl gap-[2px]"
    >
      {BANDS.map((w, i) => (
        <span key={i} ref={(el) => { bands.current[i] = el; }} style={{ flex: w }} className="relative rounded-[1px] bg-foreground/12 will-change-transform">
          <span ref={(el) => { inks.current[i] = el; }} className="absolute inset-0 rounded-[1px] bg-foreground/25 opacity-0" />
          <span
            ref={(el) => { lights.current[i] = el; }}
            className="absolute inset-0 rounded-[1px] bg-signal"
            style={{ clipPath: i === LOCI[0] ? "inset(0 0 0 0)" : "inset(0 100% 0 0)" }}
          />
        </span>
      ))}
    </motion.div>
  );
}

// A query that reads like a citation names a paper; its locus datasets come first, while the search runs below.
function CitedPaper({ paper }: { paper: Cited }) {
  const first = paper.authors.split(", ")[0];
  return (
    <section className="grid gap-2 border-l-2 border-signal pl-4">
      <p className="label text-muted-foreground">The paper you named</p>
      <Link href={paper.path} className={cn("w-fit text-[15px] leading-snug", LINK)}>{paper.title}</Link>
      <p className="text-[12.5px] text-muted-foreground">{first}{paper.authors.includes(",") && " et al."} · <span className="italic">{paper.journal}</span> {paper.year}</p>
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[13px]">
        {paper.datasets.length ? (
          <>
            <span className="text-muted-foreground">Its datasets in locus</span>
            {paper.datasets.map((d) => (
              <Link key={d.accession} href={datasetPath(d.accession)} className={cn("font-mono text-[12.5px]", LINK)} title={d.title}>{d.accession}</Link>
            ))}
            {paper.dataset_count > paper.datasets.length && <Link href={paper.path} className={MUTED_LINK}>+{paper.dataset_count - paper.datasets.length} more</Link>}
          </>
        ) : (
          <span className="text-muted-foreground">No locus dataset cites it.</span>
        )}
      </p>
    </section>
  );
}
