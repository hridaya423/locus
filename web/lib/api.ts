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

export type Verdict = "pool" | "effects" | "no" | "unclear";
export type FacetStatus = "same" | "related" | "differs" | "unknown";
export type Profile = {
  accession: string; source: string; title: string; organism: string | null; layer: string | null; technology: string | null;
  platform: string | null; material: string | null; tissue: string | null; case: number | null; control: number | null;
  contrast: string | null; build: string | null; contrast_name?: string | null; access?: string | null; sex?: string | null; shared?: number | null;
  sex_split?: Record<"cases" | "controls", { female: number; male: number }> | null; files?: string[];
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

// The laptop-tier processing job: subsampled reads -> salmon -> counts -> DESeq2 -> plots, run by the API in the background.
export const PROCESS_STAGES = ["plan", "reference", "fetch", "quantify", "count", "test", "done"] as const;
export type ProcessStage = (typeof PROCESS_STAGES)[number] | "error";
export type ProcessSample = { gsm: string; title: string; srx: string; run: string; fastq: string[]; condition: string; reads?: number; mapped?: number; mapping_rate?: number; library_type?: string };
export type TopGene = { gene_id: string; gene_name: string; base_mean: number; log2fc: number; padj: number };
export type ProcessResult = {
  accession: string; organism: string; contrast: { field: string; reference: string; target: string; levels: Record<string, string> };
  samples: ProcessSample[]; skipped: { gsm: string; title: string; reason: string }[];
  genes: number; genes_tested: number; significant: number; up: number; down: number;
  pca: { variance: [number, number]; means: Record<string, { PC1: number; PC2: number }> };
  top_genes: TopGene[]; files: { name: string; bytes: number }[]; seconds: number; reads_per_fastq: number;
  reference: { source: string; release: string; url: string; index: string }; tools: Record<string, string>;
};
export type ProcessStatus = {
  accession: string; stage: ProcessStage | null; log: string[]; stages: Record<string, { count?: number; done?: number }>;
  result: ProcessResult | null; error: string | null;
};
export type PcaPoint = { sample: string; condition: string; PC1: number; PC2: number };
export type VolcanoPoint = { gene: string; log2fc: number; neglog10p: number; padj: number; significant: boolean };
export type MaPoint = { gene: string; log10_mean: number; log2fc: number; padj: number; significant: boolean };

export async function startProcess(accession: string, topic: string): Promise<{ stage: ProcessStage; started: boolean }> {
  const res = await fetch(`${API}/process/${accession}?topic=${encodeURIComponent(topic)}`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export async function processStatus(accession: string, signal?: AbortSignal): Promise<ProcessStatus> {
  const res = await fetch(`${API}/process/${accession}`, { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const processFile = (accession: string, name: string) => `${API}/process/${accession}/files/${name}`;

export async function processJson<T>(accession: string, name: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(processFile(accession, name), { signal });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}
