"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Wordmark } from "@/components/logo";
import { BackToResults } from "@/components/back-to-results";
import { EmptyState, Heading, LINK, MUTED_LINK } from "@/components/page-kit";
import { dataType } from "@/components/result-card";
import { Button } from "@/components/ui/button";
import { datasetPath, personPath, repositoryName } from "@/lib/api";
import { ACCOUNT_EVENT, describe, me, signInHref } from "@/lib/account";
import { FOLLOW_LIMITS, followUpdates, markSeen, orcidUrl, papers, unfollow, type FollowedPerson } from "@/lib/follows";
import { useWatches } from "@/lib/watches";
import { cn } from "@/lib/utils";

const day = (iso: string) => iso.slice(0, 10);
const LATE: Record<string, string> = {
  failed: "Europe PMC did not answer for this person. Reload the page to try again.",
  late: "Europe PMC took too long for this person, so locus stopped waiting. Reload the page to try again.",
  wait: "locus read Europe PMC for you a few seconds ago. Reload the page in a moment to read this person.",
  not_checked: `locus reads the ${FOLLOW_LIMITS.checked} people you followed most recently on each visit, and this person is further down.`,
};

export function FollowingPage() {
  const [who, setWho] = useState<"loading" | "guest" | "signed-in" | "failed">("loading");

  const load = useCallback(() => {
    me().then((m) => setWho(m.user ? "signed-in" : "guest"), () => setWho("failed"));
  }, []);

  useEffect(() => {
    load();
    window.addEventListener(ACCOUNT_EVENT, load);
    return () => window.removeEventListener(ACCOUNT_EVENT, load);
  }, [load]);

  return (
    <div className="mx-auto grid w-full max-w-4xl content-start gap-10">
      <nav className="flex items-center gap-5">
        <Link href="/" aria-label="locus home" className="leading-none"><Wordmark className="text-[30px]" /></Link>
        <BackToResults />
      </nav>
      <header className="grid gap-3">
        <h1 className="font-display text-[34px] leading-[1.08] sm:text-[44px]">Following</h1>
        <p className="max-w-xl text-[15px] text-muted-foreground">
          Datasets from the papers of researchers you follow, newest paper first, and the searches you watch.
        </p>
      </header>
      {who === "loading" ? (
        <p className="text-[13px] text-muted-foreground">Checking whether you are signed in…</p>
      ) : who === "failed" ? (
        <p role="alert" className="flex flex-wrap items-baseline gap-x-3 text-[13px]">
          locus could not check whether you are signed in. <button type="button" onClick={load} className={LINK}>Try again</button>
        </p>
      ) : who === "guest" ? (
        <SignedOut />
      ) : (
        <div className="grid gap-14" data-following-page="signed-in">
          <People />
          <Questions />
        </div>
      )}
    </div>
  );
}

function SignedOut() {
  return (
    <div data-following-page="guest">
      <EmptyState
        id="signed-out"
        title="Following needs an account"
        ways={[{ href: signInHref("/following"), label: "Sign in or create an account" }, { href: "/", label: "Back to search" }]}
      >
        Follow a researcher from their page and locus lists here the datasets their papers deposited or cite, marking the ones you have not
        seen yet. Researchers are followed by ORCID, so a shared name never brings in someone else&apos;s work.
      </EmptyState>
    </div>
  );
}

