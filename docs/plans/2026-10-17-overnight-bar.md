# Overnight bar: locus becomes the lab's intern

This is the contract for an unattended overnight run. The lead agent reads it in full before any change. Builders receive only the piece they work on. Critics receive this file, the candidate running in a browser, and the evidence.

## The north star

A researcher types one question and locus does what a good **intern** would do in a week: search every repository, read every record, tell them which datasets truly fit and why, hand them the data labelled and ready, and show a first look at what is in it. They never open GEO, PRIDE, ENA or MetaboLights again.

Every page locus shows is a place the researcher never has to leave. A link that leaves locus, a value that cannot be clicked, or a question the page cannot answer is unfinished work.

Two questions judge every piece. Does it raise a judging score (impact, technical execution, presentation)? Would a researcher who sees it tell a colleague about it? A piece that does neither is not built.

The judges score Impact, Technical execution and Presentation, 10 points each, from a three-minute demo and two minutes of questions: what is the software for, what was not working, what did you make better. The brief asks for agentic AI that improves scientific software that is hard to use, disconnected, closed, or has no endpoint for agents. The judges are Alexander Hasson (Apheris), Maxim Tsenkov (PDBe), Cyril Schröder (Ellison Institute of Technology), Austin Mroz (CuspAI), Ed Hughes (Inherent) and Joanne Sheppard (UCL).

## Who it is for

Three researchers told the team what they need, in their own words, in `interviews/product-charlie.md`, `interviews/product-jurilw.md` and `interviews/product-oantico.md`. Read all three. Their tasks are the test tasks, their trust conditions are the receipts locus must show, and their complaints are the moments locus must remove. For example: proof that RNA-seq and Ribo-seq samples are matched, the authors' own QC, the paper's supplementary tables, why a dataset was returned, and real, checkable references only.

## The bar

The bar is the work locus replaces, which the critic can open tonight:

- **The repository's own pages.** For any page or capability, the critic does the same task on the repository's site (GEO series and sample pages, PRIDE project pages, ENA, ArrayExpress, MetaboLights, CELLxGENE) and on locus. locus wins when the task takes fewer clicks and less time, nothing is wrong, and the researcher never had to leave.
- **The best data pages anyone has built**, for craft. cBioPortal's study summary page (for example https://www.cbioportal.org/study/summary?id=luad_tcga_pan_can_atlas_2018), where every chart filters every other chart and the sample list, and the Hugging Face dataset viewer (for example https://huggingface.co/datasets/scikit-learn/iris), which previews a data file in the page. The critic screenshots them at the same width and compares blind.
- **The paper.** Any analysis or summary locus shows agrees with the authors' records and published results, or states where and why it differs.
- **The best general assistant**, at milestones only. Claude Opus 5.5 with web search, asked the same question. locus must be more correct and more usable.

## How the run finds what to build

The sample pages were found by using locus: a sample accession on the dataset page linked out to GEO, so locus needed its own sample page. The run finds work the same way, with three engines that run from the start, not only when the ladder runs out.

1. **The door audit (a script).** Crawl the dataset and sample pages of 30 datasets chosen at random across repositories and data types. List every link that leaves locus and every value on screen that names a thing a researcher would want to open: a platform, a person, a paper, a linked record, a characteristic value, a file. Count each kind across pages. Each frequent door is a candidate: a locus page, a filter, a preview, or a link to a page locus already has. Rerun after every milestone; the count of outbound links per page should fall.
2. **The task audit (interviews).** Turn each interview's tasks into concrete tasks on real datasets, for example "show that these RNA-seq and Ribo-seq libraries come from the same samples", "find the authors' processed protein table", "how many female IPF samples are biopsies". A critic does each task on the repository's site and on locus in a real browser, and logs clicks, seconds, and every time it had to leave locus.
3. **Use sessions.** After each milestone, a critic plays one expert at a time (a wet-lab biologist, a mass-spectrometry chemist, a computational scientist, then each judge) and works a harness question to the point where they would start their own analysis. It logs every moment they left locus, did something by hand, distrusted a number, or ignored a section.

Every door, task step and moment is one line in `progress.md` under "Moments", with the page and the dataset.

**Look back before adding.** For each kept rung, count how many sessions and tasks touched it and whether it changed what the expert did next. A rung that nothing used is deleted or merged, and its direction gets no new rungs. A rung that was used often earns the next rungs in its direction.

**New rungs come only from moments.** A candidate names the moments it removes, who hit them, what done looks like, and the gate that proves it. Rank candidates by how many moments they remove, then by how strongly a judge would retell them, then by smallness. Build the top one. Add new rungs to `progress.md` under "Ladder, found tonight", with their moments.

