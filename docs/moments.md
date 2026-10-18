# Moments

Raw material for the demo video. Each moment is one thing a researcher would retell, the claim it proves, the real dataset it was shown on, a 1280 px screenshot and a short screen capture in `docs/moments/`. Refresh every capture against the running app with `node scripts/captures.mjs --web http://localhost:3010` (one moment: `--only <slug>`).

| Moment (what a researcher retells) | Claim it proves | Shown on | Capture |
|---|---|---|---|
| "I typed SPP1 and saw it rise in IPF in every lung dataset that could answer, in 16 seconds." | One gene, every comparable dataset, each row a link to its evidence. | Search "Bulk RNA-seq of lung tissue from idiopathic pulmonary fibrosis patients and healthy controls", then SPP1 | `gene-everywhere.png`, `gene-everywhere.mp4` |
| "It told me which dataset to start with, and why, in one line each." | The answer is counted facts from sample records, not prose. | Search "Matched RNA-seq and Ribo-seq before and after mTOR inhibition" | `start-with.png`, `start-with.mp4` |
| "The authors called these libraries ribosome profiling; locus quoted the harringtonine wash that makes them TIS-seq." | Assays are read from the methods; the author's label is checked, not trusted. | GSE255191 | `tis-trap.png`, `tis-trap.mp4` |
| "It quoted the sentence where they split the lysate, and lined up every Ribo-seq library with its RNA-seq partner." | Proof of matchedness from the methods, per library. | GSE132703 | `matched-split.png`, `matched-split.mp4` |
| "50 of the 63 genes the paper mentions light up on locus's own volcano; chance would give 3." | locus's first look agrees with the paper, and says by how much. | GSE124685 | `first-look-paper.png`, `first-look-paper.mp4` |
| "The low-depth Ribo-seq libraries were re-sequencing top-ups, and locus said so instead of flagging them." | QC from the run table is read in context. | GSE132703 | `quality-top-ups.png`, `quality-top-ups.mp4` |
| "Two clicks: female IPF samples, and the download commands for just those." | Charts filter each other and the table, as on cBioPortal. | GSE173357 | `samples-filter.png`, `samples-filter.mp4` |
| "I saw the first rows of a 28 MB matrix, with each column labelled IPF or control, without downloading it." | Preview from the first bytes, columns matched to samples. | GSE86618 | `file-preview.png`, `file-preview.mp4` |
| "I pasted a PMID and got the paper, what it deposited and what it reused." | Any identifier lands on its locus page. | PMID 35680905 | `paste-paper.png`, `paste-paper.mp4` |
| "Every value on the page opens the other datasets that share it." | Doors become pages. | PXD010450 → Immunopeptidome | `doors-browse.png`, `doors-browse.mp4` |

Not yet captured: design check (GSE150910: diagnosis partly goes with institution, plate balanced, 1.13× detectable), your list against MitoCarta 3.0, dictation.
