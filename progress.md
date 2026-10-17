# Progress

## Done
- CLI `omics` searches GEO, PRIDE, and CELLxGENE from a plain-English question (Claude Haiku 5.5 via the Anthropic API).
- GEO single-cell filter: single-cell questions now return single-cell GEO studies.
- Sample-level facts for GEO (case/control counts from sample records, including title patterns and mixed pools) and CELLxGENE (controls from disease labels).
- Rule-based grading from four checks; counted facts override the model.
- Same-paper bundles across repositories (PMID, DOI → PMID through Europe PMC). Logic verified on a known PMID/DOI pair; the fibrosis query found no cross-repository pair.
- NCBI rate-limit retry (HTTP 429).
- Plan cache per question in `~/.cache/omics-agent/plans.json`.

## Evidence (fibrosis question, single-cell + proteomics, patients + controls)
- Counts checked against raw GEO records: GSE328392 IPF 102 / control 90 (exact); GSE326573 IPF 19 / control 20 (exact when the topic is IPF only).
- Grade agreement over 3 runs: 67% before → 83% after rule-based grading and plan cache. Fixed candidates: 94%.
- Strong results per run: 7, 7, 7 (6 identical).
- One run takes about 50 seconds.

## Done (interfaces)
- One shared `agent.run()` used by the CLI, the API, and the MCP server.
- MCP server (`omics-mcp`, MCP SDK 2.x `MCPServer`): tools `search_datasets`, `geo_sample_groups`. Tested over stdio with a real MCP client; `geo_sample_groups(GSE328392)` returned 102 / 90.
- Streaming API (`omics-api`, FastAPI): `POST /search` streams NDJSON stages (plan, candidates, facts, done). Tested with curl: 27 candidates, 23 datasets, 8 strong, 57 s.
- Web UI in `web/` (Next.js 16, Tailwind 4, shadcn shell and tokens from PRIDE Map): centered search bar, live progress, plan chips, result cards with counts, checks, and source quote. Checked by screenshot at 1280 px and 390 px.

