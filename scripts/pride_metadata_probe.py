#!/usr/bin/env python3
"""Probe PRIDE for sample-level metadata availability.

Evidence script behind docs/metadata-informed-analysis-plans.md. It asks the
PRIDE Archive REST API (v3) for N projects, reports which project-level fields
are populated, and counts how many projects ship an SDRF file (the per-file
sample -> condition -> replicate table that quantms/MaxQuant-style reanalysis
needs). Read-only; no downloads of raw data.

Usage:
    python3 -I scripts/pride_metadata_probe.py --projects 120 --files-for 120
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
import urllib.request

BASE = "https://www.ebi.ac.uk/pride/ws/archive/v3"
PROJECT_FIELDS = [
    "sampleProcessingProtocol", "dataProcessingProtocol", "organisms",
    "organismParts", "diseases", "instruments", "quantificationMethods",
    "softwares", "experimentTypes", "references", "keywords", "sampleAttributes",
]


def get(url: str):
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "omics-agent-probe"}
    )
    with urllib.request.urlopen(req, timeout=60) as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", type=int, default=120)
    ap.add_argument("--files-for", type=int, default=120,
                    help="how many of the projects to check for SDRF files")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    projects: list[dict] = []
    page = 0
    while len(projects) < args.projects:
        batch = get(f"{BASE}/projects?pageSize=100&page={page}")
        if not isinstance(batch, list) or not batch:
            break
        projects += batch
        page += 1
    projects = projects[: args.projects]

    populated = collections.Counter()
    for p in projects:
        for f in PROJECT_FIELDS:
            v = p.get(f)
            if v and (not isinstance(v, (list, str)) or len(v) > 0):
                populated[f] += 1

    sdrf = checked = 0
    by_type = collections.Counter()
    by_type_sdrf = collections.Counter()
    for p in projects[: args.files_for]:
        try:
            files = get(f"{BASE}/projects/{p['accession']}/files?pageSize=1000")
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"skip {p['accession']}: {exc}", file=sys.stderr)
            continue
        checked += 1
        names = [f.get("fileName", "").lower() for f in files] if isinstance(files, list) else []
        has = any("sdrf" in n for n in names)
        sdrf += has
        t = ";".join(sorted(e.get("name", "") for e in p.get("experimentTypes", [])))
        by_type[t] += 1
        by_type_sdrf[t] += has
        time.sleep(0.15)

    out = {
        "projects": len(projects),
        "populated_project_fields": {f: populated[f] for f in PROJECT_FIELDS},
        "files_checked": checked,
        "with_sdrf": sdrf,
        "sdrf_by_experiment_type": {t: [by_type_sdrf[t], n] for t, n in by_type.most_common()},
    }
    if args.json:
        print(json.dumps(out, indent=1))
        return 0
    print(f"projects fetched: {len(projects)}")
    for f in PROJECT_FIELDS:
        print(f"  {f:28s} {populated[f]:4d} ({100 * populated[f] / max(len(projects), 1):.0f}%)")
    print(f"SDRF present: {sdrf}/{checked}")
    for t, n in by_type.most_common(8):
        print(f"  {t[:40]:40s} n={n:3d} sdrf={by_type_sdrf[t]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
