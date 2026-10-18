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
