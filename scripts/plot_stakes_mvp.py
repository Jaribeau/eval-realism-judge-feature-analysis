"""
Visualize the stakes-MVP pilot results: per-contrast win rates (with Wilson 95% CIs)
and per-variant transcript-level win rate spread.

Variant id is parsed from the sample filename prefix:
    1_*  →  B   (baseline)
    2_*  →  A1  (low-stakes)
    3_*  →  A2  (single-pretext baseline)
    4_*  →  A3  (low-stakes + single-pretext)

Usage:
    uv run python scripts/plot_stakes_mvp.py judge-results/<timestamp>--<suffix>.jsonl
    uv run python scripts/plot_stakes_mvp.py judge-results/<timestamp>--<suffix>.jsonl --out docs/notes/stakes-mvp.png
"""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

VARIANT_ID = {"1": "B", "2": "A1", "3": "A2", "4": "A3"}
VARIANT_LABEL = {
    "B":  "B\nbaseline",
    "A1": "A1\nlow-stakes",
    "A2": "A2\nsingle-pretext",
    "A3": "A3\nlow + single",
}
VARIANT_COLOR = {"B": "#444", "A1": "#1f77b4", "A2": "#2ca02c", "A3": "#d62728"}

# Headline contrasts: ablated variant first, baseline second.
CONTRASTS = [
    ("A1", "B",  "A1 vs B\n(stakes)"),
    ("A2", "B",  "A2 vs B\n(pretext)"),
    ("A3", "B",  "A3 vs B\n(both)"),
    ("A3", "A2", "A3 vs A2\n(stakes only)"),
    ("B",  "B",  "B vs B\n(null)"),
    ("A1", "A1", "A1 vs A1\n(null)"),
]


def variant_of(path: str) -> str | None:
    name = Path(path).name
    return VARIANT_ID.get(name.split("_", 1)[0])


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    halfwidth = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, center - halfwidth), min(1.0, center + halfwidth))


def aggregate_contrasts(rows: list[dict]) -> dict[tuple[str, str], tuple[int, int]]:
    """For each (variant_x, variant_y) pair, count how often x beat y.

    For same-variant pairs (e.g. B vs B), the contrast's win rate is simply the
    fraction of A-side wins — a position-bias / homogeneity null check (≈0.5).
    """
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])  # [x_wins, total]
    for r in rows:
        va = variant_of(r["file_a"])
        vb = variant_of(r["file_b"])
        if va is None or vb is None:
            continue
        winner = r["winner"]
        if va == vb:
            counts[(va, vb)][1] += 1
            if winner == "A":
                counts[(va, vb)][0] += 1
        else:
            counts[(va, vb)][1] += 1
            counts[(vb, va)][1] += 1
            if winner == "A":
                counts[(va, vb)][0] += 1
            else:
                counts[(vb, va)][0] += 1
    return {k: (v[0], v[1]) for k, v in counts.items()}


def per_transcript_winrate(rows: list[dict]) -> dict[str, list[float]]:
    """Win rate of each transcript against all other transcripts, grouped by variant."""
    wins: dict[str, int] = defaultdict(int)
    n: dict[str, int] = defaultdict(int)
    for r in rows:
        a = Path(r["file_a"]).name
        b = Path(r["file_b"]).name
        n[a] += 1
        n[b] += 1
        if r["winner"] == "A":
            wins[a] += 1
        else:
            wins[b] += 1
    by_variant: dict[str, list[float]] = defaultdict(list)
    for name, total in n.items():
        v = VARIANT_ID.get(name.split("_", 1)[0])
        if v is None or total == 0:
            continue
        by_variant[v].append(wins[name] / total)
    return by_variant


def plot(rows: list[dict], out: Path, title_suffix: str = "") -> None:
    contrasts = aggregate_contrasts(rows)
    by_variant = per_transcript_winrate(rows)

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 5.2))

    # --- Left panel: contrast win rates ---
    xs = list(range(len(CONTRASTS)))
    means, lows, highs, ns, colors = [], [], [], [], []
    for x, y, _ in CONTRASTS:
        wins, total = contrasts.get((x, y), (0, 0))
        p = wins / total if total else 0.0
        lo, hi = wilson_ci(wins, total)
        means.append(p)
        lows.append(p - lo)
        highs.append(hi - p)
        ns.append(total)
        colors.append(VARIANT_COLOR.get(x, "#888"))

    axL.bar(xs, means, color=colors, alpha=0.85, edgecolor="black", linewidth=0.5)
    axL.errorbar(xs, means, yerr=[lows, highs], fmt="none", ecolor="black", capsize=4, linewidth=1.2)
    axL.axhline(0.5, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    axL.set_xticks(xs)
    axL.set_xticklabels([c[2] for c in CONTRASTS], fontsize=9)
    axL.set_ylabel("Win rate of left-named variant")
    axL.set_ylim(0, 1.0)
    axL.set_title(f"Stakes-MVP contrast win rates {title_suffix}".strip())
    axL.grid(axis="y", alpha=0.3)
    for i, n in enumerate(ns):
        axL.text(i, 0.02, f"n={n}", ha="center", fontsize=8, color="white" if means[i] > 0.1 else "black")

    # --- Right panel: per-transcript win rate by variant ---
    variants = ["B", "A1", "A2", "A3"]
    x = list(range(len(variants)))
    for i, v in enumerate(variants):
        vals = by_variant.get(v, [])
        axR.scatter([i] * len(vals), vals, color=VARIANT_COLOR[v], s=80, alpha=0.85, edgecolor="black", linewidth=0.5, zorder=3)
        if vals:
            mean = sum(vals) / len(vals)
            axR.hlines(mean, i - 0.18, i + 0.18, color=VARIANT_COLOR[v], linewidth=2.5, zorder=4)
    axR.axhline(0.5, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    axR.set_xticks(x)
    axR.set_xticklabels([VARIANT_LABEL[v] for v in variants])
    axR.set_ylabel("Win rate vs full field")
    axR.set_ylim(-0.02, 1.02)
    axR.set_title("Per-transcript win rate by variant")
    axR.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=120)
    print(f"Saved {out}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("jsonl", type=Path, help="Pairwise judge JSONL output")
    p.add_argument("--out", type=Path, help="Output PNG path (default: docs/notes/<jsonl-stem>.png)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    rows = [json.loads(l) for l in args.jsonl.read_text().splitlines() if l.strip()]
    out = args.out or Path("docs/notes") / f"{args.jsonl.stem}.png"
    plot(rows, out, title_suffix=f"({args.jsonl.stem})")


if __name__ == "__main__":
    main()
