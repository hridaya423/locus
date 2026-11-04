# locus: what it takes to scale, and how to prove it is worth using (20 Oct 2026)

## Where we are

- **Public site:** one Hetzner VPS (`locus.204.168.183.57.sslip.io`). Planning runs on Gemini's free tier, which
  already returns 429s under a small burst; triage, screening and the GEO labels fall back to Qwen on pgx through a
  tunnel.
- **Speed:** a fresh search takes about 85 s (measured 19 Oct: planning 9 s, triage and screening 16 s, reading sample
  records 44 s). Users remember it taking 30 s.
- **Users:** two IP addresses so far, both campus.
- **Evidence:** a 9-question harness with known relevant datasets, and the 20 Oct metadata audit
  (`docs/metadata-gaps/`).

## What broader adoption needs, starting at the University of Southampton

### 1. Reliability (before anyone is told about it)

- **A paid model backend with a budget cap.** Gemini Flash-Lite for triage and screening should cost little per search (measure it in the pilot); keep
  Qwen as the fallback. The free tier is not a service.
- **No dependency on a laptop or a tunnel.** Either an always-on GPU endpoint, or an API model for every stage.
- **A real domain and certificate** (for example `locus.soton.ac.uk` through iSolutions, or a project domain). An
  sslip.io address reads as a test.
- **Searches under 30 s for a fresh question, and instant for a repeated one.** Cached plans and answers already make
  repeats instant. For fresh questions: the compact-JSON switch from the 19 Oct hill-climb, label calls moved off the
  local model, and sample records read in parallel.
- **Uptime and error monitoring,** plus a weekly usage report (`locus-usage` exists).

### 2. Trust (what makes a sceptical biologist come back)

- **Published benchmark numbers** (below) on the site and in the README.
- **Coverage stated plainly:** which repositories are read live, which only from the index, and the index's date.
- **A "report a wrong result" link** on every result and study page, feeding a public issue list.
- **Fix the known defects first:** the PRIDE title encoding bug ("Alzheimerâ€™s"), and the missed GEO studies in the
  recall gap (for example GSE35469).

### 3. Fit with how Southampton researchers work

- **Iridis kits.** A processing kit that submits to Slurm on Iridis: RNA-seq exists, MaxQuant is drafted. Each kit
  states up front whether a job is laptop-sized or cluster-sized. Mani's measured MaxQuant numbers set that line:
  13 GB of RAM and 16 GB of disk for two runs.
- **Exports people already use:** a sample sheet for nf-core, an SDRF, and a citation list for a methods section.
- **Saved lists that persist** (accounts via university sign-on later; not needed for a pilot).

### 4. Reaching people

- **Pilot with three groups:** one transcriptomics, one proteomics, one clinical. Each brings two real questions it
  answered the hard way this year. Measure time to data with and without locus (this is also benchmark B3).
- **Channels:** the Institute for Life Sciences seminar and newsletter; the Iridis user mailing list and research
  computing drop-ins; doctoral training programme induction weeks; the faculty data stewards.
- **Assets:**
  - a 90-second screen recording;
  - a one-page "ask it like this" guide with real example questions;
  - a 30-minute hands-on session in which each attendee leaves with a dataset found for their own project.
- **Measures:** weekly active users, searches per user, the share of searches that end in a download or sample sheet,
  and returning users after four weeks.

### 5. Sustainability

- **A named maintainer and a roadmap in the repository.** The licence (Apache 2.0) and credits are already in place.
- **A cost line** (model API, VPS, domain) small enough for a group budget or a seed grant. Track it from the first
  pilot so the number in a grant application is real.

## Benchmarks: proving locus beats the alternatives at reaching the data that matters

**The claim to test:** starting from a plain-English research question, locus gets a researcher to relevant datasets
whose raw data and sample metadata are actually reachable, faster and more completely than Google, Google Dataset
Search, OmicsDI or a repository's own search.

### Question set

- 100 questions written by biologists, stratified by data type (bulk/single-cell RNA, proteomics, epigenomics,
  metabolomics, microbiome) and by difficulty (one dataset is the answer; many are relevant; nothing exists).
- Sources of known-relevant answers:
  - **Papers whose data-availability statement names accessions.** The question is written from the abstract, and the
    named accession must be found. This is cheap, unbiased by locus, and scales.
  - **Pooled relevance judgments.** The top 20 results of every system are pooled, shuffled and judged blind by a
    biologist (TREC style), so no system is graded only on what it alone found.
- The current 9-question harness becomes the seed set.

### Systems compared

| System | How it is run |
|---|---|
| locus | its API, fresh answers (OMICS_FRESH_ANSWERS=1), fixed index date |
| Google | Programmable Search JSON API, plain query, and query + "GEO OR PRIDE OR ArrayExpress" |
| Google Dataset Search | the same query, results captured by a scripted browser |
| OmicsDI | its REST search API |
| Repository search | GEO (E-utilities), PRIDE and ENA search APIs, with the keywords a researcher would type |

The question text is identical for every system, the run date is recorded, and every raw result list is saved.

### Measures

1. **Recall@10 and @50** of known-relevant accessions, and **precision@10** from blind judgments.
2. **Reach.** The share of the top 10 results where the raw files *and* a per-sample table can be reached from the
   result in at most two steps. This is checked by script: does a raw file URL resolve, and is there a sample table
   with at least one filled biological attribute (reusing `scripts/metadata_audit.py`).
3. **Design correctness.** For case/control questions, the case and control counts locus reports against counts a
   biologist made by hand.
4. **Time to data (user study, n of about 12).** Wall time and clicks from question to a downloaded sample sheet,
   locus versus the participant's usual route, with tasks counterbalanced.
5. **Cost and latency per question** for locus, so the comparison is honest about what locus spends.

Report each measure with a bootstrap interval over questions, publish the harness and the raw result lists, and re-run
it whenever the index or the model changes, so it doubles as a regression test.

### Who does what

- **Benchmark engineering (needs no biology):** the harness, the system runners, result capture, the reach checker,
  statistics and the dashboard. This is Mani's offer.
- **Biology:** writing questions, blind judgments, and design counts. Juri plus pilot-group volunteers (about 6 hours
  per judge for 100 questions × 20 pooled results).
