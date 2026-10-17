"""What was measured, read from the methods: protocols, reagents, antibodies and instruments, not the author's label.

Every classification carries the sentence it was read from and the record field (and sample) that holds it.
"named" means the methods name the technique; "inferred" means a reagent or step implies it (W6/32 → immunopeptidomics)."""

import re
from collections import Counter

from . import record, samples

# (assay, how, pattern). Order matters only for display. Patterns run on one sentence at a time.
RULES = [
    ("TIS-seq (initiating ribosomes)", "named", r"\b(?:TIS|GTI|QTI|TI)-seq\b"),
    ("TIS-seq (initiating ribosomes)", "inferred", r"\b(?:harringtonine|lactimidomycin)\b"),
    ("Ribo-STAMP", "named", r"\bRibo-?STAMP\b|\bRPS2-?(?:APOBEC|STAMP)|APOBEC1?-RPS2"),
    ("Ribo-seq (elongating ribosomes)", "named", r"ribosome profiling|\bribo-?seq\b|ribosome[- ]protected (?:mRNA )?fragments?|\bRPFs?\b|footprint(?:ing)? librar(?:y|ies)|ribosome footprint"),
    ("Ribo-seq (elongating ribosomes)", "inferred", r"\bRNase ?I\b.{0,120}\b(?:monosome|ribosom|sucrose)|\b(?:monosome|80S)\b.{0,120}\b(?:RNase|nuclease|digest)"),
    ("Ribo-seq (elongating ribosomes)", "inferred", r"\bcycloheximide\b|\bCHX\b"),
    ("Polysome profiling", "named", r"polysome[- ](?:profil|seq|fraction)|polysomal (?:RNA|fraction)"),
    ("Single-cell RNA-seq, droplet", "named", r"\b10[xX] Genomics\b|\bChromium\b|\bSingle Cell [35]['′’] |\bDrop-?seq\b|\binDrops?\b|\bBD Rhapsody\b"),
    ("Single-cell RNA-seq, plate", "named", r"\bSmart-?seq ?[23]?\b|\bSMART-Seq\b|\bCEL-?seq2?\b|\bMARS-?seq\b|\bFluidigm C1\b|\bC1 (?:IFC|Single-Cell|system)"),
    ("Single-cell RNA-seq, combinatorial", "named", r"\bsci-RNA-seq\b|\bSPLiT-seq\b|\bParse Biosciences\b|\bEvercode\b"),
    ("Single-nucleus RNA-seq", "named", r"\bsnRNA-?seq\b|\bsingle[- ]nucle(?:us|i) RNA"),
    ("CITE-seq (RNA + surface protein)", "named", r"\bCITE-?seq\b|\bTotalSeq\b|antibody[- ]derived tags?"),
    ("Spatial transcriptomics", "named", r"\bVisium\b|\bSlide-?seq(?:V2)?\b|\bMERFISH\b|\bXenium\b|\bCosMx\b|\bGeoMx\b|\bStereo-?seq\b|\bseqFISH\b"),
    ("RNA-seq", "named", r"\bRNA-?seq\b|\bmRNA-?seq\b|\bTruSeq\b.{0,30}\bRNA\b|\bpoly\(?A\)?\+? (?:RNA )?(?:selection|enrich|captur)|\bNEBNext\b.{0,30}\bRNA\b"),
    ("Long-read RNA (isoform-resolved)", "named", r"\bOxford Nanopore\b|\bMinION\b|\bPromethION\b|\bPacBio\b|\bIso-?Seq\b|\bdirect RNA sequencing\b"),
    ("ATAC-seq", "named", r"\bATAC-?seq\b|\bscATAC\b|\bMultiome\b"),
    ("ChIP-seq", "named", r"\bChIP-?seq\b|chromatin immunoprecipitation"),
    ("CUT&RUN / CUT&Tag", "named", r"\bCUT ?& ?(?:RUN|Tag)\b|\bCUT and (?:RUN|Tag)\b"),
    ("Hi-C", "named", r"\bHi-?C\b|\bMicro-C\b"),
    ("DNA methylation", "named", r"\bbisulfite\b|\bWGBS\b|\bRRBS\b|\bEM-seq\b|\bEPIC (?:array|BeadChip)\b|\bHumanMethylation\d+"),
    ("CLIP-seq (RNA-protein binding)", "named", r"\b(?:e|i|PAR-|HITS-)CLIP\b|\bCLIP-seq\b"),
    ("16S rRNA amplicon", "named", r"\b16S (?:rRNA|rDNA|ribosomal)|\bV3-?V4\b|\bV4 (?:hyper)?variable"),
    ("Shotgun metagenomics", "named", r"shotgun metagenom|metagenomic (?:shotgun )?sequencing"),
    ("Immunopeptidomics (HLA/MHC ligands)", "named", r"immunopeptidom|\bligandom|\b(?:HLA|MHC)[- ](?:class[- ]I{1,2} )?(?:peptidom|ligand)"),
    ("Immunopeptidomics (HLA/MHC ligands)", "inferred", r"\bW6/32\b|\bL243\b|\bBB7\.2\b|\bIVA12\b|\bTü ?39\b|(?:immunoprecipitat|immunoaffinity|immuno-affinity|pull-?down).{0,80}\b(?:HLA|MHC)\b|\b(?:HLA|MHC)\b.{0,80}(?:immunoprecipitat|immunoaffinity|immuno-affinity)"),
    ("Organelle IP", "named", r"\bMito-?IP\b|\bLyso-?IP\b|organelle (?:immuno)?(?:precipitation|IP)\b"),
    ("Organelle IP", "inferred", r"\b3X?HA-?OMP25\b|\bHA-?OMP25\b|\bTMEM192-?3X?HA\b|\bHA-?TMEM192\b|\b(?:FLAG|HA|Myc|GFP)-tagged (?:TOMM?20|OMP25|TMEM192|LAMP1)\b|(?:immunoprecipitat|immunopurif|immunoisolat)\w* (?:of )?(?:intact )?(?:mitochondria|lysosomes|peroxisomes|organelles)"),
    ("Proximity labelling", "named", r"\bBioID\b|\bTurboID\b|\bAPEX2?\b|proximity[- ](?:dependent )?(?:biotin )?label"),
    ("Phosphoproteomics", "named", r"phosphoproteom|phosphopeptide enrich|enrich\w* (?:for )?phosphopeptides"),
    ("Phosphoproteomics", "inferred", r"\bTiO2\b|titanium dioxide|\bIMAC\b|\bFe-?NTA\b|\bFe\(III\)|\bFe3\+"),
    ("Ubiquitylomics", "named", r"ubiquityl?om|ubiquitinom|\bdi-?Gly(?:cine)?\b|\bK-?[εe]-?GG\b"),
    ("Isobaric labelling (TMT/iTRAQ)", "named", r"\bTMT(?:pro)?(?:\s?-?\d+(?:-?plex)?)?\b|tandem mass tags?|\biTRAQ\b"),
    ("SILAC", "named", r"\bSILAC\b"),
    ("Label-free quantification", "named", r"\blabel[- ]free\b|\bLFQ\b"),
    ("Data-independent acquisition (DIA)", "named", r"\bDIA\b(?!-?NN\b)|data[- ]independent acquisition|\bSWATH\b|\bDIA-NN\b|\bSpectronaut\b"),
    ("Data-dependent acquisition (DDA)", "named", r"\bDDA\b|data[- ]dependent acquisition|data[- ]dependent mode|\bTop ?\d+ (?:method|mode|DDA)"),
    ("Untargeted metabolomics", "named", r"\b(?:un|non-?)targeted metabolom"),
    ("Targeted metabolomics", "named", r"(?<!un)(?<!non-)(?<!non)\btargeted metabolom"),
    ("Lipidomics", "named", r"\blipidom"),
    ("Cross-linking MS", "named", r"cross-?linking mass spec|\bXL-?MS\b|\bDSSO\b"),
]
CASE_SENSITIVE = {"Data-independent acquisition (DIA)", "Data-dependent acquisition (DDA)", "Proximity labelling"}
COMPILED = [(assay, how, re.compile(p, 0 if assay in CASE_SENSITIVE else re.I)) for assay, how, p in RULES]

