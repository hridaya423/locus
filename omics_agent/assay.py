"""What was measured, read from the methods: protocols, reagents, antibodies and instruments, not the author's label.

Every classification carries the sentence it was read from and the record field (and sample) that holds it.
"named" means the methods name the technique; "inferred" means a reagent or step implies it (W6/32 → immunopeptidomics)."""

import re
from collections import Counter

from functools import lru_cache

from . import record, samples, sources

# (assay, how, pattern). Order matters only for display. Patterns run on one sentence at a time.
RULES = [
    ("TIS-seq (initiating ribosomes)", "named", r"\b(?:TIS|GTI|QTI|TI)-seq\b"),
    ("TIS-seq (initiating ribosomes)", "inferred", r"\b(?:harringtonine|lactimidomycin)\b"),
    ("Ribo-STAMP", "named", r"\bRibo-?STAMP\b|\bRPS2-?(?:APOBEC|STAMP)|APOBEC1?-RPS2"),
    ("Ribo-seq (elongating ribosomes)", "named", r"ribosome profiling|\bribo-?seq\b|ribosome[- ]protected (?:mRNA )?fragments?|\bRPFs?\b|footprint(?:ing)? librar(?:y|ies)|ribosome footprint"),
    ("Ribo-seq (elongating ribosomes)", "inferred", r"\bRNase ?I\b.{0,120}\b(?:monosome|ribosom|sucrose)|\b(?:monosome|80S)\b.{0,120}\b(?:RNase|nuclease|digest)"),
    ("Ribo-seq (elongating ribosomes)", "inferred", r"\bcycloheximide\b|\bCHX\b"),
    ("Polysome profiling", "named", r"polysome[- ](?:profil|seq|fraction)|polysomal (?:RNA|fraction)"),
    ("Single-cell RNA-seq, droplet", "named", r"\b10[xX] (?:Genomics )?Chromium\b|\bChromium (?:Single Cell|Controller|Next GEM|X|iX|Connect)\b|\b10[xX] Genomics\b.{0,80}\b(?:single[- ]cell|scRNA|snRNA|GEMs?|[35]['′’])|\bSingle Cell [35]['′’] |\bDrop-?seq\b|\binDrops?\b|\bBD Rhapsody\b"),
    ("Single-cell RNA-seq, plate", "named", r"\bSmart-?seq ?[23]\b|\bSMART-?Seq2\b|\bSMART-Seq\b(?=.{0,80}single[- ]cell)|\bCEL-?seq2?\b|\bMARS-?seq\b|\bFluidigm C1\b|\bC1 (?:IFC|Single-Cell|system)"),
    ("Single-cell RNA-seq, combinatorial", "named", r"\bsci-RNA-seq\b|\bSPLiT-seq\b|\bParse Biosciences\b|\bEvercode\b"),
    ("Single-nucleus RNA-seq", "named", r"\bsnRNA-?seq\b|\bsingle[- ]nucle(?:us|i) RNA"),
    ("Immune repertoire (V(D)J)", "named", r"\bV\(D\)J\b|(?-i:\bVDJ\b)|\b(?:TCR|BCR) (?:repertoire|sequencing|libraries|library)"),
    ("CITE-seq (RNA + surface protein)", "named", r"\bCITE-?seq\b|\bTotalSeq\b|antibody[- ]derived tags?"),
    ("Spatial transcriptomics", "named", r"\bVisium\b|\bSlide-?seq(?:V2)?\b|\bMERFISH\b|\bXenium\b|\bCosMx\b|\bGeoMx\b|\bStereo-?seq\b|\bseqFISH\b"),
    ("RNA-seq", "named", r"\bRNA-?seq\b|\bmRNA-?seq\b|\bTruSeq\b.{0,30}\bRNA\b|\bpoly\(?A\)?\+? (?:RNA )?(?:selection|enrich|captur)|\bNEBNext\b.{0,30}\bRNA\b"),
    ("Long-read RNA (isoform-resolved)", "named", r"\bOxford Nanopore\b|\bMinION\b|\bPromethION\b|\bPacBio\b|\bIso-?Seq\b|\bdirect RNA sequencing\b"),
    ("ATAC-seq", "named", r"\bATAC-?seq\b|\bscATAC\b|\bMultiome\b"),
    ("ChIP-chip (tiling array)", "named", r"\bChIP-?chip\b|binding/occupancy profiling by genome tiling array"),
    ("ChIP-seq", "named", r"\bChIP-?seq\b|chromatin immunoprecipitation(?!.{0,60}\b(?:chip|array|microarray)\b)"),
    ("CUT&RUN / CUT&Tag", "named", r"\bCUT ?& ?(?:RUN|Tag)\b|\bCUT and (?:RUN|Tag)\b"),
    ("Hi-C", "named", r"\bHi-?C\b|\bMicro-C\b"),
    ("DNA methylation", "named", r"\bbisul(?:f|ph)ite\b|\bWGBS\b|\bRRBS\b|\bEM-seq\b|\bEPIC (?:array|BeadChip)\b|\bHumanMethylation\d+"),
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
    ("Ubiquitylomics", "named", r"ubiquityl?om|ubiquitinom|\bdi-?Gly(?:cine)? (?:remnant|motif|peptide|antibod|enrich)|(?-i:\bK-?ε-?GG\b)"),
    ("Isobaric labelling (TMT/iTRAQ)", "named", r"\bTMT(?:pro)?(?:\s?-?\d+(?:-?plex)?)?\b|tandem mass tags?|\biTRAQ\b"),
    ("SILAC", "named", r"\bSILAC\b"),
    ("Label-free quantification", "named", r"\blabel[- ]free\b|\bLFQ\b"),
    ("Data-independent acquisition (DIA)", "named", r"\bDIA\b(?!-?NN\b)|data[- ]independent acquisition|\bSWATH\b|\bDIA-NN\b|\bSpectronaut\b"),
    ("Data-dependent acquisition (DDA)", "named", r"\bDDA\b|data[- ]dependent acquisition|data[- ]dependent mode|\bTop ?\d+ (?:method|mode|DDA)"),
    ("Untargeted metabolomics", "named", r"\b(?:un|non-?)targeted metabolom"),
    ("Targeted metabolomics", "named", r"(?<!un)(?<!non-)(?<!non)\btargeted metabolom"),
    ("Lipidomics", "named", r"\blipidom"),
    ("Targeted MS (PRM/SRM/MRM)", "named", r"(?-i:\bPRM\b|\bSRM\b|\bMRM\b)|parallel reaction monitoring|selected reaction monitoring|multiple reaction monitoring"),
    ("Expression microarray", "named", r"expression profiling by array|transcription profiling by array"),
    ("Array CGH", "named", r"comparative genomic hybridi[sz]ation by array|\barray CGH\b|\baCGH\b"),
    ("Small RNA-seq", "named", r"\bmiRNA[- ]seq|\bmicroRNA sequencing|small RNA (?:sequencing|librar|-seq)|\bsRNA-seq"),
    ("Top-down proteomics", "named", r"top-?down proteom"),
    ("Nascent transcription (PRO-seq/GRO-seq)", "named", r"\bPRO-?seq\b|\bGRO-?seq\b|\bPRO-?cap\b|\bTT-?seq\b"),
    ("Cross-linking MS", "named", r"cross-?linking mass spec|\bXL-?MS\b|\bDSSO\b"),
]
CASE_SENSITIVE = {"Data-independent acquisition (DIA)", "Data-dependent acquisition (DDA)", "Proximity labelling"}
COMPILED = [(assay, how, re.compile(p, 0 if assay in CASE_SENSITIVE else re.I)) for assay, how, p in RULES]

