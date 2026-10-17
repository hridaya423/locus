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