# Harringtonine is also a leukaemia drug (homoharringtonine, omacetaxine); it marks TIS-seq only next to ribosome profiling.
RIBOSOME_PROFILING = re.compile(r"ribosome profiling|ribo-?seq|footprint|\bRPFs?\b|monosome|ribosome[- ]protected", re.I)
SINGLE_CELL = {"Single-cell RNA-seq, droplet", "Single-cell RNA-seq, plate", "Single-cell RNA-seq, combinatorial", "Single-nucleus RNA-seq", "Spatial transcriptomics"}

# Words in a sample's own title or description that say which library it is, when one protocol text describes several.
LIBRARY_WORDS = [(assay, re.compile(rf"(?<![A-Za-z0-9])(?:{words})(?![A-Za-z0-9])", re.I)) for assay, words in (
    ("TIS-seq (initiating ribosomes)", r"harr|harringtonine|HHT|LTM|lactimidomycin|TIS|GTI|QTI|TI-?seq"),
    ("Ribo-seq (elongating ribosomes)", r"ribo|riboseq|ribo-?seq|RPFs?|footprints?|FP|CHX|ribosome profiling|monosomes?"),
    ("RNA-seq", r"m?RNA|RNA-?seq|m?RNAseq|total ?RNA|input"),
)]

SENTENCE = re.compile(r"(?<=[.;!?])\s+(?=[A-Za-z0-9(\[])")


