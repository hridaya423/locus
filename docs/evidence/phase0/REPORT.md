# Phase 0 evidence report

Date: 17 October 2026. Raw outputs are in this folder. The tests only read data; no code in the app changed.

## Known-answer test: Gate G1 passes

The two *Nature* 2012 papers on mTOR and translation each link to one GEO series through PubMed:

| Paper | PubMed ID | GEO series | Samples |
|---|---|---|---|
| Thoreen et al., "A unifying model for mTORC1-mediated regulation of mRNA translation" | 22552098 | GSE36892 | 12 |
| Hsieh et al., "The translational landscape of mTOR signalling steers cancer initiation and metastasis" | 22367541 | GSE35469 | 12 |

We asked locus this question in plain English: "matched RNA-seq and Ribo-seq before and after mTOR inhibition". The search took 39 s and returned 31 datasets, 14 graded "usable as is". Both series from the papers are in the 14, at rank 4 (GSE36892) and rank 12 (GSE35469).

## Count recount against the GEO sample records

| Series | locus case/control | Hand recount from the sample titles | Match |
|---|---|---|---|
| GSE36892 | 6 / 6 | 6 Torin1, 6 vehicle | exact |
| GSE35469 | 8 / 4 | 4 PP242 + 4 rapamycin, 4 vehicle | exact |
| GSE241588 | 12 / 12 | 12 Torin1, 12 untreated | exact |
| GSE25626 | 9 / 12 | 9 rapamycin, 12 not treated | exact |

The recount also found two problems that locus does not report:

1. **GSE36892 is only partly matched.** It has 8 footprint (Ribo-seq) libraries but only 4 mRNA-seq libraries. Replicate 2 has no RNA-seq.
2. **GSE25626 has no RNA-seq libraries.** It is ribosome profiling only. locus still grades it "usable as is" for a question that asks for matched RNA-seq and Ribo-seq. This is a grading error.

## Baselines on the same plain-English question

| Tool | Results | GSE36892 | GSE35469 | Counts | Check of matched samples |
|---|---|---|---|---|---|
| GEO DataSets search | 0 | – | – | – | – |
| OmicsDI | 0 | – | – | – | – |
| Claude Opus 5.5 with web search | 2 confirmed, 3 more named | found | found | estimated "from memory" | **wrong for GSE36892:** guessed "8 + 8, one RNA-seq per Ribo-seq library"; the records show 8 + 4 |
| locus | 31 (14 usable as is) | rank 4 | rank 12 | exact | not reported (problem 1 above) |

When given expert keywords instead of the plain-English question, the two search tools did better:

- **GEO, query "mTOR ribosome profiling":** 37 results. GSE35469 is ranked 37th, the last result. GSE36892 is missing.
- **OmicsDI, query "mTOR ribosome profiling":** GSE35469 is ranked 1st and GSE36892 is ranked 26th. OmicsDI gives no counts and no check of matched samples.

The chatbot named three other accessions: GSE143333, GSE144539 and GSE158881. All three exist and match its descriptions. It invented nothing and stated its uncertainty clearly. It is a fair and strong baseline.

## Abandoned question: Gate G3 is pending

We asked: "How do isoforms of one gene differ in how efficiently they are translated?" The search took 39 s and returned 27 datasets, 25 graded "usable as is".

- **Method note, which the researcher asked for:** locus said, without being prompted, "Standard Ribo-seq has short reads that often cannot be assigned to a single isoform", and pointed to polysome profiling with long-read sequencing.
- **Candidate datasets:**
  - Long-read Ribo-STAMP (GSE255844).
  - "Tunable protein synthesis by transcript isoforms" (GSE69352).
  - Long-read polysome profiling (GSE326354, GSE244655).
  - "Isoform-specific translational control is evolutionarily conserved" (GSE230441).
  - Single-cell and isoform-specific translational profiling of the mouse brain (several series).
- **Not yet checked:** 25 of 27 graded "usable as is" is generous. Many datasets have no counts. Two biologists need to label these results before we show them live.

## Gate status

| Gate | Status | Evidence |
|---|---|---|
| G1 Receipt | **Pass** | Both datasets found and the counts are exact |
| G2 Catch | **Pass, but locus needs a build to show it** | The strongest baseline guessed matched libraries that do not exist. locus reads the sample records but does not yet show each assay's library count per condition. |
| G3 Comeback | Pending | Needs labels from the researcher and a second biologist |

## Builds this evidence calls for

1. **Library count per assay and condition, from the sample records.** For example, "Torin1: 4 footprint, 2 mRNA-seq; replicate 2 has no mRNA-seq". This is the visible catch for Reveal B.
2. **Grading fix:** a question that asks for matched RNA-seq and Ribo-seq should fail any dataset that has no RNA-seq libraries, such as GSE25626.
3. **Click-through** from a count to the GEO sample list (Reveal A).

## Still to do (people)

- The researcher's timed manual search, thinking aloud.
- Two-biologist labels for the abandoned-question results, and 20–30 datasets in total.
- A chatbot run on ChatGPT and Google Dataset Search. Both need a person, because there is no API.

## After the three builds (same question, rerun on port 8001)

Raw output: `locus-mtor-after-builds.ndjson`. The search took 35 s and returned 34 datasets, 12 graded "usable as is".

- **Library table.** GSE36892 shows Ribo-seq 4 + 4 and RNA-seq 2 + 2, with the warning "4 Ribo-seq libraries have no matching RNA-seq". This matches the hand recount. GSE35469 shows RNA-seq 4 + 2 and Ribo-seq 4 + 2, so it is fully matched.
- **Grading.** The search plan now records which assays must come from the same samples (here RNA-seq and Ribo-seq). A dataset whose counted libraries or labelled assays lack one of them fails the data-type check. As a result:
  - GSE25626 and the RNA-seq-only and microarray series now grade as close matches.
  - All 12 GEO results graded "usable as is" have both assays.
- **Known answer.** GSE36892 now ranks 2nd (it was 4th) and GSE35469 ranks 7th (it was 12th).
- **Click-through.** Each case and control count links to the GEO sample list for its series.

Limits that remain:

- GSE25626 is still labelled RNA-seq, not Ribo-seq, even with the series summary in the prompt. Its grade is correct, but its assay label is not.
- Labelling varies between runs. GSE129816 had counts in one run and none in the next.
- The new ArrayExpress and ENA results have no sample counts.
