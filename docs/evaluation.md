# How locus is checked

Every number below comes from a script in this repository or a log named in `progress.md`. Failures are listed with the successes.

| What | Ground truth | Result | Known failures |
|---|---|---|---|
| Search recall against Claude Opus 5.5 with web search (8 harness questions) | The datasets Opus named that locus indexes (34) | locus returns 15, 12 of them graded strong (was 14 and 11 before the question became its own ranking) | HLA Ligand Atlas (PXD020186) is cut at triage; GSE100007 and PXD058312 are never retrieved; q4 and q7 return none of Opus's picks |
| Assay labels, footprint libraries | Every cached Ribo-seq study title (4,273) | The title rule holds on all of them (`uv run python -m omics_agent.assay`) | A fresh check at 02:55 found RP, TTS, disome and input libraries mislabelled; fixed, then rechecked |
| Assay labels, other data types | 16 random GEO, PRIDE and ArrayExpress pages; 12 random PRIDE studies with papers | 1 false claim (a tiling array also called ChIP-seq), fixed; 0 spurious additions from papers | Assays named only in a paper behind a paywall are missed |
| First look against the paper | Genes the paper names (Europe PMC full text or text-mined) | GSE124685: 50 of 63 paper genes significant, 3.2 expected by chance; GSE86618: 35 of 97, 4.2 by chance | A screen (Welch t-test), not DESeq2; single-cell data is flagged as nested in people, not corrected |
| One gene everywhere | SPP1 in IPF, a known marker | Higher in 6 of 10 lung datasets that could answer, lower in none; 2 flagged as samples nested in donors | Datasets without a processed table cannot answer (17 looked at, 10 compared) |
| Case and control counts | Raw GEO sample records | GSE328392 102/90 and GSE326573 19/20 exact; GSE86618 counts 6 and 3 people, not 325 and 215 cells | Counts depend on a model reading which field names the groups; cached per question |
| Pages | 8 harness questions × top 3 datasets + a sample page each, at 1280 and 390 px | 36 pages, 0 problems, median load 327 ms | Cold GEO records can take 30–150 s the first time |
| Random pages | 60 + 7 × 40 random dataset pages across repositories (`scripts/crawl.mjs`) | 4 problems in the first crawl (fixed); 0 in each later crawl | — |
| Doors (`scripts/doors.mjs`, 30 random datasets) | Values on screen that a researcher would open | Values that open nothing per page 20.03 → 14.32; outbound links 5.97 → 5.63 | Dates, status and file downloads stay plain |
| Interview tasks (`progress.md`, task audit) | 10 tasks from three interviews, timed on the repository's site and on locus | 8 done without leaving locus; 2 partly | Task 1: GSE36892's GEO methods never say the lysate was split. Task 10: GSE136831 records no biopsy field. Task 3: the authors' periodicity and replicate checks are stated nowhere locus can read, and locus says "not stated" |
| MCP | Every public function in `mcp_server.py` | 25 tools registered (`uv run python scripts/mcp_check.py`) | Three tools were silently unregistered by a merge until 03:46 |