def _sentences(text: str):
    for s in SENTENCE.split(re.sub(r"\s+", " ", text)):
        if s.strip():
            yield s.strip()


def _match(sentence: str, study_text: str) -> list[tuple[str, str, str]]:
    found = []
    for assay, how, rx in COMPILED:
        if m := rx.search(sentence):
            if assay.startswith(("TIS", "Ribo-seq")) and how == "inferred" and not RIBOSOME_PROFILING.search(study_text):
                continue
            found.append((assay, how, m.group(0)))
    return found


def _texts(rec: dict) -> list[tuple[str, list[str], str]]:
    """(field, samples, text) for every methods-bearing text of a dataset, each text once with every GEO sample that states it."""
    out = [(label, [], text) for label, text in rec["texts"]]
    out += [(label, [], v) for label, values in rec["facts"] if label in {"Instrument", "Instruments", "Quantification", "Experiment types", "Platforms", "Study type", "Library strategy"} for v in values]
    if rec["source"] == "GEO":
        by_text: dict[str, tuple[str, list[str]]] = {}
        for block in (samples.CACHE / f"{rec['accession']}.txt").read_text().split("^SAMPLE = ")[1:]:
            gsm = block.split("\n", 1)[0].strip()
            for line in block.splitlines()[1:]:
                key, _, value = line.partition(" = ")
                field = re.sub(r"^!Sample_|_ch\d$", "", key)
                if field in record.GSM_TEXTS and value:
                    by_text.setdefault(value, (record.GSM_TEXTS[field], []))[1].append(gsm)
        out += [(field, gsms, text) for text, (field, gsms) in by_text.items()]
    return out


