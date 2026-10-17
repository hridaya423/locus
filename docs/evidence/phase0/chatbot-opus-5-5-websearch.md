I could only confirm two datasets that fit your criteria. My searches stopped working partway through (the search tool hit its usage limit), so I couldn't check exact sample counts on GEO. Treat the numbers below as what I expect, and check them against each GEO "Samples" list or the SRA Run Selector before you use them.

## Confirmed datasets

**1. GSE36892 — Thoreen et al. 2012, *Nature* (mouse)**
- **Cells and treatment:** Mouse embryonic fibroblasts (MEFs), normal (wild-type) and 4E-BP1/2 double knockout, treated with Torin1 or vehicle (DMSO) for 2 hours.
- **Ribo-seq samples:** The GWIPS-viz page that reprocessed this data lists 8 Ribo-seq runs:
  - Wild-type: 2 Torin1, 2 vehicle
  - Knockout: 2 Torin1, 2 vehicle
  - Total: 4 treated and 4 control
- **Matched RNA-seq:** Probably yes, but not confirmed. The paper calculated translation efficiency, so I expect one RNA-seq library for each Ribo-seq library (8 + 8). There are also gaps in the run numbering that other libraries could fill. The page I saw only listed the Ribo-seq runs.

**2. GSE35469 — Hsieh et al. 2012, *Nature* (human)**
- **Cells and treatment:** PC3 prostate cancer cells treated with vehicle, PP242 (an mTOR kinase inhibitor like Torin1) or rapamycin.
- **Libraries:** The GEO sample titles confirm both kinds of library, named "Footprint" (Ribo-seq) and "mRNA-seq", for numbered replicates. For example: "Footprint for PP242 treated PC3 cells, replicate #1" and "mRNA-seq for vehicle treated PC3 cells, replicate #2".
- **Sample counts (from memory, not checked):** about 2 replicates per condition. That would be roughly 2 vehicle, 2 PP242 and 2 rapamycin, each with Ribo-seq and RNA-seq.
- **Matched RNA-seq:** The naming suggests every footprint library has an mRNA-seq library for the same condition and replicate. I couldn't see the full sample list to confirm this.
- **Note:** INK128 was developed in this paper, but as far as I know it was tested in other assays, not by Ribo-seq. The Ribo-seq used PP242 and rapamycin.

## Possible datasets I couldn't check (accessions not confirmed)
- **Philippe et al. 2020, *PNAS* (LARP1 study):** HEK293T cells, normal and LARP1 knockout, with and without Torin1. I believe it has both Ribo-seq and RNA-seq.
- **Gameiro & Struhl 2018, *Cell Reports*:** MCF10A-derived cells; I believe it includes Torin1 alongside nutrient deprivation, with Ribo-seq and RNA-seq.
- **Park et al. 2017, *Cell Reports* (mTORC1 and ATF4):** check whether it has Ribo-seq or only polysome profiling.

## Close but not a fit
- **Gandin et al. 2016 and Morita et al. 2013:** These are mTOR-inhibition studies, but they used polysome profiling rather than Ribo-seq. They could work if polysome-based translation efficiency is acceptable.
- **GSE143333, GSE144539, GSE158881 (mouse hippocampus, TSC2/FMRP):** These change mTOR signalling genetically, not with a drug.

## How to check
1. Open each GEO series and look at the sample list. Make sure every footprint/RPF sample has an mRNA-seq sample with the same condition and replicate.
2. Search GWIPS-viz, RPFdb or the Ribo-seq atlas for "Torin" or "rapamycin" to find other studies.

If you send me the GEO sample lists, I can build the treated/control matching table for you.