# Nexus expert-panel session, 17 October 2026

How this was produced: one bounded session of the "Nexus" ExpertRouter skill (Juri's paper-grounded expert skills, normally run on Iridis under `~/.claude/skills/`). The Claude login on Iridis had an expired token, so the distilled knowledge files (without the per-paper `papers/` dumps) were copied to pgx (`/home/jlw/nexus_kb/`) and the session was run there with read-only access to that folder, no web, no code execution, 24 tool calls. The prompt is reproduced at the end. The answer below is verbatim; nothing has been edited except Markdown escaping. Items the panel marks as **persona opinion** are not paper-grounded and must be verified before being relied on.

Known limitation stated by the panel itself: no trained expert covers SDRF-Proteomics, MaxQuant/DIA-NN parameters, MitoCarta, library strandedness, nf-core/Slurm or synonym expansion. Section 4d is therefore practitioner opinion only.

---

# Nexus panel — omics-agent metadata & analysis-validity review

Routing basis: `ExpertRouter/experts-index.md`. Panel convened: **Polly** (ExpertTranslation, trained) and **Omi** (ExpertMultiomics, trained). Persona-only voices: **Genny** (CompBio), **Pip** (Bioinformatics), **Bayes** (Stats) — knowledge folders empty; their two `concepts/` files are the only non-empty content and are opinion, not paper-grounded. Per-paper `papers/` drill-downs were not copied, so where a claim's primary paper is only cited inside a review, the panel says so.

## 1. WHO / PANEL — who covers this, and which gaps matter

**Trained coverage**

| Need | Expert | Where |
|---|---|---|
| Ribo-seq QC, read lengths, periodicity, P-site offsets, drug/nuclease covariates, depth, TI-seq vs Ribo-seq | Polly | `ExpertTranslation/knowledge/08-riboseq-methodology-and-datasets.md` |
| ΔTE statistics, replicates, batch, matched pairs, regulatory classes | Polly | `ExpertTranslation/knowledge/11-deltate-methodology.md` |
| PIF / Uniformity / Drop-off thresholds for ORF calls | Polly | `ExpertTranslation/knowledge/07-translation-signature-smorf-detection.md` |
| mTOR / 5'TOP biology for the sanity check | Polly | `ExpertTranslation/knowledge/05-mtor-4ebp-5top.md` |
| DESeq2 model, replicates, outliers, compositional stats, batch-correction taxonomy, pseudobulk | Omi | `ExpertMultiomics/knowledge/04-integration-methods-and-compositional-stats.md` |
| scRNA-seq QC filters, snRNA quirks, donor-as-unit | Omi | `ExpertMultiomics/knowledge/02-single-cell-methodologies-and-limits.md` |
| Public-repository reprocessing (Expression Atlas, PRIDE→Atlas DDA/DIA, PeptideAtlas, FAIR metadata) | Omi | `ExpertMultiomics/knowledge/01-cell-atlases-and-public-resources.md` |
| Proteomics search-parameter provenance, HUPO-HPP evidence tiers, cross-modal validation | Omi (+Polly) | `ExpertMultiomics/knowledge/07-cross-modal-bridges-translatomics-proteogenomics.md` |

**Gaps that matter here (no trained expert)**

- **SDRF / sample-to-file annotation in proteomics**: zero hits for "SDRF" anywhere in the knowledge base. Nothing on what an SDRF must contain for LFQ/TMT/DIA. This is the hackathon's central observed problem and it is **uncovered**.
- **Quantitative proteomics pipelines** (MaxQuant/DIA-NN/Sage parameters, TMT ratio compression beyond one sentence, organelle-IP enrichment analysis, **MitoCarta**): MitoCarta has zero hits; MaxQuant/DIA-NN appear only as names in George 2023's Expression Atlas description. Interview 3's core need is uncovered.
- **Library strandedness / dUTP protocols**: zero hits. The riboseq-agent extracts strandedness, but no expert can ground thresholds or inference rules for it.
- **Pipelines/HPC/Slurm/nf-core** (Pip) and **experimental design / power** (Bayes): persona-only.
- **GEO/SRA/PRIDE metadata schemas and search/synonym expansion** (Genny): persona-only.

Nexus's summary: the Ribo-seq/ΔTE half of the question is well-grounded (Polly, 54 papers); the bulk/sc RNA-seq half is grounded on DESeq2 and two sc papers (Omi); the proteomics half is grounded only at the level of "what PeptideAtlas/Expression Atlas record per dataset" and is otherwise **persona opinion**.

## 2. What experimental researchers truly care about (ranked, max 12)

1. **Uniform reprocessing so results are comparable** — Why: cross-catalog smORF overlap falls below 10% when three catalogs are compared by stop site, purely from processing differences; the consensus fix is "pool data, reprocess uniformly, apply translation-signature QC." Tool must: run one pinned pipeline per tier and stamp every output with pipeline/annotation version. Source: `ExpertTranslation/knowledge/07-translation-signature-smorf-detection.md` (Chothani 2023 RNA Biol); RPFdb v3.0 "unified pipeline across all studies" in `08-riboseq-methodology-and-datasets.md` (Wang 2024 NAR).
2. **Per-sample QC gates shown, not hidden** — Why: of 102 human Ribo-seq datasets on RPFdb only 10 were primary material and only 3/10 passed the >60% CDS periodicity gate; most public data is unusable without a visible gate. Tool must: display periodicity, read-length distribution, %CDS per sample and a pass/fail. Source: `08-riboseq-methodology-and-datasets.md` (Chothani 2022 Mol Cell).
3. **Proof of matched Ribo/RNA pairs, ≥3 replicates, and non-confounded batch** — Why: ΔTE is a DESeq2 interaction term that needs paired count matrices, ≥3 biological replicates per condition, and a full-rank batch design; confounded batch "correction impossible." Tool must: surface the pairing evidence (sample-name similarity plus methods text) and refuse ΔTE when the design is rank-deficient. Source: `11-deltate-methodology.md` (Chothani 2019 Curr Protoc Mol Biol).
4. **Protocol provenance as a covariate (drug, nuclease)** — Why: drug identity is an important covariate for label construction; harringtonine/lactimidomycin/puromycin make initiation-specific (TI-seq) profiles; MNase vs RNase I give different 5' biases so P-site offsets must be nuclease-specific. Tool must: classify runs by inhibitor/nuclease and never pool TI-seq with elongation Ribo-seq. Source: `08-riboseq-methodology-and-datasets.md` (Ingolia 2018 CSH Perspect; VanInsberghe 2021 Nature; Gerashchenko+Gladyshev 2014 cited via Ingolia 2018).
5. **Adequate depth for the question asked** — Why: 6M P-sites detects ~3% of known ORFs; 1.3B pooled P-sites gives ~80% codon coverage; a single 20–30M-read sample yields ~1 read/codon. Tool must: report usable P-sites per sample and warn when below task thresholds. Source: `08-riboseq-methodology-and-datasets.md` and `07-translation-signature-smorf-detection.md` (Chothani 2023 Fig 6; Chothani 2019: ≥20M reads/sample).
6. **An explained match with checkable evidence** — Why: Deutsch 2024 only promoted ncORFs after manual inspection of spectra via Universal Spectrum Identifiers and GWIPS-viz Ribo-seq tracks; automation "provides candidates, humans provide annotation-grade ground truth." Tool must: for each match show the quoted methods sentence, PXD/GEO accession and, where possible, a USI-style resolvable pointer. Source: `ExpertMultiomics/knowledge/07-cross-modal-bridges-translatomics-proteogenomics.md` (Deutsch 2024 Cell). Synonym expansion itself is **persona opinion** (ontology-mediated synonym search exists in SCEA, George 2023 NAR, `01-cell-atlases-and-public-resources.md`).
7. **Ontology-anchored, FAIR metadata** — Why: Expression Atlas attributes reuse of GEO/PRIDE data to mapping metadata to controlled vocabularies with SME curation; "manual curation... far outstrips" ingestion. Tool must: map organism/tissue/cell type/disease to ontology terms and store a MAGE-TAB/SDRF-like sample sheet. Source: `01-cell-atlases-and-public-resources.md` (George 2023 NAR). The specific SDRF-Proteomics format is **not in corpus**.
8. **A known-result positive control** — Why: cross-modal claims are only trusted when triangulated (Ribo-seq × tryptic MS × HLA-MS tiers; IF closure of scRNA predictions). Tool must: run one canonical sanity check per modality (5'TOP under mTOR inhibition; proteomics: organelle recovery — the latter is **persona opinion**, MitoCarta not in corpus). Source: `07-cross-modal-bridges-translatomics-proteogenomics.md` (Deutsch 2024; Gim 2025 Nat Commun).
9. **Raw counts and compositional honesty** — Why: DESeq2 requires raw counts ("pre-normalization breaks the model"); RPF and RNA are compositional, so TE should be log-ratio based and spurious correlation guarded. Tool must: deliver raw count matrices plus size factors, never only TPM/RPKM. Source: `11-deltate-methodology.md` (Chothani 2019); `04-integration-methods-and-compositional-stats.md` §4.2 (Quinn 2017 Sci Rep); RiboNN CLR-TE in `08-riboseq-methodology-and-datasets.md` (Zheng 2025 Nat Biotechnol).
10. **Annotation/reference pinning** — Why: signature thresholds are "dataset-dependent: changing annotation (Ensembl vs GENCODE vs RefSeq)... requires recomputing." Tool must: pin GENCODE/Ensembl release and genome build per tier and expose them. Source: `07-translation-signature-smorf-detection.md` (Chothani 2025 Science); Genny's `ExpertCompBio/concepts/data-hygiene.md` (**persona**).
11. **Cell-type composition awareness for bulk tissue** — Why: bulk DCM vs control ΔTE "may be confounded by shifts in fibroblast/cardiomyocyte cell-fraction"; Expression Atlas only reports deconvolution when three tools agree at mean pairwise Pearson ≥0.6. Tool must: flag tissue vs cell-line samples and offer deconvolution with an agreement gate. Source: `11-deltate-methodology.md` (Chothani 2019); `04-integration-methods-and-compositional-stats.md` §4.6.3 (George 2023).
12. **Mind the detection bias of the modality you reprocess** — Why: tryptic MS robustly sees ~0.9% of ncORFs vs 24.6% in HLA-I; only 5.6% of known proteins <50 aa pass HUPO-HPP. Tool must: state what a proteomics dataset cannot have seen (short, unstable, transmembrane proteins) when explaining a "no hit." Source: `07-cross-modal-bridges-translatomics-proteogenomics.md` (Deutsch 2024).

## 3. Ribo-seq ± matched RNA-seq plan, conditioned on metadata

### 3a. Minimum metadata before processing starts
Grounded unless marked.

- **Organism + genome build + annotation release** — thresholds and ORF catalogs are annotation-dependent (Chothani 2025; `07-...md`). Pin GENCODE; Genny adds "basic, primary assembly" (**persona**, `ExpertCompBio/concepts/te-label-pipeline.md`).
- **Translation inhibitor** — CHX vs none vs harringtonine/lactimidomycin/puromycin. CHX: expect ~29 nt RPF, downstream density shift that is "ok for TE quantification, problematic for positional features"; initiation drugs = TI-seq, not TE data (`08-...md`, Ingolia 2018, Ingolia 2012 protocol via Ingolia 2018). Chothani 2025 excluded TI-drug studies so uORF enrichment is biological (`08-...md`).
- **Nuclease** — RNase I (bulk), MNase (scRibo-seq), RNase T1/S7 mixes (in vivo); P-site assignment "must be nuclease-specific" (`08-...md`, VanInsberghe 2021; Gerashchenko 2020 NAR).
- **Expected footprint window** — 27–30 nt for CHX (Chothani 2022/2025); 28–30 unrotated, ~21 rotated, ~16 truncated (Ingolia 2018); 30–45 nt trimmed for MNase scRibo (VanInsberghe 2021) (`08-...md`). Genny's 26–34 (**persona**).
- **Library adapter / UMI scheme** — needed to trim; examples in `08-...md` (cutadapt sequences, Gerashchenko 2020; VanInsberghe 2021). Strandedness: **no trained coverage**; the riboseq-agent's methods extraction is the only source (persona).
- **Sample sheet**: sample_id, condition, biological replicate, batch/patient, SeqType (RIBO/RNA) — required by the DESeq2 design (`11-...md`, Chothani 2019).

### 3b. Additional metadata before TE/ΔTE
- **Matched Ribo-seq + RNA-seq from the same biological samples** — design `~ Batch + Condition + SeqType + Condition:SeqType`, RNA as reference level (`11-...md`, Chothani 2019). Genny: same prep/run ideally (**persona**).
- **≥3 biological replicates per condition**; batch randomised across lanes; PCA to detect batch; confounded batch → non-full-rank → no correction possible (`11-...md`, Chothani 2019). DESeq2 can run at 2–3 replicates but outlier replacement requires ≥7 and ≤6 only flags genes (`04-...md` §4.1.5, Love 2014).
- **Cell type / tissue vs cell line** — bulk tissue ΔTE confounded by composition (`11-...md`, Chothani 2019).

### 3c. QC gates with numbers
- **Depth**: ≥20M reads/sample, SE50 sufficient, ~29 bp RPF (Chothani 2019, `11-...md`); typical retention ~10% post-contaminant, 20–80% unique (Chothani 2023); RiboNN requires ≥70% of RPFs in CDS (Zheng 2025); per-cell-type ≥50M P-sites for ORF discovery (Chothani 2022) — all `08-...md`.
- **Periodicity**: ≥60% 3-nt periodicity per sample at the selected lengths (gate); 85% pooled body-map; bulk frame-1 fraction 55–75%, 89% in Chothani 2019 cardiac data; scRibo ~40% (`08-...md`). ORFik auto-selection: ≥1000 reads per length, DFT peak at period 3 (Tjeldnes 2021).
- **Read length**: keep 27–30 nt (CHX); drop non-periodic lengths (`08-...md`).
- **ORF-call gates** (pooled P-sites): PIF ≥75.9%, Uniformity ≥71.3%, Drop-off ≥92.0% — derived as mean−2SD of annotated CDSs, recompute per annotation (`07-...md`, Chothani 2022; Chothani 2025; Menon/Rackham/Chothani 2026). Manual-inspection grade: ≥4 (excellent) / ≥3 (sufficient) sequential in-frame peaks in first 100 nt (Deutsch 2024).
- **Gene-level filters**: trim first 10 nt and last 35 nt of CDS for inhibitor artefacts (RiboNN); exclude first/last 10 codons and genes <200 nt (Riboformer); eukaryotic genes <5 reads/nt discarded (Shao 2024) (`08-...md`). Harnett 2022 used a 32-footprint threshold (`08-...md`); Genny suggests mean RPF ≥32 (**persona**).
- **ΔTE call**: FDR <0.05 (0.01 valid); three DESeq2 runs (interaction, RNA-only, Ribo-only) for class assignment (`11-...md`).

### 3d. What stays valid at each metadata level

| Available | Valid outputs | Not valid |
|---|---|---|
| Ribo-seq only, inhibitor known (CHX/none), nuclease known | P-site offsets, per-strand P-site bigWigs, periodicity QC, CDS RPF counts, ORF calls with PIF/Uniformity/Drop-off (pooled), pausing scores | TE, ΔTE, any "translational regulation" claim |
| Ribo-seq only, inhibitor = harringtonine/lactimidomycin | TIS calls (Ribo-TISH, ORF-Rater) only | Everything above except TIS; must be labelled TI-seq |
| Ribo + RNA, unpaired or unknown pairing | Separate ΔRPF and ΔRNA (Ribo-only, RNA-only DESeq2) | TE, ΔTE classification (needs paired cbind matrices) |
| Ribo + RNA paired, 1–2 replicates | Descriptive TE = RPF-RPKM/RNA-RPKM per sample (RPFdb v3.0 definition) | ΔTE with FDR; "Ratio" and "Overlap" methods have high FP rates (`08-...md`, `11-...md`) |
| Paired, ≥3 reps, batch confounded with condition | ΔTE only within batch | Cross-batch ΔTE |
| Paired, ≥3 reps, batch in design | Full ΔTE with forwarded/exclusive/intensified/buffered classes | — |
| Bulk tissue, no composition estimate | All of the above with a composition caveat | Cell-type-specific ΔTE (needs deconvolution or scRibo; `ExpertMultiomics/.../07-cross-modal...md` §7.4) |
| Inhibitor unknown | Nothing beyond QC until read-length/periodicity profile infers it (**persona inference**) | — |

### 3e. Known-result test: 5'TOP mRNAs under mTOR inhibition
Expected result: ribosomal-protein and translation-factor mRNAs (5'TOP class) and structured-leader mRNAs show a disproportionate **drop in TE** on mTOR inhibition, with mRNA largely unchanged — i.e., they populate the "exclusive"/translationally down class in ΔTE; TISU-containing mitochondrial mRNAs are resistant. Grounding: `ExpertTranslation/knowledge/05-mtor-4ebp-5top.md` — "Ribo-seq of mTOR-inhibitor-treated cells reveals broad target range beyond ribosomal proteins (Hsieh2012; Thoreen2012)" and "Under mTOR inhibition: ribosomal-protein mRNAs (5'TOP) and structured-leader mRNAs drop disproportionately," cited via Ingolia 2018, Robichaud 2018 and Amiri 2025 (trained reviews). **Caveat**: Thoreen 2012 and Hsieh 2012 are not in Polly's literature index (Hsieh 2012 is on the wishlist, `ExpertTranslation/literature-index.md`), so the primary-paper drill-down is unavailable. In-corpus corroboration: Harnett 2022 (Nature) — TE-down set in developing neocortex "enriched for structural constituents of ribosome (nearly all 79 RPs)" coincident with p-4E-BP1 decline (`07-...md`, `05-...md`); Gerashchenko 2020 — low-TE genes enriched for ribosome/mTOR GO terms across mouse organs (`08-...md`). Implementation (**persona**): run ΔTE on any public Torin1/rapamycin/INK128 dataset and require the RPL/RPS gene set to be significantly enriched among ΔTE<0 genes before trusting the pipeline.

## 4. Proteomics and bulk / single-cell RNA-seq

### 4a. Bulk RNA-seq (grounded, Omi/Love 2014)
Minimum: raw integer counts per gene (not TPM), condition, ≥2–3 biological replicates, batch/donor as a design covariate, genome build + GTF release. `04-integration-methods-and-compositional-stats.md` §4.1: NB GLM; median-of-ratios normalisation assumes most genes unchanged; outlier handling needs ≥7 replicates for replacement; effect-size thresholds (|LFC|>θ) available. Validity ladder: counts only → QC, rlog PCA, clustering; + condition, 1 rep → descriptive LFC only (**persona**: no inference); + ≥2–3 reps → DESeq2 DE; + batch covariate → batch-adjusted DE; "biological-vs-technical confounding (donors differ in disease AND lab) — no method fixes this" (§4.6.2). Genny's sample-sheet columns (sample_id, bio/tech replicate, batch, prep date, run, condition, cell type, donor, sex, age) are **persona** (`ExpertCompBio/concepts/data-hygiene.md`).

### 4b. Single-cell RNA-seq (grounded, Omi)
Minimum: per-cell raw counts, donor/sample ID, batch/chemistry (10x v2 vs v3 is a distributional shift needing Harmony/BBKNN-class correction, §4.6.2), cell vs nucleus (snRNA needs intron-inclusive quantification; Expression Atlas switched to alevin-fry, George 2023, `01-...md`), condition. QC numbers: drop cells <1,000 reads or <500 genes, genes in <5 cells, top 1,000 HVGs (Wang 2025, `02-...md`); or ≥200 genes, <10% mitochondrial, 2.5–97.5 percentile UMI window, doublet removal (Gim 2025). Validity ladder: counts + batch → clustering/annotation with iLISI and cLISI both reported (Gim 2025: 2.004/1.273); + donor → pseudobulk (donor × cell type) DESeq2, adj p<0.05 (Gim 2025); without donor IDs, per-cell Wilcoxon DE is possible but donor-confounded (**persona**, consistent with §2.6 item 12). Spliced/unspliced velocity: fit per sample if batch cannot be excluded (Bergen 2021).

### 4c. Proteomics — what the corpus grounds
- Dataset-level parameters that PeptideAtlas re-searches per PXD: alkylation, label (TMT/SILAC), fragmentation, instrument, enrichment — "all dataset-matched"; variable mods M-ox, N-term acetyl, pyro-Glu, deamidation; fixed carbamidomethyl-Cys when iodoacetamide used (`ExpertMultiomics/.../04-...md` §4.5.5; Deutsch 2024 Cell). Decoy FDR <0.1% protein-level.
- Expression Atlas reprocessing: DDA via MaxQuant + post-processing; DIA via Pan Human library or library-free DIA-NN; "DIA... reduction of missing values"; TMT "preferred for differential studies," baseline representation only recently possible (Wang 2023 *Proteomics*, cited second-hand) (`01-...md`; `10-virtual-cell...md`; George 2023 NAR).
- Normalisation: per-channel for TMT, median centring for label-free (`04-...md` §4.6.1, Omi standing knowledge).
- Evidence standard: HUPO-HPP two non-nested peptides ≥9 aa covering ≥18 aa; PeptideAtlas categorical labels (canonical … insufficient evidence) (`07-cross-modal...md`, Deutsch 2024).
- Validity without sample→condition mapping (grounded by analogy to Deutsch 2024): identification, baseline/aggregate quantification and presence/absence catalogues remain valid; differential analysis does not.

### 4d. Proteomics — OUTSIDE THE TRAINED CORPUS (persona-level answer)

> **Persona opinion (Omi/Genny/Pip personas; no paper grounding in this KB).** SDRF-Proteomics content, raw-header inference and MitoCarta controls are not covered by any trained expert. The following is practitioner judgement to be verified against the SDRF-Proteomics specification and PRIDE documentation.

- **Common SDRF core for every design**: one row per raw file; `source name`, `characteristics[organism]`, `[organism part]`, `[cell type]`, `[disease]`, `[biological replicate]`, `assay name`, `comment[data file]`, `comment[instrument]`, `comment[cleavage agent details]`, `comment[modification parameters]` (fixed/variable), `comment[fraction identifier]`, `comment[technical replicate]`, `factor value[...]` naming the contrast variable.
- **Label-free DDA/LFQ**: `comment[label] = label free sample`; fraction → file grouping; the condition factor must be per file. Without it only protein identification and intensity catalogues are valid; with it, LFQ/match-between-runs differential analysis.
- **TMT**: `comment[label] = TMT126 … TMT134N` per channel, several SDRF rows per raw file (one per channel); the plex/`comment[technical replicate]` groups files; `factor value` per channel. Without channel→sample mapping, even identification-to-sample assignment fails; reference-channel/bridge design must be stated for cross-plex comparison.
- **DIA**: `comment[label] = label free sample`, `comment[proteomics data acquisition method] = DIA`, window scheme/instrument, library source (library-free vs spectral library) and whether a gas-phase fractionation library exists; condition per file.
- **Inferable from raw headers when SDRF absent**: instrument model and serial, acquisition date/time (batch proxy), acquisition mode (DDA vs DIA from MS2 isolation widths), TMT presence (reporter ions in MS2/MS3), fraction numbering from file names, run order. **Not inferable**: biological condition, replicate structure, organism part — these must come from the paper's methods/figure legends, and the tool should quote the sentence and mark the mapping as "paper-inferred, unverified."
- **Organelle-IP positive control (interview 3)**: compute enrichment of a mitochondrial reference set (e.g., MitoCarta) in IP vs input/mock and report recovery and fold-enrichment; this mirrors the Deutsch 2024 principle of orthogonal validation but the specific reference list is not in the corpus.

### Nexus closing note
Grounded strongest on: Ribo-seq QC/ΔTE (Polly) and DESeq2/pseudobulk/compositional stats (Omi). Thin: proteomics search-parameter provenance (only via Deutsch 2024 and George 2023). Absent: SDRF, strandedness, MitoCarta, Slurm/nf-core, synonym expansion. Recommend training Pip and Genny from folder `07` and adding SDRF-Proteomics, Thoreen 2012 and Hsieh 2012 to the corpus before relying on this panel for the proteomics tier.

---

## Prompt used

The panel was given the omics-agent context (two-tier contract, riboseq-agent capabilities, the three interview summaries, the PRIDE SDRF probe result of 13/120) and four questions: (1) who covers this and which untrained-expert gaps matter; (2) a ranked list of what experimental researchers care about, each with why / what the tool must do / source; (3) the Ribo-seq ± matched RNA-seq plan conditioned on metadata availability with QC numbers and the 5'TOP/mTOR known-result test; (4) the same for proteomics (LFQ, TMT, DIA SDRF content; what is inferable without SDRF) and bulk/single-cell RNA-seq, with out-of-corpus answers separately labelled. Instruction: cite file and paper for every grounded claim, label the rest persona opinion, do not confabulate, under 3000 words.
