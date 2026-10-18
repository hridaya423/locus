// The door audit: opens the dataset page and one sample page of 30 datasets picked at random across repositories,
// and counts every link that leaves locus and every value on screen that names something but opens nothing.
// node scripts/doors.mjs [--web http://localhost:3010] [--seed 1] [--n 30] [--out DIR]
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { browser, PAGE_READY } from "./cdp.mjs";

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const WEB = arg("--web", process.env.LOCUS_WEB ?? "http://localhost:3010");
const SEED = Number(arg("--seed", 1));
const N = Number(arg("--n", 30));
const OUT = arg("--out", "/tmp/locus-night/doors/latest");
const DB = new URL("../data/omics.db", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

// One dataset per repository first, then the rest from the repositories locus reads in full, so every kind of page is seen.
const sql = (q) => execFileSync("sqlite3", [DB, q], { encoding: "utf8" }).trim().split("\n").filter(Boolean);
const shuffle = `ORDER BY ((rowid + ${SEED}) * 2654435761) % 1000003`;
const sources = sql("SELECT DISTINCT source FROM datasets");
const picked = sources.flatMap((s) => sql(`SELECT accession FROM datasets WHERE source='${s}' ${shuffle} LIMIT 1`));
const full = ["GEO", "PRIDE", "ENA", "ArrayExpress"];
for (let i = 0; picked.length < N; i++) {
  const s = full[i % full.length];
  const next = sql(`SELECT accession FROM datasets WHERE source='${s}' ${shuffle} LIMIT 1 OFFSET ${1 + Math.floor(i / full.length)}`)[0];
  if (next) picked.push(next);
}

// Runs in the page: every outbound link and every unlinked named value, keyed by where it sits.
const COLLECT = `(() => {
  const section = (el) => {
    const s = el.closest('section, nav, header, aside');
    const h = s?.querySelector('h2, h1');
    return (h?.textContent ?? s?.tagName.toLowerCase() ?? 'page').replace(/\\d[\\d,·. A-Za-z]*$/, '').trim().slice(0, 40);
  };
  const doors = [];
  for (const a of document.querySelectorAll('a[href]')) {
    if (!a.host || a.host === location.host || a.href.startsWith('mailto:')) continue;
    doors.push({ kind: 'leaves locus', where: section(a), what: a.host, example: a.textContent.trim().slice(0, 60) });
  }
  for (const dt of document.querySelectorAll('dt')) {
    const dd = dt.nextElementSibling;
    if (!dd) continue;
    for (const v of dd.querySelectorAll(':scope > span')) doors.push({ kind: 'value opens nothing', where: section(dt), what: dt.textContent.trim(), example: v.textContent.trim().slice(0, 60) });
  }
  for (const li of document.querySelectorAll('aside li')) {
    const first = li.firstElementChild;
    if (first && first.tagName === 'SPAN') doors.push({ kind: 'value opens nothing', where: section(li), what: section(li), example: first.textContent.trim().slice(0, 60) });
  }
  for (const table of document.querySelectorAll('table')) {
    const heads = [...table.querySelectorAll('thead th')].map(th => th.textContent.trim());
    const seen = new Set();
    for (const tr of table.querySelectorAll('tbody tr')) [...tr.children].forEach((td, i) => {
      const v = td.textContent.trim();
      if (!v || v === '–' || td.querySelector('a, button') || seen.has(i + v)) return;
      seen.add(i + v);
      doors.push({ kind: 'value opens nothing', where: section(table), what: heads[i] ?? 'column ' + i, example: v.slice(0, 60) });
    });
  }
  return doors;
})()`;

const page = await browser();
const pages = [];
for (const acc of picked) {
  for (let url = `${WEB}/d/${encodeURIComponent(acc)}`; url; ) {
    await page.goto(url);
    const ready = (await page.until(PAGE_READY, 60000)) && !(await page.eval("/did not send/.test(document.body.innerText)"));
    await new Promise((r) => setTimeout(r, 1200));
    const doors = ready ? await page.eval(COLLECT) : [];
    const sample = url.endsWith(encodeURIComponent(acc)) ? await page.eval(`document.querySelector('a[href^="/d/${encodeURIComponent(acc)}/"]')?.getAttribute('href') ?? null`) : null;
    pages.push({ accession: acc, url, ready: !!ready, doors });
    url = sample ? `${WEB}${sample}` : null;
  }
  process.stdout.write(".");
}
page.close();

const tally = new Map();
for (const p of pages) for (const d of p.doors) {
  const key = `${d.kind} | ${d.where} | ${d.what}`;
  const t = tally.get(key) ?? { key, count: 0, pages: new Set(), example: d.example };
  t.count++;
  t.pages.add(p.url);
  tally.set(key, t);
}
const rows = [...tally.values()].map((t) => ({ ...t, pages: t.pages.size })).sort((a, b) => b.pages - a.pages || b.count - a.count);
const outbound = pages.map((p) => p.doors.filter((d) => d.kind === "leaves locus").length);
const summary = {
  seed: SEED, datasets: picked, pages: pages.length, not_ready: pages.filter((p) => !p.ready).map((p) => p.url),
  outbound_per_page: +(outbound.reduce((a, b) => a + b, 0) / pages.length).toFixed(2),
  dead_values_per_page: +(pages.reduce((s, p) => s + p.doors.filter((d) => d.kind !== "leaves locus").length, 0) / pages.length).toFixed(2),
  doors: rows,
};
writeFileSync(join(OUT, "doors.json"), JSON.stringify({ ...summary, by_page: pages }, null, 1));
console.log(`\n${pages.length} pages from ${picked.length} datasets (seed ${SEED}); ${summary.not_ready.length} did not load.`);
console.log(`Outbound links per page: ${summary.outbound_per_page}. Values that open nothing per page: ${summary.dead_values_per_page}.\n`);
console.log("pages  count  door");
for (const r of rows.slice(0, 40)) console.log(`${String(r.pages).padStart(5)}  ${String(r.count).padStart(5)}  ${r.key}   e.g. ${r.example}`);
