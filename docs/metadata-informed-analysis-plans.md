# Metadata-availability-informed analysis plans

Status: proposal from the 17 October 2026 session, written on branch `juri`. Builds on `data-processing-contract.md` (tiers, raw → target table). Nothing here claims a pipeline exists in this repository. Sources: the Nexus expert panel (`nexus-panel-2026-10-17.md`; paper-grounded where marked, persona opinion where marked), a PRIDE API probe (`scripts/pride_metadata_probe.py`), a census of 80 of the 883 shared riboseq-agent plans, and the riboseq-agent code on Iridis (`/iridisfs/ddnb/jlw/riboseq-agent`, branch `jurilw-nf-core`).

## 1. The problem in numbers

Raw files are rarely the blocker. Sample-level metadata is.

**PRIDE, 120 projects probed (mixed ages, files listed for each):**

| Field | Populated |
|---|---|
| Sample and data processing protocol text, organism, instrument, experiment type, keywords | 100% |
| organism part | 74% |
| software named | 66% |
| quantification method | 31% |
| disease | 16% |
| **SDRF file (per-raw-file sample → condition → replicate → label)** | **13 / 120 (11%)** |

`sampleAttributes` in the PRIDE record is project-level (organism, organism part), not per file. So for about nine in ten PRIDE projects we can identify and quantify proteins but cannot say which raw file is which condition, which is exactly what makes differential analysis impossible.

**Shared riboseq-agent plans, 80 sampled of 883 (GEO/SRA Ribo-seq studies annotated by LLM + methods scan):**

| Field in `paper_metadata` | Populated |
|---|---|
| RNase | 54% |
| UMI used | 51% |
| RNA-seq selection (polyA / rRNA depletion) | 48% |
| translation inhibitor | 45% |
| footprint size range | 28% |
| companion accessions | 12% |
| genome build / annotation / strandedness / layout / read length | 0–2% |

Run-level: 71 of 80 plans have Ribo↔RNA `pair_id`s and 72 have RNA-seq runs, but only 27% of runs carry a replicate label and no plan has an `experiment_design` set. 1,445 of 2,694 runs are typed `other`. Sequencing metadata is therefore better than proteomics but still far from the design table ΔTE needs.

## 2. Principle: the metadata level gates the plan

Every dataset gets a **metadata level** per modality, computed from what is actually known, and the agent offers only the analyses valid at that level. Climbing a level is a curation step the agent proposes (fetch → infer → ask), never a silent assumption.

| Level | What is known | What the agent may offer |
|---|---|---|
| **L0 identity** | organism, assay type, raw files | download; QC; identification / alignment / counting with default parameters |
| **L1 protocol** | the processing-critical parameters (see per-modality lists) | tier-specific processing to analysis-ready files; descriptive per-sample quantification; tracks |
| **L2 design** | per-sample condition, biological replicate, matched pairs | differential analysis (DESeq2, ΔTE, LFQ/TMT contrasts), with replicate rules enforced |
| **L3 covariates** | batch / donor / plex / cell type, confirmed by methods text | batch-aware models, cross-study comparison, cell-type-specific claims |

Every field carries a **provenance tag**: `repository` (API field), `community` (e.g. bigbio SDRF), `paper-inferred` (quoted methods sentence, unverified), `file-inferred` (read from the raw file itself), `user`. This mirrors riboseq-agent's `extraction_method` (`regex | ai | user`) and must be shown in the GUI next to the value. Missing means unknown, not negative (AGENT.md §5).

## 3. Where metadata comes from, in order

1. **Repository fields.** PRIDE project record; SRA run table (`library_strategy`, `library_layout`, `platform`, spots); GEO sample characteristics. riboseq-agent already pulls these into `Run` / `Study` (`riboseq_agent/metadata/models.py`).
2. **Community curation.** `bigbio/sdrf-annotated-datasets` holds SDRF files for 12,007 PXD accessions as of 17 Oct 2026 (`datasets/{PXD}/{PXD}.sdrf.tsv`). Fetch before inferring; quality varies and must be surfaced as `community`, not treated as ground truth. For sequencing, the shared `riboseq-agent-plans` repo plays the same role (883 plans).
3. **Uniformly processed layers.** recount3 / ARCHS4 / CELLxGENE / Expression Atlas (see contract). Their sample sheets are already ontology-mapped and can seed L2 for RNA-seq.
4. **Paper methods and data-availability sections.** riboseq-agent's `literature/scanner.py` (Europe PMC) extracts companion accessions, inhibitor, nuclease, footprint range, UMI, RNA-seq selection, genome build. Generalise the field list per modality (§4–§7) and keep the quoted sentence.
5. **The raw file itself.** FASTQ: read-length distribution (footprint window, UMI presence), strandedness by `salmon --libType A`, adapter by over-represented k-mers. Mass-spec raw: instrument model, acquisition date/time (batch proxy), DDA vs DIA from MS2 isolation widths, TMT reporter ions, fraction numbers from file names (via ThermoRawFileParser metadata). These are `file-inferred` and cheap enough for the laptop tier.
6. **The user.** riboseq-agent's interactive review table (`metadata/sample_meta.py`) is the model: show the inferred design grouped by pairs, let the user accept, bulk-edit or override, record `user`.

