export const API = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export type Plan = { terms: string[]; organism: string; assays: string[]; repositories: string[]; method_notes: string[]; matched_assays?: string[]; wants_controls: boolean };
export type Facts = {
  case: number | null; control: number | null; mixed?: number; has_control: boolean | null;
  sample_type: string; tissue: string; source: string; assays?: string[]; library?: Record<string, number>;
  libraries?: Record<string, Partial<Record<"case" | "control" | "mixed" | "other", number>>>;
  methods?: Record<string, { value: string; label: string; evidence: string; trusted: boolean }>;
  donors?: { case: number; control: number; field: string } | null;
};
export type ReadyFiles = { processed: { name: string; kind: string; bytes: number; url: string }[]; more: number; raw: { files: number; bytes: number } };
export type Paper = { title: string; journal: string; year: string; url: string };
export type Check = "yes" | "no" | "unclear" | "same" | "other" | "n/a";
export type Hit = {
  accession: string; source: string; modality: string; title: string; organism: string;
  samples: number | null; url: string; papers: string[]; facts: Facts | null; published: string | null;
  fit: "strong" | "partial"; checks: Record<"topic" | "patient_material" | "data_type" | "controls", Check>;
  reason: string; evidence: string; paper: Paper | null; download_plan: string;
};
export type AnswerItem = { accession: string; title: string; source: string; kind: "matched" | "cohort" | "ready"; fact: string; anchor: string };
export type Result = { question: string; plan: Plan; candidates: number; datasets: Hit[]; same_paper: string[][]; answer?: AnswerItem[] };
export type Stage =
  | { stage: "plan"; data: Plan }
  | { stage: "candidates"; data: { count: number } }
  | { stage: "facts"; data: { count: number } }
  | { stage: "done"; data: Result }
  | { stage: "error"; data: string };

export async function search(question: string, onStage: (s: Stage) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`${API}/search`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`${res.status} ${await res.text()}`);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let finished = false;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines.filter(Boolean)) {
      const stage: Stage = JSON.parse(line);
      finished ||= stage.stage === "done" || stage.stage === "error";
      onStage(stage);
    }
  }
  if (!finished) throw new Error("The search stopped before it finished. Please try again.");
}

