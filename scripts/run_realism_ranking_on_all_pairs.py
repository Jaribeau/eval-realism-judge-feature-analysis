"""
All-pairs pairwise realism ranking runner.

Runs all unique pairs from a sample directory in both orders (to control for
position bias), logs each comparison to JSONL, then prints a win-rate ranking.

Usage:
    uv run python scripts/run_realism_ranking_on_all_pairs.py generated-transcripts/2026-05-06T22-22-56
    uv run python scripts/run_realism_ranking_on_all_pairs.py generated-transcripts/2026-05-06T22-22-56 \\
        --output judge-results/run1.jsonl --model claude-sonnet-4-6
"""

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
from pairwise_judge import compare, extract_conversation, format_transcript, log_result, JUDGE_MODEL


def load_samples(samples_dir: Path) -> list[tuple[Path, dict]]:
    """Load all JSON sample files from a directory, sorted by name."""
    files = sorted(samples_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No JSON files in {samples_dir}")
    return [(f, json.loads(f.read_text())) for f in files]


def run_all_pairs(
    samples_dir: Path,
    output: Path,
    model: str = JUDGE_MODEL,
) -> list[dict]:
    """Run all unique pairs in both orders. Returns list of result dicts."""
    samples = load_samples(samples_dir)
    n = len(samples)
    pairs = list(combinations(range(n), 2))
    total = len(pairs) * 2  # both orderings
    print(f"Loaded {n} transcripts → {len(pairs)} pairs × 2 orderings = {total} comparisons")
    print(f"Output: {output}\n")

    results = []
    done = 0
    for i, j in pairs:
        path_i, sample_i = samples[i]
        path_j, sample_j = samples[j]

        tx_i = format_transcript(extract_conversation(sample_i))
        tx_j = format_transcript(extract_conversation(sample_j))

        for (path_a, sample_a, tx_a), (path_b, sample_b, tx_b) in [
            ((path_i, sample_i, tx_i), (path_j, sample_j, tx_j)),
            ((path_j, sample_j, tx_j), (path_i, sample_i, tx_i)),
        ]:
            done += 1
            print(f"[{done}/{total}] {path_a.name} vs {path_b.name} … ", end="", flush=True)
            result = compare(
                tx_a,
                tx_b,
                model=model,
                seed_a=str(sample_a.get("input", "")),
                seed_b=str(sample_b.get("input", "")),
            )
            log_result(result, output, sample_a=path_a, sample_b=path_b)
            results.append(result)
            print(f"→ {result['winner']}  ({result['reasoning'][:80]}…)")

    return results


def build_ranking(results: list[dict], samples: list[tuple[Path, dict]]) -> list[dict]:
    """Aggregate pairwise results into a win-rate ranking."""
    name_to_idx = {str(p): i for i, (p, _) in enumerate(samples)}
    wins = [0] * len(samples)
    comparisons = [0] * len(samples)

    for r in results:
        file_a = r.get("file_a", "")
        file_b = r.get("file_b", "")
        idx_a = name_to_idx.get(file_a)
        idx_b = name_to_idx.get(file_b)
        if idx_a is None or idx_b is None:
            continue
        comparisons[idx_a] += 1
        comparisons[idx_b] += 1
        if r["winner"] == "A":
            wins[idx_a] += 1
        else:
            wins[idx_b] += 1

    rows = []
    for i, (path, sample) in enumerate(samples):
        n = comparisons[i]
        rows.append({
            "rank": None,
            "name": path.name,
            "wins": wins[i],
            "comparisons": n,
            "win_rate": round(wins[i] / n, 3) if n else None,
            "seed": str(sample.get("input", ""))[:60],
        })

    rows.sort(key=lambda r: r["win_rate"] or 0, reverse=True)
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


def print_ranking(ranking: list[dict]) -> None:
    print("\n" + "=" * 72)
    print("REALISM RANKING  (1 = most realistic)")
    print("=" * 72)
    header = f"{'Rank':>4}  {'Win rate':>9}  {'W/N':>7}  {'Transcript':<20}  Seed"
    print(header)
    print("-" * 72)
    for r in ranking:
        wr = f"{r['win_rate']:.3f}" if r["win_rate"] is not None else "  —  "
        wn = f"{r['wins']}/{r['comparisons']}"
        print(f"{r['rank']:>4}  {wr:>9}  {wn:>7}  {r['name']:<20}  {r['seed']}")
    print("=" * 72)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transcript_dir", type=Path, help="Directory containing a samples/ subdir")
    p.add_argument("--output", type=Path, help="JSONL output path (default: judge-results/<timestamp>[--suffix].jsonl)")
    p.add_argument("--suffix", default="", help="Tag appended to the default output filename, e.g. --suffix run2")
    p.add_argument("--model", default=JUDGE_MODEL, help="Judge model (default: %(default)s)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    samples_dir = args.transcript_dir / "samples"
    if not samples_dir.is_dir():
        sys.exit(f"No samples/ subdir found in {args.transcript_dir}")

    timestamp = args.transcript_dir.name
    suffix = f"--{args.suffix}" if args.suffix else ""
    output = args.output or Path(f"judge-results/{timestamp}{suffix}.jsonl")

    results = run_all_pairs(samples_dir, output, model=args.model)

    samples = load_samples(samples_dir)
    # Reload results from file so file_a/file_b are present
    saved = [json.loads(l) for l in output.read_text().splitlines() if l.strip()]
    ranking = build_ranking(saved, samples)
    print_ranking(ranking)

    ranking_path = output.with_suffix(".ranking.json")
    ranking_path.write_text(json.dumps(ranking, indent=2))
    print(f"\nRanking saved to {ranking_path}")
    print(f"Raw comparisons: {output}")


if __name__ == "__main__":
    main()
