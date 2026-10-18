"""Every page feature has an MCP tool that returns the same fact the page shows. Calls each tool on a real dataset and
checks the fact; prints one line per feature. Run: uv run python scripts/mcp_parity.py"""

from dotenv import load_dotenv

load_dotenv()

from omics_agent import mcp_server as m  # noqa: E402

CHECKS = [
    ("cases, controls and people on the sample table", lambda: m.filter_samples("GSE86618", {}),
     lambda r: r["comparison"]["case"] == ["IPF"] and r["people"]["total"] == 9),
    ("filter samples by a value", lambda: m.filter_samples("GSE173357", {"diagnosis": ["ipf"], "Sex": ["female"]}), lambda r: r["samples"] == 8),
    ("protein table inside a PRIDE zip, samples it names", lambda: m.preview_file("PXD047213", "txt-3.zip"),
     lambda r: r["member"]["path"].endswith("proteinGroups.txt") and len(r["experiments"]["names"]) == 36),
    ("Metabolomics Workbench mwTab with groups", lambda: m.preview_file("ST003390", "AN005559_mwtab.txt"), lambda r: r["samples"]["matched"] == 300),
    ("paper page", lambda: m.get_paper("32094190"), lambda r: any(d["accession"] == "GSE132703" for d in r["datasets"])),
    ("paste an identifier", lambda: m.resolve_id("PXD010450"), lambda r: r.get("path", "").endswith("PXD010450")),
    ("informal citation", lambda: m.find_cited_paper("Philippe 2020 PNAS LARP1"), lambda r: r["datasets"][0]["accession"] == "GSE132703"),
    ("why it matched", lambda: m.why_matched("GSE132703", ["mTOR inhibition"]), lambda r: bool(r)),
    ("assays from the paper's methods (MS)", lambda: m.classify_assays("PXD058312"), lambda r: any(a["assay"] == "Organelle IP" for a in r["assays"])),
    ("TIS-seq read from the methods", lambda: m.classify_assays("GSE255191"), lambda r: any(a["assay"].startswith("TIS") for a in r["assays"])),
    ("matched libraries and the split sentence", lambda: m.classify_assays("GSE132703"), lambda r: bool(r.get("matched")) and "split" in (r.get("split") or {}).get("text", "")),
    ("Ribo-seq QC checks", lambda: m.sample_qc("GSE132703"), lambda r: [c["stated"] for c in r["criteria"]["checklist"]].count(False) == 2),
    ("design check, power in people", lambda: m.check_design("GSE86618"), lambda r: r["power"]["unit"] == "people"),
    ("MetaboLights samples, cases and controls", lambda: m.filter_samples("MTBLS352", {}), lambda r: r["comparison"]["case"] == ["T2D patients"] and r["samples"] == 730),
    ("first look on a MetaboLights MAF", lambda: m.first_look("MTBLS8644", top=2), lambda r: r["feature"] == "metabolite" and r["tested"] > 100),
    ("get the table (metabolites)", lambda: m.get_table("ST003390"), lambda r: r.get("available")),
    ("first look with pathways", lambda: m.first_look("GSE124685", pathways=True, top=5), lambda r: r["pathways"]["sides"]["up"]["terms"][0]["term"].startswith("Extracellular")),
    ("first look on metabolites", lambda: m.first_look("ST003390", top=3), lambda r: r["feature"] == "metabolite" and r["up"] >= 1),
    ("one gene everywhere", lambda: m.gene_everywhere("SPP1", ["GSE124685", "GSE150910"], "ipf"), lambda r: r["higher"] == 2),
    ("your list, in one dataset and across", lambda: m.check_list("COL1A1 COL3A1 MMP7 SPP1 ACTB", "GSE124685", ["GSE124685", "GSE150910"], "ipf"),
     lambda r: r["dataset"]["coloured"] >= 3 and r["across"]["compared"] == 2),
    ("doors become pages (browse by a value)", lambda: m.browse_datasets("keywords", "Immunopeptidome"), lambda r: r["total"] > 100),
    ("contributor page", lambda: m.get_person("Carson C Thoreen"), lambda r: r["counts"]["datasets"] >= 5),
    ("provenance: the requests a record was read from", lambda: m.list_files("GSE132703"), lambda r: len(r["read_from"]) >= 4),
    ("the answer and watching a search", lambda: m.search_datasets("Plasma metabolomics in type 2 diabetes against healthy controls", seen=["ST003390"]),
     lambda r: r["answer"][0]["kind"] == "cohort" and "ST003390" not in r["new"] and len(r["new"]) == len(r["datasets"]) - 1),
]

failed = 0
for name, call, holds in CHECKS:
    try:
        ok = bool(holds(call()))
    except Exception as error:  # a broken tool is a failed check, reported, not a crash
        ok, name = False, f"{name} ({type(error).__name__}: {str(error)[:80]})"
    failed += not ok
    print(("PASS " if ok else "FAIL ") + name, flush=True)
print(f"{len(CHECKS) - failed} of {len(CHECKS)} features return the page's fact through MCP")
raise SystemExit(1 if failed else 0)
