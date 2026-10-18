// Opens random dataset pages and waits for every section to settle; reports console errors, failed sections and
// sections still loading. node scripts/crawl.mjs [--web http://localhost:3010] [--n 60] [--seed 7] [--out DIR]
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { browser, sleep, PAGE_READY } from "./cdp.mjs";

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const WEB = arg("--web", "http://localhost:3010");
const N = Number(arg("--n", 60));
const SEED = Number(arg("--seed", 7));
const OUT = arg("--out", "/tmp/locus-night/crawl");
mkdirSync(OUT, { recursive: true });
const DB = new URL("../data/omics.db", import.meta.url).pathname;
const sql = (q) => execFileSync("sqlite3", [DB, q], { encoding: "utf8" }).trim().split("\n").filter(Boolean);
const shuffle = `ORDER BY ((rowid + ${SEED}) * 2654435761) % 1000003`;
const picks = [
  ...sql(`SELECT accession FROM datasets WHERE source='GEO' ${shuffle} LIMIT ${Math.round(N * 0.5)}`),
  ...sql(`SELECT accession FROM datasets WHERE source='PRIDE' ${shuffle} LIMIT ${Math.round(N * 0.2)}`),
  ...sql(`SELECT accession FROM datasets WHERE source='ENA' ${shuffle} LIMIT ${Math.round(N * 0.1)}`),
  ...sql(`SELECT accession FROM datasets WHERE source='ArrayExpress' ${shuffle} LIMIT ${Math.round(N * 0.1)}`),
  ...sql(`SELECT accession FROM datasets WHERE source NOT IN ('GEO','PRIDE','ENA','ArrayExpress') ${shuffle} LIMIT ${Math.round(N * 0.1)}`),
];
const LOADING = /Reading |Still reading|testing…|Checking/;
const FAILED = /could not|did not send|failed|went wrong/i;
const page = await browser();
await page.width(1280);
const report = [];
for (const acc of picks) {
  const before = page.errors.length;
  const t0 = Date.now();
  await page.goto(`${WEB}/d/${encodeURIComponent(acc)}`);
  const ready = await page.until(PAGE_READY, 90000);
  let settled = await page.until(`!${LOADING}.test(document.body.innerText)`, 120000);
  const text = await page.eval("document.body.innerText");
  const failed = text.split("\n").filter((l) => l.length < 200 && FAILED.test(l)).slice(0, 3);
  const loading = settled ? [] : text.split("\n").filter((l) => LOADING.test(l)).slice(0, 3);
  const sections = await page.eval("[...document.querySelectorAll('h2[id]')].map(h => h.id)");
  const row = { acc, ready: !!ready, ms: Date.now() - t0, sections, failed, loading, errors: page.errors.slice(before).map((e) => e.slice(0, 200)) };
  report.push(row);
  if (!ready || failed.length || loading.length || row.errors.length) await page.shot(join(OUT, `${acc}.png`), true);
  console.log(`${acc.padEnd(14)} ${String(row.ms).padStart(6)}ms ${sections.join(",")} ${failed.length ? "FAILED " + failed.join(" | ") : ""}${loading.length ? " LOADING " + loading.join(" | ") : ""}${row.errors.length ? " ERRORS " + row.errors.length : ""}`);
}
page.close();
writeFileSync(join(OUT, "crawl.json"), JSON.stringify(report, null, 1));
const bad = report.filter((r) => !r.ready || r.failed.length || r.loading.length || r.errors.length);
console.log(`\n${report.length} pages, ${bad.length} with a problem.`);
