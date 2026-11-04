"use client";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { MUTED_LINK } from "@/components/page-kit";

// One shared toast line at the foot of the screen (F8, after papertok's toasts). A success clears itself after six
// seconds, but not while the pointer or keyboard focus is on it; an error stays until closed. `undo` reverses the action
// that raised it; each of `actions` is one more labelled step (a button, or a link when it has an href).
export type ToastAction = { label: string; onClick?: () => void; href?: string };
export type Toast = { text: string; error?: boolean; undo?: () => void; actions?: ToastAction[] };

type Shown = Toast & { id: number };
let current: Shown | null = null;
let next = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function toast(t: Toast): void {
  current = { ...t, id: next++ };
  emit();
}
export const toastError = (text: string) => toast({ text, error: true });
export function dismissToast(): void {
  current = null;
  emit();
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

const ON_INK = "underline decoration-background/40 underline-offset-4 transition-colors duration-150 hover:decoration-background";

export function Toaster() {
  const shown = useSyncExternalStore(subscribe, () => current, () => null);
  // A hold belongs to one toast: hovering or focusing a toast holds only that toast, so the next one clears itself
  // even if the pointer never left the last (F8-r1-1: one mouse click on Undo used to stop every later toast clearing).
  const [heldId, setHeldId] = useState<number | null>(null);
  const held = shown != null && heldId === shown.id;
  const setHeld = (on: boolean) => setHeldId(on && shown ? shown.id : null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!shown || shown.error || held) return;
    const t = setTimeout(dismissToast, 6000);
    return () => clearTimeout(t);
  }, [shown, held]);

  // Escape closes a toast that holds focus, and focus goes back to the page body rather than being lost.
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") dismissToast();
  };

  return (
    // The status region stays in the page so screen readers hear a success the moment it appears.
    <div className="pointer-events-none fixed inset-x-0 bottom-5 z-50 flex justify-center px-5">
      <div role="status" aria-live="polite" className="contents">
        {shown && !shown.error && (
          <div
            ref={box}
            key={shown.id}
            data-toast
            onMouseEnter={() => setHeld(true)}
            onMouseLeave={() => setHeld(false)}
            onFocus={() => setHeld(true)}
            onBlur={(e) => { if (!box.current?.contains(e.relatedTarget as Node)) setHeld(false); }}
            onKeyDown={onKey}
            className="pointer-events-auto flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg bg-foreground px-4 py-2.5 text-[13px] text-background shadow-sm motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-200"
          >
            <span>{shown.text}</span>
            {shown.actions?.map((a) => <Action key={a.label} action={a} />)}
            {shown.undo && (
              <button type="button" onClick={() => { const undo = shown.undo; dismissToast(); undo?.(); }} className={ON_INK}>
                Undo
              </button>
            )}
          </div>
        )}
      </div>
      {/* An alert region is announced when it is inserted, so it exists only while an error shows (an empty one
          would also read as an error to anything that looks for role=alert). */}
      {shown?.error && (
        <div role="alert" className="contents">
          <div key={shown.id} data-toast="error" onKeyDown={onKey} className="pointer-events-auto flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border border-rule bg-card px-4 py-2.5 text-[13px] text-destructive shadow-sm">
            <span>{shown.text}</span>
            <button type="button" onClick={dismissToast} className={MUTED_LINK}>
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Action({ action }: { action: ToastAction }) {
  const go = () => {
    dismissToast();
    action.onClick?.();
  };
  if (action.href) return <Link href={action.href} onClick={go} className={ON_INK}>{action.label}</Link>;
  return <button type="button" onClick={go} className={ON_INK}>{action.label}</button>;
}