## Done (local index, 17 Oct)
- Local SQLite index `data/omics.db` (776 MB): GEO 298,702 series (all), PRIDE 42,131 projects, CELLxGENE 2,243 datasets. Harvesters: `omics_agent/harvest.py` (GEO, resumable, POST, splits batches over NCBI's 10 MB JSON limit), `omics_agent/harvest_pride.py` (PRIDE listing + search top-up for PRD/PAD series the listing skips; CELLxGENE).
- Full-text index (FTS5, BM25) built once with `store.rebuild_fts`; keyword search 3-12 ms over the whole corpus.
- `omics_agent/index.py`: keyword + embedding search fused with reciprocal rank fusion; `gather` uses it (live search only if no index).
- `omics_agent/embed.py`: embeds the corpus on a Hugging Face GPU endpoint (`NeuML/pubmedbert-base-embeddings`), resumable, deletes the endpoint when done. Waiting for HF_TOKEN.
- Search time for a fresh question: 65 s -> 22 s (smaller parallel Haiku batches, keyed NCBI requests). Plan and sample-record caches were warm in the 22 s run.
- UI: grouped results ("usable as is" first, close matches collapsed), one fact line per result, only failed checks shown, footer removed (MIT notice in web/LICENSE.pridemap).

## Done (download plan, 17 Oct)
- Result card: "download plan" toggle shows copyable shell commands per source. GEO: supplementary files over HTTPS plus SRA runs (EDirect + sra-tools). PRIDE: `pridepy`. CELLxGENE: `cellxgene_census.download_source_h5ad`. Frontend only; nothing runs.
- Checked: GEO suppl URL returns 200, SRA search by GSE returns runs (GSE326573: 59), screenshots at 1280 px and 390 px.

## Known limits
- The plan can add a broader term (for example "interstitial lung disease"); then related diseases such as CTD-ILD count as cases (GSE326573 showed case 39 instead of 19).
- PRIDE has no sample facts yet (SDRF files not read).
- GEO counts are sample records, not patients (one patient can have several libraries).
- "Partial" is still generous: 14 partial of 22 relevant.

## Next
- Merge with PRIDE Map: use its method tags (DIA, phospho, TMT) for PRIDE results.
- Data loading (CELLxGENE .h5ad, GEO counts).
- Build `eval.csv` from the biologists' `product.md` files and report recall@10.

## Done (locus brand, 17 Oct)
- Name: locus. Boards in `brand/` (a-lab, b-editorial, c-observatory). Chosen: B's serif wordmark (the `o` is a ring with a signal dot) on A's lab system.
- Web app restyled: tokens in `web/app/globals.css` (ink, bone, signal = case/match only, control green), Instrument Serif + Inter Tight + JetBrains Mono, `components/logo.tsx` (Wordmark, Reticle), `app/icon.svg`, header, idle hero with chromosome bands, mono labels, case/control ratio bar on result cards.
- Checked live with a real search at 1280 px and 390 px.
- Not done: dark mode has tokens but no toggle; `thinking-orbs` dependency is now unused.

## Done (scientist-facing polish, 17 Oct)
- Five skill audits (design-engineering, design-taste-frontend, emil-design-eng, ui-ux-pro-max, animation-systems) merged into 17 changes; all applied.
- Trust: full question in an auto-growing field; "Searched for" / "Filters" groups; four-step progress checklist with live counts and a moving bar; close-match marker; source quote in mono; record facts in ink, model reason muted.
- Grammar: failed checks neutral with an icon (orange only for case/match); 11.5 px labels and 15 px counts; actions underlined with chevrons and focus rings; header on the content column; 8 px radius.
- Motion: tiers micro 150 ms / ui 200 ms / entrance 450 ms, no bounce (`lib/springs.ts`); results header then cards stagger 70 ms; case/control bar draws once; scanning reticle; view transition skipped under reduced motion.
- Checked at 1280 px and 390 px with a browser-only replay of real accessions and counts, because the running API (PID 37655, started 13:17) predates the `modalities` -> `assays` change and returns `error: 'repositories'`.
- Turbopack served stale CSS; fixed by clearing `web/.next/dev/cache` and restarting `npm run dev`.

## Open
- Restart `omics-api` and clear stale entries in `~/.cache/omics-agent/plans.json` (old plans lack `assays`), then run one live search end to end.

## Done (results table, 17 Oct)
- Design: `docs/plans/2026-10-17-results-table-design.md`.
- Results are now a table: `web/components/results.tsx` (summary counts, repository and "counted only" filters, sorting, selection bar with combined download plan and CSV export) and `web/components/result-card.tsx` (`DatasetRow`: expandable row with paper, failed checks, quote, download plan).
- Cut: reason sentence on strong matches, repeated "usable as is" on rows, per-card bars, per-card staggered entrance.
- Pooled libraries show as "+N pooled" under Control. GSE292589 (2 case, 0 control, 2 mixed) is graded strong on purpose (`samples.py:107`); grading was not changed.
- `color-scheme: light` forced; the PRIDE Map dark-scheme rule made native checkboxes dark on dark-mode systems.
- Checked at 1280 px and 390 px with a replay of a real live search (38 datasets), driven over Chrome DevTools Protocol (`/tmp/locus-cdp/shot.mjs`), because the T3 preview tab hangs after results render. The page itself stays responsive.

## Known issue
- Turbopack keeps serving stale `globals.css` after edits (twice today). Fix: stop `npm run dev`, `rm -rf web/.next/dev/cache`, start again.

## Done (ngrok, 17 Oct)
- Cause: over ngrok the browser called `http://localhost:8000`, which is the visitor's own machine (also mixed content and outside the CORS allowlist).
- Fix: the web app calls `/api` on its own origin; `web/next.config.ts` rewrites `/api/*` to `http://localhost:8000/*`. `NEXT_PUBLIC_API_URL` still overrides.
- Checked: a streamed search through the ngrok URL returned plan, candidates, screened, facts, done as separate lines over 22 s.

## Done (more repositories + richer embeddings, 17 Oct)
- Harvesters (Sonnet subagents, each tested on ~100 records first): `harvest_omicsdi.py` (MassIVE, iProX, jPOST, PeptideAtlas, PanoramaPublic, MetaboLights, MetabolomicsWorkbench, GNPS, EGA, dbGaP, NODE, ExpressionAtlas, EVA, LINCS), `harvest_arrayexpress.py` (skips E-GEOD mirrors of GEO), `harvest_ena.py` (read studies without a GEO series). They do not rebuild FTS; run `store.rebuild_fts` once after all finish.
- Embedding text is now title + data type + organism + summary (`index.document`). `embed.py` writes `data/vector_chunks/NNNNN.{npy,json}`; each chunk lists its accessions, so a rerun embeds only rows not yet embedded. 3 L4 replicas, about 450 docs/s. Log: `/tmp/embed_rich.log`.
- After harvests: rerun `uv run python -m omics_agent.embed` for the new rows, then `rebuild_fts`, restart the API.
- Planner: `agent.ARCHIVES` lists all 19 repositories with what each holds; it drives the enum and the prompt. Plan cache keys now include a hash of the prompt and schema.
- UI: per-repository download commands (ArrayExpress FTP, ENA filereport, EGA/dbGaP controlled access, other repos link to the study page); fixed the GEO FTP path for GSE1–999.
- Papers: preprints show their server (bioRxiv) as the journal. Europe PMC's accession search was rejected for paper linking: it mostly returns reuse papers, which would group unrelated datasets as one study.
- Old `data/vector_parts/` can be deleted once the new vectors are in place.

## Done (OmicsDI harvest, 17 Oct)
- `omics_agent/harvest_omicsdi.py` pulls all 14 repositories (MassIVE, iProX, jPOST, PeptideAtlas, PanoramaPublic, MetaboLights, MetabolomicsWorkbench, GNPS, EGA, dbGaP, NODE, ExpressionAtlas, EVA, LINCS) from `https://www.omicsdi.org/ws/dataset/search?query=repository:"<name>"`, one filter query per repository, size=1000 (max the API accepts; 2000 returns 404), 6 concurrent workers (20 concurrent triggered intermittent 404s under load — looked like throttling, not real 429s). Pages cached under `data/omicsdi_pages/<repo>_NNNN.json` so a rerun only re-fetches missing pages (confirmed: cold run 9 s for 2,294 PeptideAtlas rows, warm rerun 0.1 s).
- No per-dataset calls: the search endpoint already carries title, description, organisms, omicsType, publicationDate; per-record `/ws/dataset/{db}/{acc}` adds publication IDs but at 68k records that is 68k extra HTTP calls, so `papers` is left `[]` for every OmicsDI-sourced row. MassIVE's native `datasets_json.jsp` was tried and dropped — it hung past 2 minutes with no gain over OmicsDI.
- Full run: 14 s, 68,059 rows fetched. Rerun: `uv run python -I -m omics_agent.harvest_omicsdi` (cached pages make it near-instant unless `data/omicsdi_pages/` is cleared).
- **Surprising repository behavior, not patched**: `datasets` has a single-column `PRIMARY KEY (accession)`, but OmicsDI gives the same accession to the same physical submission under more than one repository facet — GNPS re-lists MassIVE spectral submissions under their original `MSV*` IDs. Writing MassIVE first and GNPS later (an arbitrary order in `REPOS`) meant GNPS's `INSERT OR REPLACE` silently relabeled 1,602 MassIVE rows as GNPS (`source='MassIVE'` count: 9,931 listed vs 8,329 stored; the gap is exactly explained by GNPS keeping all 4,390 of its own `MSV*` rows). iProX/jPOST/PanoramaPublic also share `PXD*` accessions with PRIDE but no loss showed up this run — order-dependent, so it could bite on a future rerun. Needs a lead decision: either key on `(accession, source)` or namespace the accession, not something to change unilaterally mid-harvest.
- Field quality varies by repository, all from OmicsDI itself, not a mapping bug: `MetabolomicsWorkbench` has no `description` in search results at all (summary empty for all 2,167 rows); `EGA`, `MetaboLights`, `ExpressionAtlas`, `dbGaP` have no `organisms`; `EGA` and `dbGaP` have no `publicationDate`. `iProX`, `jPOST`, `PanoramaPublic`, `EVA`, `NODE` are fully populated on summary/organism.

## Done (ENA harvest, 17 Oct)
- `omics_agent/harvest_ena.py`: ENA/SRA studies (BioProjects) with real read data that GEO doesn't already cover. Portal API (`ebi.ac.uk/ena/portal/api/search`) streamed as TSV, chunked by year (study metadata) and quarter (per-run `library_strategy`/`instrument_model`, aggregated in Python to one run count + strategy/model set per study) — a single unbounded `limit=0` request gets silently cut off by the server after about 2 minutes regardless of row count, so each chunk stays well under that. Chunks cached under `data/ena/studies/*.tsv` and `data/ena/read_run/*.tsv`; a rerun only re-fetches chunks it doesn't have (confirmed empty 2008/2009 quarters re-skip correctly, and a chunk that silently 429'd and cached an HTML error page was caught by checking the response doesn't start with `<` before writing to disk).
- Filter stages, each counted: 1,097,183 ENA studies total -> 705,467 have at least one read run (drops genome-assembly-only and metadata-only submissions) -> 538,450 are not a GEO mirror (ENA's own `geo_accession` field is a complete, well-populated signal: 271,465 studies carry it, and cross-checking `center_name='GEO'`/`study_alias` starting `GSE` found zero additional mirrors it missed) -> 461,758 after dropping 73,823 templated mass single-isolate submissions (MRSA/plant-panel/etc. resequencing where 15+ studies share one title with digits stripped and every one of them has 5 runs or fewer — verified this rule keeps legitimately-varied-size studies like "homo sapiens raw sequence reads" while catching exact noise clusters like "mrsa surveillance ii" ×1,264) and 2,869 studies whose title or description says "surveillance". The big single-BioProject pathogen-surveillance dumps (COG-UK, CDC SARS-CoV-2, PulseNet Salmonella — millions of runs under one accession each) are literally one row each in the output regardless, so they cost almost nothing even where left in.
- `modality` = library strategies + instrument models, e.g. `"RNA-Seq; Illumina NovaSeq 6000"`. `samples` = run count (proxy; ENA has no per-study sample count without a second per-sample join). `papers` left empty — ENA's `read_study`/`study` results have no PubMed field, and the xref service wasn't worth a call per study at this count.
- Full run: 461,758 rows written to `data/omics.db` (`source='ENA'`) in 46 s wall time once chunks are cached (download pass itself was about 15 minutes earlier, done once). Rerun: `uv run python -m omics_agent.harvest_ena`.
- Not run: `store.rebuild_fts` (left for the lead per instructions).

## Plan (17 Oct)
- Megaplan for judging: `docs/plans/2026-10-17-megaplan.md` (workstreams A–G, 3-day schedule, cut list). Not started; awaiting approval and team split.
- Phase 0 tests run (17 Oct): `docs/evidence/phase0/REPORT.md`. G1 pass (GSE36892 #4, GSE35469 #12, counts exact). G2 pass but needs per-assay library split (Opus+web guessed 8+8 for GSE36892; records say 8 footprint + 4 mRNA). G3 pending labels. Grading bug: GSE25626 (no RNA-seq) graded strong for a matched question.
- Builds done (17 Oct): per-assay library counts from GEO sample records (`samples.geo_samples`, `samples.libraries`, self-check `uv run python -m omics_agent.samples`); plan field `matched_assays` + grading override in `agent._apply_facts`; facts cache key versioned by label prompt/schema hash; UI library line + unmatched warning + count links to GEO sample list. Verified live on port 8001 and by screenshot (1280 px, 390 px). Port 8000 API still runs old code until restarted.

### Result (15:30)
- Corpus: 890,961 datasets in 18 repositories (ENA 461,758; GEO 298,702; PRIDE 42,111; ArrayExpress 21,604; EGA 18,671; MassIVE 12,719 incl. GNPS; iProX 8,207; NODE 7,865; MetabolomicsWorkbench 4,639 via its native API; MetaboLights 3,534; jPOST 3,179; PeptideAtlas 2,294; CELLxGENE 2,243; dbGaP 1,316; EVA 1,021; PanoramaPublic 476; LINCS 447; ExpressionAtlas 195).
- All 890,961 embedded with the richer text (`data/vector_chunks`); FTS rebuilt; API restarted.
- Harvest rule: a dataset keeps the first repository that stored it (OmicsDI lists some under several). E-GEOD copies are skipped everywhere.
- Rows with no species (most ENA, EGA, MetaboLights, NODE, dbGaP) pass any species filter (`index.py`).
- Planner prompt is cached (`_ask(cached=...)`): 7,625 tokens read from cache on repeat calls.
- Live searches through the API (all returned results): T2D plasma metabolomics 34 s (MetaboLights 6, Workbench 9, GEO 8, MassIVE 2); glioblastoma phosphoproteomics 25 s (PRIDE 22, MassIVE 4, iProX 3); C-section infant microbiome 28 s (ENA 34); IPF RNA-seq 61 s (GEO 38, ENA 1, ArrayExpress 1).
- Open: ENA species (needs a re-download of read_run with scientific_name); paper links for OmicsDI and ENA rows; old `data/vector_parts/` (527 MB) can be deleted.
