export const API = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export type Plan = { terms: string[]; organism: string; assays: string[]; repositories: string[]; method_notes: string[]; matched_assays?: string[]; wants_controls: boolean };
export type Facts = {
  case: number | null; control: number | null; mixed?: number; has_control: boolean | null;
  sample_type: string; tissue: string; source: string; assays?: string[]; library?: Record<string, number>;
  libraries?: Record<string, Partial<Record<"case" | "control" | "mixed" | "other", number>>>;
  methods?: Record<string, { value: string; label: string; evidence: string; trusted: boolean }>;
};
export type Partner = { accession: string; source: string; title: string; url: string; organism: string; assay: string; tissue: string };
export type ReadyFiles = { processed: { name: string; kind: string; bytes: number; url: string }[]; more: number; raw: { files: number; bytes: number } };
export type Paper = { title: string; journal: string; year: string; url: string };
export type Check = "yes" | "no" | "unclear" | "same" | "other" | "n/a";
export type Hit = {
  accession: string; source: string; modality: string; title: string; organism: string;
  samples: number | null; url: string; papers: string[]; facts: Facts | null; published: string | null;
  fit: "strong" | "partial"; checks: Record<"topic" | "patient_material" | "data_type" | "controls", Check>;
  reason: string; evidence: string; paper: Paper | null; download_plan: string; partners?: Partner[];
};
export type Result = { question: string; plan: Plan; candidates: number; datasets: Hit[]; same_paper: string[][] };
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
  accession: string; source: string; url: string; title: string;
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
export type PreviewColumn = { name: string; type: "integer" | "number" | "boolean" | "text" | "empty"; missing: number; min?: string; max?: string; distinct?: number; group: string | null };
export type FilePreview = {
  file: string; url: string; format: string; sheet: string | null; skipped: number; bytes_read: number; size: number | null; complete: boolean;
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
export const looksLikeIdentifier = (text: string) => text.length <= 200 && text.trim().split(/\s+/).length <= 2 && /\d/.test(text);

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

// A record's paper ID ("pmid:…" or "doi:…") is the path of its locus paper page.
export const paperPath = (id: string) => `/p/${id.replace(/^(pmid|doi):/, "")}`;
// Harvested records carry placeholder PMIDs such as "pmid:1"; a real one has at least six digits.
export const isPaperId = (id: string) => !/^pmid:\d{1,5}$/.test(id);
export type Evidence = { text: string; term?: string; field: string; samples: string[] };
export type LibraryRow = { sample: string; title: string; why: string };
export type Assay = { assay: string; how: "named" | "inferred"; terms: string[]; evidence: Evidence[]; samples?: string[]; stated?: Record<string, number>; strategy?: Record<string, number>; mislabelled: number; library_rows?: LibraryRow[] };
export type PairedLibrary = LibraryRow & { assay: string };
export type Matched = { pairs: { key: string; footprint: PairedLibrary; rna: PairedLibrary; tis?: PairedLibrary }[]; unpaired: PairedLibrary[]; top_ups: PairedLibrary[] };
export type Assays = { accession: string; source: string; assays: Assay[]; unassigned_samples: LibraryRow[]; split: Evidence | null; read_from: string[]; matched?: Matched };

export async function assays(accession: string, signal?: AbortSignal): Promise<Assays> {
  const res = await fetch(`${API}/assay/${encodeURIComponent(accession)}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}
