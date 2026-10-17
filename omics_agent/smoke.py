import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

QUESTIONS = [
    "Arabidopsis root transcriptome under drought stress compared with well-watered plants",
    "Mouse hippocampus RNA-seq from a gene knockout compared with wild type",
    "Time course of Staphylococcus aureus gene expression during infection",
    "Proteomics of human breast cancer tumour tissue versus normal breast tissue",
    "ATAC-seq of human T cells after activation",
    "Single-cell atlas of the human kidney",
    "DNA methylation changes with age in human blood",
    "Matched RNA-seq and Ribo-seq of cells treated with an mTOR inhibitor",
    "Zebrafish heart regeneration after injury, bulk RNA-seq",
    "Gut microbiome metatranscriptomics in inflammatory bowel disease",
]


def check(question: str) -> dict:
    from . import agent

    started = time.time()
    result = agent.run(question)
    strong = [d for d in result["datasets"] if d["fit"] == "strong"]
    return {
        "question": question,
        "seconds": round(time.time() - started),
        "assays": result["plan"]["assays"],
        "repositories": result["plan"]["repositories"],
        "notes": result["plan"]["method_notes"],
        "candidates": result["candidates"],
        "strong": len(strong),
        "partial": len(result["datasets"]) - len(strong),
        "top": [f"{d['accession']} | {(d['facts'] or {}).get('assays') or d['modality'][:40]} | {d['title'][:70]}" for d in strong[:3]],
    }


if __name__ == "__main__":
    load_dotenv()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for report in pool.map(check, QUESTIONS):
            print(json.dumps(report, indent=1), flush=True)
