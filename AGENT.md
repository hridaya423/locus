# AGENT.md

## Purpose and scope

Guide coding agents working in `UoSDDNB/omics-agent`. Apply the attached Hackathon Prompting Playbook as a working discipline: design before code, a runnable end-to-end skeleton, test-first increments, independent review, then ship.

The current project direction is a PRIDE-first mass-spectrometry discovery agent (MS-agent), with potential expansion to other public biological repositories. Help users identify relevant datasets through natural-language queries, inspect why they match, and retrieve the underlying data or reliable download references. Prioritising high-quality datasets and datasets generated with protocols suitable for smORF discovery is a key use case.

The longer-term omics/bioseq ambition is context, not permission to build every modality now. The embedding exploration/visualisation GUI is a separate exploratory idea unless the team explicitly includes it in this task.

These instructions record project intent and working practices, not an assertion that particular components already exist.

## 1. Start with the actual repository

Before proposing changes:

- Read the README, existing agent instructions, dependency manifests, tests and relevant source files. Check the working tree and current branch.
- Identify what already runs, the current interface, data flow, test commands and any existing architecture decisions.
- Preserve other contributors' changes. Do not reset, overwrite or clean untracked work.
- State what you verified, what you inferred and what remains unknown. Do not invent paths, commands, deployed services or capabilities.
- If an external service, instrument, credential or cluster is unavailable, report the limitation. Use an explicit test fixture or fake where appropriate; never present a fake response as live evidence.

Before coding a new workflow, describe its first user and three main tasks. Decide whether the immediate interface is a GUI, CLI, API or agent-facing tool. Keep business logic independent of the interface; a GUI should call an API or application layer rather than contain the scientific logic.

## 2. Design before implementation

Explain a small number of components, each in one sentence, using ordinary domain terminology. Prefer clear abstractions with explicit responsibilities over tangled helper functions or speculative frameworks.

Resolve or document:

- The specific problem and first user.
- The smallest useful end-to-end behaviour and its acceptance criteria.
- What is out of scope.
- Which existing APIs, algorithms, formats and libraries to keep, wrap or rebuild, with costs and risks.
- Inputs, outputs, failure states and ownership of each component.
- Any material options and their trade-offs.

Be candid if the proposed tool is only a thin wrapper or does not improve a real workflow. Do not flatter the team or assume a replacement is better because it uses embeddings or an LLM.

Record agreed decisions in the repository's existing decision location, or a short decision log if none exists. Keep this file focused on durable instructions. Do not create competing sources of truth in multiple agent instruction files.

Do not silently introduce major dependencies, databases, paid services, architecture changes or scope expansions. Seek agreement for consequential choices; proceed with small, reversible implementation details within an agreed plan.

## 3. Build a runnable skeleton first

Before implementing all features:

1. Obtain the smallest real, redistributable input or metadata response that exercises the real format.
2. Ask the scientific team for expected results and relevance judgements. Do not invent a scientific answer key.
3. Write an end-to-end test and demonstrate that it fails for the intended reason.
4. Make the complete path run with one documented command, using clearly labelled placeholders where necessary.
5. Keep that end-to-end test passing throughout development.

For the discovery agent, the initial vertical slice should demonstrate:

`natural-language query -> retrieved candidates -> inspectable evidence/ranking -> dataset accessions and file/download references`

Include a small real download only if agreed, affordable and necessary for the demo. Downloading full raw-data collections is not a prerequisite for a useful discovery demonstration.

Placeholders must return the correct schema and remain visibly distinguishable from real extraction, retrieval and scoring. A skeleton passing tests does not establish retrieval accuracy or scientific validity.

Where an existing tool produces a result for the same input, retain it as a comparison baseline with explicit tolerances or relevance criteria. Investigate differences rather than automatically declaring the old tool wrong.

## 4. Implement in test-first increments

For each bounded piece:

1. State the behaviour being changed and its acceptance criteria.
2. Write the test first and run it to observe the expected failure.
3. Implement the smallest sound change that passes the test.
4. Run the targeted tests and the end-to-end regression test.
5. Review the diff for unnecessary changes, hidden assumptions and unintended side effects.
6. Report what changed, what passed and any limitations before taking on the next substantial piece.

Do not weaken assertions, remove inconvenient cases or change expected scientific answers merely to make tests pass. If a test is demonstrably wrong, explain why and obtain agreement before changing its contract. Technical fixtures may be generated, but scientific labels must have a traceable source or expert review.

Prefer small, reviewable commits after working increments when commits are authorised. Never stage unrelated files, push, rewrite shared history or change repository settings without permission.

If a component has no clear purpose, ask what would break without it. Remove unnecessary complexity rather than building around it. If a failure needs a design rethink, say so instead of accumulating patches.

## 5. Discovery, indexing and scientific integrity

### Retrieval architecture

Treat the representation as a design decision, not a requirement to deploy every search technology:

- Structured records and relationships describe entities such as projects, samples, files, publications and protocols.
- Vector embeddings can support semantic retrieval over text.
- Exact identifiers, metadata filters and lexical search may remain necessary.

