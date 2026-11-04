#!/usr/bin/env python
"""P-sites, metagene and footprint-length figures, and CDS counts from transcriptome BAMs (laptop Ribo-seq tier).

Runs inside the omics-ribo environment (pysam, numpy, matplotlib), as a subprocess of omics_agent.riboseq and as the
same file in the laptop kit. Two subcommands, each taking GSM=path.bam arguments:

  riboseq_psite.py psite --cds cds.tsv --out DIR GSM=ribo.bam ...
      For each Ribo-seq library: the read-length distribution; per read length (25–35 nt by default) the P-site offset:
      the mode of the distance from 5′ ends to the start codon over reads whose 5′ ends lie within 30 nt upstream of it
      (the most abundant length's offset when fewer than 200 such reads or when more than 3 nt away from it), then
      corrected to the nearest value that puts the length's dominant in-CDS frame in frame 0, as riboWaltz corrects its
      temporary offsets; P-site = 5′ end + offset. Metagene coverage of P-sites from −30 to +60 nt
      around the start codon and −60 to +30 around the stop codon by frame, pooled over transcripts; the periodicity
      (share of in-frame P-sites within CDSs). Writes DIR/counts/<GSM>.count (P-sites per CDS, first 15 and last 5
      codons excluded), DIR/psite_summary.json, DIR/footprint_lengths.png/.pdf and DIR/metagene.png/.pdf.
  riboseq_psite.py count --cds cds.tsv --out DIR GSM=rna.bam ...
      For each RNA-seq library: reads whose alignment start falls inside the CDS, per gene, to DIR/counts/<GSM>.count.

cds.tsv is the reference's table (transcript, gene_id, gene_name, gene, cds_start, cds_end, length; 1-based, inclusive,
stop codon included). Only primary, forward-strand alignments with MAPQ >= 10 count.
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

MIN_MAPQ = 10
ANCHOR_WINDOW = 3
START_WINDOW = (-30, 60)
STOP_WINDOW = (-60, 30)
FRAME_COLOURS = ["#2a78d6", "#eb6834", "#2e9e6b"]
INK, MUTED = "#0b0b0b", "#52514e"


def psite_offset(distances, fallback=12, minimum=200):
    """The same rule as omics_agent.riboseq.psite_offset (copied so this file runs alone in the kit)."""
    counts = Counter(d for d in distances if 1 <= d <= 30)
    n = sum(counts.values())
    if n < minimum:
        return fallback, n, True
    return max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0], n, False


def corrected_offset(temporary, frames, minimum_share=0.4):
    """The same rule as omics_agent.riboseq.corrected_offset (copied so this file runs alone in the kit)."""
    total = sum(frames)
    if not total:
        return temporary, False
    dominant = max(range(3), key=lambda f: (frames[f], -f))
    if frames[dominant] / total < minimum_share:
        return temporary, False
    for shift in (0, 1, -1, 2, -2):
        if (dominant + temporary + shift) % 3 == 0:
            return temporary + shift, shift != 0
    return temporary, False


def read_cds(path):
    """transcript -> (gene, cds_start0, cds_end_exclusive) from cds.tsv."""
    cds = {}
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            cds[row["transcript"]] = (row["gene"], int(row["cds_start"]) - 1, int(row["cds_end"]))
    return cds


def alignments(bam):
    """(transcript, five_prime_0based, aligned_length) for every usable read."""
    import pysam

    with pysam.AlignmentFile(bam, "rb") as handle:
        for read in handle.fetch(until_eof=True):
            if read.is_unmapped or read.is_secondary or read.is_supplementary or read.is_reverse or read.mapping_quality < MIN_MAPQ:
                continue
            yield read.reference_name, read.reference_start, read.query_alignment_length


def psite_library(bam, cds, min_length, max_length):
    """Two passes over one Ribo-seq BAM: offsets per read length, then P-sites, metagene, periodicity and CDS counts."""
    lengths = Counter()
    start_distance = defaultdict(Counter)
    cds_frames = defaultdict(lambda: [0, 0, 0])
    for tx, five, length in alignments(bam):
        lengths[length] += 1
        if min_length <= length <= max_length and tx in cds:
            gene, cds_start, cds_end = cds[tx]
            d = cds_start - five
            if 1 <= d <= min(30, length - 1):
                start_distance[length][d] += 1
            if cds_start + 45 <= five < cds_end - 60:
                cds_frames[length][(five - cds_start) % 3] += 1
    # Temporary offsets from the start codon; lengths with too few reads there take the most abundant length's offset
    # (12 when that one is short too); then each is corrected by the frame its reads hold inside CDSs.
    temporary, offset_reads, fallbacks, corrected = {}, {}, [], []
    for length in range(min_length, max_length + 1):
        temporary[length], offset_reads[length], used_fallback = psite_offset(start_distance[length].elements())
        if used_fallback:
            fallbacks.append(length)
    abundant = max(range(min_length, max_length + 1), key=lambda L: lengths.get(L, 0))
    reference_offset = temporary[abundant] if abundant not in fallbacks else 12
    offsets, anchored = {}, []
    for length in range(min_length, max_length + 1):
        base = temporary[length]
        # A temporary offset far from the most abundant length's is noise from a thin start-codon window (riboWaltz
        # pulls such offsets toward the reference length's too); P-site offsets of one library differ by a few nt at most.
        if length in fallbacks or abs(base - reference_offset) > ANCHOR_WINDOW:
            if length not in fallbacks:
                anchored.append(length)
            base = reference_offset
        offsets[length], was_corrected = corrected_offset(base, tuple(cds_frames[length]))
        if was_corrected:
            corrected.append(length)

    start = [[0] * (START_WINDOW[1] - START_WINDOW[0] + 1) for _ in range(3)]
    stop = [[0] * (STOP_WINDOW[1] - STOP_WINDOW[0] + 1) for _ in range(3)]
    frames = [0, 0, 0]
    counts = Counter()
    psites = 0
    for tx, five, length in alignments(bam):
        if not (min_length <= length <= max_length) or tx not in cds:
            continue
        gene, cds_start, cds_end = cds[tx]
        p = five + offsets[length]
        psites += 1
        rel = p - cds_start
        frame = rel % 3
        if START_WINDOW[0] <= rel <= START_WINDOW[1]:
            start[frame][rel - START_WINDOW[0]] += 1
        rel_stop = p - (cds_end - 3)
        if STOP_WINDOW[0] <= rel_stop <= STOP_WINDOW[1]:
            stop[frame][rel_stop - STOP_WINDOW[0]] += 1
        if cds_start <= p < cds_end:
            frames[frame] += 1
            if cds_start + 45 <= p < cds_end - 15:
                counts[gene] += 1
    in_cds = sum(frames)
    total = sum(lengths.values())
    return {
        "reads": total, "reads_in_range": sum(n for L, n in lengths.items() if min_length <= L <= max_length), "psites": psites, "psites_in_cds": in_cds,
        "modal_length": lengths.most_common(1)[0][0] if lengths else None, "lengths": {str(k): v for k, v in sorted(lengths.items())},
        "offsets": {str(k): v for k, v in offsets.items()}, "temporary_offsets": {str(k): v for k, v in temporary.items()},
        "offset_reads": {str(k): v for k, v in offset_reads.items()}, "offset_fallback_lengths": fallbacks, "offset_anchored_lengths": anchored, "offset_corrected_lengths": corrected,
        "cds_frames_by_length": {str(k): v for k, v in sorted(cds_frames.items())},
        "periodicity": round(frames[0] / in_cds, 4) if in_cds else None, "frames": frames,
        "metagene": {"start": start, "stop": stop},
    }, counts


def count_rna_library(bam, cds):
    """Reads whose alignment start falls inside the CDS, per gene."""
    counts = Counter()
    n = 0
    for tx, five, _ in alignments(bam):
        if tx in cds:
            gene, cds_start, cds_end = cds[tx]
            n += 1
            if cds_start <= five < cds_end:
                counts[gene] += 1
    return counts, n


def write_count(counts, genes, path):
    with open(path, "w") as handle:
        for gene in genes:
            handle.write(f"{gene}\t{counts.get(gene, 0)}\n")


# ---------------------------------------------------------------- figures

def _style(ax, title=None):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_linewidth(0.4)
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=7, width=0.4, length=2.5)
    if title:
        ax.set_title(title, fontsize=8, loc="left", color=INK)


def save(fig, out, name):
    fig.savefig(out / f"{name}.png", dpi=300, facecolor="white")
    fig.savefig(out / f"{name}.pdf", facecolor="white")


def footprint_figure(libraries, out, min_length, max_length):
    """One panel per library: share of reads at each length (15–45 nt), the 25–35 window shaded, the modal length named."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(libraries)
    cols = min(4, n)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(2.2 * cols + 0.4, 1.9 * rows + 0.6), squeeze=False, sharey=True)
    for ax, (gsm, lib) in zip(axes.flat, libraries.items()):
        total = max(lib["reads"], 1)
        xs = list(range(15, 46))
        ys = [100 * lib["lengths"].get(str(x), 0) / total for x in xs]
        ax.axvspan(min_length - 0.5, max_length + 0.5, color="#eef2f7", lw=0, zorder=0)
        ax.bar(xs, ys, width=0.8, color=FRAME_COLOURS[0], lw=0)
        _style(ax, f"{gsm}")
        ax.text(0.98, 0.95, f"mode {lib['modal_length']} nt\n{lib['reads']:,} reads", transform=ax.transAxes, ha="right", va="top", fontsize=6.5, color=MUTED)
        ax.set_xlabel("read length (nt)", fontsize=7, color=INK)
    for ax in axes.flat[n:]:
        ax.axis("off")
    for ax in axes[:, 0]:
        ax.set_ylabel("% of reads", fontsize=7, color=INK)
    fig.suptitle(f"Footprint lengths after trimming (shaded: {min_length}–{max_length} nt used for P-sites)", fontsize=8.5, x=0.01, ha="left", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    save(fig, out, "footprint_lengths")
    plt.close(fig)


def metagene_figure(libraries, out):
    """Start and stop panels of pooled P-site counts by frame, with each library's periodicity written on the panel."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 2.8))
    for ax, key, window, label in ((axes[0], "start", START_WINDOW, "start codon"), (axes[1], "stop", STOP_WINDOW, "stop codon")):
        pooled = [[0] * (window[1] - window[0] + 1) for _ in range(3)]
        for lib in libraries.values():
            for f in range(3):
                for i, v in enumerate(lib["metagene"][key][f]):
                    pooled[f][i] += v
        xs = list(range(window[0], window[1] + 1))
        for f in range(3):
            # A position's frame is its distance from the start codon mod 3 (CDS lengths are whole codons, so the same holds at the stop).
            ax.bar([x for x in xs if x % 3 == f], [pooled[f][x - window[0]] for x in xs if x % 3 == f], width=0.85, color=FRAME_COLOURS[f], lw=0, label=f"frame {f}")
        ax.axvline(0, color=MUTED, lw=0.5, ls=(0, (2, 2)))
        _style(ax, f"P-sites around the {label} (0 = first nt of the codon)")
        ax.set_xlabel(f"nt from the {label}", fontsize=7, color=INK)
        ax.set_ylabel("P-sites, pooled", fontsize=7, color=INK)
        ax.set_xlim(window[0] - 1, window[1] + 1)
    axes[0].legend(fontsize=6.5, frameon=False, loc="upper right")
    text = "\n".join(f"{gsm}: {lib['periodicity']:.2f}" if lib["periodicity"] is not None else f"{gsm}: n/a" for gsm, lib in libraries.items())
    axes[1].text(0.98, 0.97, "in-frame share\n" + text, transform=axes[1].transAxes, ha="right", va="top", fontsize=6, color=MUTED, linespacing=1.3)
    fig.tight_layout()
    save(fig, out, "metagene")
    plt.close(fig)


# ---------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["psite", "count"])
    parser.add_argument("--cds", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-length", type=int, default=25)
    parser.add_argument("--max-length", type=int, default=35)
    parser.add_argument("libraries", nargs="+", help="GSM=path.bam")
    args = parser.parse_args(argv)
    out = Path(args.out)
    (out / "counts").mkdir(parents=True, exist_ok=True)
    cds = read_cds(args.cds)
    genes = sorted({g for g, _, _ in cds.values()})
    libs = dict(item.split("=", 1) for item in args.libraries)

    if args.mode == "count":
        done = {}
        for gsm, bam in libs.items():
            counts, n = count_rna_library(bam, cds)
            write_count(counts, genes, out / "counts" / f"{gsm}.count")
            done[gsm] = {"aligned_reads": n, "counted": sum(counts.values())}
            print(f"{gsm}: {sum(counts.values()):,} of {n:,} aligned reads start inside a CDS", flush=True)
        (out / "rna_count_summary.json").write_text(json.dumps(done, indent=2) + "\n")
        return

    import matplotlib
    import pysam

    summary = {"libraries": {}, "rule": f"offset = mode of 5′-end-to-start distance per length {args.min_length}–{args.max_length}, 12 when < 200 reads; MAPQ >= {MIN_MAPQ}",
               "versions": {"pysam": pysam.__version__, "matplotlib": matplotlib.__version__, "python": sys.version.split()[0]}}
    for gsm, bam in libs.items():
        lib, counts = psite_library(bam, cds, args.min_length, args.max_length)
        write_count(counts, genes, out / "counts" / f"{gsm}.count")
        summary["libraries"][gsm] = lib
        print(f"{gsm}: {lib['reads']:,} reads, modal length {lib['modal_length']}, periodicity {lib['periodicity']}, offsets {lib['offsets']}, "
              f"fallback for lengths {lib['offset_fallback_lengths'] or 'none'}, anchored for {lib['offset_anchored_lengths'] or 'none'}, frame-corrected for {lib['offset_corrected_lengths'] or 'none'}, "
              f"{sum(counts.values()):,} P-sites counted in CDSs", flush=True)
    (out / "psite_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    footprint_figure(summary["libraries"], out, args.min_length, args.max_length)
    metagene_figure(summary["libraries"], out)


if __name__ == "__main__":
    main()
