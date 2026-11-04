"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AuthPrompt } from "@/components/auth-prompt";
import { LINK, MUTED_LINK } from "@/components/page-kit";
import { Button } from "@/components/ui/button";
import { ACCOUNT_EVENT, describe, me } from "@/lib/account";
import { coverage, follow, identity, listFollows, nameWindow, orcidUrl, papers, unfollow, type Identity } from "@/lib/follows";
import { cn } from "@/lib/utils";

type Who = "loading" | "guest" | "signed-in" | "failed";

// Who a person page's name is, by ORCID, with Follow only when the API says "one": Europe PMC ties most of the name's
// tagged papers (at least 3) to one ORCID, the name is not common, and the ORCID record's own name agrees with the
// page's. Every other answer gets a plain explanation and no Follow (papertok's unverified guard).
export function FollowPerson({ name }: { name: string }) {
  const [id, setId] = useState<Identity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    identity(name).then(
      (r) => {
        if (!live) return;
        setId(r);
        setError(null);
      },
      (e) => {
        if (live) setError(e?.code === "BUSY" || e?.code === "RATE_LIMITED" ? e.message : "locus could not check which ORCID Europe PMC ties to this name.");
      },
    );
    return () => {
      live = false;
    };
  }, [name, attempt]);

  if (error)
    return (
      <p className="flex flex-wrap items-baseline gap-x-3 text-[13px] text-muted-foreground" data-follow-panel="error">
        {error}
        <button type="button" onClick={() => setAttempt((n) => n + 1)} className={LINK}>Try again</button>
      </p>
    );
  if (!id) return <p className="text-[13px] text-muted-foreground" data-follow-panel="loading">Checking which ORCID Europe PMC ties to this name…</p>;
  if (id.status === "no_name") return null;
  if (id.status === "several" && id.reason === "common")
    return (
      <p className="max-w-[80ch] text-[13px] text-muted-foreground" data-follow-panel="several" data-reason="common">
        This name matches several people: Europe PMC finds {papers(id.matched!)} under it. locus follows people by ORCID only, and with a name
        this common it cannot tell whose ORCID is whose, so it offers no Follow here.
      </p>
    );
  if (id.status === "several")
    return (
      <p className="max-w-[80ch] text-[13px] text-muted-foreground" data-follow-panel="several" data-reason="shared">
        This name matches several people. Of {nameWindow(id.scanned!, id.matched!)}, Europe PMC tags {papers(id.tagged!)} with {id.orcids} different
        ORCIDs, and none of them accounts for most. locus follows people by ORCID only, so it offers no Follow here.
      </p>
    );
  if (id.status === "none")
    return (
      <p className="max-w-[80ch] text-[13px] text-muted-foreground" data-follow-panel="none">
        None of {nameWindow(id.scanned!, id.matched!)} tags this author with an ORCID in Europe PMC, so locus cannot tell whose papers
        they are and offers no Follow.
      </p>
    );
  if (id.status === "unconfirmed")
    return (
      <p className="max-w-[80ch] text-[13px] text-muted-foreground" data-follow-panel="unconfirmed" data-reason={id.reason}>
        {id.reason === "few" && <>Europe PMC ties only {papers(id.claimed!)} of {nameWindow(id.scanned!, id.matched!)} to one ORCID. That is too few to say whose name this is, so locus offers no Follow.</>}
        {id.reason === "other_name" && <>The ORCID Europe PMC tags most often under this name, <a href={orcidUrl(id.orcid!)} target="_blank" rel="noreferrer" className={LINK}>{id.orcid}</a>, belongs to {id.orcid_name ?? "someone with no public name"}, whose name does not match this page. locus offers no Follow.</>}
        {id.reason === "no_record" && <>locus could not confirm whose ORCID this is: the ORCID record did not answer in time. It offers no Follow until it can. Reload the page to try again.</>}
      </p>
    );
  return <OneOrcid id={id} name={name} />;
}

function OneOrcid({ id, name }: { id: Identity; name: string }) {
  const orcid = id.orcid!;
  const [who, setWho] = useState<Who>("loading");
  const [following, setFollowing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [asked, setAsked] = useState(false);
  const [problem, setProblem] = useState("");

  const load = useCallback(() => {
    me()
      .then(async (m) => {
        if (!m.user) return { who: "guest" as const, following: false };
        return { who: "signed-in" as const, following: (await listFollows()).some((f) => f.orcid === orcid) };
      })
      .then(
        (r) => {
          setWho(r.who);
          setFollowing(r.following);
        },
        () => setWho("failed"),
      );
  }, [orcid]);

  useEffect(() => {
    load();
    window.addEventListener(ACCOUNT_EVENT, load);
    return () => window.removeEventListener(ACCOUNT_EVENT, load);
  }, [load]);

  async function toggle() {
    if (who === "guest") {
      setAsked(true);
      return;
    }
    setBusy(true);
    setProblem("");
    try {
      if (following) await unfollow(orcid);
      else await follow(orcid, name);
      setFollowing(!following);
    } catch (e) {
      setProblem(describe(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid max-w-[80ch] gap-2" data-follow-panel="one" data-orcid={orcid}>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px]">
        <span>
          <span className="text-muted-foreground">ORCID </span>
          <a href={orcidUrl(orcid)} target="_blank" rel="noreferrer" className={cn("font-mono", LINK)}>{orcid}</a>
          {id.orcid_name && <span className="text-muted-foreground"> · {id.orcid_name}</span>}
        </span>
        <Button size="sm" variant={following ? "outline" : "default"} disabled={busy || who === "loading" || who === "failed"} onClick={toggle}
          aria-pressed={who === "signed-in" ? following : undefined} data-follow={following ? "on" : "off"}>
          {busy ? (following ? "Unfollowing…" : "Following…") : following ? "Following" : "Follow"}
        </Button>
        {following && <Link href="/following" className={MUTED_LINK}>See what they bring</Link>}
      </p>
      <p className="text-[12.5px] text-muted-foreground" data-coverage>{coverage(id)}</p>
      {who === "failed" && <p role="alert" className="text-[12.5px] text-destructive">locus could not check whether you are signed in. Reload the page to try again.</p>}
      {problem && <p role="alert" className="text-[12.5px] text-destructive">{problem}</p>}
      {asked && who === "guest" && (
        <AuthPrompt className="mt-1" reason="Following keeps a researcher in your account, so locus can show you datasets from their ORCID-linked papers on your Following page." />
      )}
    </div>
  );
}