export async function readyFiles(accession: string, signal?: AbortSignal): Promise<ReadyFiles> {
  const res = await fetch(`${API}/files/${accession}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function samplesheet(accession: string, topic: string): Promise<Blob> {
  const res = await fetch(`${API}/samplesheet/${accession}?topic=${encodeURIComponent(topic)}`);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.blob();
}

export type Design = {
  source: string; samples: number; shared: Record<string, string>;
  factors: { name: string; column: string; levels: Record<string, number>; unstated?: number; aliases?: string[] }[];
  crossed?: { rows: string; columns: string; counts: [string, string, number][] };
  comparison?: { factor: string; case: string[]; control: string[] } | null;
  people?: { field: string; total: number; samples: number; case?: number; control?: number } | null;
};

export async function design(accession: string, source: string): Promise<Design | null> {
  const res = await fetch(`${API}/design/${accession}?source=${encodeURIComponent(source)}`);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  const body = await res.json();
  return body.factors ? body : null;
}

export type Verdict = "pool" | "effects" | "no" | "unclear";
export type FacetStatus = "same" | "related" | "differs" | "unknown";
export type Profile = {
  accession: string; source: string; title: string; organism: string | null; layer: string | null; technology: string | null;
  platform: string | null; material: string | null; tissue: string | null; case: number | null; control: number | null;
  contrast: string | null; build: string | null; contrast_name?: string | null; access?: string | null; sex?: string | null; shared?: number | null;
  sex_split?: Record<"cases" | "controls", { female: number; male: number }> | null; files?: string[]; diseases?: string | null;
};
export type Facet = { key: string; label: string; a: string | null; b: string | null; status: FacetStatus; note: string; source: string; required: boolean };
export type Comparison = { a: Profile; b: Profile; verdict: Verdict; reason: string; facets: Facet[]; steps: string[] };

export async function compare(accessions: [string, string], topic: string, signal?: AbortSignal): Promise<Comparison> {
  const res = await fetch(`${API}/compare`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ accessions, topic }),
    signal,
  });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `${res.status}`);
  return res.json();
}

const REPOSITORY_NAMES: Record<string, string> = {
  MetabolomicsWorkbench: "Metabolomics Workbench", ExpressionAtlas: "Expression Atlas", PanoramaPublic: "Panorama Public",
};
export const repositoryName = (source: string) => REPOSITORY_NAMES[source] ?? source;

export const SAMPLE_TYPE: Record<string, string> = {
  patient_tissue: "patient tissue", patient_biofluid: "patient fluid", primary_cells: "primary cells",
  cell_line: "cell line", animal_or_organoid_model: "model system", unknown: "",
};

export type RecordFile = { name: string; url: string; group: string; bytes: number | null; processed: boolean; kind: string; preview: boolean };
export type DatasetRecord = {
  accession: string; source: string; url: string; title: string; sources?: string[];
  texts: [string, string][]; facts: [string, string[]][];
  people: { role: string; name: string; affiliation?: string; email?: string; phone?: string; web?: string }[];
  papers: { title: string; journal: string; year: string; url: string; id?: string }[];
  links: [string, string][];
  samples: { columns: string[]; rows: string[][]; link: string; pages?: boolean } | null;
  files: RecordFile[]; unmapped: string[];
  modality: string; organism: string; published: string | null; sample_count: number | null; download_plan: string;
};

export async function datasetRecord(accession: string, signal?: AbortSignal): Promise<DatasetRecord> {
  const res = await fetch(`${API}/record/${encodeURIComponent(accession)}`, { signal });
  if (!res.ok) throw new Error(res.status === 404 ? "missing" : `${res.status}`);
  return res.json();
}

// What a search found out about each dataset, kept so the dataset page can show it, also in a new tab.
export type Found = { hit: Hit; topic: string; terms: string[]; assays: string[]; matched: string[] };
const FOUND = "locus:found";

export function rememberFound(result: Result) {
  const topic = result.plan.terms.join(", ");
  const matched = result.plan.matched_assays ?? [];
  const { terms, assays } = result.plan;
  const found = Object.fromEntries(result.datasets.map((hit) => [hit.accession, { hit, topic, terms, assays, matched }]));
  try {
    localStorage.setItem(FOUND, JSON.stringify(found));
  } catch {}
}

export function found(accession: string): Found | null {
  try {
    return JSON.parse(localStorage.getItem(FOUND) ?? "{}")[accession] ?? null;
  } catch {
    return null;
  }
}

// Where the search's terms and quote sit in a dataset's record. Offsets count Unicode code points.
export type Spot = { field: string; kind: "title" | "text" | "fact"; index: number; start: number; end: number };
export type Why = {
  accession: string;
  terms: { term: string; count: number; first: Spot | null }[];
  fields: { field: string; kind: Spot["kind"]; index: number; matches: { start: number; end: number; terms: string[] }[] }[];
  quote: Spot | null;
};

const asked = new Map<string, Promise<Why>>();

// The dataset page and its result row ask the same question; they share one answer.
export function why(accession: string, terms: string[], quote: string): Promise<Why> {
  const body = JSON.stringify({ terms, quote });
  const key = `${accession} ${body}`;
  let answer = asked.get(key);
  if (!answer) {
    answer = fetch(`${API}/why/${encodeURIComponent(accession)}`, { method: "POST", headers: { "content-type": "application/json" }, body }).then((res) => {
      if (!res.ok) throw new Error(`${res.status}`);
      return res.json();
    });
    answer.catch(() => asked.delete(key));
    asked.set(key, answer);
  }
  return answer;
}

export const datasetPath = (accession: string) => `/d/${encodeURIComponent(accession)}`;
export const samplePath = (dataset: string, sample: string) => `${datasetPath(dataset)}/${encodeURIComponent(sample)}`;

export type SampleRecord = DatasetRecord & {
  dataset: { accession: string; title: string; source: string };
  position: { index: number; total: number; previous: string | null; next: string | null };
};

export async function sampleRecord(dataset: string, sample: string, signal?: AbortSignal): Promise<SampleRecord> {
  const res = await fetch(`${API}/record/${encodeURIComponent(dataset)}/samples/${encodeURIComponent(sample)}`, { signal });
  if (!res.ok) throw new Error(res.status === 404 ? "missing" : `${res.status}`);
  return res.json();
}

export type Filters = Record<string, string[]>;
export type Subset = {
  samples: number; total: number; rows: number[]; counts: Record<string, Record<string, number>>; unstated: Record<string, number>;
  crossed?: [string, string, number][]; downloads: { commands: string | null; note: string | null } | null;
};

export async function subset(accession: string, filters: Filters, text: string, signal?: AbortSignal): Promise<Subset> {
  const res = await fetch(`${API}/subset/${accession}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ filters, text }), signal });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export type PreviewColumn = { name: string; type: "integer" | "number" | "boolean" | "text" | "empty"; missing: number; min?: string; max?: string; distinct?: number; group: string | null };
