# Delivery checklist for the 18 October pitch

The judging criteria from the hackathon slides, and what satisfies each. Written at 01:05 BST on 18 October 2026. Pitches 10:15–12:15, **submission by 10:00** (repo URL + commit hash), team meeting 09:00.

| Criterion | 10 points each | What we show |
|---|---|---|
| Impact | "How useful is the tool to the scientific community? Does it solve a real pain point?" | Finding a public dataset and getting an answer out of it takes days and a bioinformatician. locus searches 891k datasets across 18 repositories, counts case and control samples from the sample records, and now runs the first analysis on a laptop. |
| Technical execution | "Is the tool working and usable? Does it solve the problem it claims to solve?" | A real run, not a mock: GSE273888 from subsampled ENA reads to `.count` files to DESeq2 to figures, 3 minutes on this machine, with every tool version in a manifest. 21 tests pass. |
| Presentation | "Can non-experts understand the problem, its importance and the solution?" | `docs/plans/2026-10-18-demo-script.md`, three minutes, no assumed knowledge of GEO, salmon or DESeq2. The slides' own framing: what is it for, what was not working, what did we make better. |

## Blocker: the submitted repository must be public

The slides require "a new public GitHub repository", a permissive licence with a `LICENSE` file in the root, and no commit history from before the hackathon.

Current state, checked 01:05:

- `UoSDDNB/omics-agent` is **PRIVATE**. Apache-2.0, history starts 17 October, so the licence and history are fine, but it cannot be submitted while private.
- `hridaya423/locus` is **PUBLIC**, Apache-2.0, but its last push was 15:32 on 17 October, so it lacks everything built since: Compare, the enrichment work, the local-model option, the whole processing pipeline, the figures and voice mode.

Two ways to resolve, needing a human decision at 09:00:

1. **Make `UoSDDNB/omics-agent` public** (`gh repo edit UoSDDNB/omics-agent --visibility public --accept-visibility-change-consequences`). Needs org permission. Check `interviews/` and `data/` first for anything personal that should not be public; `.env` is gitignored and must stay out.
2. **Push the final state to `hridaya423/locus`**, which is already public. Needs Hridya's agreement, and they must add it as a remote or grant push access.

Whichever is chosen, the submitted commit must contain the processing pipeline, which currently lives only on `juri-processing-pipeline`.

## Morning runbook

1. **Read the overnight results.** Status logs in `docs/plans/2026-10-18-fastq-to-deseq2-mvp.md`, `…-phase2-explain-and-sdrf.md`, `…-phase3-figures-and-voice.md`. Logs: `~/overnight-goal*.log`.
2. **Free the GPU for the demo.** The expert-distillation run shares the vLLM server on port 8000 with locus search. `~/gpu-guard.sh` stops it at 07:45 automatically; confirm with `pgrep -af run_qwen_v2` returning nothing. Restart it after the pitch with the resume command in `~/train-domain-experts/RUN.md`.
3. **Merge for submission.** `git -C /home/jlw/omics-agent fetch && git -C /home/jlw/omics-agent merge --ff-only juri-processing-pipeline` (it is a fast-forward unless Hridya pushed to `main` overnight; if they did, merge their work in first and re-run the tests).
4. **Smoke test from the merged state**: `uv run pytest`, `uv run omics process GSE273888` against the cached run, `npm run build`.
5. **Start the services** for the demo: API on 8020, web on 3020, with `data/process/GSE273888/` present so Process returns instantly. A live search takes about 8 minutes on the local model, so either start it before the pitch or use the cached question.
6. **Submit**: repo URL plus `git rev-parse HEAD`, before 10:00.

## Demo risks and their answers

| Risk | Answer |
|---|---|
| Live search is slow on the local model | Use the cached question; the plan and sample labels are cached, so a repeat is fast. Say out loud that it runs on a local model with no API key. |
| Voice mode needs a secure context | Over `http://<ip>:3020` the browser blocks the microphone. Demo it on `localhost` on the presenting machine, or show the disabled state and explain why. Do not claim it works if it does not. |
| A judge asks whether the numbers are real | They are: 2,000,000 reads per sample from ENA, 89% mapping, 84 genes at padj < 0.05, DDIT4 and SCD down after rapamycin as expected. Subsampling is stated in the manifest and on the slide. |
| A judge asks what is not finished | Honest list: proteomics counts only cover projects with an SDRF; Ribo-seq and ΔTE are designed but not built; one contrast per dataset; the HPC tier is nf-core, not ours. |

