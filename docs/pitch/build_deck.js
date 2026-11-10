// Builds the 3-minute pitch deck for the Reinvent the Wheel hackathon, 18 Oct 2026.
// Palette and wording follow the locus web app; every number comes from the GSE273888 run.
const pptxgen = require("pptxgenjs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const PLOTS = path.join(ROOT, "data/process/GSE273888/plots");

const THEME = {
  name: "locus",
  headFontFace: "Arial",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "111110", lt1: "FFFFFF", dk2: "2D2B28", lt2: "EFEBE3",
    accent1: "FF5A24", accent2: "111110", accent3: "6B6760",
    accent4: "D9D3C7", accent5: "2D2B28", accent6: "E6E1D7",
    hlink: "FF5A24", folHlink: "6B6760",
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625 in
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.author = "Juri Westendorf";
pres.title = "locus";
const C = pres.SchemeColor;

// Layouts: a cream content frame and a dark frame for the demo and closing slides.
pres.defineSlideMaster({
  title: "LIGHT",
  background: { color: C.background2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.45, w: 8.8, h: 0.9,
      fontSize: 34, bold: true, color: C.text1, fontFace: THEME.headFontFace, valign: "top", align: "left", margin: 0 }, text: "" } },
  ],
});

pres.defineSlideMaster({
  title: "DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.5, w: 8.8, h: 0.9,
      fontSize: 34, bold: true, color: C.background1, fontFace: THEME.headFontFace, valign: "top", align: "left", margin: 0 }, text: "" } },
  ],
});

const NOTE = { fontSize: 11, color: C.accent3, fontFace: THEME.bodyFontFace, isTextBox: true, margin: 0 };

// A stat block: big figure over a small label.
function stat(slide, x, y, value, label, w = 2.3, valueColor = C.accent1) {
  slide.addText(value, { x, y, w, h: 0.72, fontSize: 40, bold: true, color: valueColor,
    fontFace: THEME.headFontFace, isTextBox: true, margin: 0, objectName: `stat-${label}` });
  slide.addText(label, { x, y: y + 0.72, w, h: 0.62, fontSize: 13, color: C.text2,
    fontFace: THEME.bodyFontFace, isTextBox: true, margin: 0 });
}

// ---------------------------------------------------------------- 1. What we built
pres.addSection({ title: "Pitch" });
const s1 = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Pitch" });
s1.addText("From a question to an answer", { placeholder: "title" });

s1.addText(
  [
    { text: "What was not working", options: { bold: true, color: C.text1, fontSize: 15, breakLine: true } },
    { text: "Finding a usable public dataset takes days. The labels are inconsistent, the sample counts are not what they seem, and once you find one you still cannot see what it says.",
      options: { fontSize: 14, color: C.text2, breakLine: true, paraSpaceAfter: 14 } },
    { text: "What locus does", options: { bold: true, color: C.text1, fontSize: 15, breakLine: true } },
    { text: "Ask in plain English. It searches the public archives, reads the sample records to count cases and controls, and then runs the first analysis on your laptop.",
      options: { fontSize: 14, color: C.text2 } },
  ],
  { x: 0.6, y: 1.55, w: 5.3, h: 2.3, isTextBox: true, margin: 0, valign: "top", objectName: "problem-and-answer" }
);

// Three steps, each a tinted card with an orange numeral.
const steps = [["1", "Ask", "A question, typed or spoken"],
               ["2", "Find", "Ranked studies, with counted facts"],
               ["3", "Analyse", "Counts, statistics and figures"]];
steps.forEach(([n, head, sub], i) => {
  const y = 1.55 + i * 0.95;
  s1.addShape(pres.ShapeType.roundRect, { x: 6.25, y, w: 3.15, h: 0.82, fill: { color: C.background1 },
    line: { color: C.accent4, width: 0.75 }, rectRadius: 0.08, objectName: `step-card-${n}` });
  s1.addText(n, { x: 6.45, y: y + 0.08, w: 0.4, h: 0.66, fontSize: 26, bold: true, color: C.accent1,
    fontFace: THEME.headFontFace, isTextBox: true, margin: 0, valign: "middle" });
  s1.addText([{ text: head, options: { bold: true, fontSize: 14, color: C.text1, breakLine: true } },
              { text: sub, options: { fontSize: 11.5, color: C.text2 } }],
    { x: 6.9, y: y + 0.08, w: 2.35, h: 0.66, isTextBox: true, margin: 0, valign: "middle" });
});

s1.addText("Open source · Apache-2.0 · github.com/UoSDDNB/omics-agent", { x: 0.6, y: 4.75, w: 8.8, h: 0.3, ...NOTE });
s1.addNotes("After the video. What was not working, what locus does, the three steps. Keep to 30 seconds, then switch to the browser.");

// ---------------------------------------------------------------- 2. Live demo
const s2 = pres.addSlide({ masterName: "DARK", sectionTitle: "Pitch" });
s2.addText("Live", { placeholder: "title" });
s2.addText("The question we are about to ask", { x: 0.6, y: 1.5, w: 8.8, h: 0.3,
  fontSize: 13, color: C.accent3, fontFace: THEME.bodyFontFace, isTextBox: true, margin: 0 });
s2.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 1.95, w: 8.8, h: 1.25, fill: { color: C.accent5 },
  line: { color: C.accent3, width: 0.75 }, rectRadius: 0.1, objectName: "question-box" });
s2.addText("“bulk RNA-seq of human cells treated with an mTOR inhibitor\nsuch as rapamycin, compared with vehicle”",
  { x: 0.95, y: 1.95, w: 8.1, h: 1.25, fontSize: 19, italic: true, color: C.background1,
    fontFace: THEME.bodyFontFace, isTextBox: true, margin: 0, valign: "middle", lineSpacingMultiple: 1.25 });