export type FilePreview = {
  file: string; url: string; format: string; sheet: string | null; member?: { path: string; files: number } | null; skipped: number;
  experiments?: { names: string[]; groups: Record<string, number> | null; channels: number | null } | null; bytes_read: number; size: number | null; complete: boolean;
  rows_read: number; total_rows: number | null; column_count: number; columns: PreviewColumn[]; rows: string[][];
  samples: { by: string | null; matched: number; of: number; factor: string | null; levels: Record<string, number>; keys?: string[]; looks_like?: string | null } | null;
};

export async function filePreview(accession: string, file: string, signal?: AbortSignal): Promise<FilePreview> {
  const res = await fetch(`${API}/preview/${encodeURIComponent(accession)}?file=${encodeURIComponent(file)}`, { signal }).catch((e: Error) => {
    throw e.name === "AbortError" ? e : Object.assign(new Error("locus could not reach its server."), { retry: true });
  });
  if (!res.ok) throw Object.assign(new Error((await res.json().catch(() => null))?.detail ?? `${res.status}`), { retry: res.status >= 500 });
  return res.json();
}
export type Resolved = { kind: "dataset" | "sample" | "paper"; path: string; found_in: string; title?: string };

// An identifier is one or two words with a digit (for "PMID: 123"); anything else is a question and never leaves the browser.
// The tab's last search, kept so that back from a dataset page, and the list page, see the same results.
export const LAST_SEARCH = "locus:last-search";

// A watched search remembers the datasets it showed; a later run marks the ones locus has indexed since.
const WATCHED = "locus:watched";
export type Watch = { question: string; since: string; seen: string[] };

export function watches(): Watch[] {
  try {
    return JSON.parse(localStorage.getItem(WATCHED) ?? "[]");
  } catch {
    return [];
  }
}

export function setWatch(question: string, accessions: string[] | null): Watch | null {
  const rest = watches().filter((w) => w.question !== question);
  const watch = accessions ? { question, since: new Date().toISOString().slice(0, 10), seen: accessions } : null;
  localStorage.setItem(WATCHED, JSON.stringify(watch ? [watch, ...rest] : rest));
  return watch;
}

export const looksLikeIdentifier = (text: string) => text.length <= 200 && text.trim().split(/\s+/).length <= 2 && /\d/.test(text);

// "Philippe 2020 PNAS LARP1": a capitalised surname, optionally "et al.", then a year.
export const looksLikeCitation = (text: string) => /\b[A-Z][A-Za-zÀ-ÿ'-]+(?:\s+et\s+al\.?)?,?\s+\(?(?:19|20)\d\d\)?/.test(text);
export type Cited = { title: string; journal: string; year: string; authors: string; path: string; datasets: PaperDataset[]; dataset_count: number };

export async function cite(text: string, signal?: AbortSignal): Promise<Cited | null> {
  const res = await fetch(`${API}/cite?q=${encodeURIComponent(text)}`, { signal });
  if (!res.ok) return null;
  const body = await res.json();
  return body.title ? body : null;
}

export async function resolve(text: string, signal?: AbortSignal): Promise<Resolved | null> {
  const res = await fetch(`${API}/resolve/${encodeURIComponent(text.trim())}`, { signal });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `${res.status}`);
  return res.json();
}

