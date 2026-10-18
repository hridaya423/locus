"use client";
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { flushSync } from "react-dom";
import { ArrowUp, Check, LoaderCircle, Mic, Square } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import NumberFlow from "@number-flow/react";
import { cn } from "@/lib/utils";
import { motionTier } from "@/lib/springs";
import { search, type Plan, type Result } from "@/lib/api";
import { Results } from "@/components/results";
import { Reticle, Wordmark } from "@/components/logo";

const SHOWN = { opacity: 1, scale: 1, filter: "blur(0px)" };
const HIDDEN = { opacity: 0, scale: 0.9, filter: "blur(4px)" };
const iconSwap = motionTier.micro;

// The browser's own speech recognition, which lib.dom does not type. Nothing leaves the page through our code.
type Recognition = {
  lang: string; interimResults: boolean; continuous: boolean; start(): void; stop(): void; abort(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null; onerror: ((e: { error: string }) => void) | null;
};
type RecognitionCtor = new () => Recognition;

// Why voice cannot run here, or "" when it can: the API must exist and the page must be a secure context
// (localhost or HTTPS; plain HTTP to another machine's address is not).
function voiceSupport(): { ctor: RecognitionCtor | null; reason: string } {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  const ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
  if (!ctor) return { ctor: null, reason: "This browser has no speech recognition." };
  if (!window.isSecureContext) return { ctor: null, reason: "Voice needs a secure page: open the app on localhost or over HTTPS." };
  return { ctor, reason: "" };
}

const VOICE_ERRORS: Record<string, string> = {
  "not-allowed": "The microphone was not allowed.",
  "audio-capture": "No microphone was found.",
  network: "Speech recognition could not reach its service.",
  "no-speech": "No speech was heard.",
};

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
  // Voice: the reason it is unavailable (read on the client only, so the server render matches), else idle or
  // listening; the transcript is appended to what was typed.
  const voiceReason = useSyncExternalStore(() => () => {}, () => voiceSupport().reason, () => "");
  const [listening, setListening] = useState(false);
  const voice: "idle" | "listening" | "unavailable" = voiceReason ? "unavailable" : listening ? "listening" : "idle";
  const [voiceNote, setVoiceNote] = useState("");
  const recognition = useRef<Recognition | null>(null);
  const spokenBase = useRef("");

  function stopListening() {
    recognition.current?.stop();
  }

  function startListening() {
    const { ctor } = voiceSupport();
    if (!ctor) return;
    const r = new ctor();
    r.lang = navigator.language || "en-GB";
    r.interimResults = true;
    r.continuous = true;
    spokenBase.current = q.trim();
    r.onresult = (e) => {
      const heard = Array.from(e.results, (result) => result[0].transcript).join(" ").replace(/\s+/g, " ").trim();
      setQ([spokenBase.current, heard].filter(Boolean).join(" "));
    };
    r.onerror = (e) => setVoiceNote(VOICE_ERRORS[e.error] ?? `Voice stopped (${e.error}).`);
    r.onend = () => { recognition.current = null; setListening(false); };
    recognition.current = r;
    setVoiceNote("");
    setListening(true);
    r.start();
  }

  useEffect(() => {
    if (voice !== "listening") return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") stopListening(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [voice]);

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
        if (s.stage === "facts") setCounts((c) => ({ ...c, facts: s.data.count }));
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
          className="block min-h-14 w-full resize-none overflow-hidden rounded-lg border border-rule bg-card py-[15px] pl-5 pr-28 text-[15px] leading-relaxed text-foreground placeholder:text-muted-foreground outline-none transition-colors duration-150 focus:border-foreground"
        />
        <span className="absolute bottom-2 right-[52px]" title={voice === "unavailable" ? voiceReason : voice === "listening" ? "Stop listening (Escape)" : "Ask by voice"}>
          <button
            type="button"
            onClick={() => (voice === "listening" ? stopListening() : startListening())}
            disabled={voice === "unavailable"}
            aria-label={voice === "unavailable" ? `Voice unavailable: ${voiceReason}` : voice === "listening" ? "Stop listening" : "Ask by voice"}
            aria-pressed={voice === "listening"}
            data-voice={voice}
            className={cn(
              "relative grid size-10 place-items-center rounded-md border transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground disabled:cursor-not-allowed disabled:opacity-25",
              voice === "listening" ? "border-[#eb6834] text-[#eb6834]" : "border-rule text-muted-foreground hover:border-foreground hover:text-foreground",
            )}
          >
            {voice === "listening" && <span aria-hidden className="absolute inset-0 animate-ping rounded-md border-2 border-[#eb6834] opacity-60" />}
            {voice === "listening" ? <Square className="size-3.5 fill-current" strokeWidth={2} /> : <Mic className="size-4" strokeWidth={2} />}
          </button>
        </span>
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

      {(voice === "listening" || voiceNote) && (
        <p role="status" className="text-[13px] text-muted-foreground">
          {voice === "listening" ? "Listening… the words appear above; press the button again or Escape to stop, then edit and search." : voiceNote}
        </p>
      )}
      {plan && <PlanChips plan={plan} />}
      <AnimatePresence>{running && <Progress key="progress" reached={reached} counts={counts} seconds={seconds} />}</AnimatePresence>
      {error && <p className="rounded-lg border border-foreground/30 bg-card p-4 text-sm text-foreground">{error}</p>}

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
