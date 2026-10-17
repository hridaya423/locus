# product.md

## Who
Computational biologist with a wet-lab background working on translation regulation: Ribo-seq, Ribo-STAMP, matched RNA-seq/Ribo-seq, with interest in isoform- and single-cell-resolution translation and the role of translation in cognition ("like long-term memory formation"). Spoke on behalf of biological researchers generally across the omics: "genome sequencing and expression analysis with various -seq types (like ATAC-seq, CITE-seq, etc.), to transcriptomics and translatomics and proteomics and metabolomics etc."

## Pain, in their words
1. **Finding data takes manual detective work across papers and repositories.** Their last search: "I looked first in google to find the actual paper and then within that used ctrl-f to find the gse accession number and pasted that into the GEO website search line." They then had to verify "which data it links to (the specific Riboseq and Ribostamp data from the papers I had found them by)". Time lost: not stated.
2. **Search tools match keywords and don't understand the biology.** OmicsDI "at least partially addresses this gap" but "the natural language aspect is lacking". Their example: "If I e.g. ask for transcript isoform resolution translation evidence data, it should know that riboseq data does not resolve at the isoform resolution due to the riboseq short reads rarely overlapping exon junctions." Even knowing which methods exist was a barrier: "Even finding out relevant experimental methods (like Ribo-STAMP but possibly also other modalities) was a hindrance." Time lost: not stated.
3. **Processing after download is slow and manual for most researchers.** "the downstream processing/analysis/visualisation that right now is often done manually, painstakingly and slowly by non-computational wet-lab people." For their own Ribo-seq work they handed accessions to riboseq-agent (https://github.com/OwenRackham/riboseq-agent) "to make plans based on which automatic downloading and downstream processing would be initiated", and they want "something like that, but for other data modalities". Time lost: not stated.

## The question they gave up on
"how isoforms of a single gene differ in translation patterns." What stopped them: "the barrier of identifying reliably relevant data (something an agent should identify and convince me of)", plus not knowing which experimental methods could answer it.

A related, larger need: "matched RNA and Riboseq data to derive reliable labels of translation efficiency and the holy grail - deltaTE labels, so labels for how translation efficiency changed across treatment/upon perturbation/between treatment/KO and control/WT". This requires "sample-matched RNA and Riboseq data before and after treatment and then to avoid batch effects reprocess those from the raw fastq files". They said riboseq-agent addressed the reprocessing part.

## The Monday-morning ask
- **Standing job:** "monitor any data that is published as it relates to measuring translation and ideally measuring it at multiple levels and resolutions simultaneously (at the level of transcript isoforms, single cells, co-measuring RNA abundance and RPF abundance, measuring downstream protein abundance, effects of RBPs, mi-RNAs, MPRAs of different UTR combinations etc.)"
- **Immediate task:** "get me TE labels per cell type and deltaTE labels per treatment condition/disease, functional knockout, developmental stage etc." Particular interest: "the role of translation in cognition, like long-term memory formation".
- **Then:** "get the raw fastq's and process using riboseq-agent" (possibly also "clean up or even re-build riboseq-agent from scratch since it's gotten a bit cluttered through interations/vibe-coding/pivots/adding functions"), producing ".bigwig files of matched RNA and Riboseq (and potentially also matched protein abundances if available), ideally at the transcript isoform level, and potentially also data at single cell level, although I think it's sparse".
- **End goal:** "finetune sequence models for predicting translation intensity from sequence for smORF discovery as well as generation of novel transcripts with specified levels of translation (controlled up- or downregulation)".

## Trust
What the tool must show:
- **The authors' QC:** "focussing on the QC the researchers applied when getting the data (e.g., 70% cutoff for PIF of RPF signal and presence only in CDS as criteria of accepting the data as measuring genuine translation)".
- **Signals of the source's integrity:** "other publications of that researcher/research group, the journal they published in and the supplementary data they published".
- **Proof of matchedness from the methods section:** "verify the degree of 'matchedness' and when asked explain at which point the samples [were] split and how they were split for matched rnaseq and riboseq protocol execution."
- **A known result reproduced** before trusting the label pipeline (see Demo candidate).

Where AI has already failed them: "The riboseq agent has in the past confused experimental methods and taken e.g. TIS-seq for riboseq-data."

Interviewer note: TIS-seq captures initiating ribosomes (harringtonine/lactimidomycin treatment), so it is not interchangeable with standard elongating-footprint Ribo-seq. Repository library-type fields alone may not tell them apart, so the agent likely has to read the methods.

## Reaction to the direction
- **Most valuable:** not stated directly. Interviewer note: their earlier answers put the most weight on an agent that "feel[s] like a science collaborator that understands what the user is asking for beyond simple keyword matching", one that explains why data fits and can "convince me of" its relevance.
- **What is missing or wrong:** "'delivers the data ready for analysis' is vague for now". Their version: "it would first suggest the relevant data and ask the user whether it should download the raw data to a proposed location and also offer processing steps". On building it: "we can borrow from riboseq-agent which borrows from next-flow for sequencing data and then from other public repos for processing proteomics data to build on what already works and merge it in one place [omics-agent] rather than building from scratch".
- **Scope they described:** search across many omics types using the same backends OmicsDI uses ("like PRIDE for proteomics, SRA for sequencing data, GEO for multiomics, etc."), metadata curation, and "a neat gui that accepts and sends concise, expert-guided natural language". The order: "First getting broad with the types of data one can search for and then specific with the downstream processing". "Downstream uniform processing for reliable quantification/visualisation is the ambitious followup on the search function of the agent."

## Demo candidate
- **Research question:** reproduce a known translational response from matched RNA-seq/Ribo-seq data using ΔTE labels. Their framing: "first briefly stating the known expected results ... and then verifying that using the deltaTE label would be a good sanity test that would enhance my trust in the model derivation pipeline".
- **Well-known result:** the shift in translation of TOP mRNAs under mTOR inhibition. Interviewer note: the interviewer suggested this example and the respondent accepted it ("to me that one would be convincing"). They noted "There may be better, more convinving, more layman-friendly examples".
- **Known datasets:** none named.
- **Open method question:** "the maths part of how to derive the labels from the matched data is a moving part in this - deltaTE DESeq2 is for deltaTE labels but a compositional approach may be better for the baseline TE labels".

## Their ideal product
A chat-like science collaborator with a clean GUI. You describe what you need in plain language, and it understands the biology behind the request, for example that Ribo-seq can't resolve isoforms and that Ribo-STAMP or other methods might. It searches across public omics repositories (GEO, SRA, PRIDE and others), suggests relevant datasets with reasons, and backs each one with the authors' QC, the methods-section evidence for how matched the samples are, and the track record of the group and journal. It never confuses one assay for another. Once you approve, it downloads raw data to a location it proposes and offers uniform processing, built from existing pipelines such as riboseq-agent and nf-core rather than new code. The output is matched RNA, Ribo-seq and, where available, protein tracks, plus TE and ΔTE labels. Over time it watches for newly published translation datasets, so the respondent can build isoform-level training sets for sequence-to-translation models.
