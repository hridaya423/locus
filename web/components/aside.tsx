"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { LINK, MUTED_LINK } from "@/components/page-kit";
import { isPaperId, paperPath, type DatasetRecord } from "@/lib/api";

const VALUES_SHOWN = 6;

function FactValues({ values }: { values: string[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? values : values.slice(0, VALUES_SHOWN);
  return (
    <dd className="grid gap-0.5 text-[13.5px] leading-snug">
      {shown.map((v) => <span key={v} className="break-words">{v}</span>)}
      {values.length > VALUES_SHOWN && (
        <button type="button" onClick={() => setAll((v) => !v)} className={cn("w-fit text-[12.5px]", MUTED_LINK)}>
          {all ? "fewer" : `+${values.length - VALUES_SHOWN} more`}
        </button>
      )}
    </dd>
  );
}

function AsideSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="grid content-start gap-3">
      <h2 className="label text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

export function Aside({ rec: full }: { rec: DatasetRecord }) {
  const rec = { ...full, papers: full.papers.filter((p) => !p.id || isPaperId(p.id)) };
  const roles = [...new Set(rec.people.map((p) => p.role))];
  return (
    <aside className="grid content-start gap-10 lg:border-l lg:border-rule lg:pl-8">
      <AsideSection title="Record">
        <dl className="grid gap-3">
          {rec.facts.map(([label, values]) => (
            <div key={label} className="grid gap-0.5">
              <dt className="text-[12px] text-muted-foreground">{label}</dt>
              <FactValues values={values} />
            </div>
          ))}
        </dl>
      </AsideSection>
      {rec.papers.length > 0 && (
        <AsideSection title={rec.papers.length === 1 ? "Paper" : "Papers"}>
          <ul className="grid gap-3">
            {rec.papers.map((p) => (
              <li key={p.url || p.title} className="grid gap-0.5 text-[13.5px] leading-snug">
                {p.id ? <Link href={paperPath(p.id)} className={LINK}>{p.title}</Link> : p.url ? <a href={p.url} target="_blank" rel="noreferrer" className={LINK}>{p.title}</a> : <span>{p.title}</span>}
                {(p.journal || p.year) && <span className="text-[12.5px] text-muted-foreground"><span className="italic">{p.journal}</span> {p.year}</span>}
                {p.id && p.url && <a href={p.url} target="_blank" rel="noreferrer" className={cn("w-fit text-[12.5px]", MUTED_LINK)}>{new URL(p.url).hostname}</a>}
              </li>
            ))}
          </ul>
        </AsideSection>
      )}
      {roles.map((role) => {
        const people = rec.people.filter((p) => p.role === role);
        return (
          <AsideSection key={role} title={people.length > 1 ? `${role}s` : role}>
            <ul className="grid gap-2 text-[13.5px] leading-snug">
              {people.map((p, i) => (
                <li key={`${p.name}${i}`} className="grid gap-0.5">
                  <span>{p.name}</span>
                  {p.affiliation && <span className="text-[12.5px] text-muted-foreground">{p.affiliation}</span>}
                  {p.email && <a href={`mailto:${p.email}`} className={cn("w-fit text-[12.5px] break-all", MUTED_LINK)}>{p.email}</a>}
                  {p.web && <a href={p.web} target="_blank" rel="noreferrer" className={cn("w-fit text-[12.5px] break-all", MUTED_LINK)}>{p.web}</a>}
                </li>
              ))}
            </ul>
          </AsideSection>
        );
      })}
      {rec.links.length > 0 && (
        <AsideSection title="Linked records">
          <ul className="grid gap-1.5 text-[13.5px]">
            {rec.links.map(([label, url]) => (
              <li key={url}>
                <a href={url} target="_blank" rel="noreferrer" className={cn("group/link inline-flex items-center gap-1", LINK)}>
                  {label}
                  <ArrowUpRight aria-hidden className="size-3.5 text-muted-foreground group-hover/link:text-foreground" />
                </a>
              </li>
            ))}
          </ul>
        </AsideSection>
      )}
    </aside>
  );
}
