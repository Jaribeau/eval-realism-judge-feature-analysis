# Plan: Results Browser

## Context

The project accumulates judge-result JSONL files in `judge-results/`. Currently the only way to inspect results is running matplotlib scripts that produce static PNGs. The goal is an interactive web browser that lets you pick a result file, see the plot, and drill into individual comparison reasons — replacing the static PNG workflow with something explorable.

## What to Build

A single new script: `scripts/serve_results_browser.py`

- Starts a local HTTP server (Python built-in `http.server`, no new deps)
- Serves a self-contained HTML page with embedded Plotly.js (CDN)
- Three-panel layout: left file list, center plot + table, right detail panel

## Layout

```
+-- file list --+----------- plot -----------+-- detail --+
|               |  [bar chart] [scatter]     |  (click    |
| judge-results |                            |   to fill) |
| JSONL files   |                            |            |
+---------------+----------------------------+------------+
|                    comparisons table                    |
+---------------------------------------------------------+
```

- **Left sidebar**: lists all `*.jsonl` files from `judge-results/`. Clicking one loads it.
- **Top center**: two Plotly charts side-by-side (replicating `plot_stakes_mvp.py` logic)
  - Left chart: contrast win-rate bar chart with Wilson CI error bars (only shown if file has variant-prefixed filenames like `1_*`, `2_*` etc.)
  - Right chart: scatter of per-transcript win rates, colored by variant
- **Top right**: detail panel — populated when a scatter dot is clicked; shows that transcript's name, win rate, and all its comparison reasons (winner + reasoning text)
- **Bottom**: scrollable table of all comparisons (timestamp, file_a, file_b, winner, reasoning); clicking a row also populates the detail panel

## Server API

Two JSON endpoints:

- `GET /api/files` — lists JSONL files in `judge-results/`, returns `[{name, path, has_variants}]`
- `GET /api/data?file=<filename>` — parses the JSONL, returns:
  ```json
  {
    "comparisons": [{file_a, file_b, winner, reasoning, model, timestamp}],
    "transcripts": [{name, variant, win_rate, wins, n_comparisons}],
    "contrasts": [{label, x, y, win_rate, lo, hi, n}],
    "has_variants": true
  }
  ```

The data processing in `/api/data` reuses the logic from `plot_stakes_mvp.py`:
- `variant_of()` — parse variant from filename prefix
- `aggregate_contrasts()` — count wins per (variant_x, variant_y) pair
- `wilson_ci()` — confidence intervals
- `per_transcript_winrate()` — win rate per transcript file

## Files to create

- `scripts/serve_results_browser.py` — new file (HTML is embedded as a string in the Python)

## No files to modify

The existing plot script and data files are untouched.

## Verification

1. `uv run python scripts/serve_results_browser.py` — should print a localhost URL
2. Open in browser; left sidebar should list the JSONL files
3. Click `2026-05-07T09-48-06--stakes-mvp.jsonl` — both charts should render
4. Click a scatter dot — detail panel populates with comparisons for that transcript
5. Click a non-stakes file (e.g. `2026-05-06T23-22-14.jsonl`) — bar chart hides, scatter still renders with unlabeled/single variant
6. Table rows are clickable and populate the detail panel
