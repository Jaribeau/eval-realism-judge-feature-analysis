"""Plot per-seed win rates for sonnet vs haiku judge rankings."""
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "judge-results"
SONNET = RESULTS / "2026-05-06T23-22-14.ranking.json"
HAIKU = RESULTS / "2026-05-06T23-22-14--haiku.ranking.json"
OUT = ROOT / "docs" / "notes" / "judge-comparison-may7.png"

SEED_LABELS = {
    "1": "S1\ncooking",
    "2": "S2\nboundaries",
    "3": "S3\nrambling",
    "4": "S4\ncontradict",
    "5": "S5\nlaw enf.",
}


def load_by_seed(path):
    by_seed = defaultdict(list)
    for row in json.loads(path.read_text()):
        seed_id = row["name"].split("_")[0]
        by_seed[seed_id].append(row["win_rate"])
    return by_seed


sonnet = load_by_seed(SONNET)
haiku = load_by_seed(HAIKU)

seeds = ["1", "2", "3", "4", "5"]
x = np.arange(len(seeds))
offset = 0.18

fig, ax = plt.subplots(figsize=(9, 5))

for i, seed in enumerate(seeds):
    s_vals = sonnet[seed]
    h_vals = haiku[seed]
    ax.scatter([x[i] - offset] * len(s_vals), s_vals, color="#1f77b4", s=80, zorder=3, label="Sonnet" if i == 0 else None)
    ax.scatter([x[i] + offset] * len(h_vals), h_vals, color="#ff7f0e", s=80, marker="^", zorder=3, label="Haiku" if i == 0 else None)
    ax.hlines(np.mean(s_vals), x[i] - offset - 0.06, x[i] - offset + 0.06, color="#1f77b4", linewidth=2)
    ax.hlines(np.mean(h_vals), x[i] + offset - 0.06, x[i] + offset + 0.06, color="#ff7f0e", linewidth=2)

ax.axhline(0.5, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
ax.set_xticks(x)
ax.set_xticklabels([SEED_LABELS[s] for s in seeds])
ax.set_ylabel("Win rate (vs all other transcripts)")
ax.set_ylim(-0.05, 1.05)
ax.set_title("Per-seed pairwise win rates: Sonnet vs Haiku judge\n(3 epochs per seed, 28 comparisons each)")
ax.legend(loc="upper right")
ax.grid(axis="y", alpha=0.3)

plt.tight_layout()
OUT.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(OUT, dpi=120)
print(f"Saved {OUT}")
