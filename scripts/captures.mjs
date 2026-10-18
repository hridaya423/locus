// Captures for docs/moments.md: for each moment, a 1280 px screenshot of the final state and a short MP4 of the interaction.
// node scripts/captures.mjs [--web http://localhost:3010] [--only slug,slug]
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { browser, sleep } from "./cdp.mjs";

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const WEB = arg("--web", process.env.LOCUS_WEB ?? "http://localhost:3010");
const ONLY = arg("--only", "").split(",").filter(Boolean);
const OUT = new URL("../docs/moments/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

const typeInto = (selector, text) => `(() => { const el = document.querySelector(${JSON.stringify(selector)}); const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement : HTMLInputElement;
  Object.getOwnPropertyDescriptor(proto.prototype, "value").set.call(el, ${JSON.stringify(text)}); el.dispatchEvent(new Event("input", { bubbles: true })); return true })()`;
const submit = (selector) => `(() => { document.querySelector(${JSON.stringify(selector)}).closest("form").requestSubmit(); return true })()`;
const click = (text, scope = "button, a, summary") => `(() => { const el = [...document.querySelectorAll(${JSON.stringify(scope)})].find((e) => e.textContent.trim().startsWith(${JSON.stringify(text)})); el?.scrollIntoView({ block: "center" }); el?.click(); return !!el })()`;
const scrollTo = (selector) => `(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; window.scrollTo({ top: el.getBoundingClientRect().top + scrollY - 40, behavior: "smooth" }); return true })()`;
const scrollText = (text, scope = "h2, h3") => `(() => { const el = [...document.querySelectorAll(${JSON.stringify(scope)})].find((e) => e.textContent.includes(${JSON.stringify(text)})); if (!el) return false; window.scrollTo({ top: el.getBoundingClientRect().top + scrollY - 40, behavior: "smooth" }); return true })()`;
const fresh = `(() => { sessionStorage.clear(); return true })()`;
const IPF_BULK = "Bulk RNA-seq of lung tissue from idiopathic pulmonary fibrosis patients and healthy controls";
const MTOR = "Matched RNA-seq and Ribo-seq before and after mTOR inhibition";

export const MOMENTS = [
  { slug: "gene-everywhere", steps: [["go", "/"], ["eval", fresh], ["go", "/"], ["wait", "!!document.querySelector('textarea')"], ["eval", typeInto("textarea", IPF_BULK)], ["pause", 400], ["eval", submit("textarea")],
    ["wait", "!!document.querySelector('#gene-across')", 240000], ["pause", 1200], ["eval", scrollTo("#start-with")], ["pause", 1500], ["eval", typeInto("#gene-across", "SPP1")], ["pause", 600], ["eval", submit("#gene-across")],
    ["wait", "/datasets that could answer/.test(document.body.innerText)", 400000], ["pause", 1500]] },
  { slug: "start-with", steps: [["go", "/"], ["eval", fresh], ["go", "/"], ["wait", "!!document.querySelector('textarea')"], ["eval", typeInto("textarea", MTOR)], ["pause", 400], ["eval", submit("textarea")],
    ["wait", "!!document.querySelector('#start-with')", 240000], ["pause", 800], ["eval", scrollTo("#start-with")], ["pause", 2000]] },
  { slug: "tis-trap", steps: [["go", "/d/GSE255191"], ["wait", "!!document.querySelector('#measured') && !/Reading the methods/.test(document.body.innerText)", 120000], ["pause", 800], ["eval", scrollTo("#measured")], ["pause", 2500]] },
  { slug: "matched-split", steps: [["go", "/d/GSE132703"], ["wait", "/split in two/.test(document.body.innerText)", 120000], ["eval", scrollTo("#measured")], ["pause", 1500], ["eval", click("Ribo-seq (elongating", "summary")], ["pause", 2500]] },
  { slug: "first-look-paper", steps: [["go", "/d/GSE124685"], ["wait", "/The paper mentions/.test(document.body.innerText)", 180000], ["eval", scrollTo("#first-look")], ["pause", 3000]] },
  { slug: "quality-top-ups", steps: [["go", "/d/GSE132703"], ["wait", "!!document.querySelector('#quality')", 180000], ["eval", scrollTo("#quality")], ["pause", 2500]] },
  { slug: "samples-filter", steps: [["go", "/d/GSE173357"], ["wait", "!!document.querySelector('#samples')", 120000], ["eval", scrollTo("#samples")], ["pause", 1200], ["eval", click("ipf", "button[aria-pressed]")], ["pause", 1500],
    ["eval", click("female", "button[aria-pressed]")], ["pause", 2500]] },
  { slug: "file-preview", steps: [["go", "/d/GSE86618"], ["wait", "!!document.querySelector('#files')", 120000], ["eval", scrollTo("#files")], ["pause", 1200], ["eval", click("Preview")], ["wait", "/IPF/.test(document.querySelector('#files').parentElement.innerText)", 60000], ["pause", 2500]] },
  { slug: "paste-paper", steps: [["go", "/"], ["eval", fresh], ["go", "/"], ["wait", "!!document.querySelector('textarea')"], ["eval", typeInto("textarea", "PMID: 35680905")], ["pause", 600], ["eval", submit("textarea")],
    ["wait", "/Deposited/.test(document.body.innerText)", 120000], ["pause", 2500]] },
  { slug: "cases-controls", steps: [["go", "/d/GSE173357"], ["wait", "!!document.querySelector('#samples') && /control/.test(document.querySelector('#samples').parentElement.innerText)", 120000], ["eval", scrollTo("#samples")], ["pause", 2500]] },
  { slug: "contributor", steps: [["go", "/d/GSE132703"], ["wait", "!!document.querySelector('#about')", 120000], ["pause", 800], ["eval", click("Carson C Thoreen", "aside a")], ["wait", "/Datasets in locus/.test(document.body.innerText)", 60000], ["pause", 2500]] },
  { slug: "pathways", steps: [["go", "/d/GSE124685"], ["wait", "/Pathways higher/.test(document.body.innerText) && !/Asking Enrichr/.test(document.body.innerText)", 180000], ["eval", scrollText("Pathways higher")], ["pause", 2500]] },
  { slug: "ribo-checks", steps: [["go", "/d/GSE132703"], ["wait", "/Ribo-seq checks/.test(document.body.innerText)", 180000], ["eval", scrollText("Ribo-seq checks")], ["pause", 2500]] },
  { slug: "mito-ip-paper", steps: [["go", "/d/PXD058312"], ["wait", "/from the paper/.test(document.body.innerText)", 180000], ["eval", scrollTo("#measured")], ["pause", 1200], ["eval", click("Organelle IP", "summary")], ["pause", 2500]] },
  { slug: "design-check", steps: [["go", "/d/GSE150910"], ["wait", "/detectable/.test(document.body.innerText)", 240000], ["eval", scrollTo("#first-look")], ["pause", 3000]] },
  { slug: "your-list", steps: [["go", "/list?in=GSE124685"], ["wait", "!!document.querySelector('textarea')"], ["eval", typeInto("textarea", "COL1A1 COL3A1 MMP7 SPP1 CTHRC1 POSTN SDHB TOMM20 CYC1 P08574 ACTB GAPDH")], ["pause", 600], ["eval", submit("textarea")],
    ["wait", "/MitoCarta 3.0 mitochondrial proteins/.test(document.body.innerText)", 240000], ["pause", 2500]] },
  { slug: "zip-preview", steps: [["go", "/d/PXD047213"], ["wait", "!!document.querySelector('#files') && !/Reading /.test(document.body.innerText)", 120000], ["eval", scrollTo("#files")], ["pause", 1200], ["eval", click("Preview")], ["wait", "/inside the zip/.test(document.body.innerText)", 60000], ["pause", 2500]] },
  { slug: "doors-browse", steps: [["go", "/d/PXD010450"], ["wait", "!!document.querySelector('#about')", 120000], ["pause", 800], ["eval", click("Immunopeptidome", "aside a")], ["wait", "/datasets in locus/.test(document.body.innerText)", 60000], ["pause", 2500]] },
];

async function capture(page, moment) {
  const frames = mkdtempSync(join(tmpdir(), "locus-frames-"));
  let n = 0;
  const onFrame = async (m) => {
    if (m.method !== "Page.screencastFrame") return;
    writeFileSync(join(frames, `${String(n++).padStart(5, "0")}.jpg`), Buffer.from(m.params.data, "base64"));
    page.send("Page.screencastFrameAck", { sessionId: m.params.sessionId });
  };
  page.listen(onFrame);
  await page.send("Page.startScreencast", { format: "jpeg", quality: 80, maxWidth: 1280, maxHeight: 900, everyNthFrame: 2 });
  for (const [kind, value, ms] of moment.steps) {
    if (kind === "go") await page.goto(`${WEB}${value}`);
    if (kind === "eval") await page.eval(value);
    if (kind === "wait" && !(await page.until(value, ms ?? 60000))) throw new Error(`${moment.slug}: timed out waiting for ${value}`);
    if (kind === "pause") await sleep(value);
  }
  await page.send("Page.stopScreencast");
  page.unlisten(onFrame);
  await page.shot(join(OUT, `${moment.slug}.png`));
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", "15", "-pattern_type", "glob", "-i", join(frames, "*.jpg"), "-vf", "scale=1280:-2,format=yuv420p", "-movflags", "+faststart", join(OUT, `${moment.slug}.mp4`)]);
  rmSync(frames, { recursive: true, force: true });
  return n;
}

const page = await browser();
await page.width(1280);
for (const moment of MOMENTS.filter((m) => !ONLY.length || ONLY.includes(m.slug))) {
  try {
    console.log(moment.slug, await capture(page, moment), "frames");
  } catch (error) {
    console.log(moment.slug, "FAILED", error.message);
  }
}
page.close();