# Harringtonine is also a leukaemia drug (homoharringtonine, omacetaxine); it marks TIS-seq only next to ribosome profiling.
RIBOSOME_PROFILING = re.compile(r"ribosome profiling|ribo-?seq|footprint|\bRPFs?\b|monosome|ribosome[- ]protected", re.I)
SINGLE_CELL = {"Single-cell RNA-seq, droplet", "Single-cell RNA-seq, plate", "Single-cell RNA-seq, combinatorial", "Single-nucleus RNA-seq", "Spatial transcriptomics"}

BACKGROUND = re.compile(r"\bto date\b|\bpreviously\b|\bprevious (?:stud|work|method)|\bhas (?:involved|been)\b|\bhave been\b|\btraditional(?:ly)?\b|\bconventional(?:ly)?\b|\btypically\b|\bcommonly\b|\bexisting\b|\bin contrast to\b", re.I)
TIS, RIBO, RNA, SMALL = "TIS-seq (initiating ribosomes)", "Ribo-seq (elongating ribosomes)", "RNA-seq", "Small RNA-seq"
WORD = lambda words: re.compile(rf"(?<![A-Za-z])(?:{words})(?![A-Za-z])", re.I)
TIS_WORDS = WORD(r"harr|harringtonine|HAR|HHT|LTM|lactimidomycin|retapamulin|Ret|TIS|GTI|QTI|TI-?seq")
FOOT_WORDS = WORD(r"ribo|riboseq|ribo-?seq|RPFs?|RFP|RP|fp|footprints?|monosomes?|disomes?|trisomes?|TTS|TTS-?seq|StRP|80S|ribosome profiling")
INPUT_WORDS = WORD(r"IN|input")
CHX_WORDS = WORD(r"CHX|cycloheximide")
SMALL_WORDS = WORD(r"s(?:mall ?)?RNA(?:-?seq)?|miRNA(?:-?seq)?|ncRNA(?:-?seq)?")
RNA_WORDS = WORD(r"RNA|mRNA|TotRNA|total ?RNA|RNA-?seq|RNAseq|mRNA-?seq|poly-?A\+?")
OTHER_ASSAY = {"ATAC": "ATAC-seq", "CHIP": "ChIP-seq", "CLIP": "CLIP-seq (RNA-protein binding)", "CUT": "CUT&RUN / CUT&Tag", "CUTRUN": "CUT&RUN / CUT&Tag",
               "HIC": "Hi-C", "WGBS": "DNA methylation", "BISULFITE": "DNA methylation", "DNASEQ": "DNA sequencing", "WGS": "DNA sequencing", "WES": "DNA sequencing"}