s2.addText(
  [
    { text: "Search the archives", options: { bullet: true, breakLine: true } },
    { text: "Open the study it ranks first, with its cases and controls already counted", options: { bullet: true, breakLine: true } },
    { text: "Press Process", options: { bullet: true } },
  ],
  { x: 0.6, y: 3.5, w: 8.8, h: 1.1, fontSize: 15, color: C.background2,
    fontFace: THEME.bodyFontFace, isTextBox: true, margin: 0, paraSpaceAfter: 6 }
);
s2.addNotes("Switch to the browser here. Cached question, so results in about four minutes; press Process while talking. Do not claim a Nextflow run: Process uses salmon on the laptop tier, and the samplesheet button exports the Nextflow handoff.");

// ---------------------------------------------------------------- 3. The result
const s3 = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Pitch" });
s3.addText("Three minutes later, on a laptop", { placeholder: "title" });

s3.addImage({ path: path.join(PLOTS, "pca.png"), x: 0.6, y: 1.5, w: 2.75, h: 2.6, objectName: "pca" });
s3.addImage({ path: path.join(PLOTS, "volcano.png"), x: 3.5, y: 1.5, w: 2.75, h: 2.6, objectName: "volcano" });
s3.addText("Treated and untreated samples separate. Nobody wrote any code.",
  { x: 0.6, y: 4.2, w: 5.65, h: 0.3, ...NOTE });

stat(s3, 6.65, 1.5, "84", "genes changed\n(padj < 0.05)", 2.8);
stat(s3, 6.65, 3.0, "DDIT4 ↓", "a gene that needs mTOR,\nfalling as expected", 2.8, C.text1);


s3.addText("GSE273888 · HeLa cells, rapamycin vs untreated, 3 + 3 · first 2 million reads per sample · every tool version recorded in a manifest",
  { x: 0.6, y: 4.8, w: 8.8, h: 0.3, ...NOTE });
s3.addNotes("The payoff slide. Rapamycin blocks mTOR; DDIT4 depends on mTOR and goes down, so the biology is right. Say the reads are subsampled for speed.");

// ---------------------------------------------------------------- Backup: limits
pres.addSection({ title: "Backup" });
const b1 = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Backup" });
b1.addText("What it does not do yet", { placeholder: "title" });
b1.addText(
  [
    { text: "Reads are subsampled for speed, so the gene counts are smaller than a full run.", options: { bullet: true, breakLine: true } },
    { text: "One comparison per dataset, and we choose which column marks treatment.", options: { bullet: true, breakLine: true } },
    { text: "Bulk RNA-seq only so far. Ribo-seq and proteomics are designed, not built.", options: { bullet: true, breakLine: true } },
    { text: "Proteomics sample counts need an SDRF file, which only some projects have.", options: { bullet: true, breakLine: true } },
    { text: "The heavy pipelines stay on a cluster. We export the files and the command for Nextflow and MaxQuant rather than pretending a laptop can run them.", options: { bullet: true, breakLine: true } },
    { text: "This machine has no index built, so today's search queries GEO, PRIDE and CELLxGENE live rather than all 18.", options: { bullet: true, breakLine: true } },
    { text: "The written summary comes from a model, and a check rejects any number it did not get from us.", options: { bullet: true } },
  ],
  { x: 0.6, y: 1.55, w: 8.8, h: 3.1, fontSize: 15, color: C.text2, fontFace: THEME.bodyFontFace,
    isTextBox: true, margin: 0, paraSpaceAfter: 10 }
);
b1.addNotes("For questions. Being first to name the limits is worth more than being asked.");

// ---------------------------------------------------------------- Backup: underneath
const b2 = pres.addSlide({ masterName: "LIGHT", sectionTitle: "Backup" });
b2.addText("What is underneath", { placeholder: "title" });
stat(b2, 0.6, 1.5, "18", "repositories covered\nby the index", 2.1);
stat(b2, 2.9, 1.5, "891k", "datasets, once the\nindex is built", 2.1);
stat(b2, 5.2, 1.5, "9", "MCP tools, so an\nagent can use it too", 2.1);
stat(b2, 7.5, 1.5, "21", "tests, green from\na clean clone", 2.1);
b2.addText(
  [
    { text: "Counted, not guessed. ", options: { bold: true, color: C.text1 } },
    { text: "Cases and controls are counted in people where the records allow it, and reported as unknown where they do not. The model chooses which field marks treatment; the arithmetic is code.", options: { color: C.text2 }, breakLine: true },
  ],
  { x: 0.6, y: 3.15, w: 8.8, h: 0.7, fontSize: 14, fontFace: THEME.bodyFontFace, isTextBox: true, margin: 0 }
);
b2.addText(
  [
    { text: "Runs on your own hardware. ", options: { bold: true, color: C.text1 } },
    { text: "Search works against a local model, so no data leaves the machine and no API key is needed.", options: { color: C.text2 } },
  ],
  { x: 0.6, y: 3.95, w: 8.8, h: 0.7, fontSize: 14, fontFace: THEME.bodyFontFace, isTextBox: true, margin: 0 }
);
b2.addNotes("For questions about scale, trust, or agent access.");

(async () => {
  const out = path.join(ROOT, "docs/pitch/locus-pitch.pptx");
  await pres.writeFile({ fileName: out });
  const { applyTheme } = require("/home/jlw/.claude/skills/synced/4f6904af-8a55-4326-9f3c-0cacbe56a648_1d30b092-593a-4c38-bbfb-f73d2caa698c/pptx/scripts/apply_theme.js");
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