export type PaperDataset = {
  accession: string; source: string; title: string; modality: string; samples: number | null; url: string; path: string;
  role: "deposited" | "reused" | "cited";
};
export type PaperRecord = {
  pmid: string | null; pmcid: string | null; doi: string | null; path: string;
  title: string; authors: string[]; journal: string; year: string; abstract: [string, string][];
  data_availability: {
    status: "stated" | "not_stated" | "no_full_text" | "unavailable"; section?: string; text?: string; note?: string;
    accessions: { accession: string; role: "deposited" | "reused" | "named"; in_locus: boolean }[];
  };
  supplementary: { zip: string | null; files: { name: string; caption: string; bytes: number | null; url: string }[]; note: string | null };
  datasets: PaperDataset[]; cited_total: number; dataset_count: number;
  sources: { metadata: string; full_text: string | null; europe_pmc: string | null; doi: string | null };
};

export async function paperRecord(id: string, signal?: AbortSignal, offset = 0): Promise<PaperRecord> {
  const res = await fetch(`${API}/paper/${id.split("/").map(encodeURIComponent).join("/")}?offset=${offset}`, { signal });
  if (!res.ok) throw new Error(res.status === 404 ? "missing" : `${res.status}`);
  return res.json();
}

export type PersonPaper = {
  key: string; pmid: string | null; doi: string | null; title: string; year: string; journal: string; preprint: boolean; authors: string;
  cited_by: number; open_access: boolean; supplementary: boolean; accessions_in_text: boolean; last_author: boolean;
  datasets: { accession: string; source: string; title: string; modality: string }[];
};
export type Person = {
  name: string; query?: string; available: boolean; reason?: string; matched?: number; shown?: number; search?: string;
  journals?: Record<string, number>; papers?: PersonPaper[];
  counts?: { preprints: number; supplementary: number; open_access: number; last_author: number; with_datasets: number; datasets: number };
};

