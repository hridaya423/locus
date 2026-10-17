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

export function Wordmark({ className }: { className?: string }) {
  return (
    <span role="img" aria-label="locus" className={cn("inline-flex items-baseline font-display [line-height:.8] tracking-[-0.02em]", className)}>
      l<Reticle className="mx-[0.01em] size-[0.52em]" />cus
    </span>
  );
}