## Secondary work, explicitly not for the pitch

The expert-knowledge distillation (`~/train-domain-experts`) and the sequence-to-TE diagnosis (`/home/jlw/seq2te`) run tonight on their own goals. Neither appears in the pitch, neither blocks submission, and both must yield the GPU and attention to the demo.

## Status log

- 2026-10-18 01:36 BST, pre-submission report (Phase 4). Branch `juri-processing-pipeline` at **3978436** (3978436420c0487b96df0f0dbff9fd771765d380) plus this log entry's commit on top.
  - **Clean-clone check** (`git clone --branch juri-processing-pipeline https://github.com/UoSDDNB/omics-agent.git /tmp/clean-clone`, 01:28): clone 1 s; `uv sync` 0.6 s (packages cached on this machine; a stranger downloads torch and sentence-transformers, several GB); `uv run pytest` **21 passed** in 0.7 s with no files outside the repository (the SDRF fixtures are vendored); `npm ci` 15 s and `npm run build` 10 s pass. What a stranger hits: no `.env` and no `data/` in the clone (both gitignored, as intended); without a model key or `LOCAL_LLM_URL` the search used to die with an anthropic traceback and now exits with one sentence naming the two options; without the index every search runs on the live GEO, PRIDE and CELLxGENE APIs (documented); `omics process` needs the micromamba environment, downloads the GENCODE reference on first use (7 min index build) and expects ENA to be reachable; proteomics counts need the SDRF corpus clone (`git clone --depth 1 … data/sdrf`). All of these are in the README's Quick start, Process and Limits sections.
  - **Rehearsal** (01:29, headless browser against the running web app and API): page open 1 s; question submitted; results table after **3 min 46 s** (plan and labels cached; a new question is about 8 min); 27 rows, GSE273888 present; row opened and **Process** clicked at 3:48; full results panel with figures, the model's paragraph and downloads at **3:53** (4 s, cached run). The demo script was rewritten with these timings, "34 strong hits" replaced by "about 30, varies", the "appears at once" claim replaced by "a few seconds", and all stage wording moved to plain words. The rehearsal also exposed a Phase 3 regression: the new counts panel overwrote the PCA means the summary file needs, so a fresh `omics process` run failed at the explanation step; fixed in 3978436 and re-run (exit 0, 31 output files including the five figures as PNG and PDF, served by the API).
  - **Readability**: README gained "In plain words" (what it is for, what was not working, what we made better), definitions of GEO, PRIDE, ENA, salmon, GENCODE, tximport, DESeq2, apeglm and padj where they first appear, and an "honest limits" list covering subsampling, one contrast, model-written text, label choice, the empty index on this machine, uncached scoring stages, SDRF coverage, what is not built, and voice's secure-context need. The demo script no longer uses salmon, DESeq2, TPM or padj at all.
  - **Tests and build**: `uv run pytest` 21 passed; `npm run build` and `npm run lint` exit 0 (01:35, this commit).
  - **Merge command for the morning** (fast-forward unless main moved): `git -C /home/jlw/omics-agent fetch origin && git -C /home/jlw/omics-agent merge --ff-only origin/juri-processing-pipeline`; then `git -C /home/jlw/omics-agent push origin main`, and submit `git -C /home/jlw/omics-agent rev-parse HEAD`. Not run tonight: merging and pushing main are Juri's calls.
  - **Needs a human decision**: (1) which public repository to submit: make `UoSDDNB/omics-agent` public (check `interviews/`, `progress.md` and the two `tese_lysoip_*.py` scripts for anything that should not be public first) or push to `hridaya423/locus`; (2) whether Hridya pushed to `main` overnight, in which case merge theirs first and re-run the tests; (3) voice in the demo: present on `localhost` or show the disabled state over the IP; (4) confirm the GPU guard stopped the distillation run before the pitch (`pgrep -af run_qwen_v2` empty); (5) the API on 8010 was restarted once by the overnight session at 00:04 after a mistaken `pkill`; it is up, but whoever owns it should know.
  - Services at hand-over: vLLM 8000 and web 3000 untouched; API 8010 up (200); API 8020 restarted at 01:35 with the final code; web 3020 running with `OMICS_API_URL=http://localhost:8020 EXTRA_DEV_ORIGINS=152.78.149.61`; `data/process/GSE273888/` present so Process is instant.