Only after step 5 fails may the agent ask the user. Steps 4 and 5 are where the LLM earns its place: proposing values with evidence, never deciding.

## 4. Ribo-seq ± matched RNA-seq (primary plan; borrow riboseq-agent)

### 4.1 Fields and where they come from

| Field | Needed for | Level | Primary source | Fallback |
|---|---|---|---|---|
| organism, genome build, annotation release | everything; ORF thresholds are annotation-dependent (Chothani 2025) | L0 / pinned by tier | SRA/GEO; tier pins GENCODE release | — |
| translation inhibitor (CHX / none / harringtonine / lactimidomycin / puromycin) | run typing (TI-seq vs elongation Ribo-seq), expected RPF length, trimming of start/stop artefacts | L1 | methods scan (45% of plans today) | file-inferred: read-length mode + 5' pile-up at start codons suggests TI-seq (persona inference, must be shown as such) |
| nuclease (RNase I / MNase / T1+S7) | P-site offsets are nuclease-specific (VanInsberghe 2021) | L1 | methods scan (54%) | default RNase I with warning |
| footprint window | read-length filter (27–30 nt CHX; 30–45 nt MNase) | L1 | methods scan (28%) | file-inferred from length distribution + periodicity per length (ORFik rule: ≥1000 reads, DFT peak at 3) |
| adapter, UMI | trimming | L1 | methods scan (UMI 51%) | file-inferred over-represented sequence |
| strandedness, layout | alignment / counting | L1 | SRA layout; strandedness almost never stated (1%) | `salmon --libType A` on a subsample |
| RNA-seq selection (polyA vs rRNA-depleted) | matched RNA comparability | L1 | methods scan (48%) | — |
| run type Ribo / RNA / TI-seq / other | pairing, everything downstream | L1 | riboseq-agent `SampleType` + AI suggestion | user review; never pool TI-seq with Ribo-seq |
| Ribo↔RNA pair, same biological sample | TE, ΔTE | L2 | `metadata/pairing.py` name similarity (auto ≥0.90) plus methods sentence on how samples were split | user |
| condition, biological replicate (≥3 per condition) | ΔTE with FDR | L2 | regex + AI on sample names (27% of runs today) | user |
| batch / patient / lane; tissue vs cell line | full-rank design, composition caveat | L3 | methods, GEO characteristics | PCA flag |

### 4.2 QC gates (paper-grounded via Polly)

- Depth ≥20 M reads per sample; expect ~10% usable after contaminant removal; ≥70% of RPFs in CDS; ≥50 M pooled P-sites per cell type for ORF discovery.
- 3-nt periodicity ≥60% per sample at the retained read lengths; drop non-periodic lengths.
- ORF calls on pooled P-sites: PIF ≥75.9%, Uniformity ≥71.3%, Drop-off ≥92.0%, recomputed as mean − 2 SD of annotated CDSs whenever the annotation changes.
- ΔTE: DESeq2 `~ Batch + Condition + SeqType + Condition:SeqType`, RNA as reference, raw counts only, FDR < 0.05, three runs (interaction, RNA-only, Ribo-only) for the forwarded / exclusive / intensified / buffered classes.

### 4.3 Validity ladder

| Known | Offer | Withhold |
|---|---|---|
| L1, Ribo only, elongation inhibitor | per-strand P-site bigWigs, periodicity QC, CDS counts, pooled ORF calls, pause scores | TE, ΔTE, any "translational regulation" wording |
| L1, Ribo only, initiation inhibitor | TIS calls only, labelled TI-seq | all of the above |
| L2 without pairing | ΔRPF and ΔRNA separately | TE, ΔTE |
| L2 paired, 1–2 replicates | descriptive TE per sample (RPFdb ratio definition), clearly marked | ΔTE with FDR |
| L2 paired, ≥3 replicates | full ΔTE and classes | cross-batch claims if batch is confounded |
| L3 | batch-aware ΔTE; cell-type caveat or deconvolution for tissue | — |

### 4.4 Known-result test

