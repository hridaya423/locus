export const API = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export type Plan = { terms: string[]; organism: string; assays: string[]; repositories: string[]; method_notes: string[]; matched_assays?: string[]; wants_controls: boolean };
export type Facts = {
  case: number | null; control: number | null; mixed?: number; has_control: boolean | null;
  sample_type: string; tissue: string; source: string; assays?: string[]; library?: Record<string, number>;
  libraries?: Record<string, Partial<Record<"case" | "control" | "mixed" | "other", number>>>;
};
export type Paper = { title: string; journal: string; year: string; url: string };
export type Check = "yes" | "no" | "unclear" | "same" | "other" | "n/a";
export type Hit = {
  accession: string; source: string; modality: string; title: string; organism: string;
  samples: number | null; url: string; papers: string[]; facts: Facts | null; published: string | null;
  fit: "strong" | "partial"; checks: Record<"topic" | "patient_material" | "data_type" | "controls", Check>;
  reason: string; evidence: string; paper: Paper | null;
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

export const SAMPLE_TYPE: Record<string, string> = {
  patient_tissue: "patient tissue", patient_biofluid: "patient fluid", primary_cells: "primary cells",
  cell_line: "cell line", animal_or_organoid_model: "model system", unknown: "",
};
