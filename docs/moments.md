# Moments

Raw material for the demo video. Each moment is one thing a researcher would retell, the claim it proves, the real dataset it was shown on, a 1280 px screenshot and a short screen capture in `docs/moments/`. Refresh every capture against the running app with `node scripts/captures.mjs --web http://localhost:3010` (one moment: `--only <slug>`).

| Moment (what a researcher retells) | Claim it proves | Shown on | Capture |
|---|---|---|---|
| "I typed SPP1 and saw it rise in IPF in 6 of the 9 lung datasets that could answer, and fall in none." | One gene, every comparable dataset, each row a link to its evidence. | Search "Bulk RNA-seq of lung tissue from idiopathic pulmonary fibrosis patients and healthy controls", then SPP1 | `gene-everywhere.png`, `gene-everywhere.mp4` |
| "It told me which dataset to start with, and why, in one line each." | The answer is counted facts from sample records, not prose. | Search "Matched RNA-seq and Ribo-seq before and after mTOR inhibition" | `start-with.png`, `start-with.mp4` |
| "The authors called these libraries ribosome profiling; locus quoted the harringtonine wash that makes them TIS-seq." | Assays are read from the methods; the author's label is checked, not trusted. | GSE255191 | `tis-trap.png`, `tis-trap.mp4` |
| "It quoted the sentence where they split the lysate, and lined up every Ribo-seq library with its RNA-seq partner." | Proof of matchedness from the methods, per library. | GSE132703 | `matched-split.png`, `matched-split.mp4` |
| "50 of the 63 genes the paper mentions light up on locus's own volcano; chance would give 3." | locus's first look agrees with the paper, and says by how much. | GSE124685 | `first-look-paper.png`, `first-look-paper.mp4` |
| "The low-depth Ribo-seq libraries were re-sequencing top-ups, and locus said so instead of flagging them." | QC from the run table is read in context. | GSE132703 | `quality-top-ups.png`, `quality-top-ups.mp4` |
| "Two clicks: female IPF samples, and the download commands for just those." | Charts filter each other and the table, as on cBioPortal. | GSE173357 | `samples-filter.png`, `samples-filter.mp4` |
| "I saw the first rows of a 28 MB matrix, with each column labelled IPF or control, without downloading it." | Preview from the first bytes, columns matched to samples. | GSE86618 | `file-preview.png`, `file-preview.mp4` |
| "I pasted a PMID and got the paper, what it deposited and what it reused." | Any identifier lands on its locus page. | PMID 35680905 | `paste-paper.png`, `paste-paper.mp4` |
| "Every value in the record, from the instrument to the keywords, opens the other datasets that share it." | Doors become pages. | PXD010450 → Immunopeptidome | `doors-browse.png`, `doors-browse.mp4` |
| "The IPF and control bars were coloured, and so was every row of the table." | Cases and controls are named once and marked everywhere on the page. | GSE173357 | `cases-controls.png`, `cases-controls.mp4` |
| "I clicked the contact's name and saw 42 papers, 13 as last author, the journals, and the 6 datasets in locus." | A contributor's track record without leaving locus. | GSE132703 → Carson C Thoreen | `contributor.png`, `contributor.mp4` |
| "The genes up in IPF came back as extracellular matrix and collagen pathways, with the genes behind each." | The first look says what the top genes do, from Enrichr, with its background stated. | GSE124685 | `pathways.png`, `pathways.mp4` |
| "It told me the authors state footprint length and rRNA removal but never periodicity or replicate agreement." | QC is checked against what a Ribo-seq expert looks for, and gaps are named. | GSE132703 | `ribo-checks.png`, `ribo-checks.mp4` |
| "The PRIDE record never says mito-IP; locus found it in the paper's methods and said so." | Assays are read from the paper when the record leaves them out, and labelled as such. | PXD058312 | `mito-ip-paper.png`, `mito-ip-paper.mp4` |
| "Before I trusted the volcano, it warned that diagnosis partly goes with batch and institution, and that a 1.13× change is detectable." | The design is checked before the numbers are read. | GSE150910 | `design-check.png`, `design-check.mp4` |
| "I pasted my gene list: 3 of 11 are MitoCarta proteins, and 6 are among the significant IPF genes, against 0.6 by chance." | Bring your own list: MitoCarta recovery and its rank in a dataset. | /list against GSE124685 | `your-list.png`, `your-list.mp4` |
| "The protein table was inside a 1.6 GB txt.zip; locus showed proteinGroups.txt, 365 columns, in under a second without downloading it." | Preview reaches inside archives: two Range reads, the zip's directory and the table's first bytes. | PXD047213 | `zip-preview.png`, `zip-preview.mp4` |
| "I pasted my 15 genes once and saw them light up in 8 of 11 IPF datasets, each with its odds against chance." | A list is checked across every comparable dataset of the search, not one at a time. | IPF bulk search → /list | `list-across.png`, `list-across.mp4` |
| "locus read the 300 samples' factors from the Metabolomics Workbench API, 200 controls and 100 T2DM, and drew a volcano where S-adenosylhomocysteine rose." | The first look works on metabolite tables, not only transcripts. | ST003390 | `metabolite-volcano.png`, `metabolite-volcano.mp4` |
| "For phosphoproteomics it told me to start with the study whose protein table I could open right there: 36 samples named, inside a 1.6 GB zip." | The answer works for mass spectrometry too, from what the files hold. | Search "Phosphoproteomics of human liver cancer against normal liver tissue" | `ms-start-with.png`, `ms-start-with.mp4` |
| "It warned me the 540 'samples' were cells from 9 patients, and that only a 7.8-fold change would be detectable." | locus checks the statistics a reviewer would, before the reader trusts a volcano. | GSE86618 | `nested-people.png`, `nested-people.mp4` |
| "The page lists the exact repository API calls it was built from; I can rerun any of them." | Provenance for every fact, from the repository's own API. | GSE132703 | `provenance.png`, `provenance.mp4` |

Not captured: dictation (needs real speech; the headless browser has no microphone).
