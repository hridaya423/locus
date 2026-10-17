"use client";
import { useRef } from "react";
import { animate, motion, useMotionValue, useMotionValueEvent, useReducedMotion, useSpring, useTransform, type AnimationPlaybackControls, type MotionValue } from "framer-motion";
import { cn } from "@/lib/utils";

export function Reticle({ className, scanning }: { className?: string; scanning?: boolean }) {
  return (
    <svg viewBox="0 0 40 40" aria-hidden className={className}>
      <circle
        cx="20" cy="20" r="15.5" fill="none" stroke="currentColor" strokeWidth="3.4"
        strokeDasharray={scanning ? "72 25.4" : undefined}
        className={scanning ? "origin-center animate-spin [animation-duration:1.4s]" : undefined}
      />
      <circle cx="20" cy="20" r="5.2" className="fill-signal" />
    </svg>
  );
}

// The hover is one path: a comet spirals out of the dot, makes one turn inside the ring and spirals back in. Each shard
// replays the head's path a fixed time later, so the trail never bunches, never overlaps, and leaves and re-enters the
// dot one shard at a time. Positions are pure functions of one clock, so nothing fights anything else.
const SWEEP = 0.72;
const LAG = 0.034;
const REACH = 10.5;
const SIZES = [1.7, 1.4, 1.1, 0.8, 0.5];
const END = SWEEP + LAG * (SIZES.length - 1);
const clamp = (x: number) => Math.min(1, Math.max(0, x));
const smooth = (x: number) => {
  const c = clamp(x);
  return c * c * c * (c * (c * 6 - 15) + 10);
};
// Speed along the path is 0.6 at both ends and 1.4 in the middle: it moves the moment the pointer arrives, and still
// dives into the dot instead of drifting in.
const ramp = (x: number) => {
  const c = clamp(x);
  return c * c * (3 - 2 * c);
};
const progress = (x: number) => {
  const c = clamp(x);
  return c - (0.4 / (2 * Math.PI)) * Math.sin(2 * Math.PI * c);
};
const path = (t: number) => {
  const s = progress(t / SWEEP);
  return { reach: REACH * ramp(s / 0.14) * ramp((1 - s) / 0.14), angle: -Math.PI / 2 + 2 * Math.PI * s };
};

type ShardProps = { index: number; size: number; clock: MotionValue<number>; retract: MotionValue<number> };

function Shard({ index, size, clock, retract }: ShardProps) {
  const at = () => {
    const { reach, angle } = path(clock.get() - index * LAG);
    return { reach: reach * retract.get(), angle };
  };
  const cx = useTransform(() => { const p = at(); return 20 + p.reach * Math.cos(p.angle); });
  const cy = useTransform(() => { const p = at(); return 20 + p.reach * Math.sin(p.angle); });
  const r = useTransform(() => size * smooth(at().reach / 4));
  return <motion.circle cx={cx} cy={cy} r={r} className="fill-signal" />;
}

export function Wordmark({ className }: { className?: string }) {
  const still = useReducedMotion();
  const clock = useMotionValue(END);
  const retract = useMotionValue(1);
  const target = useMotionValue(0);
  const lock = useSpring(target, { stiffness: 420, damping: 24 });
  const dot = useTransform(() => 5.2 - 1.2 * (path(clock.get()).reach / REACH) * retract.get() + 1.1 * lock.get());
  const fired = useRef(true);
  const hovered = useRef(false);

  useMotionValueEvent(clock, "change", (t) => {
    if (fired.current || !hovered.current || t < END - 0.05) return;
    fired.current = true;
    target.set(1);
  });

  const sweep = useRef<AnimationPlaybackControls | null>(null);
  const pull = useRef<AnimationPlaybackControls | null>(null);

  function seek() {
    hovered.current = true;
    if (still) return target.set(1);
    pull.current?.stop();
    if (clock.get() >= END || retract.get() < 0.02) {
      sweep.current?.stop();
      clock.set(0);
      fired.current = false;
    }
    pull.current = animate(retract, 1, { type: "spring", duration: 0.16, bounce: 0 });
    if (clock.get() < END) sweep.current = animate(clock, END, { duration: END - clock.get(), ease: "linear" });
  }

  // The comet keeps travelling while it is pulled in, so leaving mid-sweep spirals it home instead of freezing it.
  function rest() {
    hovered.current = false;
    target.set(0);
    pull.current?.stop();
    pull.current = animate(retract, 0, { type: "spring", duration: 0.14, bounce: 0 });
  }

  return (
    <span
      role="img"
      aria-label="locus"
      onPointerEnter={(e) => e.pointerType === "mouse" && seek()}
      onPointerLeave={rest}
      className={cn("inline-flex items-baseline font-display [line-height:.8] tracking-[-0.02em]", className)}
    >
      l
      <svg viewBox="0 0 40 40" aria-hidden className="mx-[0.01em] size-[0.52em] overflow-visible">
        <circle cx="20" cy="20" r="15.5" fill="none" stroke="currentColor" strokeWidth="3.4" />
        {SIZES.map((size, index) => <Shard key={size} index={index} size={size} clock={clock} retract={retract} />)}
        <motion.circle cx="20" cy="20" r={dot} className="fill-signal" />
      </svg>
      cus
    </span>
  );
}
