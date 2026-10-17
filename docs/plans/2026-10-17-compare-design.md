# Compare two datasets

## Tasks

1. Read the poteto Principles in full. Done.
2. Feature step 1: walk the affected subsystem. Done (see "Grounding").
3. Feature step 2: `architect`, sketch-first. Candidates and synthesis below. `arena` is not installed, so the bake-off is written here.
4. Feature step 3: throughput checkpoint (below).
5. Feature step 4: delegate the backend and the frontend to two owners with disjoint files.
6. Feature step 5: verify on the real surface (real pairs through the API, screenshots of the connector and the dialog at 1280 px and 390 px).
7. Feature step 6: small ordered commits.
8. Feature step 7: adversarial review only if the verdict rules are contested.
9. Feature step 8: Opening a PR. Skip unless asked; this repo publishes to `hridaya423/locus` by push.

## The question a researcher asks

"Can I use these two datasets together?" The answer is not yes or no. It decides which analysis is valid:

| Verdict | Meaning | Analysis it allows |
|---|---|---|
| `pool` | Same organism, same measurement, same contrast, and each dataset has its own cases and controls | Combine the samples into one analysis, with the study as a batch term. Reprocess both from raw with one pipeline first. |
| `effects` | Same kind of measurement and a same or related contrast, and each dataset has its own cases and controls, but samples cannot be mixed (different organism, technology, or perturbation) | Analyse each dataset on its own, then compare the effects (fold changes, direction, overlap of hits). |
| `no` | Different molecular layer, no shared contrast, or a dataset without both groups | Do not combine. Say which fact rules it out. |
| `unclear` | No required fact contradicts combining, but one is not stated (for example no counted cases and controls) | Say which facts to check. Missing evidence is not evidence against combining. |

Two facts are easy to miss and are the reason this feature exists:

- **Each dataset must contain both groups.** If dataset A holds only cases and dataset B only controls, the study and the condition are the same variable. No batch correction can separate them. This rules out `pool` and `effects`.
- **Two studies always differ in batch.** `pool` never means "merge the matrices"; it means "model the study as a covariate after uniform reprocessing".

## Grounding

- Selection lives in `Results` (`web/components/results.tsx`): `selected: Set<string>`, `picked: Hit[]`, a fixed selection bar at the bottom. Rows are `DatasetRow` (`result-card.tsx`) inside a table; study groups nest rows in `StudyRow`.
- A `Hit` carries `source`, `organism`, `modality`, `facts` (`case`, `control`, `assays`, `libraries`, `sample_type`, `tissue`), `paper`.
- GEO sample records are cached as text (`samples.geo_records`). Besides the fields kept today, they hold `platform_id`, `instrument_model`, `library_selection`, `library_source`, and `Genome_build` in `data_processing`. Checked on GSE36892, GSE35469, GSE225683, GSE167324, GSE122960.
- `agent.geo_labels(topic, accession, summary)` gives the case values, control values and assay labels, cached per study and topic.
- Non-GEO rows have only `store` fields (title, organism, modality). PRIDE method facts arrive later from PRIDE Map's tags; until then their method facets are `unknown`, not guessed.

## Design candidates

| | A. Rules over structured facts | B. Model reads everything | C. Rules, plus the model for the contrast only |
|---|---|---|---|
| How | A table of facets; code compares values and computes the verdict | Claude reads both records and methods and writes the verdict | Code compares every factual facet; Haiku only classifies whether the two contrasts are the same, related or different, with a quoted reason |
| Strength | Deterministic, testable, every value cited to a record field | Handles anything | Deterministic verdict; the one judgement code cannot make (is Torin1 the same contrast as rapamycin?) is cited and cached |
| Weakness | String match cannot tell that Torin1 and rapamycin are related | Verdict changes between runs; numbers can be invented; contradicts "code computes the grade" | One model call per pair |

**Synthesis: C.** It keeps locus's rule that code computes the grade and the model never writes a number. The model answers one narrow question with a quote.

## Data shape

One registry of facets. Each facet reads a value from a dataset profile and states which verdicts a difference rules out. The verdict is the first level whose required facets are all `same`; an `unknown` required facet also rules a level out, because the claim needs evidence.

