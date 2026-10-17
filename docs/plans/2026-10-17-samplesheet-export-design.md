# Samplesheet export for nf-core/riboseq

## Goal

A researcher selects a GEO result and downloads a zip with three files: `samplesheet.csv` and `contrasts.csv` in the nf-core/riboseq 1.2.0 format, and a `README.txt`. Each cell comes from a GEO or ENA record, or the README says why the cell is missing. locus writes the files. locus does not run the pipeline.

## Why the file is the hard part

A wrong `type` or `pair` value does not stop the pipeline. The pipeline finishes and gives a wrong translational efficiency result. The cached GEO records show the three cases the export must handle:

- GSE36892 has a second factor (genotype). The four Replicate 2 footprint libraries have no mRNA library.
- GSE35469 has two drugs (rapamycin, PP242) against one vehicle.
- GSE132703 has three genotypes and four resequenced RPF libraries with no RNA library.

## How nf-core/riboseq uses the files

Read from the 1.2.0 source (`conf/modules.config`, `anota2seqrun.r`):

- The pipeline runs anota2seq once for each contrast row, with `--subset_to_contrast_samples TRUE`. Only samples whose `variable` column equals `reference` or `target` go in.
- With a `pair` column, anota2seq sorts the Ribo-seq samples and the RNA-seq samples by the pair value and uses them as matched columns. Thus each contrast must contain the same number of Ribo-seq and RNA-seq samples, and each must have a unique pair value.

## Design

Source data: the GEO sample records (`samples.geo_records`) and the Haiku labels (`agent.geo_labels`, cached per study and topic, and shared with the search so that the table counts and the export agree).

For each sample:

- `sample` is the GSM ID. One row for each SRA run; nf-core merges rows with the same sample.
- `fastq_1`, `fastq_2` come from one ENA query over all SRX IDs of the series, as HTTPS URLs.
- `type` comes from the assay labels. Assays other than Ribo-seq, RNA-seq and TIS-seq are left out and listed in the README.
- `group` is case, control, mixed or other, from the labels.
- One column for each characteristic that varies within the series. A field whose values each belong to one assay (for example "fraction: Total RNA") is left out, because it only repeats `type`.
- `pair` links one Ribo-seq and one RNA-seq library. The rule removes words that occur in the titles of only one assay (for example "Footprint", "RPF", "mRNA"). Two libraries pair only if they are the only two with the same remaining title and the same characteristics. Otherwise the cell stays empty. A wrong pair is worse than an empty cell.
- `condition` is the design value that contrasts use. It is the treatment level (the value of the group field, or case/control when that field also names the assay), inside each level of every crossed factor. A crossed factor has both case and control samples at each of its levels, for example genotype in GSE36892. Replicate, batch, donor, sex and age fields are not crossed factors. An unpaired Ribo-seq or RNA-seq library gets `<condition>_unpaired`, so no contrast includes it.

Contrasts: one row for each control and case condition in the same stratum, if each side has at least two pairs. Other combinations go in the README with the reason.

## Verification

- `uv run python -m omics_agent.samplesheet` checks the pairing and condition rules on the GSE36892 design without network access.
- The exports for GSE36892, GSE35469, GSE132703 and GSE225683 pass the nf-core/riboseq `schema_input.json` and match a hand-written expectation.
- Independent check still to do: the team researcher reviews one export.

## Not built

- Running the pipeline, and other pipeline formats (nf-core/rnaseq, nf-core/scrnaseq).
- PRIDE or ENA-only studies.
- An MCP tool for the export. Add it when an agent needs the export.
