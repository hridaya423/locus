"use client";
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { size } from "@/components/row-details";
import type { Selection } from "@/components/design";
import { repositoryName, type DatasetRecord, type RecordFile } from "@/lib/api";

type Group = { name: string; files: RecordFile[]; bytes: number; processed: number };

function groups(files: RecordFile[]): Group[] {
  const by = new Map<string, RecordFile[]>();
  for (const f of files) by.set(f.group, [...(by.get(f.group) ?? []), f]);
  return [...by]
    .map(([name, list]) => ({
      name,
      files: [...list].sort((a, b) => Number(b.processed) - Number(a.processed)),
      bytes: list.reduce((n, f) => n + (f.bytes ?? 0), 0),
      processed: list.filter((f) => f.processed).length,
    }))
    .sort((a, b) => Number(b.processed > 0) - Number(a.processed > 0));
}

export function Files({ rec, selection }: { rec: DatasetRecord; selection?: Selection }) {
  const list = useMemo(() => groups(rec.files), [rec.files]);
  const total = list.reduce((n, g) => n + g.bytes, 0);
  const [copied, setCopied] = useState(false);
  const picked = selection?.result?.downloads;
  const plan = picked?.commands ?? rec.download_plan;
  const nothing = selection?.active && selection.result?.rows.length === 0;
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);
  return (
    <section className="grid content-start gap-8">
      <Heading id="files" count={rec.files.length ? `${rec.files.length.toLocaleString()} · ${size(total)}` : undefined}>Files</Heading>
      {list.length === 0 && <p className="text-[13px] text-muted-foreground">{repositoryName(rec.source)} lists no files for this dataset.</p>}
      {total > 0 && list.length > 1 && (
        <figure className="grid gap-3">
          <div aria-hidden className="flex h-2 gap-[2px] overflow-hidden rounded-full">
            {list.filter((g) => g.bytes).map((g) => (
              <span key={g.name} title={`${g.name}: ${size(g.bytes)}`} className={cn("h-full min-w-[3px]", g.processed ? "bg-foreground" : "bg-foreground/25")} style={{ flexGrow: g.bytes }} />
            ))}
          </div>
          <figcaption className="flex flex-wrap gap-x-5 gap-y-1 text-[12.5px]">
            {list.map((g) => (
              <a key={g.name} href={`#files-${g.name}`} className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground">
                <span aria-hidden className={cn("size-2 rounded-full", g.processed ? "bg-foreground" : "bg-foreground/25")} />
                {g.name} <span className="font-mono tabular">{g.bytes ? size(g.bytes) : `${g.files.length}`}</span>
              </a>
            ))}
          </figcaption>
        </figure>
      )}
      {list.map((g) => <FileGroup key={g.name} group={g} />)}
      {rec.download_plan && !nothing && (
        <details id="download-commands" className="group/plan scroll-mt-16">
          <summary className={cn("flex w-fit cursor-pointer list-none items-center gap-1 text-[13px] [&::-webkit-details-marker]:hidden", MUTED_LINK)}>
            {picked?.commands ? `Commands to download the ${selection?.result?.samples.toLocaleString()} selected samples` : "Commands to download everything"}
            <ChevronDown aria-hidden className="size-3.5 transition-transform duration-200 group-open/plan:rotate-180" />
          </summary>
          <div className="mt-3 grid min-w-0 gap-1.5 border-l-2 border-foreground pl-3">
            {picked?.note && <p className="text-[12.5px] text-muted-foreground">{picked.note}</p>}
            <pre className="max-h-96 overflow-auto font-mono text-[12px] leading-relaxed">{plan}</pre>
            <button type="button" onClick={() => navigator.clipboard.writeText(plan).then(() => setCopied(true))} className={cn("w-fit text-xs font-medium", LINK)}>
              {copied ? "copied" : "copy"}
            </button>
          </div>
        </details>
      )}
    </section>
  );
}

const FILES_SHOWN = 6;

function FileGroup({ group }: { group: Group }) {
  const [all, setAll] = useState(false);
  const shown = all ? group.files : group.files.slice(0, FILES_SHOWN);
  return (
    <div id={`files-${group.name}`} className="grid scroll-mt-8 gap-2">
      <h3 className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-foreground pb-2 text-[14px] font-medium">
        <span>
          {group.name}
          {group.processed > 0 && <span className="ml-2 text-[12.5px] font-normal text-muted-foreground">ready to use</span>}
        </span>
        <span className="font-mono text-[12px] font-normal tabular text-muted-foreground">
          {group.files.length.toLocaleString()} {group.files.length === 1 ? "file" : "files"}{group.bytes ? ` · ${size(group.bytes)}` : ""}
        </span>
      </h3>
      <ul className="grid">
        {shown.map((f) => (
          <li key={f.url} className="group/file grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 border-b border-rule/60 py-1.5 text-[13px] last:border-b-0 sm:grid-cols-[minmax(0,1fr)_9rem_4.5rem]">
            <a href={f.url} download className="flex min-w-0 items-baseline gap-1.5 hover:text-foreground" title={f.name}>
              <Download aria-hidden className="size-3 shrink-0 translate-y-[1px] text-muted-foreground group-hover/file:text-foreground" />
              <span className="truncate underline decoration-transparent underline-offset-4 group-hover/file:decoration-foreground">{f.name}</span>
            </a>
            <span className="truncate text-[12.5px] text-muted-foreground max-sm:hidden">{f.kind}</span>
            <span className="text-right font-mono text-[12px] tabular text-muted-foreground">{f.bytes != null ? size(f.bytes) : "–"}</span>
          </li>
        ))}
      </ul>
      {group.files.length > FILES_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[13px]", MUTED_LINK)}>
          {all ? "Show fewer" : `Show all ${group.files.length.toLocaleString()}`}
        </button>
      )}
    </div>
  );
}