OTHER_WORDS = WORD(r"ATAC|ChIP|CLIP|CUT&RUN|CUTRUN|Hi-?C|WGBS|bisulfite|DNA-?seq|WGS|WES")


def _library_word(text: str) -> tuple[str, str] | None:
    """The library a short label names: the earliest family word wins; a footprint library with an initiation word is TIS."""
    if m := OTHER_WORDS.search(text):
        return OTHER_ASSAY.get(m.group(0).upper().replace("-", "").split("&")[0], "Other assay"), m.group(0)
    rna = min((m for rx in (SMALL_WORDS, RNA_WORDS) if (m := rx.search(text))), key=lambda m: m.start(), default=None)
    foot = min((m for rx in (TIS_WORDS, FOOT_WORDS) if (m := rx.search(text))), key=lambda m: m.start(), default=None)
    if not foot and not rna and (chx := CHX_WORDS.search(text)):
        foot = chx
    if foot and (not rna or foot.start() < rna.start()):
        tis = TIS_WORDS.search(text)
        return (TIS, tis.group(0)) if tis else (RIBO, foot.group(0))
    if rna:
        return (SMALL, rna.group(0)) if SMALL_WORDS.search(text) else (RNA, rna.group(0))
    return None


SENTENCE = re.compile(r"(?<=[.;!?])\s+(?=[A-Za-z0-9(\[])")


ABBREVIATIONS = re.compile(r"\b(?:et al|e\.g|i\.e|Rev|Fig|Figs|approx|vs|No|Inc|Ltd|Co|cat|Cat|ca|resp|Suppl|Ref|Refs|Dr|Prof|St|min|max)\.", re.I)


def _sentences(text: str):
    protected = ABBREVIATIONS.sub(lambda m: m.group(0)[:-1] + "\u2024", re.sub(r"\s+", " ", text))
    for s in SENTENCE.split(protected):
        if s.strip():
            yield s.strip().replace("\u2024", ".")


