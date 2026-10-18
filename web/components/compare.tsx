"use client";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowDown, ArrowUpRight, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { EASE_OUT, motionTier } from "@/lib/springs";
import { compare, datasetPath, repositoryName, type Comparison, type Facet, type FacetStatus, type Hit, type Profile, type Verdict } from "@/lib/api";
import { ACTION, SEP, draw, shortAccession, tone } from "@/components/result-card";
import { Reticle } from "@/components/logo";

const LANE = -24;
const CORNER = 8;

type Point = { x: number; y: number };

function measure(section: HTMLElement, ids: string[] | null): [Point, Point] | null {
  if (!ids) return null;
  const origin = section.getBoundingClientRect();
  const rows = [...section.querySelectorAll<HTMLElement>("[data-accession]")];
  // A selected dataset inside a closed study has no row of its own; the study row lists its accessions.
  const find = (id: string) => rows.find((r) => r.dataset.accession === id) ?? rows.find((r) => r.dataset.accession?.split(" ").includes(id));
  const points = ids.map(find).map((row) => {
    const box = row?.querySelector("input")?.getBoundingClientRect();
    return row && box ? { row, x: Math.round(box.left - origin.left), y: Math.round(box.top + box.height / 2 - origin.top) } : null;
  });
  const [a, b] = points;
  if (!a || !b || a.row === b.row) return null;
  return a.y <= b.y ? [a, b] : [b, a];
}

const same = (p: [Point, Point] | null, q: [Point, Point] | null) => (p && q ? p.every((a, i) => a.x === q[i].x && a.y === q[i].y) : p === q);