Any public mTOR-inhibitor (Torin1, rapamycin, INK128) matched dataset: ribosomal-protein (5'TOP) mRNAs must fall in the translationally-down / exclusive class with mRNA unchanged. Enrichment of RPL/RPS among ΔTE < 0 genes is the pass criterion. The panel notes Thoreen 2012 and Hsieh 2012 are not in its corpus; the expectation is corroborated by Harnett 2022 and Gerashchenko 2020. A concrete accession still needs choosing and checking.

### 4.5 Tier mapping

- **HPC**: nf-core/riboseq 1.2.0 as riboseq-agent runs it (Trim Galore, SortMeRNA, STAR + Salmon, riboWaltz, RiboTISH, Ribotricer, MultiQC), then riboseq-agent's `bam2bw` for per-strand P-site CPM bigWigs (`rpf_v3` policy) and unstranded bigWigs for RNA. SortMeRNA needs up to 230 GB on deep libraries, so this cannot move to the laptop tier.
- **Laptop**: designed, not built (contract open item). bowtie2 to rRNA/tRNA, then transcriptome alignment and P-site projection to genome; CDS counts and bigWigs only. Must be validated against the HPC path on one study before being offered.

## 5. Bulk RNA-seq

- **L1 fields**: layout, strandedness (`salmon --libType A`), selection method, read length, genome build; tier pins GENCODE.
- **L2**: condition, ≥2–3 biological replicates; **L3**: batch/donor.
- **Ladder** (Omi / Love 2014): L0–L1 → counts, rlog PCA, clustering; L2 with one replicate → descriptive LFC only; ≥2–3 replicates → DESeq2; L3 → batch covariate; donor-confounded-with-condition cannot be rescued by any method, say so.
- **Fetch first**: recount3 / ARCHS4 for human and mouse, which arrive at L2-ish with curated sample sheets.

## 6. Single-cell RNA-seq

- **L1 fields**: chemistry (10x v2 / v3 / other), cell vs nucleus (intron-inclusive quantification for snRNA), species, reference.
- **L2**: donor / sample ID, condition; **L3**: batch, tissue dissociation protocol.
- **Gates**: ≥200 genes and <10% mitochondrial per cell (or <1,000 reads / <500 genes drop rule), doublet removal, report iLISI and cLISI after integration.
- **Ladder**: L1 → `.h5ad`, clustering, annotation; L2 with donor IDs → pseudobulk (donor × cell type) DESeq2; without donor IDs per-cell tests are donor-confounded and must be labelled as such.
- **Fetch first**: CELLxGENE Census (ontology cell types already attached).

## 7. Proteomics (the metadata-poor modality)

The panel found no trained expert for SDRF, MaxQuant/DIA-NN parameters or MitoCarta; §7.2 is practitioner opinion to be verified against the SDRF-Proteomics specification (bigbio/proteomics-sample-metadata).

### 7.1 Recovery order for the missing sample table

1. PRIDE files endpoint: any `*sdrf*.tsv` or `EXPERIMENTAL DESIGN` file (11%).
2. `bigbio/sdrf-annotated-datasets` by accession (12,007 PXDs; tag `community`).
3. PRIDE project text (`sampleProcessingProtocol`, `dataProcessingProtocol`, always present) and the paper: extract label type, enzyme, fixed/variable modifications, instrument, fractionation, number of conditions and replicates, and the raw-file naming convention. Tag `paper-inferred` with the quoted sentence.
4. Raw-file headers: instrument, acquisition time (batch proxy), DDA vs DIA, TMT reporter presence, fraction index from file name. Tag `file-inferred`.
5. User confirmation of the file → condition → replicate table in an SDRF-shaped editor. Store the result as SDRF and offer to contribute it back to the community repository.

### 7.2 Minimum SDRF content by design (persona-level)

- **All designs**: one row per raw file (per channel for TMT): source name, organism, organism part, cell type, disease, biological replicate, assay name, data file, instrument, cleavage agent, modification parameters, fraction identifier, technical replicate, `factor value[...]` naming the contrast.
- **Label-free DDA**: `label = label free sample`; condition per file. Without it: identification and intensity catalogue only; with it: LFQ with match-between-runs and contrasts.
- **TMT**: `label = TMT126 … TMT134N` per channel; plex grouping; bridge/reference channel stated for cross-plex comparison. Without channel → sample mapping nothing beyond identification is valid.
- **DIA**: `label free sample`, acquisition method DIA, window scheme, library source (library-free vs spectral library).

### 7.3 Validity ladder

| Known | Offer | Withhold |
|---|---|---|
| L0 (raw + organism + instrument) | conversion to mzML, identification against a pinned FASTA, QC (IDs per run, missed cleavages, mass error) | any quantification across samples |
| L1 (enzyme, mods, label type, fractions) | per-run protein-group intensities; aggregate / baseline catalogue; presence-absence | contrasts |
| L2 (file → condition → replicate) | LFQ / TMT / DIA differential analysis with ≥2–3 replicates | cross-plex without bridge |
| L3 (plex, batch, bridge) | batch-aware contrasts; cross-study comparison on the same FASTA and tier | — |

### 7.4 Known-result test

Organelle-IP recovery (interview 3): fraction of IP proteins in MitoCarta (or an equivalent reference list) and fold-enrichment IP vs input or mock. The reference list is outside the panel's corpus; the choice of list and threshold is a decision for the proteomics teammate.

### 7.5 Tier mapping

HPC: MaxQuant / FragPipe / DIA-NN via nf-core/quantms, which consumes exactly this SDRF. Laptop: ThermoRawFileParser → mzML → Sage via quantms. Because quantms is SDRF-driven on both tiers, the recovered SDRF is the single handoff artefact, the proteomics equivalent of riboseq-agent's `plan.json`.

## 8. What experimental researchers care about, mapped to features

Condensed from the panel's ranked list (sources in `nexus-panel-2026-10-17.md` §2).

| Rank | They care about | Feature |
|---|---|---|
| 1 | uniform reprocessing, comparable results | one pinned pipeline per tier; manifest with versions |
| 2 | QC gates visible per sample | periodicity, read length, %CDS, IDs per run with pass/fail in the result card |
| 3 | proof of matched pairs, replicates, non-confounded batch | pairing evidence shown; ΔTE refused on rank-deficient designs |
| 4 | protocol provenance as covariate | inhibitor / nuclease / label type as first-class fields; TI-seq never pooled |
| 5 | adequate depth for the question | usable P-sites / reads per sample vs task threshold |
| 6 | explained match with checkable evidence | quoted methods sentence, accession, USI or GWIPS-style link |
| 7 | ontology-anchored metadata | map organism / tissue / cell type / disease to ontology terms; SDRF-like sample sheet |
| 8 | a known-result positive control | 5'TOP under mTOR inhibition; organelle recovery |
| 9 | raw counts, compositional honesty | deliver raw counts plus size factors, never only TPM |
| 10 | annotation pinning | GENCODE / UniProt release in every manifest |
| 11 | composition awareness for tissue | tissue vs cell-line flag; deconvolution with agreement gate |
| 12 | detection bias of the modality | explain what a proteomics dataset could not have seen |

## 9. What to borrow

From `OwenRackham/riboseq-agent` (private, Juri has access):

- `riboseq_agent/metadata/models.py`: `Run`, `Study`, `SampleAnnotation`, `ExperimentMeta` with `extraction_method`, `StudyPlan` with `paper_metadata` and phase lifecycle. Generalise `SampleType` beyond Ribo/RNA/TI-seq and add the level and provenance tags from §2.
- `riboseq_agent/metadata/pairing.py`: pure Ribo↔RNA pairing by normalised sample-name similarity with auto (≥0.90) and propose (≥0.50) thresholds.
- `riboseq_agent/metadata/sample_meta.py`: regex-then-AI extraction of condition / replicate / timepoint / tissue, with an interactive review table.
- `riboseq_agent/literature/scanner.py`: Europe PMC methods scan for companion accessions and protocol fields. Extend the field list per modality.
- `riboseq_agent/pipeline/psite_bigwig.py`, `ribowaltz_offsets.py`, `bigwig_policy.py`, `bw_qc.py`: per-strand P-site tracks with coherent CPM scaling and a QC JSON.
- `riboseq_agent/pipeline/blockers.py`, `failure_classification.py`: log-pattern blockers with fixes; useful for both tiers.
- `riboseq_agent/bw_catalog.py`: TSV catalogue of tracks joined to plan metadata, the pattern for the GUI's track browser.
- HPC pieces (`runner.py`, `manage_hpc.py`, Iridis configs) stay HPC-tier only.

From `UoSDDNB/kitsune_labs`: strand-aware bigWig reading, per-region and per-transcript coverage extraction, overlay and per-biotype metagene plots. This is the visualisation layer for the tracks the contract promises.

## 10. Open items

- Pick the mTOR-inhibition accession for the Ribo-seq known-result test and confirm its metadata level reaches L2.
- Verify §7.2 against the SDRF-Proteomics specification and lesSDRF / quantms requirements; sample the quality of `bigbio/sdrf-annotated-datasets` for a few PXDs.
- Decide how the level badge and provenance tags appear in the search GUI (teammate's codebase, not in this repo).
- Laptop-tier Ribo-seq path remains designed, not built.
- Expert corpus gaps to close before relying on Nexus for proteomics: SDRF, MaxQuant/DIA-NN, MitoCarta, strandedness; train Pip and Genny.
