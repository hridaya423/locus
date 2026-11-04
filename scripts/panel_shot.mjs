// Opens the web app, runs a question, expands one dataset's row, clicks Process and screenshots the three-row panel,
// then opens the "Here, now" row's results. Evidence for docs/plans/2026-10-19-modalities-overnight.md.
// CHROME=... CHROME_FLAGS=--no-sandbox node scripts/panel_shot.mjs --web http://localhost:3040 --q "..." --acc GSE273888 --out DIR
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { browser, sleep } from "./cdp.mjs";

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const WEB = arg("--web", "http://localhost:3040");
const Q = arg("--q", "Bulk RNA-seq of human cells treated with an mTOR inhibitor such as Torin1 or rapamycin compared with vehicle");
const ACC = arg("--acc", "GSE273888");
const OUT = arg("--out", "docs/evidence/process/panel");
const ROW = arg("--row", "here");
mkdirSync(OUT, { recursive: true });
const page = await browser();
await page.width(1280);
await page.goto(`${WEB}/`);
await page.eval("sessionStorage.clear()");
await page.goto(`${WEB}/`);
await page.until("!!document.querySelector('textarea')", 20000);
const t0 = Date.now();
await page.eval(`(() => {
  const ta = document.querySelector('textarea');
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(ta, ${JSON.stringify(Q)});
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  setTimeout(() => document.querySelector('form').requestSubmit(), 200);
})()`);
const outcome = await page.until(`document.querySelector('tbody[data-accession]') ? 'results' : [...document.querySelectorAll('p')].find(p => p.className.includes('border-foreground/30'))?.textContent`, 900000);
console.log(`search: ${outcome} in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
await sleep(1500);
const rows = await page.eval(`[...document.querySelectorAll('tbody[data-accession]')].flatMap(t => t.dataset.accession.split(' '))`);
console.log(`rows: ${rows.length}; ${ACC} at ${rows.indexOf(ACC) + 1 || "not found"}: ${rows.slice(0, 8).join(" ")}`);
// A dataset grouped with others of the same paper sits inside a group row that must be opened first.
const grouped = await page.eval(`(() => {
  if (document.querySelector('button[aria-label="Details of ${ACC}"]')) return false;
  const tb = [...document.querySelectorAll('tbody[data-accession]')].find(t => t.dataset.accession.split(' ').includes('${ACC}'));
  const b = tb && tb.querySelector('button[aria-expanded]'); if (!b) return false; b.click(); return true; })()`);
if (grouped) await sleep(1200);
const expanded = await page.eval(`(() => {
  const b = document.querySelector('button[aria-label="Details of ${ACC}"]'); if (!b) return false; b.click(); return true; })()`);
if (!expanded) { console.log("row not found"); page.close(); process.exit(1); }
await sleep(1200);
const clicked = await page.eval(`(() => {
  const tb = document.querySelector('tbody[data-accession="${ACC}"]'); const b = [...tb.querySelectorAll('button')].find(b => b.textContent.trim() === 'Process'); if (!b) return false; b.click(); return true; })()`);
console.log(`Process button: ${clicked}`);
await page.until(`!!document.querySelector('[data-options="${ACC}"] li[data-row]') || /Not processed here|cannot/.test(document.querySelector('tbody[data-accession="${ACC}"]')?.innerText ?? '')`, 180000);
await sleep(800);
const panel = await page.eval(`document.querySelector('[data-options="${ACC}"]')?.innerText ?? document.querySelector('tbody[data-accession="${ACC}"]').innerText`);
console.log("--- panel text ---\n" + panel + "\n---");
await page.eval(`document.querySelector('[data-options="${ACC}"]')?.scrollIntoView({block: 'start'})`);
await sleep(400);
await page.shot(join(OUT, `${ACC}-rows-1280.png`), false);
await page.width(390);
await sleep(800);
await page.eval(`document.querySelector('[data-options="${ACC}"]')?.scrollIntoView({block: 'start'})`);
await page.shot(join(OUT, `${ACC}-rows-390.png`), false);
await page.width(1280);
const ran = await page.eval(`(() => {
  const li = document.querySelector('[data-options="${ACC}"] li[data-row="${ROW}"]'); const b = li && [...li.querySelectorAll('button')].find(b => /Run|Show the results/.test(b.textContent)); if (!b) return false; b.click(); return true; })()`);
console.log(`${ROW} row started: ${ran}`);
if (ran) {
  await page.until(`!!document.querySelector('[data-run="${ROW}"] figure') || /text-warn/.test(document.querySelector('[data-run="${ROW}"]')?.innerHTML ?? '')`, 1800000);
  await sleep(2500);
  await page.eval(`document.querySelector('[data-options="${ACC}"]')?.scrollIntoView({block: 'start'})`);
  await page.shot(join(OUT, `${ACC}-${ROW}-results-1280.png`), false);
  console.log("--- results text ---\n" + (await page.eval(`document.querySelector('[data-run="${ROW}"]')?.innerText.slice(0, 1500)`)) + "\n---");
}
writeFileSync(join(OUT, `${ACC}-panel.txt`), panel);
console.log("errors:", page.errors.slice(0, 5));
page.close();