def _match(sentence: str, study_text: str) -> list[tuple[str, str, str]]:
    found = []
    for assay, how, rx in COMPILED:
        if m := rx.search(sentence):
            if assay.startswith(("TIS", "Ribo-seq")) and how == "inferred" and not RIBOSOME_PROFILING.search(study_text):
                continue
            if assay == "Phosphoproteomics" and how == "inferred" and not re.search(r"phospho(?:peptide|proteom|site|rylat)", study_text, re.I):
                continue
            if assay.startswith("Targeted MS") and not re.search(r"mass spectrometr|\bMS\b|\bLC\b|transition|peptide|Skyline", sentence):
                continue
            if assay.startswith(("Data-independent", "Data-dependent", "Isobaric", "Label-free", "SILAC")) and (
                    BACKGROUND.search(sentence) or not re.search(r"acquired|operat|\bmode\b|\brun\b|analy[sz]ed|measured|performed|recorded|collected|labell?ed|quantif", sentence, re.I)):
                continue
            if assay.endswith("droplet") and re.search(r"Visium|Xenium|hexavalent|chromium (?:\(VI\)|contamin|reduc|metal)", sentence, re.I):
                continue
            found.append((assay, how, m.group(0)))
    return found


def _texts(rec: dict) -> list[tuple[str, list[str], str]]:
    """(field, samples, text) for every methods-bearing text of a dataset, each text once with every GEO sample that states it."""
    out = [(label, [], text) for label, text in rec["texts"]]
    out += [(label, [], v) for label, values in rec["facts"] if label in {"Instrument", "Instruments", "Quantification", "Experiment type", "Experiment types", "Platforms", "Study type", "Library strategy"} for v in values]
    if rec["source"] == "GEO":
        samples.geo_records(rec["accession"])
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


def _libraries(rec: dict, study: str) -> dict[str, dict]:
    """Which GEO sample is which library: its title decides; then its characteristics and description; then its own
    protocol, if not shared by the whole study; then the authors' 'library strategy:' line; else undetermined."""
    parsed = []
    for block in (samples.CACHE / f"{rec['accession']}.txt").read_text().split("^SAMPLE = ")[1:]:
        fields: dict[str, list[str]] = {}
        for line in block.splitlines()[1:]:
            key, _, value = line.partition(" = ")
            fields.setdefault(re.sub(r"^!Sample_|_ch\d$", "", key), []).append(value)
        stated = next((m.group(1).strip() for v in fields.get("data_processing", []) if (m := re.match(r"library strategy:\s*(.+)", v, re.I))), None)
        parsed.append({"gsm": block.split("\n", 1)[0].strip(), "title": (fields.get("title") or [""])[0], "stated": stated,
                       "strategy": (fields.get("library_strategy") or ["not stated"])[0],
                       "words": " ".join(fields.get("description", []) + fields.get("characteristics", [])),
                       "protocol": " ".join(fields.get("treatment_protocol", []) + fields.get("extract_protocol", []))})
    everyone = len({p["protocol"] for p in parsed}) == 1 and len(parsed) > 1
    own: dict[str, dict] = {}
    for p in parsed:
        kind, why = None, "undetermined: no library word in its title or characteristics, and its protocol is shared"
        if hit := _library_word(p["title"]):
            kind, why = hit[0], f"title: {hit[1]}"
        elif INPUT_WORDS.search(p["title"]):
            kind, why = None, "undetermined: an input library, which can be total RNA or ribosome input"
        elif hit := _library_word(p["words"]):
            kind, why = hit[0], f"characteristics: {hit[1]}"
        elif p["protocol"] and not everyone and len(calls := {a for a, h, _ in _match(p["protocol"], study) if a in (TIS, RIBO)}) == 1:
            kind = calls.pop()
            why = f"own protocol: {next(t for a, _, t in _match(p['protocol'], study) if a == kind)}"
        elif p["stated"] and (hit := _library_word(p["stated"])):
            kind, why = hit[0], f"authors' library strategy: {p['stated']}"
        own[p["gsm"]] = {"assay": kind, "why": why, "stated": p["stated"], "strategy": p["strategy"], "title": p["title"]}
    return own