def _libraries(rec: dict, assays: list[str], study: str) -> dict[str, dict]:
    """For a GEO study with ribosome footprints: which samples are which library. A sample's own title and description
    decide first; then its own protocol, unless every sample shares that protocol and the titles tell the libraries apart."""
    parsed = []
    for block in (samples.CACHE / f"{rec['accession']}.txt").read_text().split("^SAMPLE = ")[1:]:
        fields: dict[str, list[str]] = {}
        for line in block.splitlines()[1:]:
            key, _, value = line.partition(" = ")
            fields.setdefault(re.sub(r"^!Sample_|_ch\d$", "", key), []).append(value)
        words = " ".join(fields.get("title", []) + fields.get("description", []) + fields.get("source_name", []) + fields.get("characteristics", []))
        protocol = " ".join(fields.get("treatment_protocol", []) + fields.get("extract_protocol", []) + fields.get("growth_protocol", []))
        stated = next((m.group(1).strip() for v in fields.get("data_processing", []) if (m := re.match(r"library strategy:\s*(.+)", v, re.I))), None)
        parsed.append((block.split("\n", 1)[0].strip(), words, protocol, stated or (fields.get("library_strategy") or ["not stated"])[0], (fields.get("title") or [""])[0]))
    shared = len({p for _, _, p, _, _ in parsed}) == 1
    titled = any(rx.search(w) for _, w, _, _, _ in parsed for a, rx in LIBRARY_WORDS[1:])
    own: dict[str, dict] = {}
    for gsm, words, protocol, label, title in parsed:
        kind = next((a for a, rx in LIBRARY_WORDS if a in assays + ["RNA-seq"] and rx.search(words)), None)
        if not (shared and titled) and kind != "RNA-seq":
            by_protocol = [a for a, _, _ in _match(protocol, study) if a.startswith(("TIS-seq", "Ribo-seq"))]
            kind = by_protocol[0] if by_protocol else kind
        own[gsm] = {"assay": kind, "label": label, "title": title}
    return own


SPLIT = re.compile(r"\b(?:split|divided|aliquot\w*|a (?:sample|portion|fraction) (?:of the lysate )?was (?:taken|removed|saved|set aside)|in parallel)\b", re.I)
RNA_SEQ = re.compile(r"\b(?:total |poly\(?A\)?\+? |m)RNA[- ](?:seq|librar(?:y|ies)|sequencing)|\bRNA-?seq librar(?:y|ies)|\bmRNA-?seq\b", re.I)


def classify(accession: str) -> dict | None:
    rec = record.record(accession)
    if rec is None:
        return None
    texts = _texts(rec)
    study = " ".join(t for _, _, t in texts)
    found: dict[str, dict] = {}
    for field, sample_list, text in texts:
        for sentence in _sentences(text):
            for assay, how, term in _match(sentence, study):
                entry = found.setdefault(assay, {"assay": assay, "how": how, "terms": [], "evidence": []})
                if how == "named":
                    entry["how"] = "named"
                short = term if len(term) <= 24 else " ".join(term.split()[:2])
                if short.lower() not in (t.lower() for t in entry["terms"]):
                    entry["terms"].append(short)
                if sentence not in (e["text"] for e in entry["evidence"]):
                    entry["evidence"].append({"text": sentence, "term": term, "field": field, "samples": sample_list, "how": how})

    if SINGLE_CELL & set(found):
        found.pop("RNA-seq", None)
    libraries = {}
    ribo_family = [a for a in found if a.startswith(("TIS-seq", "Ribo-seq"))]
    if rec["source"] == "GEO" and ribo_family:
        libraries = _libraries(rec, ribo_family, study)
        for assay, entry in found.items():
            members = [g for g, s in libraries.items() if s["assay"] == assay]
            if members:
                entry["samples"] = members
                entry["labels"] = dict(Counter(libraries[g]["label"] for g in members))
                own = [e for e in entry["evidence"] if not e["samples"] or set(e["samples"]) & set(members)]
                entry["evidence"] = [e for e in own if not e["samples"] or set(e["samples"]) <= set(members) or len(e["samples"]) == len(libraries)] or own
                entry["mislabelled"] = sum(n for label, n in entry["labels"].items() if _names_other(label, assay))
        rna = [g for g, s in libraries.items() if s["assay"] == "RNA-seq"]
        if rna:
            evidence = [{"text": sentence, "term": m.group(0), "field": field, "samples": sample_list}
                        for field, sample_list, text in texts for sentence in _sentences(text) if (m := RNA_SEQ.search(sentence))][:3]
            found.setdefault("RNA-seq", {"assay": "RNA-seq", "how": "named", "terms": [e["term"] for e in evidence[:1]], "evidence": evidence})
            found["RNA-seq"]["samples"] = rna
            found["RNA-seq"]["labels"] = dict(Counter(libraries[g]["label"] for g in rna))
        unassigned = [g for g, s in libraries.items() if s["assay"] is None]
        if len(unassigned) < len(libraries):
            found = {a: e for a, e in found.items() if not a.startswith(("TIS-seq", "Ribo-seq", "RNA-seq")) or e.get("samples")}
    else:
        unassigned = []
    split = None
    if {"RNA-seq"} & set(found) and any(a.startswith(("Ribo-seq", "TIS-seq")) for a in found):
        split = next(({"text": sentence, "field": field, "samples": sample_list} for field, sample_list, text in texts for sentence in _sentences(text)
                      if SPLIT.search(sentence) and re.search(r"lysate|RNA|librar|sample", sentence, re.I)), None)
    for entry in found.values():
        entry["evidence"] = [e for e in entry["evidence"] if not split or e["text"] != split["text"]] or entry["evidence"]
        ranked = sorted(entry["evidence"], key=lambda e: "protocol" not in e["field"].lower())
        picks = [next((e for e in ranked if e.get("how") == how), None) for how in ("named", "inferred")]
        entry["evidence"] = [e for e in picks if e] or ranked[:2]
        entry.setdefault("mislabelled", 0)
    return {
        "accession": accession,
        "source": rec["source"],
        "assays": [e for e in found.values() if e["evidence"] or e.get("samples")],
        "unassigned_samples": unassigned,
        "split": split,
        "read_from": sorted({f for f, _, _ in texts}),
    }


