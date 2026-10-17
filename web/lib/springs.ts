// Three tiers matched to locus's moments. No bounce: data should land, not wobble.
export const EASE_OUT = [0.23, 1, 0.32, 1] as const;

export const motionTier = {
  micro: { type: "tween" as const, duration: 0.15, ease: EASE_OUT, exit: { duration: 0.1 } },
  ui: { type: "spring" as const, duration: 0.2, bounce: 0, exit: { duration: 0.12 } },
  entrance: { type: "tween" as const, duration: 0.45, ease: EASE_OUT, exit: { duration: 0.16 } },
} as const;
