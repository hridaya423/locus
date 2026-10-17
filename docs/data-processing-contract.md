# Data-processing contract: laptop tier vs HPC tier

Status: agreed direction from the 17 October 2026 brainstorm. Not an assertion that any pipeline exists in this repository yet.

## Principle

omics-agent has two processing tiers. A user runs one tier, so results need only be comparable **within** a tier. The HPC tier uses the field-standard tools; the laptop tier substitutes lighter tools where the standard ones cannot run in the available memory. Every output ships with a manifest that records tier, tool versions, reference and annotation versions.

Where a trusted, uniformly reprocessed public layer already exists, the agent **fetches** it instead of reprocessing raw data (see "Fetch, don't reprocess" below). The pipeline is still published so that anyone can reprocess additional raw data, matched samples only, or with different parameters.

## Tier definitions

| | Laptop tier | HPC tier |
|---|---|---|
| Target machine | 16 GB RAM laptop, 4–8 GB free, 4–8 cores | Slurm cluster (reference: Iridis X, 64-core / 240 GB AMD nodes, A100/H100/H200 GPUs) |
| Wall-clock budget | overnight: 8–12 h default, 24 h if the user opts in | per-job limits set by the scheduler |
| Container runtime | Docker or Podman | Apptainer |
| Workflow engine | Nextflow, `-profile laptop` | Nextflow, `-profile slurm` |
| Storage pattern | stream one sample, process, delete raw input, clean `work/` per sample | keep raw inputs on scratch, clean `work/` at the end |
| GPU | none | ML rescoring of PSMs, de novo sequencing, scVI / foundation-model embeddings |

Memory, not time, is the binding constraint on the laptop tier. Human STAR indexes need ~32 GB and will not start; MaxQuant and FragPipe need 8–16 GB. Setting `--max_memory 6.GB` alone makes these tools fail rather than fall back, so the laptop profile must select tools explicitly.

## Raw → analysis-ready, by modality

"Target" is the file a biologist can load without further processing. "Comparable unit" is what can be compared across studies processed on the same tier.

| Modality | Raw | Target (analysis-ready) | HPC tier tool | Laptop tier tool | Comparable unit |
|---|---|---|---|---|---|
| Bulk RNA-seq | FASTQ | gene/transcript counts + bigWig | nf-core/rnaseq (STAR + Salmon) | nf-core/rnaseq `--pseudo_aligner salmon --skip_alignment`; no bigWig | counts / TPM, same GENCODE version |
| scRNA-seq | FASTQ | filtered count matrix (`.h5ad`) | nf-core/scrnaseq (STARsolo or Cell Ranger) | nf-core/scrnaseq `--aligner kallisto` (kb-python) | cell × gene with cell-type labels |
| CITE-seq | FASTQ (RNA + ADT) | `.h5mu` RNA + protein | nf-core/scrnaseq feature-barcode mode | kb-python `--workflow kite` | cell × gene + cell × antibody |
| Ribo-seq | FASTQ | P-site bigWig/bedGraph, ORF calls, CDS counts | nf-core/riboseq / riboseq-agent (STAR) | bowtie2 to rRNA then transcriptome; P-sites projected to genome (to be built and checked) | P-site counts per CDS; TE and ΔTE with matched RNA-seq from the same tier |
| ATAC / ChIP / CUT&RUN | FASTQ | bigWig + peaks + consensus count matrix | nf-core/atacseq, chipseq, cutandrun | not offered (needs genome alignment) | counts on a shared peak set |
| WGS / WES | FASTQ | VCF / gVCF | nf-core/sarek (DRAGEN node where available) | not offered | variants on the same reference |
| Bisulfite-seq | FASTQ | methylation bedGraph / `.cov` | nf-core/methylseq | not offered | β-values per CpG |
| Long-read RNA | POD5 / uBAM | isoform GTF + isoform counts | nf-core/nanoseq, IsoQuant | not offered | isoform counts |
| Hi-C | FASTQ | `.mcool` / `.hic` | nf-core/hic | not offered | contact matrices at fixed resolution |
| MPRA | FASTQ | element activity table | MPRAflow / MPRAsnakeflow | same (light) | log2 RNA/DNA per element |
| Spatial transcriptomics | FASTQ + image | `.h5ad` with coordinates | spaceranger / nf-core/spatialvi | not offered | spot × gene |
| DDA proteomics | vendor `.raw` / `.d` / `.wiff` | protein-group and peptide intensity matrices (mzTab, `proteinGroups.txt`) + SDRF | MaxQuant or FragPipe; nf-core/quantms | ThermoRawFileParser → mzML → **Sage** via nf-core/quantms | protein-group LFQ intensities with q-values |
| DIA proteomics | vendor raw | `pg_matrix.tsv`, `pr_matrix.tsv` | DIA-NN library-free (quantms) | DIA-NN with a spectral library | precursor / protein matrices |
| TMT / isobaric | vendor raw | reporter-ion protein matrix per plex | quantms, FragPipe-TMT, MaxQuant | Sage (supports TMT) | within-plex ratios; cross-plex via bridge channel |
| Phospho / PTM | vendor raw | site table with localisation probability | as above with PTM search | Sage with variable mods | site intensity, localisation ≥ 0.75 |
| Metabolomics / lipidomics | vendor raw | annotated feature table (mzTab-M) | MZmine 3, XCMS, nf-core/metaboigniter, GNPS | same | feature intensities, annotation tiered by MSI level |

