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
