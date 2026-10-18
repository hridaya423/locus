# Phase 3: publication-quality figures, and voice mode in the search bar

Status: asked for by Juri at 00:55 BST on 18 October 2026, after Phase 2 passed. Designed, not built, at the time of writing. Two independent pieces; the figures come first because the demo shows them.

## 3.1 Publication-quality differential-expression figures

`omics_agent/deseq2.R` currently writes three plots with ggplot2 defaults. They are legible but they are not figure-quality: default grey theme, no gene labels, no thresholds drawn, one size, PNG only.

What "publication level" means here, concretely. Read the `dataviz` skill before writing any plotting code, and apply it to both the R figures and the web panel so they look like one system.

**Shared style.** One `theme_locus()` in the R script: white panel, thin axis lines, no gridlines except a faint horizontal one where it aids reading, a serif-free typeface at a size that survives being shrunk into a figure panel (base 9–10 pt), consistent margins, no chart junk. A colourblind-safe palette for condition colours, with the same hues used in the web panel. Legends inside the panel where there is room, titles sentence case, no bold title shouting.

**Per figure.**

- **PCA.** Percent variance on both axis labels, points sized to be visible but not blobby, sample names labelled next to points, a faint ellipse or convex hull per condition only if there are ≥3 samples in each, equal aspect so distances are not distorted.
- **Volcano.** Log2 fold change against −log10 adjusted p-value (state which p is plotted in the axis label; do not label it "p-value" when it is adjusted). Significance thresholds drawn as thin dashed lines with their values annotated. Points coloured in three states: not significant, significant, and significant with |log2FC| above the effect threshold. The top 10–15 genes labelled with repelled, non-overlapping labels in italic gene symbols. Axes symmetric about zero.
- **MA.** Mean of normalised counts (log scale, labelled as such) against the shrunken log2 fold change, significant points highlighted, a horizontal line at zero, and the same top genes labelled.
- **Add two conventional panels:** a sample-to-sample distance heatmap (or correlation heatmap) that shows the replicates grouping, and a counts plot for the top 6 genes, points per sample grouped by condition on a log scale. These are what a reviewer looks for alongside the first three.

**Output.** Every figure written at 300 dpi or more at a stated physical size, as PNG for the slides and PDF or SVG as vector for a manuscript, into `plots/`. Keep the existing JSON for the web panel unchanged in shape so nothing downstream breaks.

**Dependencies.** `ggrepel` for labels and a heatmap package are needed; check for `linux-aarch64` builds in the existing micromamba env and install only if available. If a package has no build, implement the panel without it rather than dropping the panel, and record the substitution.

**Acceptance.** Regenerate the figures for GSE273888 from the stored results without re-running the pipeline; print the file list with sizes and dimensions; copy the PNGs into `docs/evidence/process/GSE273888/`; look at each one and state in the status log what it shows (replicates grouping, how many genes pass, which genes are labelled). A figure nobody looked at is not accepted.

## 3.2 Voice mode in the locus search bar

A button in the search bar that lets someone ask their question out loud instead of typing it.

**How.** The browser's own speech recognition (`SpeechRecognition` / `webkitSpeechRecognition`). No new dependency, no API key, nothing sent to a third party by our code. Interim results stream into the textarea as they arrive so the speaker sees it working; the final transcript stays in the textarea for the person to edit before they submit. It does not auto-submit.

**The button.** In the search bar next to the existing submit control, a microphone icon from the icon set already in use, with an `aria-label` and a visible focus ring, reachable by keyboard. Three states: idle, listening (a clear animated indicator and a different icon), and unavailable. Pressing it again stops listening, as does Escape.

**Degrade honestly.** Speech recognition needs both browser support and a secure context: it works on `localhost` and over HTTPS, but **not** over plain HTTP to another machine's IP, which is how the demo browser reaches this app (`http://<pgx-ip>:3020`). So:

- When the API is missing or the context is insecure, the button renders disabled with a tooltip that says why in one short sentence, rather than appearing to work and silently failing.
- Verify this for real: check `window.isSecureContext` in the actual demo setup and write the result in the status log. If voice cannot work over the IP, say so plainly and note the two options (open the app on `localhost` on the presenting machine, or put it behind HTTPS). Do not claim voice works in the demo if it does not.

**Optional, only if the above is finished and solid:** read the model's explanation paragraph aloud with `speechSynthesis`, behind the same button's menu or a small speaker control on the panel. Skip it rather than rush it.

**Acceptance.** `npm run build` and `npm run lint` pass; the button is in the search bar with all three states exercised; a Playwright or manual check shows the transcript landing in the textarea on `localhost`, or, if the browser in use has no support, a recorded check that the button is correctly disabled with its reason; a screenshot in `docs/evidence/process/`; the README mentions voice mode and its secure-context requirement.

## Priority

3.1 before 3.2. Within 3.1: theme and the three existing figures first, then the two added panels. Stop and commit whatever is finished rather than leaving a half-styled figure set.

## Status log

