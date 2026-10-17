// Runs the harness questions through the real web app, opens the top three datasets and one sample of each,
// and saves results, timings, console errors and screenshots at 1280 and 390 px.
// node scripts/harness.mjs [--web http://localhost:3010] [--out DIR] [--only 1,3] [--pages]
// --pages skips the searches and reopens the datasets of the last run in --out (fast regression).
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { browser, sleep, PAGE_READY } from "./cdp.mjs";

export const QUESTIONS = [
  "Matched RNA-seq and Ribo-seq before and after mTOR inhibition",
  "How isoforms of one gene differ in how efficiently they are translated",
  "Lung fibrosis single-cell and proteomics data from patients and healthy controls",
  "Phosphoproteomics of human liver cancer against normal liver tissue",
  "Plasma metabolomics in type 2 diabetes against healthy controls",
  "The gut microbiome of infants born by caesarean section against vaginal birth",
  "Mitochondrial proteomics from organelle immunoprecipitation",
  "Human immunopeptidomics",
];

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const WEB = arg("--web", process.env.LOCUS_WEB ?? "http://localhost:3010");
const OUT = arg("--out", "/tmp/locus-night/harness/latest");
const ONLY = arg("--only", "")?.split(",").filter(Boolean).map(Number);
const PAGES = process.argv.includes("--pages");
mkdirSync(OUT, { recursive: true });

const page = await browser();
const slug = (s) => s.replace(/[^A-Za-z0-9]+/g, "_");

async function both(name, full) {
  await page.width(1280);
  await sleep(400);
  await page.shot(join(OUT, `${name}-1280.png`), full);
  await page.width(390);
  await sleep(600);
  const overflow = await page.eval("document.documentElement.scrollWidth - window.innerWidth");
  await page.shot(join(OUT, `${name}-390.png`), full);
  await page.width(1280);
  return overflow;
}

async function open(url, name) {
  const before = page.errors.length;
  await page.width(1280);
  const t0 = Date.now();
  await page.goto(url);
  const ready = await page.until(PAGE_READY, 60000);
  const ms = Date.now() - t0;
  const outbound = await page.eval(`[...document.querySelectorAll('a[href]')].filter(a => a.host && a.host !== location.host && !a.href.startsWith('mailto:')).length`);
  const overflow = await both(name, true);
  return { url, ready: !!ready, ms, outbound, overflow_390: overflow, errors: page.errors.slice(before) };
}

const previous = PAGES && existsSync(join(OUT, "results.json")) ? JSON.parse(readFileSync(join(OUT, "results.json"), "utf8")) : null;
const results = [];
for (const [n, question] of QUESTIONS.entries()) {
  if (ONLY?.length && !ONLY.includes(n + 1)) continue;
  const run = { n: n + 1, question };
  if (previous) {
    Object.assign(run, previous.find((r) => r.n === n + 1) ?? {}, { pages: [] });
  } else {
    const before = page.errors.length;
    await page.width(1280);
    await page.goto(`${WEB}/`);
    await page.eval("sessionStorage.clear()");
    await page.goto(`${WEB}/`);
    await page.until("!!document.querySelector('textarea') && !document.querySelector('tbody[data-accession]')", 20000);
    const t0 = Date.now();
    await page.eval(`(() => {
      const ta = document.querySelector('textarea');
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(ta, ${JSON.stringify(question)});
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      setTimeout(() => document.querySelector('form').requestSubmit(), 200);
    })()`);
    const done = await page.until(`document.querySelector('tbody[data-accession]') ? 'results' : [...document.querySelectorAll('p')].find(p => p.className.includes('border-foreground/30'))?.textContent`, 240000);
    run.search_ms = Date.now() - t0;
    run.outcome = done;
    await sleep(1500);
    run.rows = await page.eval(`[...document.querySelectorAll('tbody[data-accession]')].flatMap(t => t.dataset.accession.split(' '))`);
    run.top = (run.rows ?? []).slice(0, 3);
    run.overflow_390 = await both(`q${n + 1}-results`, false);
    run.errors = page.errors.slice(before);
    run.pages = [];
  }
  for (const acc of run.top ?? []) {
    const p = await open(`${WEB}/d/${encodeURIComponent(acc)}`, `q${run.n}-${slug(acc)}`);
    p.sample = await page.eval(`[...document.querySelectorAll('a[href^="/d/${encodeURIComponent(acc)}/"]')].map(a => a.getAttribute('href'))[0] ?? null`);
    run.pages.push(p);
    if (p.sample) run.pages.push(await open(`${WEB}${p.sample}`, `q${run.n}-${slug(acc)}-sample`));
  }
  results.push(run);
  const bad = run.pages.filter((p) => !p.ready || p.errors.length || p.overflow_390 > 0).length;
  console.log(`q${run.n} ${run.outcome ?? "pages"} rows=${run.rows?.length ?? "-"} search=${run.search_ms ?? "-"}ms pages=${run.pages.length} bad=${bad} outbound/page=${(run.pages.reduce((s, p) => s + p.outbound, 0) / (run.pages.length || 1)).toFixed(1)}`);
}
page.close();
writeFileSync(join(OUT, PAGES ? "pages.json" : "results.json"), JSON.stringify(results, null, 1));
const pages = results.flatMap((r) => r.pages);
const failed = pages.filter((p) => !p.ready || p.errors.length || p.overflow_390 > 0);
console.log(`\n${pages.length} pages, ${failed.length} with a problem, median load ${pages.map((p) => p.ms).sort((a, b) => a - b)[pages.length >> 1] ?? "-"} ms. Output: ${OUT}`);
for (const p of failed) console.log(`  ${p.url} ready=${p.ready} overflow=${p.overflow_390} ${p.errors.slice(0, 2).join(" | ")}`);
process.exitCode = failed.length ? 1 : 0;