**Guards on growth.**
- A rung with no logged moment is not built, however good it sounds.
- Polish of one capability gets at most two rungs in a row; then the next rung must remove a different moment.
- A rung that adds a section must also remove or merge one, unless a task or session asked for it.
- If no candidate is left, rerun the engines on unseen repositories, diseases and data types.

## The ladder

The seed ladder, in order. The engines reorder and extend it; the order of the tiers holds.

**Tier 1. Pages the researcher never has to leave.** The dataset page (`/d/<accession>`, `web/components/dataset.tsx`, `omics_agent/record.py`) shows everything the repository page shows for GEO, PRIDE, ENA and ArrayExpress, and a stored summary for the other repositories. GEO samples and ENA runs have their own pages (`/d/<dataset>/<sample>`, `web/components/sample.tsx`). Build on them; do not rebuild them. `uv run python -m omics_agent.record` fails if a real record has a field the page does not show; keep it passing.
1. **Samples that filter each other.** Clicking a level in any factor chart filters the sample table and every other chart, as on cBioPortal; the filtered samples download as a sample sheet and narrow the download commands to their files.
2. **Cases and controls in the sample table.** For the search's question, mark each sample case, control or other, with the record field and value that decided it.
3. **Preview a file.** The first rows and the columns of a processed table, read from the first bytes of the file. When the columns are sample accessions, say so and show which group each column belongs to.
4. **The paper's page.** Title, abstract, the data availability sentence, every dataset from the same paper, and the paper's supplementary tables (from Europe PMC), which is where many researchers find processed data today.
5. **Doors become pages.** The doors the audit counts most often, for example a platform with every locus dataset measured on it, a contributor or lab head with their other datasets and papers, the journals they publish in and their papers' supplementary data (the track record jurilw uses to trust a source), and linked SuperSeries, SubSeries and BioProjects opened in locus when locus has them.
6. **QC from the records.** Reads and bases per sample from the run table, as a chart that flags outliers, and the authors' QC criteria quoted from the data processing text (jurilw: "70% cutoff for PIF of RPF signal and presence only in CDS").
7. **Design check and power.** Traps an expert looks for (condition confounded with batch, very small groups, controls of a different tissue or cell type, unmatched assays), each linked to its evidence, and the smallest change the study could reliably detect.
8. **Paste anything, land on locus.** A GSE, GSM, SRR, PXD, E-MTAB, PRJ, PMID or DOI pasted into the search box, or put in the URL, opens the locus page it names; a PMID or DOI opens the paper's page with every dataset from that paper. This is jurilw's workflow today: Google the paper, Ctrl-F for the GSE, paste it into GEO.
9. **Why it matched, on the page.** Opened from a search, the dataset page highlights the matched terms and the method evidence (for example 10x Chromium, TMT, anti-HLA) in its text, and each check on the row links to the highlighted line. charlie asked for this.
10. **Classified from protocol evidence.** The technology read from protocols, reagents and instruments, not the author's label: 10x Chromium means droplet single-cell RNA-seq, SMART-seq2 plate-based single-cell, TMT quantitative proteomics, anti-HLA antibodies (for example W6/32) immunopeptidomics, Visium spatial transcriptomics. Each classification shows its evidence line, and the results show the synonyms the search added. charlie asked for this; harness question 8 tests it.
11. **Assays never confused.** TIS-seq (harringtonine or lactimidomycin) is not elongating Ribo-seq, and Ribo-seq does not resolve isoforms. locus checks each assay label against the methods text, shows the line that decides it, and keeps a mislabelled library out of samplesheets and comparisons. riboseq-agent once took TIS-seq for Ribo-seq, which is why jurilw distrusts agents here.
12. **Matched libraries.** For studies with more than one assay (RNA-seq and Ribo-seq, proteome and phosphoproteome), show which libraries come from the same biological sample, side by side, and quote the methods sentence that says where and how the sample was split. jurilw needs this proof before trusting translation-efficiency labels; `samplesheet._pairs` already pairs Ribo-seq and RNA-seq libraries by title.

**Tier 2. The data itself.** A teammate owns processing: `docs/data-processing-contract.md` (merged from `origin/main`) defines the tiers, the tools and the common output shape (sample by feature matrix, sample metadata, feature annotation, tracks). Do not write pipelines or processing kits. Fetch what already exists, and shape it as the contract says.
13. **Get the table.** One click for the finished, processed table with every sample labelled, plus a provenance file, in formats that load in one line of Python or R. Sources: NCBI-generated raw counts for human GEO RNA-seq (`https://www.ncbi.nlm.nih.gov/geo/download/?acc=<GSE>` lists them; GSE124685 has a 2.8 MB matrix whose columns are the GSM IDs locus labels, GSE213001 has none), GEO supplementary matrices, PRIDE protein tables (`sources.pride_files`), MetaboLights and Expression Atlas processed tables, and CELLxGENE summary counts (never the full `.h5ad`).

