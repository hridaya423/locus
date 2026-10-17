# Live pitch plan: the moment that wins the room

This plan replaces feature-first planning. We test what locus can really do, choose the single strongest moment from the evidence, then build only what that moment needs. `2026-10-17-megaplan.md` stays as the pool of possible builds. Nothing in it starts until the gates below decide what to build.

## What a top professional does differently

1. **They engineer one reveal, not ten features.** Judges remember one moment. Every minute of work either makes that moment stronger or makes it safer.
2. **They earn the right to the claim before they make it.** "This changes researchers' lives" has to be shown live, with receipts. The receipts are a published result, a repository record and a real researcher.
3. **They show the status quo failing first.** A reveal shocks only after the audience has seen the normal tools fall short. Without that contrast, a good result looks ordinary.
4. **They never fake it.** These judges include people from data repositories and machine learning. One cherry-picked or staged result loses the room. Everything shown is real and checkable. Cached runs are disclosed if anyone asks.

## Phase 0: evidence. Run the tests and do not build anything.

| Test | Method | Raw material | External truth |
|---|---|---|---|
| Known answer | Ask locus in plain English: "Matched RNA-seq and Ribo-seq before and after mTOR inhibition". Check whether the results include the datasets behind Thoreen et al., *Nature* 2012 and Hsieh et al., *Nature* 2012. | Raw locus output (NDJSON), the papers' data-availability statements | The published papers and their GEO accessions |
| Abandoned question | Ask the question the researcher gave up on: "How do isoforms of a single gene differ in translation?" Record whether locus explains which methods can answer it and finds datasets that use those methods. | Raw locus output, plus the methods sections of the datasets it returns | Two biologists, labelling independently |
| Baselines | Ask the same two questions in GEO DataSets search, OmicsDI, Google Dataset Search and a general chatbot with web search. Record every result and every error: wrong assay, an accession that does not exist, a missed known dataset. | Screenshots and copied outputs, with timestamps | The repository records |
| Counts | For every case/control count that locus shows on the demo questions, open the GEO sample records and recount by hand. | The GEO series and sample records | The records themselves |
| Manual search | The researcher answers one fresh question by hand while thinking aloud, with a stopwatch running and the screen recorded. | The recording | The clock |
| Ground truth | The researcher and a second biologist label 20–30 datasets independently: assay type, whether samples are matched, counts, relevance. Measure how often they agree, then score locus against their labels. | The labelling sheet | Agreement between the two labellers |

**Output of Phase 0:** a single page of results, including the failures.

## Phase 1: choose the reveal, based on the evidence

The tests decide which reveal to use. Wishes do not.

| Gate | If it passes | If it fails |
|---|---|---|
| **G1.** The known-answer test finds the published datasets, and the counts match GEO | **Reveal A, the receipt.** Plain English in, and the datasets behind two *Nature* papers come out in seconds. Click through to GEO live, and the counts match. | Find out why. Fix the search if the cause is clear. Otherwise drop Reveal A. |
| **G2.** A baseline makes a checkable error, such as calling TIS-seq data Ribo-seq, inventing an accession, or missing a known dataset | **Reveal B, the catch.** Show both side by side. The usual tool is confidently wrong. locus shows the methods sentence that settles the question, for example "harringtonine-treated", which means TIS-seq. | Do not invent a contrast. Use the stopwatch contrast instead. |
| **G3.** The abandoned question returns credible datasets, confirmed by the two labellers | **Reveal C, the comeback.** "Our researcher gave up on this question." locus explains why Ribo-seq cannot answer it, names methods that can, and finds data for them. | Keep it as a vision slide only. Never show weak results live. |

**Best case, in this order:** B as the hook (the tools you trust are wrong), A as the proof (receipts from two published papers), and C as the close (the question a scientist abandoned is open again).

## Phase 2: build only what the chosen reveal needs

Map each reveal to the smallest build that supports it. Candidates from the megaplan:

- **Reveal A:** a click-through from a count to the matching GEO sample records, and a cached demo run.
- **Reveal B:** assay type read from the methods text, shown with the sentence that proves it. The results row may be enough, so a chat may not be needed.
- **Reveal C:** method-fit notes ("What can answer this") shown before the results.
- **For all three:** reliability work on the backend, the eval numbers on one slide, and a fallback for every step.

The chat assistant stays in only if a chosen reveal needs it. That would be, for example, asking "Where were these samples split?" and getting back a cited answer.

## Phase 3: pitch architecture (3 minutes, live)

1. **Stakes (20 s).** The researcher pitches with us and says this in person: "I spent [measured time] looking for one dataset. Then I gave up on the question." The time comes from the think-aloud recording.
2. **The status quo fails (30 s).** Reveal B, if G2 passes: the baseline tool is confidently wrong.
3. **locus (60 s).** Type the question live. Results appear. Click one count through to GEO and show that it matches. Click the methods sentence. This is Reveal A.
4. **The comeback (30 s).** Reveal C, if G3 passes.
5. **Proof (20 s).** One slide: the known-answer test passed, assay accuracy against two experts, exact counts, and the before-and-after time.
6. **Vision (20 s).** Processing handoff and monitoring for new data. Close with one line.

## Phase 4: rehearsal and stagecraft

- **Memorability test.** Show the draft pitch to three to five outsiders, including at least one scientist. The next day, ask them what they remember. Keep what they remember and cut the rest.
- **Teach-back.** After the pitch, a non-expert explains the problem and the solution back. If they cannot, simplify.
- **Pre-mortem.** Assume the pitch failed and write down why. Fix the top three causes.
- **Questions from the judges.** Read each judge's actual published work. Write the five hardest questions each one could ask, with answers that cite our evidence. Example: "Why not just ask ChatGPT?" is answered by Reveal B.
- **Stage setup.**
  - Have the question pre-typed.
  - Use large type on one screen, with no scrolling during the reveal.
  - Cache runs and keep a fallback machine and a mobile hotspot.
  - Rehearse five or more timed runs, and at least one with a deliberate failure, so recovery is practised.

## Honesty rules

- Every number on screen comes from Phase 0 and can be traced to its source.
- Failures from Phase 0 are kept in the Q&A notes, not hidden.
- If a judge asks whether a run is live or cached, say which, and offer to run a fresh question.