function People() {
  const [people, setPeople] = useState<FollowedPerson[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    followUpdates().then(
      (r) => {
        setPeople(r);
        setError("");
      },
      (e) => setError(describe(e)),
    );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const fresh = people?.reduce((n, p) => n + (p.new ?? 0), 0) ?? 0;
  return (
    <section aria-labelledby="people" className="grid content-start gap-5" data-following-people={people ? people.length : "loading"}>
      <Heading id="people" count={people && people.length > 0 ? `${people.length} followed${fresh ? ` · ${fresh} new` : ""}` : undefined}>People</Heading>
      {error ? (
        <p role="alert" className="flex flex-wrap items-baseline gap-x-3 text-[13px]">{error} <button type="button" onClick={load} className={LINK}>Try again</button></p>
      ) : !people ? (
        <p className="text-[13px] text-muted-foreground">Reading their ORCID-linked papers from Europe PMC…</p>
      ) : people.length === 0 ? (
        <div data-following-empty>
          <EmptyState id="no-people" title="You follow nobody yet" ways={[{ href: "/", label: "Search for datasets" }]}>
            Open a researcher&apos;s page from a dataset or paper and choose Follow. locus offers it when Europe PMC ties their papers to one ORCID.
          </EmptyState>
        </div>
      ) : (
        <>
          {fresh === 0 && (
            <EmptyState id="nothing-new" data="nothing-new" title="Nothing new" ways={[{ href: "/", label: "Search for datasets" }]}>
              {people.some((p) => (p.datasets ?? []).length > 0)
                ? "You have seen every dataset below. New ones from the people you follow will be marked here."
                : "No locus dataset comes from the papers of the people you follow yet. New ones will be marked here."}
            </EmptyState>
          )}
          <p className="max-w-[80ch] text-[12.5px] text-muted-foreground">
            Europe PMC links only some of a researcher&apos;s papers to their ORCID, more often the recent ones. locus uses those papers alone,
            so a dataset from an older paper without the ORCID link does not appear here.
          </p>
          <ul className="grid gap-10">
            {people.map((p) => <Person key={p.orcid} person={p} onChange={load} />)}
          </ul>
        </>
      )}
    </section>
  );
}

function Person({ person: p, onChange }: { person: FollowedPerson; onChange: () => void }) {
  const [busy, setBusy] = useState<"" | "seen" | "unfollow">("");
  const [problem, setProblem] = useState("");
  const datasets = p.datasets ?? [];

  async function run(kind: "seen" | "unfollow") {
    setBusy(kind);
    setProblem("");
    try {
      if (kind === "seen") await markSeen(p.orcid, datasets.map((d) => d.accession));
      else await unfollow(p.orcid);
      onChange();
    } catch (e) {
      setProblem(describe(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <li className="grid gap-3" data-followed={p.orcid}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-b border-foreground pb-2">
        <p className="flex flex-wrap items-baseline gap-x-3">
          <Link href={personPath(p.page_name ?? p.display_name)} className={cn("font-display text-[22px] leading-tight", LINK)}>{p.display_name}</Link>
          <a href={orcidUrl(p.orcid)} target="_blank" rel="noreferrer" className={cn("font-mono text-[12px]", MUTED_LINK)}>{p.orcid}</a>
          <span className="font-mono text-[11.5px] tabular text-muted-foreground">followed {day(p.followed_at)}</span>
        </p>
        <span className="flex gap-2">
          {(p.new ?? 0) > 0 && (
            <Button size="sm" variant="outline" disabled={!!busy} onClick={() => run("seen")} data-mark-seen>
              {busy === "seen" ? "Marking…" : "Mark all as seen"}
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => run("unfollow")} data-unfollow>
            {busy === "unfollow" ? "Unfollowing…" : "Unfollow"}
          </Button>
        </span>
      </div>
      {problem && <p role="alert" className="text-[12.5px] text-destructive">{problem}</p>}
      {p.status !== "ok" ? (
        <p className="text-[13px] text-muted-foreground">{LATE[p.status]}</p>
      ) : (
        <>
          <p className="text-[12.5px] text-muted-foreground" data-coverage>
            Europe PMC links {papers(p.linked ?? 0)} to this ORCID{(p.linked ?? 0) > (p.read ?? 0) && `; locus reads the newest ${p.read}`}.
            {datasets.length === 0 ? " No locus dataset cites them yet." : ` ${datasets.length} locus ${datasets.length === 1 ? "dataset comes" : "datasets come"} from them.`}
          </p>
          {datasets.length > 0 && (
            <ul className="grid border-t border-rule">
              {datasets.map((d) => (
                <li key={d.accession} className="border-b border-rule" data-followed-dataset={d.accession} data-new={d.new ? "1" : "0"}>
                  <Link href={datasetPath(d.accession)} className="group/row grid gap-x-6 gap-y-1 py-3 sm:grid-cols-[11rem_minmax(0,1fr)_auto]">
                    <span className="grid content-start gap-0.5">
                      <span className="flex items-baseline gap-2">
                        <span className="font-mono text-[13px] font-medium underline decoration-transparent underline-offset-4 transition-colors duration-150 group-hover/row:decoration-foreground">{d.accession}</span>
                        {d.new && <span className="label text-signal" title="You have not marked this dataset as seen.">new</span>}
                      </span>
                      <span className="text-[12.5px] text-muted-foreground">{repositoryName(d.source)}</span>
                    </span>
                    <span className="grid min-w-0 gap-0.5">
                      <span className="break-words text-[14.5px] leading-snug">{d.title}</span>
                      <span className="truncate text-[12.5px] text-muted-foreground">from {d.paper.title}{d.paper.year && ` (${d.paper.year})`}</span>
                    </span>
                    <span className="text-[12.5px] text-muted-foreground sm:text-right">{dataType(d.modality) || "data type not stated"}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </li>
  );
}

// Watched searches (F4's store). Nothing runs here: a search calls the model, so each one opens on the home page, which
// marks what is new since the last run.
function Questions() {
  const w = useWatches();
  return (
    <section aria-labelledby="questions" className="grid content-start gap-5" data-following-questions={w.status === "signed-in" ? w.watches.length : w.status}>
      <Heading id="questions" count={w.watches.length || undefined}>Watched searches</Heading>
      {w.status === "loading" ? (
        <p className="text-[13px] text-muted-foreground">Reading your watched searches…</p>
      ) : w.status === "failed" ? (
        <p role="alert" className="text-[13px]">locus could not read your watched searches. Reload the page to try again.</p>
      ) : w.watches.length === 0 ? (
        <div role="status" className="grid max-w-xl gap-1 text-[13px]">
          <p className="font-medium">No watched searches</p>
          <p className="text-muted-foreground">Run a search and choose Watch this search. Each later run marks the datasets that are new since the one before.</p>
        </div>
      ) : (
        <>
          <p className="text-[12.5px] text-muted-foreground">Open one to run it again; the results mark what is new since its last run.</p>
          <ul className="grid border-t border-rule">
            {w.watches.map((x) => (
              <li key={x.question} className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-rule py-3" data-following-question={x.question}>
                <a href={`/?q=${encodeURIComponent(x.question)}`} className={cn("text-[14.5px]", LINK)}>{x.question}</a>
                <span className="font-mono text-[11.5px] tabular text-muted-foreground">watching since {x.since}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