def _names_other(label: str, assay: str) -> bool:
    """Whether an author's library label names a different library type than the methods show."""
    named = next((a for a, rx in LIBRARY_WORDS if rx.search(label)), None)
    return named is not None and named != assay


def library_types(accession: str) -> tuple[dict[str, str], str]:
    """Each GEO sample's library type as the methods show it (only for studies with ribosome footprints), and the sentence
    that shows initiating ribosomes, if any."""
    result = classify(accession) or {"assays": []}
    types = {g: a["assay"] for a in result["assays"] for g in a.get("samples", [])}
    tis = next((a["evidence"][0]["text"] for a in result["assays"] if a["assay"].startswith("TIS-seq") and a["evidence"]), "")
    return types, tis


if __name__ == "__main__":
    def assays(acc: str) -> dict[str, dict]:
        return {a["assay"]: a for a in classify(acc)["assays"]}

    RIBO, TIS, RNA = "Ribo-seq (elongating ribosomes)", "TIS-seq (initiating ribosomes)", "RNA-seq"
    mtor = assays("GSE36892")
    assert set(mtor) == {RIBO, RNA} and len(mtor[RIBO]["samples"]) == 8 and len(mtor[RNA]["samples"]) == 4, mtor.keys()
    neurons = assays("GSE255191")
    assert len(neurons[TIS]["samples"]) == 2 and neurons[TIS]["mislabelled"] == 2 and "harringtonine" in neurons[TIS]["evidence"][0]["text"]
    assert len(neurons[RIBO]["samples"]) == 2 and "cycloheximide" in neurons[RIBO]["evidence"][0]["text"]
    assert set(assays("GSE150375")) == {TIS}
    for drug in ("GSE182020", "GSE296679"):
        assert not {RIBO, TIS} & set(assays(drug)), drug
    assert "Clarified lysates were split in two" in classify("GSE132703")["split"]["text"]
    assert "Single-cell RNA-seq, plate" in assays("GSE86618") and "Single-cell RNA-seq, droplet" in assays("E-MTAB-6149")
    assert "W6/32" in assays("PXD010450")["Immunopeptidomics (HLA/MHC ligands)"]["terms"]
    assert "Organelle IP" in assays("PXD062418") and "Phosphoproteomics" in assays("PXD047213")
    assert "16S rRNA amplicon" in assays("PRJEB39707")
    print("assay self-check passed")