SPLIT = re.compile(r"\b(?:split|divided|partitioned|aliquot\w*|a (?:sample|portion|fraction) (?:of the lysate )?was (?:taken|removed|saved|set aside)|in parallel)\b", re.I)
RNA_SEQ = re.compile(r"\b(?:total |poly\(?A\)?\+? |m)RNA[- ](?:seq|librar(?:y|ies)|sequencing)|\bRNA-?seq librar(?:y|ies)|\bmRNA-?seq\b", re.I)


@lru_cache(maxsize=256)
def _methods(paper: str) -> dict:
    return sources.paper_methods(paper)


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
    unassigned = []
    if rec["source"] == "GEO" and any(a in (TIS, RIBO) for a in found):
        libraries = _libraries(rec, study)
        kinds = list(dict.fromkeys(s["assay"] for s in libraries.values() if s["assay"]))
        for kind in kinds:
            members = [g for g, s in libraries.items() if s["assay"] == kind]
            entry = found.setdefault(kind, {"assay": kind, "how": "named", "terms": [], "evidence": []})
            if kind == RNA and not entry["evidence"]:
                entry["evidence"] = [{"text": sentence, "term": m.group(0), "field": field, "samples": sample_list, "how": "named"}
                                     for field, sample_list, text in texts for sentence in _sentences(text) if (m := RNA_SEQ.search(sentence))][:2]
            own = [e for e in entry["evidence"] if not e["samples"] or set(e["samples"]) & set(members)]
            entry["evidence"] = [e for e in own if not e["samples"] or set(e["samples"]) <= set(members) or len(e["samples"]) == len(libraries)] or own
            entry["samples"] = members
            entry["stated"] = dict(Counter(libraries[g]["stated"] for g in members if libraries[g]["stated"]))
            entry["strategy"] = dict(Counter(libraries[g]["strategy"] for g in members))
            entry["library_rows"] = [{"sample": g, "title": libraries[g]["title"], "why": libraries[g]["why"]} for g in members]
            entry["mislabelled"] = sum(1 for g in members if libraries[g]["stated"] and not libraries[g]["why"].startswith("authors")
                                       and (named := _library_word(libraries[g]["stated"])) and named[0] != kind)
        unassigned = [{"sample": g, "title": s["title"], "why": s["why"]} for g, s in libraries.items() if s["assay"] is None]
        found = {a: e for a, e in found.items() if a not in (TIS, RIBO, RNA, SMALL) or e.get("samples")}
    split = None
    if {"RNA-seq"} & set(found) and any(a.startswith(("Ribo-seq", "TIS-seq")) for a in found):
        paper = next((p["id"] for p in rec["papers"] if p.get("id") and p["id"] != "pmid:1"), None)
        where = texts + ([(f"Paper methods: {p['section']}", [], p["text"]) for p in _methods(paper).get("paragraphs", [])] if paper else [])
        split = next(({"text": sentence, "field": field, "samples": sample_list} for field, sample_list, text in where for sentence in _sentences(text)
                      if SPLIT.search(sentence) and re.search(r"lysate|extract|RNA|librar|sample", sentence, re.I)), None)
    for entry in found.values():
        entry["evidence"] = [e for e in entry["evidence"] if not split or e["text"] != split["text"]] or entry["evidence"]
        ranked = sorted(entry["evidence"], key=lambda e: "protocol" not in e["field"].lower())
        picks = [next((e for e in ranked if e.get("how") == how), None) for how in ("named", "inferred")]
        entry["evidence"] = [e for e in picks if e] or ranked[:2]
        entry.setdefault("mislabelled", 0)
    out = {
        "accession": accession,
        "source": rec["source"],
        "assays": [e for e in found.values() if e["evidence"] or e.get("samples")],
        "unassigned_samples": unassigned,
        "split": split,
        "read_from": sorted({f for f, _, _ in texts}),
    }
    if any(a["assay"] in (RIBO, TIS) and a.get("library_rows") for a in out["assays"]) and any(a["assay"] == RNA for a in out["assays"]):
        out["matched"] = pairs(out)
    return out


