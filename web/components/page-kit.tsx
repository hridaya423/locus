import Link from "next/link";

export const LINK = "underline decoration-rule underline-offset-4 transition-colors duration-150 hover:decoration-foreground";
export const MUTED_LINK = "text-muted-foreground underline decoration-rule underline-offset-4 transition-colors duration-150 hover:text-foreground hover:decoration-foreground";

export function Heading({ id, children, count }: { id?: string; children: React.ReactNode; count?: React.ReactNode }) {
  return (
    <h2 id={id} className="flex scroll-mt-8 items-baseline gap-3 font-display text-[28px] leading-none">
      {children}
      {count != null && <span className="font-mono text-[13px] tabular text-muted-foreground">{count}</span>}
    </h2>
  );
}

// A status or empty screen (F8 c, after papertok's empty states): a serif heading, one sentence, and labelled links as
// the way out. The first link is the main step; the rest are muted. `data` names the screen for page checks.
export type WayOut = { href: string; label: string };
export function EmptyState({ id, title, children, ways, data, alert = false }: {
  id: string; title: string; children: React.ReactNode; ways: WayOut[]; data?: string; alert?: boolean;
}) {
  return (
    <section role={alert ? "alert" : "status"} aria-labelledby={id} data-empty-state={data ?? id} className="grid max-w-xl content-start gap-3">
      <h2 id={id} className="font-display text-[24px] leading-tight">{title}</h2>
      <p className="text-[14px] text-muted-foreground">{children}</p>
      {ways.length > 0 && (
        <p className="flex flex-wrap gap-x-5 gap-y-1 text-[14px]">
          {ways.map((w, i) => (
            <Link key={w.href + w.label} href={w.href} className={i === 0 ? LINK : MUTED_LINK}>{w.label}</Link>
          ))}
        </p>
      )}
    </section>
  );
}
