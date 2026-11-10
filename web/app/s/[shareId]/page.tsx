import { cache } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Wordmark } from "@/components/logo";
import { LINK } from "@/components/page-kit";
import { datasetPath, repositoryName } from "@/lib/api";
import type { Snapshot } from "@/lib/lists";

// A public list (F6, papertok's public lists): a read-only copy its owner published, served to anyone, signed in or
// not. It is rendered on the server from the API's /public/lists/<id>, so the page reads no cookie and the title and
// description are in the first HTML. Not indexed until Juri decides otherwise.
type PublicItem = { accession: string; snapshot: Snapshot; note?: string };
type PublicList = { name: string; description: string; owner: string | null; updated_at: string; count: number; shown: number; items: PublicItem[] };

const BACKEND = process.env.OMICS_API_URL ?? "http://localhost:8000";
const SEP = " ·  ";

const read = cache(async (shareId: string): Promise<PublicList | null> => {
  if (!/^[0-9a-f]{32}$/.test(shareId)) return null;
  const res = await fetch(`${BACKEND}/public/lists/${shareId}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`locus could not read this list (${res.status}).`);
  return res.json();
});

const datasets = (n: number) => `${n.toLocaleString("en-GB")} ${n === 1 ? "dataset" : "datasets"}`;

export async function generateMetadata({ params }: { params: Promise<{ shareId: string }> }): Promise<Metadata> {
  const list = await read((await params).shareId);
  if (!list) notFound();
  const about = list.description || `A list of ${datasets(list.count)} shared from locus.`;
  return {
    title: `${list.name} · locus`,
    description: about,
    robots: { index: false, follow: false },
    referrer: "no-referrer",
    openGraph: { title: list.name, description: about, type: "website", siteName: "locus" },
  };
}

export default async function Page({ params }: { params: Promise<{ shareId: string }> }) {
  const list = await read((await params).shareId);
  if (!list) notFound();
  return (
    <div className="mx-auto grid w-full max-w-4xl content-start gap-10" data-public-list>
      <nav className="flex items-center gap-5">
        <Link href="/" aria-label="locus home" className="leading-none"><Wordmark className="text-[30px]" /></Link>
      </nav>
      <header className="grid gap-4">
        <p className="label text-muted-foreground">Shared list</p>
        <h1 className="max-w-4xl font-display text-[34px] leading-[1.08] break-words sm:text-[44px]">{list.name}</h1>
        {list.description && <p className="max-w-2xl text-[15px] text-muted-foreground">{list.description}</p>}
        <p className="flex flex-wrap items-baseline gap-x-5 gap-y-2 border-y border-rule py-3 text-[13px]">
          <span className="font-mono tabular" data-count={list.count}>{datasets(list.count)}</span>
          <span className="font-mono tabular text-muted-foreground">updated {list.updated_at.slice(0, 10)}</span>
          {list.owner && <span className="text-muted-foreground" data-owner>shared by {list.owner}</span>}
        </p>
      </header>
      {list.items.length === 0 ? (
        <p className="text-[14px] text-muted-foreground">This list is empty.</p>
      ) : (
        <ol className="-mt-10 grid">
          {list.items.map((item) => {
            const s = item.snapshot;
            const meta = [s.source && repositoryName(s.source), s.organism, s.modality, s.samples != null && `${s.samples.toLocaleString("en-GB")} samples`].filter(Boolean).join(SEP);
            return (
              <li key={item.accession} className="grid gap-1 border-b border-rule py-5" data-item={item.accession}>
                <Link href={datasetPath(item.accession)} className={`w-fit text-[15px] leading-snug ${LINK}`}>{s.title || item.accession}</Link>
                <p className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                  <span className="font-mono text-[12px] font-medium text-foreground/80">{item.accession}</span>
                  {meta && <span className="label min-w-0 text-muted-foreground">{meta}</span>}
                </p>
                {item.note && <p className="mt-1 max-w-2xl whitespace-pre-line border-l-2 border-foreground pl-3 text-[14px] text-muted-foreground" data-note>{item.note}</p>}
              </li>
            );
          })}
        </ol>
      )}
      <p className="text-[12px] text-muted-foreground">
        {list.count > list.shown && <>Showing the first {list.shown} of {datasets(list.count)}. </>}
        A read-only copy, as its owner last published it. Titles and sample counts are as they were when each dataset was saved; the dataset pages show the current records.
      </p>
    </div>
  );
}