Indicative laptop-tier throughput in a 12-hour window on 8 cores: 20–40 bulk RNA-seq samples, 5–8 10x samples, 40–100 DDA raw files, or one Ribo-seq study with matched RNA-seq. Disk and download bandwidth (10x FASTQs 20–50 GB per sample, proteomics raw 1–3 GB per file) bind before CPU does.

## Common output shape

Every modality converges on the same four objects, which is what the GUI renders:

1. sample × feature matrix
2. sample metadata table (SDRF for proteomics, curated metadata from the search step otherwise)
3. feature annotation table (see "Per-gene feature table")
4. genome-browser tracks (bigWig) for sequence-anchored modalities, HPC tier only unless noted

`.h5ad` / `.h5mu` (AnnData / MuData) is the container for 1–3. Mass spec has no BAM equivalent: identification and quantification depend on the search FASTA, so a proteomics output is only defined relative to a recorded FASTA. For smORF work the FASTA is built from Ribo-seq ORF calls, which makes the two modalities dependent.

## Manifest

Every run writes a manifest alongside its outputs containing: tier and profile, pipeline name and version, tool names and versions, container digests, reference genome / proteome and annotation version (e.g. GENCODE release, UniProt release date), search FASTA checksum for proteomics, input accessions and file checksums, start and end time, and any samples that failed or were skipped.

## Fetch, don't reprocess

Prefer these uniformly processed layers to reprocessing raw data, and record the source in the manifest:

- **recount3 / ARCHS4**: human and mouse bulk RNA-seq gene and exon counts, one pipeline across ~750k samples.
- **CELLxGENE Census**: harmonised single-cell `.h5ad` with ontology cell types.
- **Expression Atlas**: curated bulk and single-cell expression.

No such layer exists for PRIDE, Ribo-seq or metabolomics repositories. Reprocessing budget goes there first, and to any case where matched samples must go through the same pipeline (ΔTE, Ribo-seq ORF → peptide validation).

## Per-gene feature table

Computed once per reference (GTF + genome FASTA), independent of any dataset, and used to colour embeddings: transcript and CDS length, GC content, 5′ UTR / 3′ UTR length, minimum free energy (ViennaRNA RNAfold), uORF count, Kozak score, codon adaptation index, RBP and miRNA motif counts (FIMO with ATtRACT / CISBP-RNA). Stored as the feature annotation table in the common output shape.

## Open items

- Laptop-tier Ribo-seq path (transcriptome alignment and P-site projection) is designed, not built.
- Whether nf-core/riboseq can run without STAR needs checking.
- Which modalities marked "not offered" on the laptop tier deserve a reduced version.
- How the processing step is surfaced in the GUI without cluttering the search view (next brainstorm step).