- 2026-10-18 00:55 BST: spec written; no code yet.
- 2026-10-18 01:02 BST (3.1): `r-ggrepel 0.9.8`, `r-pheatmap 1.0.13` and `r-svglite 2.2.2` have linux-aarch64 builds and were installed into `omics-rnaseq`; no substitution needed. The condition pair blue `#2a78d6` / orange `#eb6834` is slots 1–2 of the dataviz skill's reference palette; `validate_palette.js` passes all five checks for the pair (CVD ΔE 24.7, normal-vision 33.6, contrast ≥ 3:1). The grey `#c2c6ca` for "not significant" is a de-emphasis neutral, not a series colour. The web panel now uses the same two hex values.
- 2026-10-18 01:08 BST (3.1): figures regenerated for GSE273888 by running `deseq2.R` on the stored salmon quantifications (no fetch or quant rerun, ~35 s). Output in `data/process/GSE273888/plots/` and copied to `docs/evidence/process/GSE273888/plots/`, each as a 300 dpi PNG and a vector PDF (cairo_pdf): pca 3.6×3.4 in (1080×1020 px), volcano 3.6×3.4 in, ma 3.6×3.4 in, sample_distance 5.4×4.2 in, top_genes_counts 5.2×3.6 in. Looked at every one (three rounds; the first had a legend over a sample label, clipped axis titles and a heatmap laid out for the wrong device, all fixed):
  - **pca.png**: the three untreated samples (blue, PC1 −2.0 to −4.0) and the three rapamycin samples (orange, PC1 +1.0 to +4.2) sit on opposite sides of PC1 (25 % of variance); each sample is labelled with its GSM; a faint hull per condition; legend in the empty bottom-right corner; equal aspect.
  - **volcano.png**: 84 of 6,471 tested genes at padj < 0.05, with dashed lines at padj = 0.05 and log2FC = ±1 annotated; three states (grey not significant, blue significant, orange significant with |log2FC| ≥ 1); the 12 labelled genes in italics are CCN2, KRT7, DDIT4, TPM1, KRT17, PANK3, CCN1, PPP1R12B, THBS1, SCD, CSRP1, IGFBP7; axes symmetric about zero; y axis says "adjusted p-value (BH)".
  - **ma.png**: mean of normalised counts on a log10 axis against the shrunken log2 fold change, zero line, same three states and the same 12 labels; the strongest effects (PPP1R12B −2.28, PANK3 −1.52, CCN2 +1.22) are all at low-to-moderate mean counts, as expected after shrinkage.
  - **sample_distance.png**: Euclidean distances on VST counts; the dendrogram splits the six samples into the three rapamycin and the three untreated replicates, with the orange/blue condition bar matching; within-condition distances are visibly smaller (darker) than between-condition ones.
  - **top_genes_counts.png**: normalised counts of CCN2, KRT7, DDIT4, TPM1, KRT17 and PANK3 per sample on a log10 axis with a group-mean bar; the three replicates of each condition cluster tightly and the direction matches the table (CCN2, KRT7, TPM1, KRT17 up; DDIT4, PANK3 down after rapamycin).
- 2026-10-18 01:12 BST (3.2): microphone button added to the search bar (`web/components/search.tsx`): lucide `Mic`, `aria-label`, visible focus ring, keyboard reachable; three states via `data-voice` (idle; listening with a pulsing ring and a stop icon, stopped by pressing again or Escape; unavailable = disabled with the reason as tooltip and in the aria-label). Interim results stream into the textarea after whatever was typed; nothing auto-submits. `npm run build` and `npm run lint` pass. **Secure-context check in the demo setup (headless Chromium, Playwright):** `http://152.78.149.61:3020` → `isSecureContext: false`, button `unavailable`, disabled, tooltip "Voice needs a secure page: open the app on localhost or over HTTPS."; `http://localhost:3020` → `isSecureContext: true`, button idle → listening (`aria-pressed=true`, status line shown) → Escape returns it to idle with the typed text intact. So **voice does not work over the IP in the demo**; it works if the app is opened on localhost on the presenting machine or put behind HTTPS. A real spoken transcript could not be verified headlessly (no microphone); the listening state and the stop paths were. Screenshots: `docs/evidence/process/voice-ip-unavailable.png`, `voice-localhost-idle.png`, `voice-localhost-listening.png`. Found on the way: without `EXTRA_DEV_ORIGINS=<ip>` the dev server blocks hydration over the IP and the page is static (the button looked idle but inert); the demo dev server must be started with it, as the README already says.
- Optional read-aloud (speechSynthesis) was skipped.

### Acceptance at hand-over (2026-10-18 01:13 BST)

| Item | Result |
|---|---|
| 3.1 figures regenerated, listed with sizes and dimensions, copied to the evidence folder, each looked at and described | pass |
| 3.2 button with three states, build and lint, Playwright check of states, screenshots, README | pass; a live transcript needs a real microphone and was not verified |
| Secure context in the demo setup | verified: false over the IP (voice disabled with reason), true on localhost |
