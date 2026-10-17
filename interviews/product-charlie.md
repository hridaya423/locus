
## Who
I am a PhD student and bioinformatician who uses single-cell RNA sequencing and machine learning to build gene regulatory networks that reveal relationships between genes and transcription factors. My research relies heavily on publicly available datasets from repositories such as GEO, SRA and 10x Genomics for transcriptomics, alongside PRIDE and iProX for proteomics validation. A significant part of my work involves identifying suitable datasets across multiple repositories before performing downstream integrative analyses.

## Pain, in their words
Finding suitable datasets is often harder than analysing them. GEO and PRIDE searches are difficult to reproduce, frequently return incomplete results, and rely on inconsistent user-defined labels and descriptions. Metadata quality varies substantially between submissions, making it difficult to identify relevant experiments without manually reading protocols, publications and supplementary materials. As a result, dataset discovery can take days and becomes a major bottleneck in the research workflow.

## The question they gave up on
"Where are the datasets that actually match my biological question?"

Repositories contain thousands of datasets, but there is no reliable way to search based on the experimental biology being studied. Researchers must manually inspect protocols, reagents, instruments and publications to determine whether a dataset truly contains the data they need. Searching for a specific biological context often feels like finding a needle in a haystack.

## The Monday-morning ask
1. Create standardised biological categories

Automatically classify datasets using metadata, experimental protocols, reagents, chemicals, antibodies, instruments and sequencing technologies rather than relying solely on author-provided labels.

Examples:

10x Chromium reagents → Single-cell RNA-seq
SMART-seq2 protocol → Plate-based scRNA-seq
TMT reagents → Quantitative proteomics
Anti-HLA antibodies → Immunopeptidomics
Visium slides → Spatial transcriptomics
2. Enable biological keyword searching

Allow researchers to search using biological concepts rather than repository-specific terminology.

For example:

Search: "human immunopeptidomics"

Automatically include:

HLA
MHC
MHC-I
MHC-II
antigen presentation
immunopeptidome
ligandome
HLA-A
HLA-B
HLA-C

The user should not need to know every synonym or technical term beforehand.

## Trust
The platform must demonstrate biological understanding rather than simple keyword matching.

For every search result, the tool should:

Show why the dataset was returned.
Highlight matched metadata fields.
Display detected biological concepts and synonyms.
Explain which protocol characteristics support the classification.
Provide confidence scores for classifications.

For example, searching for "human immunopeptidomics" should successfully retrieve datasets labelled as HLA peptidomics, MHC ligandomics or antigen presentation studies, even when the exact search term does not appear in the dataset title.

## Reaction to the direction
The most valuable aspect is the biological enrichment layer that translates research questions into biologically relevant search terms and identifies datasets using protocol evidence.

The missing piece in existing repositories is not access to data but understanding of the underlying biology. Simply creating categories is not enough. The system must infer biological context from protocols, reagents and metadata to identify relevant datasets even when they have been poorly described by the original submitter.
## Demo candidate
Research question

Identify human immunopeptidomics datasets from cancer samples that can be integrated with transcriptomics data to investigate antigen presentation pathways and HLA regulation.

Known datasets

The demonstration should include well-characterised immunopeptidomics datasets from repositories such as:

PRIDE
MassIVE
ProteomeXchange
iProX

alongside associated transcriptomic datasets from:

GEO
SRA
10x Genomics
Well-known result to validate against

A search for "human immunopeptidomics" should retrieve datasets related to:

HLA peptidomics
MHC ligandomics
antigen presentation
HLA class I
HLA class II

even when "human immunopeptidomics" is absent from the title or repository tags.

Success is demonstrated when the tool consistently retrieves these known datasets while explaining the biological evidence used to identify them.

## Their ideal product
I use a single search platform that connects GEO, SRA, 10x Genomics, PRIDE, iProX, MassIVE and other public repositories through one interface. Instead of relying on inconsistent repository labels, the platform automatically analyses metadata, protocols, reagents, instruments and associated publications to classify datasets into biologically meaningful categories. I can search using natural biological terms such as "human immunopeptidomics", "early embryonic development" or "single-cell liver fibrosis", and the system automatically expands my query using biological ontologies, pathways, genes, proteins and experimental methods. Every result explains why it was selected, what protocol evidence supports its classification, and how strongly it matches my biological question. What currently takes days of manual searching and protocol review can be accomplished in minutes with confidence that relevant datasets have not been missed.