def _pair_key(title: str) -> str:
    """A title without its library words and lab prefix: the biological sample a library was made from."""
    t = title.split(":")[-1]
    for rx in (TIS_WORDS, FOOT_WORDS, CHX_WORDS, SMALL_WORDS, RNA_WORDS):
        t = rx.sub(" ", t)
    t = re.sub(r"(?<![A-Za-z])(?:seq|library|libraries|reseq|lib)(?![A-Za-z])", " ", t, flags=re.I)
    return " ".join(re.findall(r"[a-z0-9]+", t.lower()))


TOP_UP = re.compile(r"(?<![A-Za-z])(?:re-?seq|top-?up|re-?run|resequenc\w*)(?![A-Za-z])", re.I)


def pairs(result: dict) -> dict:
    """Footprint and RNA-seq libraries of the same biological sample, matched by title: one elongating (else
    initiating) footprint library and one RNA-seq library per key; a TIS library of the same key rides along.
    Re-sequencing top-ups and keys shared by two libraries of one kind stay out of pairs."""
    rows = {a["assay"]: a.get("library_rows", []) for a in result["assays"]}
    by_key: dict[str, dict[str, list]] = {}
    top_ups = []
    for kind in (RIBO, TIS, RNA):
        for r in rows.get(kind, []):
            if TOP_UP.search(r["title"]):
                top_ups.append({**r, "assay": kind})
                continue
            by_key.setdefault(_pair_key(r["title"]), {RIBO: [], TIS: [], RNA: []})[kind].append({**r, "assay": kind})
    matched, paired = [], set()
    for key, v in by_key.items():
        foot = v[RIBO] if v[RIBO] else v[TIS]
        if key and len(foot) == 1 and len(v[RNA]) == 1:
            pair = {"key": key, "footprint": foot[0], "rna": v[RNA][0]}
            if v[RIBO] and len(v[TIS]) == 1:
                pair["tis"] = v[TIS][0]
            matched.append(pair)
            paired |= {foot[0]["sample"], v[RNA][0]["sample"], *([pair["tis"]["sample"]] if "tis" in pair else [])}
    unpaired = [r for v in by_key.values() for kind in (RIBO, TIS, RNA) for r in v[kind] if r["sample"] not in paired]
    return {"pairs": sorted(matched, key=lambda m: m["key"]), "unpaired": unpaired, "top_ups": top_ups}


def library_types(accession: str) -> tuple[dict[str, str], str]:
    """Each GEO sample's library type where its own title, characteristics or protocol shows it (studies with ribosome
    footprints only), and the sentence that shows initiating ribosomes, if any."""
    result = classify(accession) or {"assays": []}
    types = {r["sample"]: a["assay"] for a in result["assays"] for r in a.get("library_rows", []) if r["why"].startswith(("title", "characteristics", "own protocol"))}
    tis = next((a["evidence"][0]["text"] for a in result["assays"] if a["assay"].startswith("TIS-seq") and a["evidence"]), "")
    return types, tis


def _title_invariant() -> tuple[int, list[str]]:
    """Across every cached GEO series with footprint libraries: a title with only footprint words is never RNA-seq, and
    a title with only RNA words is never Ribo-seq or TIS-seq."""
    checked, wrong = 0, []
    for path in samples.CACHE.glob("GSE*.txt"):
        text = path.read_text(errors="replace")
        if not RIBOSOME_PROFILING.search(text):
            continue
        for title in re.findall(r"^!Sample_title = (.*)$", text, re.M):
            foot, rna = bool(FOOT_WORDS.search(title) or TIS_WORDS.search(title)), bool(RNA_WORDS.search(title) or SMALL_WORDS.search(title))
            if foot == rna or OTHER_WORDS.search(title):
                continue
            checked += 1
            kind = (_library_word(title) or ("",))[0]
            if foot and kind not in (TIS, RIBO) or rna and kind not in (RNA, SMALL):
                wrong.append(f"{path.stem}: {title} -> {kind}")
    return checked, wrong


