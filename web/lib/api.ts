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
  factors: { name: string; levels: Record<string, number>; aliases?: string[] }[];
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

export type RecordFile = { name: string; url: string; group: string; bytes: number | null; processed: boolean; kind: string };
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
export type Found = { hit: Hit; topic: string; matched: string[] };
const FOUND = "locus:found";

export function rememberFound(result: Result) {
  const topic = result.plan.terms.join(", ");
  const matched = result.plan.matched_assays ?? [];
  const found = Object.fromEntries(result.datasets.map((hit) => [hit.accession, { hit, topic, matched }]));
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

export type TableSummary = { accession: string; available: boolean; reason?: string; genes?: number; samples?: number; reads?: number; organism?: string;
  source?: { url: string; file: string; build: string; pipeline: string; sha256: string; bytes: number } };
export type Gene = [symbol: string, lfc: number, minusLog10P: number, q: number];
export type FirstLook = { accession: string; available: boolean; reason?: string; factor: string; case: string[]; control: string[]; n_case: number; n_control: number;
  tested: number; method: string; q: number; lfc: number; up: number; down: number; genes: Gene[]; source: NonNullable<TableSummary["source"]>;
  groups: { factors: { name: string; levels: Record<string, number> }[]; default: { factor: string; case: string[]; control: string[] } | null } };

export async function tableSummary(accession: string, signal?: AbortSignal): Promise<TableSummary> {
  const res = await fetch(`${API}/table/${encodeURIComponent(accession)}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export const tableDownload = (accession: string) => `${API}/table/${encodeURIComponent(accession)}/download`;

export async function firstLook(accession: string, pick: { factor: string; case: string[]; control: string[] } | null, signal?: AbortSignal): Promise<FirstLook> {
  const q = new URLSearchParams();
  if (pick) {
    q.set("factor", pick.factor);
    pick.case.forEach((c) => q.append("case", c));
    pick.control.forEach((c) => q.append("control", c));
  }
  const res = await fetch(`${API}/first-look/${encodeURIComponent(accession)}?${q}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export type PaperGene = { gene: string; sentence: string | null; where: string; says: "higher" | "lower" | null; log2fc: number; q: number; significant: boolean; agrees: boolean | null };
export type PaperCheck = { available: boolean; reason?: string; paper?: string; title?: string; journal?: string; year?: string; url?: string; read?: string;
  genes: PaperGene[]; named: number; significant: number; agree: number; disagree: number };

export async function paperCheck(accession: string, pick: { factor: string; case: string[]; control: string[] }, signal?: AbortSignal): Promise<PaperCheck> {
  const q = new URLSearchParams({ factor: pick.factor });
  pick.case.forEach((c) => q.append("case", c));
  pick.control.forEach((c) => q.append("control", c));
  const res = await fetch(`${API}/first-look/${encodeURIComponent(accession)}/paper?${q}`, { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}
