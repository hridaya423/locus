# MaxQuant search kit for PRIDE datasets

Status: asked for by Juri at 08:15 BST on 18 October 2026. Built on the `maxquant-kit` branch (off `main`) by 08:35 BST; see the status log. Additive: it must not change or risk anything in the demo path.

## Where the idea comes from

`FlynnLachendro/pridemap` (MIT; Juri is one of the copyright holders, so reuse is clean) generates a per-dataset "search kit": scripts that preflight the machine, pull the raw instrument files from PRIDE, fetch the UniProt reference proteome, convert vendor formats where needed, and run MaxQuant in Docker, streaming progress and resuming after an interruption. It also carries an `mqpar.xml` contract with tests and a validator. Read `docs/maxquant-local.md`, `tests/test_mqpar_contract.py` and `tools/mqpar-validate/` there before writing anything.

Credit it the way the web app already credits pridemap: a `LICENSE.pridemap`-style notice naming the MIT licence and its authors, and a line in the README. Prefer re-implementing in this repository's style over copying files, but where a file is taken, keep its notice.

## What locus adds

A **Download MaxQuant kit** action on PRIDE rows, next to the existing samplesheet export, producing a zip containing:

- `mqpar.xml` with the dataset's own parameters filled in: the raw file list, the experiment and fraction assignment taken from the SDRF (phase 2 already parses it), the labelling type from `comment[label]`, the instrument from `comment[instrument]`, the FASTA, and sensible defaults for everything else. Variable and fixed modifications follow the SDRF where it states them.
- `fasta/` fetch script for the UniProt reference proteome matching `characteristics[organism]`.
- `download_raw.sh` for the project's raw files from PRIDE, with checksums where PRIDE publishes them.
- `run_maxquant.sh`, `preflight.sh`, `run_all.sh`: resume-safe, progress to a JSONL file, exits on first failure.
- `README.txt`: what the kit does, the exact commands, the resource requirements, and the honest caveats below.

## The caveat, stated everywhere it appears

**This does not run on a laptop and it does not run here.** MaxQuant needs 8–16 GB of RAM per search and hours to days of CPU, and the published container is x86-64 while this machine is ARM64, so it would run only under emulation. Per `docs/data-processing-contract.md`, proteomics is HPC tier. So:

- The kit is **generated and validated** by locus, and **run by the user** on a cluster or a workstation that meets the requirements.
- The button's label and the README say so plainly. No progress bar, no implication that a search is running.
- Add a Slurm submission script (`submit_slurm.sh`) with the memory, CPU and walltime the search needs, since HPC is where this will actually run.

## Acceptance

1. `mqpar.xml` is generated for three real PRIDE projects with different labelling (one label-free, one TMT, one with fractions) and each passes a schema or contract check; print the diff of the fields that differ between them.
2. The kit's scripts pass `shellcheck` or an equivalent syntax check; `preflight.sh` run here reports the architecture and memory blockers correctly rather than claiming it can proceed.
3. Tests cover the SDRF-to-mqpar mapping, including a project with no SDRF, where the kit must refuse with a clear message rather than guess.
4. `uv run pytest` and `npm run build` pass; the demo path (search, Process, figures) is untouched and still passes.
5. README and the row action both carry the HPC caveat; pridemap is credited with its MIT notice.
6. Committed on a branch off `main`, pushed, with a PR description ready. Do not merge to `main` while the pitch is running.

## Priority

Below everything in the delivery checklist. If the submission or the demo needs attention, stop this and say so.

## Status log

- 2026-10-18 08:15 BST: spec written; no code yet.
- 2026-10-18 08:35 BST: built, on branch `maxquant-kit` off `main`. The branch lives in its own worktree (`/home/jlw/fast/locus/omics-agent.wt/maxquant-kit`) because the demo's web app on port 3020 is `next dev` serving `/home/jlw/fast/locus/omics-agent.wt/juri-processing-pipeline/web`, so editing files there would have hot-reloaded into the pitch.
  - Acceptance 1 passes: `uv run python -m omics_agent.maxquant PXD000159 PXD000001 PXD001345 --out kits` writes three kits (label-free Orbitrap, TMT6plex, fractionated label-free with 8 experiments × 3 fractions), each passing `validate_mqpar` (the PRIDE Map contract re-implemented), and prints the 14 fields that differ (lcmsRunType, lfqMode, matchBetweenRuns, isobaricLabels, reporter settings, fractions, experiments, FASTA, variable modifications, run count); 41 fields are the same.
  - Acceptance 2 passes: `shellcheck -S warning` on the 18 generated scripts is clean, `bash -n` passes. `preflight.sh` on pgx (aarch64, 121 GB total, 11 GB available with the demo services up) reports two blockers, architecture and memory, writes a `blocked` line to `progress.jsonl` and exits 1.
  - Acceptance 3 passes: `tests/test_maxquant.py` (11 tests) covers label-free, TMT, fractions and modifications from the SDRF, reagent inference, SILAC multiplicity, the contract catching each known late failure, kit files and notices, and the refusal without an SDRF (`LookupError`, surfaced as a 404 with the message by the API).
  - Acceptance 4 passes: `uv run pytest` 32 passed; `npm run build` and `npm run lint` pass. The demo path is untouched: `agent.py`, `process.py`, `search.tsx`, `process-panel.tsx` and the figures have no diff; `api.py` gains one route, `result-card.tsx` one action on PRIDE rows.
  - Acceptance 5 passes: the caveat is in the kit's README.txt and preflight.sh, the README's "MaxQuant search kit" section and the row action's label text. `LICENSE.pridemap` added at the repository root; credit in README.md, the module docstring and the kit's README.txt.
  - Acceptance 6: committed and pushed to `origin/maxquant-kit`; draft PR https://github.com/UoSDDNB/omics-agent/pull/1 against `main`, not merged.
  - Not done, by design: the deep validator that parses mqpar.xml with MaxQuant's own libraries (PRIDE Map's `tools/mqpar-validate`) needs the x86-64 MaxQuant image and so cannot run here; the structural contract check is what runs. SILAC amino acids are assumed (Arg10;Lys8) because the SDRF does not name them, and the kit says so. No MCP tool for the kit yet.

_Paths updated 2026-10-27: the checkouts moved from ~/omics-agent* to ~/fast/locus/omics-agent(.wt/<branch>) and the index from ~/locus-data to ~/fast/locus/data on 25 Oct 2026._