if __name__ == "__main__":
    checked, wrong = _title_invariant()
    assert not wrong, wrong[:10]
    def assays(acc: str) -> dict[str, dict]:
        return {a["assay"]: a for a in classify(acc)["assays"]}

    def counts(acc: str) -> dict[str, int]:
        return {k: len(v.get("samples", [])) for k, v in assays(acc).items()}

    assert counts("GSE36892") == {RIBO: 8, RNA: 4}
    assert counts("GSE157490") == {TIS: 30, RIBO: 36, RNA: 48, SMALL: 13}, counts("GSE157490")
    assert counts("GSE286083") == {TIS: 4, RIBO: 4, RNA: 4}, counts("GSE286083")
    assert counts("GSE299222") == {RNA: 8}, counts("GSE299222")
    assert assays("GSE80133")[RIBO]["mislabelled"] == 0, "GEO's forced library strategy is not the authors' label"
    neurons = assays("GSE255191")
    assert counts("GSE255191") == {TIS: 2, RIBO: 2} and neurons[TIS]["mislabelled"] == 2 and "harringtonine" in neurons[TIS]["evidence"][0]["text"]
    assert set(assays("GSE150375")) == {TIS}
    for drug in ("GSE182020", "GSE296679"):
        assert not {RIBO, TIS} & set(assays(drug)), drug
    assert "split in two" in classify("GSE132703")["split"]["text"]
    assert "partitioned" in classify("GSE36892")["split"]["text"], "the split sentence comes from the paper's methods"
    assert "Single-cell RNA-seq, plate" in assays("GSE86618") and "Single-cell RNA-seq, droplet" in assays("E-MTAB-6149")
    assert "W6/32" in assays("PXD010450")["Immunopeptidomics (HLA/MHC ligands)"]["terms"]
    assert "Organelle IP" in assays("PXD062418") and "Phosphoproteomics" in assays("PXD047213")
    assert "16S rRNA amplicon" in assays("PRJEB39707")
    assert "Ubiquitylomics" not in assays("PXD051023"), "KEGG is not K-ε-GG"
    assert not assays("PRJNA528752"), "hexavalent chromium is not 10x Chromium"
    assert "Single-cell RNA-seq, droplet" not in assays("GSE300303") and "Phosphoproteomics" not in assays("PXD040914")
    assert "Expression microarray" in assays("GSE14346")
    for acc, expected in {"GSE154992": {RIBO: 9, RNA: 9}, "GSE125218": {RIBO: 16, TIS: 9, RNA: 8}, "GSE143311": {RIBO: 2, TIS: 2, RNA: 2},
                          "GSE125038": {RIBO: 28, RNA: 28}, "GSE169632": {RIBO: 14, RNA: 28, "ATAC-seq": 8}}.items():
        assert {k: v for k, v in counts(acc).items() if v} == expected, (acc, counts(acc))
    assert assays("GSE154992")[RIBO]["mislabelled"] == 0, "the authors' own Ribo-Seq line agrees with the title"
    assert "ChIP-seq" not in assays("GSE25958") and not any(a.startswith("Targeted") for a in assays("PRJNA1013390"))
    assert "Data-dependent acquisition (DDA)" not in assays("PXD066697") and "Phosphoproteomics" not in assays("PXD012401")
    assert "Single-cell RNA-seq, plate" not in assays("GSE276671")
    mtor = classify("GSE36892")["matched"]
    assert len(mtor["pairs"]) == 4 and len(mtor["unpaired"]) == 4, (len(mtor["pairs"]), [u["title"] for u in mtor["unpaired"]])
    larp = classify("GSE132703")["matched"]
    assert len(larp["pairs"]) == 12 and not larp["unpaired"] and len(larp["top_ups"]) == 4, (len(larp["pairs"]), larp["unpaired"])
    print(f"assay self-check passed; title rule held on {checked} footprint-study titles")
