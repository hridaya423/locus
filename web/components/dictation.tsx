"use client";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Mic } from "lucide-react";
import { cn } from "@/lib/utils";

type Recognizer = {
  lang: string; interimResults: boolean; start(): void; stop(): void; abort(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};

const recognizer = () => {
  const w = window as unknown as Record<string, (new () => Recognizer) | undefined>;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
};

const REASONS: Record<string, string> = {
  "not-allowed": "The browser blocked the microphone. Allow it for this site to dictate.",
  "service-not-allowed": "The browser blocked speech recognition. Allow it for this site to dictate.",
  "no-speech": "No speech heard. Select the microphone and try again.",
  "audio-capture": "No microphone found.",
  network: "The browser's speech service did not answer.",
};

// Dictation with the browser's own speech recognition: interim words fill the field, and the user submits as usual.
export function useDictation(text: string, setText: (text: string) => void) {
  const supported = useSyncExternalStore(() => () => {}, () => !!recognizer(), () => false);
  const [listening, setListening] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const active = useRef<Recognizer | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  const toggle = () => {
    if (active.current) return active.current.stop();
    const Recognition = recognizer()!;
    const r = new Recognition();
    const before = text.trim();
    r.lang = navigator.language;
    r.interimResults = true;
    r.onresult = (e) => setText([before, ...Array.from(e.results, (alternatives) => alternatives[0].transcript.trim())].filter(Boolean).join(" "));
    r.onerror = (e) => e.error !== "aborted" && setProblem(REASONS[e.error] ?? `Dictation stopped (${e.error}).`);
    r.onend = () => {
      active.current = null;
      setListening(false);
    };
    setProblem(null);
    setListening(true);
    active.current = r;
    r.start();
  };
  return { supported, listening, problem, toggle, stop: () => active.current?.abort() };
}

export function MicButton({ listening, onClick }: { listening: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={listening ? "Stop dictating" : "Dictate your question"}
      aria-pressed={listening}
      className={cn(
        "absolute bottom-2 right-[3.25rem] grid size-10 place-items-center rounded-md transition-colors duration-150 active:scale-[0.96]",
        listening ? "border border-foreground bg-card text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      <Mic aria-hidden className={cn("size-4", listening && "animate-pulse")} strokeWidth={2} />
    </button>
  );
}