**Tier 3. A first look.**
14. **Volcano plot** (https://en.wikipedia.org/wiki/Volcano_plot_(statistics)) on the dataset page, from the table: each gene's change between cases and controls against its significance, with the method, the group sizes and the multiple-testing correction shown. Proteins too, for PRIDE protein tables.
15. **The paper's genes on the plot.** The genes the paper reports, read from its open-access text, highlighted on our plot; where they land is the check that our numbers are right.
16. **What the top genes do.** Pathways from Enrichr (a free public service) for the top genes.

**Tier 4. Across datasets.**
17. **Your gene, everywhere.** One gene in; its change in every comparable dataset, one row per dataset. *For example: SPP1 rises in IPF in five of five datasets.*
18. **The answer.** At the top of the results, the two or three best datasets and the one fact that makes each the best, each a link to its evidence.
19. **Watch a search.** A saved question shows the datasets added since the last visit, from locus's own harvests. This is jurilw's standing job.
20. **Bring your own list.** A pasted gene or protein list is matched against a dataset's processed table and against the other datasets of the same type: overlap, and where each hit ranks. This is oantico's ask, starting with mitochondrial proteins.

Build on what exists: `omics_agent/record.py`, `design.py`, `samplesheet.py`, `compare.py`, `methods.py`, `sources.download_plan` and `sources.pride_files`, the MCP server, and the components in `web/components/`. The environment has numpy, scipy and scikit-learn. Add a library only when it is the standard tool for the job, and record why.

## Steps

0. **Before the run (the user).** Commit the day's work, then merge `origin/main` into it; that brings the teammate's processing contract, the interviews and configurable ports. Start the run from that commit.
1. **Isolate.** Create a git worktree on a new branch `overnight/<date>`. Other sessions use this checkout and ports 8000 and 3000. Run the API with `OMICS_API_PORT=8010` and the web app on port 3010 with `OMICS_API_URL=http://localhost:8010`.
2. **Build the harness.** One script runs the six questions below through the real web app in a headless browser, opens the top three datasets' pages and one sample page each, and saves results, screenshots at 1280 px and 390 px, console errors and timings. A second script is the door audit. Commit both before any feature work. Keep them fast; they run after every piece.
3. **Climb.** Up to three capabilities in flight at once, each a different feature that touches different files, each with one builder in its own worktree. Never two agents on one feature, one file or one idea, and no agents that only brainstorm. When two pieces need the same file, run them one after the other. A builder makes the smallest version that does the whole job, including its MCP tool; a critic with fresh context runs the piece gates. Keep it only if every piece gate passes; otherwise revert and log why.
4. **Review at each milestone.** A milestone is each finished tier, or four kept pieces, whichever comes first. Then rerun the three engines, update `docs/moments.md` and run the milestone gates. `docs/moments.md` is raw material for the user's motion-design video, which the user makes separately: for each kept feature, the moment a researcher would retell, the claim it proves, the dataset it was shown on, a screenshot at 1280 px, and a short screen capture of the interaction (under `docs/moments/`). A failed milestone gate does not revert anything; its gap becomes the next piece.
5. **Keep climbing** until 06:00 or until the user stops the run. Finishing the ladder is never a reason to stop.
6. **Hand off by 07:00.** The pitch is in the morning. From 06:00, start no new piece: run the final milestone review, refresh the captures in `docs/moments.md` so they show the final UI, and write the morning report.

## Questions

The harness set, used for regression and for choosing real datasets to test on:

1. Matched RNA-seq and Ribo-seq before and after mTOR inhibition.
2. How isoforms of one gene differ in how efficiently they are translated.
3. Lung fibrosis single-cell and proteomics data from patients and healthy controls.
4. Phosphoproteomics of human liver cancer against normal liver tissue.
5. Plasma metabolomics in type 2 diabetes against healthy controls.
6. The gut microbiome of infants born by caesarean section against vaginal birth.
7. Mitochondrial proteomics from organelle immunoprecipitation (from the oantico interview).
8. Human immunopeptidomics (from the charlie interview).

## Piece gates

Run after every piece. Cheap and fast: checkable facts are checked by scripts, not by opinion.

| Gate | Method | Pass condition |
|---|---|---|
| Works on real data | The critic picks three eligible datasets at random from the harness results, never the builder's examples, and runs the capability on each. | It does the whole job on all three, or says clearly why one is not eligible. A first look agrees with the paper or states why not. |
| Beats the website | The critic does the same task on the repository's own site. | locus takes fewer clicks and less time, with nothing wrong and no need to leave. |
| Craft | The critic screenshots the changed page next to the matching bar page (cBioPortal study summary or Hugging Face dataset viewer) at the same width, labels stripped. | A designer would pick ours, or name one gap that becomes the next piece. |
| States | The critic loads the changed screens with a slow network, a dataset with no samples, a dataset with thousands of samples, a failed request, and long values. | Each has a deliberate loading, empty, error and overflow state; nothing breaks the layout. |
| Doors | The door audit on the changed pages. | No new link leaves locus where locus has the page. |
| Receipts | The critic opens ten random numbers and claims on screen. | Each opens the record, file or paper line it came from; unverifiable values read "not stated". |
| Clean | The critic screenshots the changed screens at 1280 px and 390 px and applies the slop rules below. | No rule is broken. |
| Agent tool | The critic calls the piece's MCP tool on the same three datasets. | It returns the same facts the page shows, with their sources. The brief names "no endpoints for agentic control" as a problem; every capability is also a tool. |
| Regression | The harness, the self-checks, `tsc` and `eslint`, keyboard-only use of the changed controls. | Every question and page works at both widths, with no console errors, no slower than before. |

## Milestone gates

| Gate | Method | Pass condition |
|---|---|---|
| Beats the assistant | Claude Opus 5.5 with web search answers the harness questions; the critic compares blind, playing a wet-lab biologist, a mass-spectrometry chemist and a computational scientist. | The experts would act on locus first, every time. |
| Interview tasks | Every task from the task audit, on locus only. | Each is done without leaving locus, or the gap is the next piece. |
| Unseen datasets | The same capabilities on three datasets from repositories and diseases the night has not touched. | They work, or state clearly why not. |
| Shock | The critic plays each judge and goes through `docs/moments.md` and its captures, without the claims column. | Each judge names a moment they would retell; none calls a claim unproven. |
| Hard questions | Two hardest questions per judge, from their field. | Each is answerable from the product in under 30 seconds. |
| Teach-back | A critic with no science background goes through the captures in `docs/moments.md`. | In two sentences it states what the tool is for, what was not working, and what locus makes better. |
| Whole-page clean | The deletion test on every screen, not only the changed ones. | Nothing an expert would not miss. Removing things counts as progress. |

## Slop rules

Clean is a gate, not a taste. A screen fails if any of these holds:

- A sentence on screen without a source, or text that restates what the screen already shows.
- Model-written prose longer than two sentences anywhere. Insight is shown as numbers, labels, charts and links.
- A new colour, font, radius or shadow outside `web/app/globals.css`; motion that does not explain a change of state.
- An expanded result row taller than one screen at 1280 px, or a section an expert would not open.
- The same fact shown twice on one page, or on the result row and the page it opens.
- A chart that cannot be read without its legend, or that encodes nothing a table would not show better.
- A visible "agent step", spinner or progress line that is not a real call whose result can be opened.
- A feature that works only on the demo datasets.

When the critic compares two versions, ties go to the shorter and simpler one. Length is never evidence of quality.

## Budget of attention

Spend the night building. Checkable facts (counts, files, links, matches to the paper) are checked by scripts. Critics judge only what scripts cannot. No expert gold answers are written; the records, the files, the papers and the interviews are the ground truth.

## Boundaries

- Commit locally on the night's branch, one commit per kept piece. Pushing, deploying and merging wait for the morning. Do no deploy or public-hosting work at all; the user will decide on it much later, if ever.
- Treat `data/` and `~/.cache/omics-agent/` as append-only: add rows and files, keep existing ones.
- This is a small machine. No pipelines run here. Fetch processed tables up to 200 MB each and only the first bytes of larger files for previews, never raw files, and keep everything under `~/omics-data/`, which the user can delete. Analysis runs on processed tables in seconds, in memory.
- Every number and claim on screen comes from a record, a file or a paper. A value locus cannot verify reads "not stated".
- If a piece fails its gates three times with the same approach, change the approach or log it as stalled and move to the next rung.
- Subagents run on Claude Sonnet 5.5 (`claude-sonnet-5-5`), as AGENTS.md says. Use one only for a distinct feature or a distinct check; an agent whose work overlaps another's is waste.
- Paid API calls have hard caps for the whole night: Claude Opus 5.5 at most $5 (the milestone comparison) and Claude Haiku 5.5 at most $3 (locus's own searches in the harness, which reuse cached answers). Log the spend in the morning report and stop that kind of call at the cap.

## Morning report

In `progress.md`: the rungs climbed and their evidence (screenshots before and after, the random datasets each capability was tested on); the door audit counts at the start and the end; the interview tasks, with clicks and time on the repository site and on locus; the rungs the run found itself, with the moments that justified them; the rungs deleted by the look back; reverted and stalled pieces with the reason; everything removed; `docs/moments.md` with its captures; the MCP tools added; the API spend against the caps; the commands to rerun the harness, the door audit and the captures.