export async function person(name: string, signal?: AbortSignal): Promise<Person> {
  const res = await fetch(`${API}/person?name=${encodeURIComponent(name)}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export const personPath = (name: string) => `/a/${encodeURIComponent(name)}`;

// A record's paper ID ("pmid:…" or "doi:…") is the path of its locus paper page.
export const paperPath = (id: string) => `/p/${id.replace(/^(pmid|doi):/, "")}`;
// Harvested records carry placeholder PMIDs such as "pmid:1"; a real one has at least six digits.
export const isPaperId = (id: string) => !/^pmid:\d{1,5}$/.test(id);
export type Evidence = { text: string; term?: string; field: string; samples: string[] };
export type LibraryRow = { sample: string; title: string; why: string };
export type Assay = { assay: string; how: "named" | "inferred"; terms: string[]; evidence: Evidence[]; samples?: string[]; stated?: Record<string, number>; strategy?: Record<string, number>; mislabelled: number; library_rows?: LibraryRow[]; from_paper?: boolean };
export type PairedLibrary = LibraryRow & { assay: string };
export type Matched = { pairs: { key: string; footprint: PairedLibrary; rna: PairedLibrary; tis?: PairedLibrary }[]; unpaired: PairedLibrary[]; top_ups: PairedLibrary[] };
export type Assays = { accession: string; source: string; assays: Assay[]; unassigned_samples: LibraryRow[]; split: Evidence | null; read_from: string[]; matched?: Matched };

export async function assays(accession: string, signal?: AbortSignal): Promise<Assays> {
  const res = await fetch(`${API}/assay/${encodeURIComponent(accession)}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export type TableSummary = { accession: string; available: boolean; reason?: string; genes?: number; samples?: number; reads?: number; organism?: string;
  source?: { url: string; file: string; build: string; pipeline: string; sha256: string; bytes: number } };
export type Gene = [symbol: string, lfc: number, minusLog10P: number, q: number];
export type FirstLook = { accession: string; available: boolean; reason?: string; factor: string; case: string[]; control: string[]; n_case: number; n_control: number;
  tested: number; method: string; q: number; lfc: number; up: number; down: number; genes: Gene[]; source: NonNullable<TableSummary["source"]>;
  groups: { factors: { name: string; levels: Record<string, number>; nuisance: boolean }[]; default: { factor: string; case: string[]; control: string[] } | null };
  within: [string, string] | null; pooled: { factor: string; levels: string[] }[]; warnings: string[]; samples_with_data: number; record_samples: number; feature?: "gene" | "metabolite" };

export async function tableSummary(accession: string, signal?: AbortSignal): Promise<TableSummary> {
  const res = await fetch(`${API}/table/${encodeURIComponent(accession)}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export type Browse = { field: string; value: string; phrase: string; matched_in: string; source: string; total: number; offset: number; by_source: Record<string, number>;
  datasets: { accession: string; source: string; title: string; samples: number | null; published: string | null; modality: string }[] };

export async function browseValue(field: string, value: string, source: string, offset: number, signal?: AbortSignal): Promise<Browse> {
  const res = await fetch(`${API}/browse?${new URLSearchParams({ field, value, source, offset: String(offset) })}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export type DepthRow = { sample: string; title: string; runs: string[]; reads: number; bases: number; library: string; paired: boolean; read_length: number | null; outlier: string | null; top_up_of: string | null };
export type Quality = {
  accession: string;
  depth: { available: boolean; reason?: string; subseries?: string[]; sequencing?: boolean; project?: string; rows: DepthRow[]; outliers: number; top_ups: number; rule: string; source: string;
    groups: Record<string, { samples: number; median_reads: number; min_reads: number; max_reads: number; flagged: boolean }> };
  criteria: { quotes: { text: string; field: string }[]; read: string[]; checklist: { check: string; stated: boolean; text?: string; field?: string }[] | null };
};

export async function quality(accession: string, signal?: AbortSignal): Promise<Quality> {
  const res = await fetch(`${API}/qc/${encodeURIComponent(accession)}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}
export const tableDownload = (accession: string) => `${API}/table/${encodeURIComponent(accession)}/download`;

export type Pick = { factor: string; case: string[]; control: string[]; within?: [string, string] | null };

export async function firstLook(accession: string, pick: Pick | null, signal?: AbortSignal): Promise<FirstLook> {
  const q = new URLSearchParams();
  if (pick) {
    q.set("factor", pick.factor);
    pick.case.forEach((c) => q.append("case", c));
    pick.control.forEach((c) => q.append("control", c));
    if (pick.within) {
      q.set("within_factor", pick.within[0]);
      q.set("within", pick.within[1]);
    }
  }
  const res = await fetch(`${API}/first-look/${encodeURIComponent(accession)}?${q}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export type PaperGene = { gene: string; sentence: string | null; where: string; log2fc: number; q: number; significant: boolean };
export type PaperCheck = { available: boolean; reason?: string; paper?: string; title?: string; journal?: string; year?: string; url?: string; read?: string;
  genes: PaperGene[]; named: number; significant: number; by_chance: number };

export type PathwaySide = { genes: number; terms: { term: string; id: string; p: number; q: number; genes: string[] }[]; significant?: number; reason?: string };
export type Pathways = { available: boolean; reason?: string; library?: string; source?: string; method?: string; sides?: { up: PathwaySide; down: PathwaySide } };

export async function pathways(accession: string, pick: Pick, signal?: AbortSignal): Promise<Pathways> {
  const q = new URLSearchParams({ factor: pick.factor });
  pick.case.forEach((c) => q.append("case", c));
  pick.control.forEach((c) => q.append("control", c));
  pick.within?.forEach((w) => q.append("within", w));
  const res = await fetch(`${API}/first-look/${encodeURIComponent(accession)}/pathways?${q}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function paperCheck(accession: string, pick: { factor: string; case: string[]; control: string[] }, signal?: AbortSignal): Promise<PaperCheck> {
  const q = new URLSearchParams({ factor: pick.factor });
  pick.case.forEach((c) => q.append("case", c));
  pick.control.forEach((c) => q.append("control", c));
  const res = await fetch(`${API}/first-look/${encodeURIComponent(accession)}/paper?${q}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export type GeneRow = { accession: string; title: string; status: "higher" | "lower" | "no clear change" | "not tested" | "no table" | "no groups" | "failed"; reason?: string;
  factor?: string; case?: string[]; control?: string[]; n_case?: number; n_control?: number; source?: string; file?: string; warnings?: string[];
  log2fc?: number; minus_log10_p?: number; q?: number; rank?: number; tested?: number };
export type GeneAcross = { gene: string; description: string; hint: string; rows: GeneRow[]; measured: number; higher: number; lower: number; method: string };

export async function geneAcross(gene: string, accessions: string[], hint: string, signal?: AbortSignal): Promise<GeneAcross> {
  const q = new URLSearchParams({ hint });
  accessions.forEach((a) => q.append("in", a));
  const res = await fetch(`${API}/gene/${encodeURIComponent(gene)}?${q}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export const genePath = (gene: string, accessions: string[], hint: string) =>
  `/g/${encodeURIComponent(gene)}?${new URLSearchParams([...accessions.map((a) => ["in", a]), ["hint", hint]])}`;

// The datasets of this tab's last search, so a gene or list is compared within one question; else every dataset found.
export function foundAll(): { accessions: string[]; topic: string } {
  try {
    const last: Result | null = JSON.parse(sessionStorage.getItem(LAST_SEARCH) ?? "null");
    if (last) return { accessions: last.datasets.map((d) => d.accession), topic: last.plan.terms.join(", ") };
  } catch {}
  try {
    const all: Record<string, Found> = JSON.parse(localStorage.getItem(FOUND) ?? "{}");
    const list = Object.values(all);
    return { accessions: list.map((f) => f.hit.accession), topic: list[0]?.topic ?? "" };
  } catch {
    return { accessions: [], topic: "" };
  }
}

export type Trap = { kind: "small" | "batch" | "tissue" | "imbalance"; title: string; detail: string; factor: string; table: [string, number, number][] | null };
export type DesignCheck = { accession: string; available: boolean; reason?: string; factor: string; case: string[]; control: string[]; n_case: number; n_control: number;
  traps: Trap[]; balanced: { factor: string; v: number }[]; power: { n_case: number; n_control: number; unit?: "people" | "samples"; median_sd: number; detectable_log2fc: number; fold: number; method: string } | null };

export async function designCheck(accession: string, pick: Pick, signal?: AbortSignal): Promise<DesignCheck> {
  const q = new URLSearchParams({ factor: pick.factor });
  pick.case.forEach((c) => q.append("case", c));
  pick.control.forEach((c) => q.append("control", c));
  const res = await fetch(`${API}/design-check/${encodeURIComponent(accession)}?${q}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export type MitoGene = { symbol: string; description: string; evidence: string; compartment: string; pathways: string; tissues: string };
export type ListRow = { item: string; mitocarta: MitoGene | null; dataset?: { rank: number; log2fc: number; q: number; coloured: boolean } };
export type ListCheck = { items: number; mitocarta: number; recovery: number | null; compartments: Record<string, number>; rows: ListRow[];
  source: { name: string; url: string; citation: string; genes: number };
  dataset?: { accession: string; reason?: string; factor?: string; case?: string[]; control?: string[]; tested?: number; in_table?: number; coloured?: number; expected?: number; p?: number | null; method?: string } };

type Overlap = { accession: string; reason?: string; factor?: string; case?: string[]; control?: string[]; tested?: number; in_table?: number; coloured?: number; expected?: number; p?: number | null };
export type ListAcross = { items: number; compared: number; rows: (Overlap & { hits?: { item: string; log2fc: number; q: number }[] })[] };

export async function checkListAcross(text: string, accessions: string[], hint: string, signal?: AbortSignal): Promise<ListAcross> {
  const res = await fetch(`${API}/list/across`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, accessions, hint }), signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function checkList(text: string, accession: string, signal?: AbortSignal): Promise<ListCheck> {
  const res = await fetch(`${API}/list`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, accession }), signal });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail?.[0]?.msg ?? `${res.status}`);
  return res.json();
}
export const browsePath = (field: string, value: string) => `/browse?${new URLSearchParams({ field, value })}`;