```python
Verdict = Literal["pool", "effects", "no"]
Status = Literal["same", "related", "differs", "unknown"]

@dataclass(frozen=True)
class Profile:              # one dataset, built once from the records
    accession: str
    source: str
    title: str
    organism: str | None
    layer: str | None       # transcriptome, translatome, proteome, epigenome, ...
    technology: str | None  # bulk RNA-seq, microarray, single-cell, Ribo-seq + RNA-seq, DIA, ...
    platform: str | None    # instrument model or array platform
    material: str | None    # patient tissue, cell line, primary cells, model
    tissue: str | None
    case: int | None
    control: int | None
    contrast: str | None    # "Torin1 vs vehicle", from the labels
    build: str | None       # genome build, when stated

@dataclass(frozen=True)
class Facet:
    key: str
    label: str
    a: str | None
    b: str | None
    status: Status
    note: str               # the consequence, shown when the status is not "same"
    source: str             # where the values come from

@dataclass(frozen=True)
class Comparison:
    a: Profile
    b: Profile
    verdict: Verdict
    reason: str             # the facet that stopped the higher verdict
    facets: list[Facet]
    steps: list[str]        # what to do next, given the verdict
```

Required facets per verdict:

| Facet | `pool` needs | `effects` needs | Otherwise |
|---|---|---|---|
| Organism | same | any (different: compare through orthologous genes, as a caution) | |
| Molecular layer | same | same | different layer: `no` (multi-omics integration is a different analysis) |
| Technology | same | any | caution |
| Contrast | same | same or related | different: `no` |
| Both groups in each | yes | yes | missing group: `no` |
| Platform, material, tissue, genome build, group sizes | caution only | caution only | |

## Rules added after the first real runs

- Layers and technologies are sets. A partial overlap (Ribo-seq and RNA-seq against RNA-seq) is `related`, and the steps say to use only the shared data.
- Each facet carries `required`. In the dialog, a difference in a required facet is a warning; a difference in a caution facet is neutral.
- Group sizes flag only a group under three samples. Different sizes are normal.
- A model reason that names "dataset 1" or an accession is replaced by code, because pairs are judged in accession order.
- A related contrast is stated as related before the model's sentence, so the reason cannot read as agreement.
- Two datasets from the same paper cannot be compared: the UI offers no Compare, and the API returns 422.

## API

`POST /compare` with `{ "accessions": [a, b], "topic": "..." }` returns the `Comparison` as JSON. The accession pattern is checked at the boundary. Exactly two accessions.

## UI

- When exactly two rows are selected, an SVG connector leaves each selected row's checkbox to the left, into the page gutter, and the two curves join at a **Compare** button in the gutter, between the two rows. The button sits in a sticky slot between the two rows, so it stays in view while the user scrolls between them. The curves draw in when the second row is selected and retract when the selection changes.
- Below the width where the gutter fits the button, the selection bar shows **Compare** instead. The bar always shows it when two rows are selected.
- **Compare** opens a native `<dialog>`: the verdict first (one headline and the deciding reason), then one row per facet (label, A, B, status), then the next steps. Facets that are `same` are compact; differences carry their note. `unknown` reads "not stated".
- Reduced motion: the connector appears without the draw.

## Throughput checkpoint

- **Blocking first steps.** The JSON contract above. Both owners code against it.
- **Independent workstreams.** Backend: `omics_agent/compare.py` (new), `samples.py` (`geo_records` keeps platform, instrument, selection, build), `agent.py` (`compare_datasets`), `api.py` (route), `mcp_server.py` (tool). Frontend: `web/components/compare.tsx` (new), `results.tsx`, `lib/api.ts`. No file is shared.
- **Shared mutable state.** None. The frontend codes against a fixture of the contract until the backend lands.
- **Smallest safe decomposition.** Two owners. One would serialize unrelated work; three would split one module.

## Success criteria

- `uv run python -m omics_agent.compare` passes offline self-checks: a confounded pair (cases only against controls only) gives `no`; a cross-species pair with the same contrast gives `effects`; a same-everything pair gives `pool`.
- Real pairs through the API give these verdicts:
  - GSE36892 (mouse, Torin1) against GSE167324 (mouse, Torin1): `pool`, with cautions for different cell types and platforms.
  - GSE36892 (mouse, Torin1) against GSE35469 (human, rapamycin and PP242): `effects`.
  - A transcriptome dataset against a PRIDE proteome dataset: `no`.
- The connector, the button and the dialog are checked by screenshot at 1280 px and 390 px, with the two rows far apart and close together.