Do not equate a vector index with a knowledge graph. Reuse the team's chosen architecture where it exists; propose the simplest combination that meets evaluated requirements.

Do not claim that a newer index outperforms PRIDE or its existing search implementation without a fair comparison. Distinguish documented limitations from hypotheses to test.

### Evidence and ranking

Keep separate assessments for:

- Relevance to the user's biological question.
- Evidence of scientific/data quality.
- Suitability for smORF-focused analysis.
- Availability and readiness for download or reprocessing.

Do not collapse these into an unexplained score. Missing quality metadata means unknown, not automatically poor quality. Similarity, citation count, publication date or laboratory identity must not stand in for validated scientific quality.

For extracted claims, retain the source identifier or URL, supporting text or field, retrieval date, extraction method and uncertainty. Distinguish explicit protocol evidence from inferred suitability and mere keyword mentions. Let domain experts define the protocol rubric; do not invent authoritative smORF criteria.

Use LLMs to propose queries, extract metadata and explain evidence. Validate schemas, accession identity, completeness and source support before using their outputs. Never fabricate datasets, methods, citations, file locations or download availability.

Build a small expert-reviewed relevance set containing positive, negative and ambiguous cases. Evaluate retrieval and ranking separately from schema correctness. Keep evaluation examples separate from tuning examples where practical.

### Data handling and reproducibility

- Preserve original metadata alongside normalised fields; record transformations and index/embedding model versions.
- Keep dataset, sample, spectrum, peptide, protein and ORF entities distinct. Do not imply spectrum-level indexing when only project-level text was ingested.
- Retain canonical source links and accession identifiers. Prefer manifests and remote references over duplicating large raw datasets.
- Record download size where available; use checksums when provided and make interrupted/failed downloads visible.
- Use resumable, idempotent ingestion where practical. Handle pagination, rate limits, retries, duplicate records, schema changes and partial failures explicitly.
- Keep raw data, indexes, embeddings, caches and credentials out of Git unless a small fixture is intentionally approved.
- Do not perform bulk downloads, full-database re-indexing, paid API batches or destructive operations without an agreed budget and authorisation.

If downstream MS analysis is added, keep acquisition/search protocols and evidence types explicit. Do not treat undetected peptides as proof of absent translation or ordinary protein-level confidence as sufficient validation of novel smORF evidence.

## 6. Go looking for failures before polishing

Use a fresh review session or independent reviewer where possible. Give the reviewer the repository, requirements and tests, not an argument defending the implementation.

Look especially for results that are wrong but plausible:

- Wrong accessions, mismatched samples and unsupported protocol assignments.
- Hallucinated relevance explanations or citations.
- Missing values converted into negatives or invented defaults.
- Silent truncation, swallowed errors and incomplete pagination.
- Duplicate ingestion, stale indexes and incompatible embedding versions.
- Rankings dominated by laboratory, year or vocabulary rather than the intended relevance.
- Broken URLs, partial downloads, invalid checksums and misleading success statuses.
- Units, coordinate conventions, axis/channel order and indexing errors wherever numerical or scientific data are handled.
- Untrusted publication or metadata text treated as agent instructions rather than data.

Rank findings by impact before fixing them. Separate problems with the overall idea from local implementation defects. Prioritise incorrect scientific results, security/data-loss risks and broken end-to-end behaviour over cosmetic work.

Test a second real input and account for every important difference from the baseline: our bug, a baseline bug, or a documented intentional choice.

## 7. Handover and session discipline

At a pause, handover or context reset, leave a concise record:

- What works and how to run it.
- What changed and why.
- Tests run, their outcomes, and tests not run.
- Remaining work and blockers.
- Decisions, assumptions and any unrequested changes.
- The next bounded task.

Never claim tests passed unless they were executed. Separate offline fixture tests from live-service tests. If asked for a status report, provide it and wait rather than continuing implementation.

## 8. Ship honestly

Start the fresh-clone check before the deadline and repeat it at the end:

- Follow documented installation steps in a clean environment.
- Run tests and one demo command with example data.
- Explain required credentials, local resources and optional services.
- Clearly distinguish real functionality, placeholders and future plans.
- Keep the README short and practical: purpose, current limitations, first-minute setup and example workflow. Ask a human teammate to edit the final wording.
- Check for secrets, unintended large files, data-sharing restrictions and dependency/licence issues.
- Verify hackathon submission requirements, including repository visibility, licence and any commit-date rules. Report failures; do not change visibility/licensing or delete/rewrite history to satisfy them without approval.
- If requested, draft a three-minute pitch covering the original problem, what improved, evidence from the demo and remaining limitations, plus five likely judging questions and candid answers.

A demo is successful only when its outputs are inspectable, its limitations are explicit, and another person can reproduce the stated workflow.

## Source

Adapted from Rory Byrne's “Hackathon Prompting Playbook”, dated 16 October 2026, and the team's stated PRIDE-first omics-agent direction. Repository-specific commands and architecture must be verified from the actual checkout.