// Two curves leave the checkboxes into the page gutter and meet in one line; the button hangs off it, stuck near the
// middle of the viewport while the rows are far apart. The gutter must fit the button: 768 content + 2 x 144.
export function Connector({ section, accessions, onCompare }: { section: RefObject<HTMLElement | null>; accessions: string[] | null; onCompare: () => void }) {
  const still = useReducedMotion();
  const [points, setPoints] = useState<[Point, Point] | null>(null);
  const latest = useRef(accessions);

  const update = () => {
    const next = section.current ? measure(section.current, latest.current) : null;
    setPoints((prev) => (same(prev, next) ? prev : next));
  };
  useLayoutEffect(() => {
    latest.current = accessions;
    update();
  });
  useEffect(() => {
    const el = section.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      const next = measure(el, latest.current);
      setPoints((prev) => (same(prev, next) ? prev : next));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [section]);

  const [a, b] = points ?? [];
  const mid = a && b ? (a.y + b.y) / 2 : 0;
  const exit = still ? {} : { pathLength: 0, transition: motionTier.ui.exit };
  return (
    <AnimatePresence>
      {a && b && (
        <div key={accessions?.join()} className={cn("hidden min-[1056px]:block", tone(true))}>
          <svg aria-hidden className="pointer-events-none absolute left-0 top-0 size-px overflow-visible">
            {[
              { from: a, d: `A${CORNER} ${CORNER} 0 0 0 ${LANE} ${a.y + CORNER}` },
              { from: b, d: `A${CORNER} ${CORNER} 0 0 1 ${LANE} ${b.y - CORNER}` },
            ].map(({ from, d }) => (
              <motion.path key={from.y} d={`M${from.x - 3} ${from.y} H${LANE + CORNER} ${d} V${mid}`} fill="none" stroke="currentColor" strokeLinecap="round" exit={exit} {...draw(still, 0)} />
            ))}
          </svg>
          <motion.div
            initial={still ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, transition: motionTier.ui.exit }}
            transition={{ ...motionTier.entrance, delay: 0.2 }}
            style={{ top: a.y, height: b.y - a.y, right: `calc(100% + ${-LANE}px)` }}
            className="pointer-events-none absolute flex flex-col justify-center"
          >
            <div className="sticky bottom-[35vh] top-[35vh] flex items-center self-end">
              <button type="button" onClick={onCompare} tabIndex={-1} aria-hidden className="pointer-events-auto h-7 rounded-lg bg-foreground px-3 text-[13px] font-medium text-background transition-transform duration-150 active:scale-[0.97]">
                Compare
              </button>
              <span className="h-px w-3 bg-current" />
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

const HEADLINE: Record<Verdict, string> = { pool: "Can be analysed together", effects: "Compare results, not samples", no: "Not comparable", unclear: "Not enough information" };

type Lane = "joined" | "near" | "apart";
const STRAND: Record<FacetStatus, Lane> = { same: "joined", related: "near", differs: "apart", unknown: "apart" };
const GAP: Record<Lane, number> = { joined: 0, near: 6, apart: 18 };
const DRAW = 0.9;
const GRID = "relative grid grid-cols-[1fr_2.75rem_1fr] sm:grid-cols-[7.5rem_1fr_4rem_1fr]";
const WARN_ONLY = new Set(["sizes", "shared"]);
// One-line labels keep every row a single line tall, so the whole comparison fits on a laptop screen.
const SHORT: Record<string, string> = { layer: "Layer", groups: "Groups", tissue: "Tissue", build: "Genome", access: "Data", sex: "Sex", shared: "Shared", sizes: "Group size" };

// The accession prefix repeats the dataset; the end of a file name (counts, normalised, format) is what tells files apart.
const fileLabel = (url: string, accession: string) => {
  const name = decodeURIComponent(url.split("/").pop() ?? url).replace(new RegExp(`^${accession}_`), "");
  return name.length > 24 ? `…${name.slice(-23)}` : name;
};

type Knot = { x: number; y: number; lane: Lane; facet?: Facet };

function Bars({ hit }: { hit: Hit }) {
  const { case: cases, control } = hit.facts ?? {};
  if (!cases && !control) return null;
  return (
    <span className="mt-1.5 flex h-4 w-36 gap-0.5 font-mono text-[10.5px] font-medium not-italic leading-4 text-background tabular [.text-right_&]:ml-auto" title={`${cases ?? 0} cases, ${control ?? 0} controls`}>
      {/* A minimum width keeps a small group's number readable inside its segment. */}
      {[[cases, "bg-signal"], [control, "bg-control"]].map(([n, tone]) => !!n && (
        <i key={tone as string} className={cn("min-w-6 rounded-[2px] px-1 text-center", tone as string)} style={{ flex: n as number }}>{n}</i>
      ))}
    </span>
  );
}

// Women and men per group, as one split bar per group; the group names carry the case and control colours.
function SexSplit({ split }: { split: NonNullable<Profile["sex_split"]> }) {
  return (
    <span className="grid w-48 gap-1 [.text-right_&]:ml-auto">
      {(["cases", "controls"] as const).map((group) => {
        const { female, male } = split[group];
        return (
          <span key={group} className="grid grid-cols-[4rem_1fr] items-center gap-2" title={`${group}: ${female} women, ${male} men`}>
            <span className={cn("label text-left", group === "cases" ? "text-signal" : "text-control")}>{group}</span>
            <span className="flex h-4 gap-0.5 font-mono text-[10.5px] font-medium leading-4 tabular">
              {!!female && <i className="min-w-9 rounded-[2px] bg-foreground/75 px-1 text-left not-italic text-background" style={{ flex: female }}>{female} F</i>}
              {!!male && <i className="min-w-9 rounded-[2px] bg-foreground/15 px-1 text-right not-italic text-foreground/80" style={{ flex: male }}>{male} M</i>}
            </span>
          </span>
        );
      })}
    </span>
  );
}

const CHIP = "flex min-w-0 items-center gap-1 rounded-[4px] border border-rule px-1.5 py-0.5 font-mono text-[11.5px] text-foreground/85 transition-colors duration-150 hover:border-foreground hover:text-foreground";

// What can be downloaded, as links: raw reads at SRA, the first processed files, then the rest of the folder.
function Access({ profile, hit }: { profile: Profile; hit: Hit }) {
  if (profile.access === "controlled access") {
    return <a href={hit.url} target="_blank" rel="noreferrer" className={cn(CHIP, "w-fit [.text-right_&]:ml-auto")}>Controlled access, apply<ArrowUpRight aria-hidden className="size-3" /></a>;
  }
  const files = profile.files ?? [];
  return (
    <span className="flex flex-wrap gap-1.5 [.text-right_&]:justify-end">
      {profile.access?.includes("raw reads") && (
        <a href={`https://www.ncbi.nlm.nih.gov/Traces/study/?acc=${hit.accession}`} target="_blank" rel="noreferrer" className={CHIP}>raw reads, SRA<ArrowUpRight aria-hidden className="size-3 shrink-0" /></a>
      )}
      {files.slice(0, 2).map((url) => (
        <a key={url} href={url} className={CHIP} title={url}><span className="truncate">{fileLabel(url, hit.accession)}</span><ArrowDown aria-hidden className="size-3 shrink-0" /></a>
      ))}
      {files.length > 2 && <Link href={`${datasetPath(hit.accession)}#files`} className={cn(CHIP, "text-muted-foreground")}>+{files.length - 2}</Link>}
      {!profile.access?.includes("raw reads") && !files.length && <span className="text-muted-foreground">none listed</span>}
    </span>
  );
}

// Each dataset is one strand running down the facets: the strands join where the two datasets agree and part where
// they differ, so the shape of the comparison is visible before any value is read.
function Strands({ comparison, a, b }: { comparison: Comparison; a: Hit; b: Hit }) {
  const still = useReducedMotion();
  const box = useRef<HTMLDivElement>(null);
  const [knots, setKnots] = useState<Knot[]>([]);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => {
      const origin = el.getBoundingClientRect();
      setKnots([...el.querySelectorAll<HTMLElement>("[data-lane]")].map((anchor) => {
        const r = anchor.getBoundingClientRect();
        const facet = comparison.facets.find((f) => f.key === anchor.dataset.facet);
        return { x: r.left + r.width / 2 - origin.left, y: r.top + r.height / 2 - origin.top, lane: anchor.dataset.lane as Lane, facet };
      }));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [comparison]);

  const strand = (side: -1 | 1) =>
    knots.map((k, i) => {
      const x = k.x + side * GAP[k.lane];
      if (!i) return `M${x} ${k.y}`;
      const p = knots[i - 1];
      const bend = (k.y - p.y) / 2;
      return `C${p.x + side * GAP[p.lane]} ${p.y + bend} ${x} ${k.y - bend} ${x} ${k.y}`;
    }).join(" ");
  const height = knots.at(-1)?.y || 1;
  const appear = (y: number) => (still ? {} : { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { duration: 0.2, delay: (y / height) * DRAW } });
  const draw = still ? {} : { initial: { pathLength: 0 }, animate: { pathLength: 1 }, transition: { duration: DRAW, ease: EASE_OUT } };
  const value = (v: string | null) => v ?? <span className="text-muted-foreground">not stated</span>;
  const cell = (f: Facet, side: "a" | "b") => {
    const profile = comparison[side];
    if (f.key === "sex" && profile.sex_split) return <SexSplit split={profile.sex_split} />;
    if (f.key === "access" && profile.access) return <Access profile={profile} hit={side === "a" ? a : b} />;
    // The bars already show both groups; words are needed only when a group is missing.
    if (f.key === "groups" && f[side] === "cases and controls") return null;
    return value(f[side]);
  };

  return (
    <div ref={box} className="relative grid">
      <svg aria-hidden className="pointer-events-none absolute inset-0 size-full overflow-visible">
        {knots.length > 1 && (
          <>
            <motion.path d={strand(-1)} fill="none" strokeWidth={1.5} stroke="currentColor" className="text-foreground" {...draw} />
            <motion.path d={strand(1)} fill="none" strokeWidth={1.5} stroke="currentColor" className="text-[color-mix(in_oklab,var(--foreground)_45%,var(--card))]" {...draw} />
          </>
        )}
        {knots.map((k) => k.facet && k.lane === "joined" && (
          <motion.circle key={k.facet.key} cx={k.x} cy={k.y} r={3} className="fill-foreground" {...appear(k.y)} />
        ))}
        {knots.map((k) => k.facet?.status === "differs" && k.facet.required && [-1, 1].map((side) => (
          <motion.circle key={`${k.facet!.key}${side}`} cx={k.x + side * GAP.apart} cy={k.y} r={4} strokeWidth={2} className="fill-foreground stroke-card" {...appear(k.y)} />
        )))}
        {knots.map((k) => k.facet?.status === "unknown" && [-1, 1].map((side) => (k.facet![side < 0 ? "a" : "b"] === null) && (
          <motion.circle key={`${k.facet!.key}${side}`} cx={k.x + side * GAP.apart} cy={k.y} r={3.5} strokeDasharray="2 2" className="fill-card stroke-muted-foreground" {...appear(k.y)} />
        )))}
      </svg>

      <div className={cn(GRID, "items-end pb-1")}>
        <span className="col-start-2 row-start-1 h-5 self-end sm:col-start-3" data-lane="apart" />
        {[a, b].map((hit, i) => (
          <span key={hit.accession} className={cn("row-start-1 grid min-w-0 gap-0.5 pb-2", i ? "col-start-3 sm:col-start-4" : "col-start-1 text-right sm:col-start-2")}>
            <span className="font-mono text-[12px] font-medium text-foreground/80">{shortAccession(hit)}</span>
            <span className="line-clamp-2 text-[13px] leading-snug" title={hit.title}>{hit.title}</span>
          </span>
        ))}
      </div>

      {/* A row neither dataset states says nothing, unless the verdict needs it. Group sizes already sit in the
          bars and shared samples only matter when there are some, so those rows appear only to warn. */}
      {comparison.facets.filter((f) => (f.required || f.a !== null || f.b !== null) && (!WARN_ONLY.has(f.key) || f.status === "differs")).map((f) => {
        const lane = STRAND[f.status];
        return (
          <div key={f.key} title={f.required || f.status === "same" ? undefined : f.note} className={cn(GRID, "border-t border-rule/70 py-2 text-sm leading-snug")}>
            <span className={cn("label col-start-1 row-start-1 text-right sm:row-span-2 sm:text-left", f.required && f.status !== "same" ? "text-foreground" : "text-muted-foreground")}>{SHORT[f.key] ?? f.label}</span>
            <span className={cn("col-start-1 row-start-2 min-w-0 text-right sm:col-start-2 sm:row-start-1", lane === "joined" && "text-muted-foreground")}>
              {cell(f, "a")}
              {f.key === "groups" && <Bars hit={a} />}
            </span>
            <span data-lane={lane} data-facet={f.key} className="col-start-2 row-start-2 h-5 sm:col-start-3 sm:row-start-1" />
            <span className={cn("col-start-3 row-start-2 min-w-0 sm:col-start-4 sm:row-start-1", lane === "joined" && "text-muted-foreground")}>
              {cell(f, "b")}
              {f.key === "groups" && <Bars hit={b} />}
            </span>
            {(f.required ? f.status !== "same" : (WARN_ONLY.has(f.key) || f.key === "sex") && f.status === "differs") && f.note && <span className="col-start-3 row-start-3 mt-1 text-[12.5px] text-muted-foreground sm:col-start-4 sm:row-start-2">{f.note}</span>}
          </div>
        );
      })}

      <div className={cn(GRID, "border-t border-rule/70 pt-5")}>
        <span className="col-start-2 row-start-1 flex justify-center sm:col-start-3" data-lane={comparison.verdict === "pool" ? "joined" : "apart"}>
          <motion.span {...appear(height)} className="whitespace-nowrap rounded-full bg-foreground px-3.5 py-1.5 text-sm font-medium text-background">
            {HEADLINE[comparison.verdict]}
          </motion.span>
        </span>
        <p className="col-span-3 mt-3 text-balance text-center text-[13px] leading-snug text-muted-foreground sm:col-span-4">{comparison.reason}</p>
      </div>

    </div>
  );
}

function Dataset({ hit, letter }: { hit: Hit; letter: string }) {
  return (
    <div className="grid min-w-0 content-start gap-1">
      <span className="flex items-baseline gap-2">
        <span className="font-mono text-[12px] font-medium text-foreground/80">{shortAccession(hit)}</span>
        <span className="label truncate text-muted-foreground">{letter}{SEP}{repositoryName(hit.source)}</span>
      </span>
      <span className="line-clamp-2 text-sm leading-snug">{hit.title}</span>
      <Link href={`${datasetPath(hit.accession)}#samples`} className={cn(ACTION, "w-fit")}>
        Samples
      </Link>
    </div>
  );
}

export function CompareDialog({ a, b, topic, onClose }: { a: Hit; b: Hit; topic: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [got, setGot] = useState<{ attempt: number; comparison?: Comparison; error?: string }>({ attempt: -1 });

  useEffect(() => {
    if (!dialog.current?.open) dialog.current?.showModal();
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    compare([a.accession, b.accession], topic, ctrl.signal).then(
      (comparison) => setGot({ attempt, comparison }),
      (error: Error) => !ctrl.signal.aborted && setGot({ attempt, error: error.message }),
    );
    return () => ctrl.abort();
  }, [a.accession, b.accession, topic, attempt]);

  const current = got.attempt === attempt ? got : null;
  let body: ReactNode;
  if (!current) {
    body = (
      <p role="status" className="flex items-center gap-2.5 py-6">
        <Reticle scanning className="size-5" />
        <span className="label text-muted-foreground">Comparing</span>
      </p>
    );
  } else if (!current.comparison) {
    body = (
      <p role="alert" className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-6 text-sm">
        {current.error && !/^(\d+|Not Found)$/.test(current.error) ? current.error : "The comparison could not be made."}
        <button type="button" onClick={() => setAttempt((n) => n + 1)} className={ACTION}>Try again</button>
      </p>
    );
  } else {
    body = <Strands comparison={current.comparison} a={a} b={b} />;
  }

  return (
    <dialog
      ref={dialog}
      aria-label={`Compare ${a.accession} and ${b.accession}`}
      onClose={onClose}
      onClick={(e) => e.target === e.currentTarget && e.currentTarget.close()}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(42rem,calc(100%-2rem))] overflow-y-auto overscroll-contain rounded-lg border border-rule bg-card p-0 text-foreground shadow-[0_12px_32px_-12px_rgb(17_17_16/0.5)] backdrop:bg-foreground/40"
    >
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={motionTier.ui} className="relative grid gap-4 p-5 sm:p-6">
        <button type="button" onClick={() => dialog.current?.close()} aria-label="Close" className="absolute right-2.5 top-2.5 z-10 grid size-8 place-items-center text-muted-foreground transition-colors duration-150 hover:text-foreground">
          <X aria-hidden className="size-4" />
        </button>
        {!current?.comparison && (
          <div className="grid gap-4 pr-8 sm:grid-cols-2 sm:gap-6">
            <Dataset hit={a} letter="A" />
            <Dataset hit={b} letter="B" />
          </div>
        )}
        {body}
      </motion.div>
    </dialog>
  );
}
