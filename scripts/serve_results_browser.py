#!/usr/bin/env python3
"""Interactive results browser for judge-result JSONL files.

Usage:
    uv run python scripts/serve_results_browser.py [--port 8080]
"""
from __future__ import annotations

import argparse
import json
import math
import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ── constants ────────────────────────────────────────────────────────────────

RESULTS_DIR = Path(__file__).parent.parent / "judge-results"

# Fallbacks used when no `.labels.json` sidecar is present.
DEFAULT_VARIANT_ID = {"1": "B", "2": "A1", "3": "A2", "4": "A3"}
DEFAULT_VARIANT_COLOR = {"B": "#555", "A1": "#1f77b4", "A2": "#2ca02c", "A3": "#d62728"}
PALETTE = ["#555", "#1f77b4", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#17becf"]

CONTRASTS = [
    ("A1", "B",  "A1 vs B\n(stakes)"),
    ("A2", "B",  "A2 vs B\n(pretext)"),
    ("A3", "B",  "A3 vs B\n(both)"),
    ("A3", "A2", "A3 vs A2\n(stakes only)"),
    ("B",  "B",  "B vs B\n(null)"),
    ("A1", "A1", "A1 vs A1\n(null)"),
]


def load_labels(jsonl_path: Path) -> tuple[dict, dict]:
    """Load `<jsonl stem>.labels.json` sidecar if present.

    Returns (variant_id, variant_color), where variant_id maps Petri sample-id
    prefix (e.g. "1") to the variant's display label (e.g. "B baseline").
    Falls back to DEFAULT_* if the sidecar is missing.
    """
    sidecar = jsonl_path.with_suffix(".labels.json")
    if not sidecar.exists():
        return dict(DEFAULT_VARIANT_ID), dict(DEFAULT_VARIANT_COLOR)
    try:
        data = json.loads(sidecar.read_text())
    except json.JSONDecodeError:
        return dict(DEFAULT_VARIANT_ID), dict(DEFAULT_VARIANT_COLOR)
    petri_id_map = data.get("petri_id_map", {})
    variant_id, variant_color = {}, {}
    for i, (pid, seed) in enumerate(sorted(petri_id_map.items(), key=lambda kv: int(kv[0]))):
        label = seed.get("label") or seed.get("id") or f"#{pid}"
        variant_id[pid] = label
        variant_color[label] = PALETTE[i % len(PALETTE)]
    return variant_id, variant_color

# ── data processing (mirrors plot_stakes_mvp.py) ─────────────────────────────

def variant_of(path: str, variant_id: dict[str, str]) -> str | None:
    name = Path(path).name
    return variant_id.get(name.split("_", 1)[0])


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    halfwidth = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, center - halfwidth), min(1.0, center + halfwidth))


def aggregate_contrasts(rows: list[dict], variant_id: dict[str, str]) -> dict[tuple[str, str], tuple[int, int]]:
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        va = variant_of(r["file_a"], variant_id)
        vb = variant_of(r["file_b"], variant_id)
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


def per_transcript_winrate(rows: list[dict], variant_id: dict[str, str]) -> list[dict]:
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
    return [
        {
            "name": name,
            "variant": variant_of(name, variant_id) or "?",
            "win_rate": wins[name] / total if total else 0.0,
            "wins": wins[name],
            "n_comparisons": total,
        }
        for name, total in sorted(n.items())
    ]


def build_contrast_list(variants_in_order: list[str]) -> list[tuple[str, str]]:
    """Cross-variant pairs (sorted) followed by same-variant null contrasts."""
    cross = [
        (variants_in_order[i], variants_in_order[j])
        for i in range(len(variants_in_order))
        for j in range(len(variants_in_order))
        if i != j
    ]
    # Deduplicate to one direction per pair: ablated-vs-baseline canonical order is later-vs-earlier.
    seen: set[frozenset[str]] = set()
    cross_unique: list[tuple[str, str]] = []
    for pair in cross:
        key = frozenset(pair)
        if key in seen:
            continue
        seen.add(key)
        # Put the later-listed variant first (treated as "ablated vs baseline").
        a, b = pair
        if variants_in_order.index(a) < variants_in_order.index(b):
            a, b = b, a
        cross_unique.append((a, b))
    nulls = [(v, v) for v in variants_in_order]
    return cross_unique + nulls


def process_data(jsonl_path: Path) -> dict:
    variant_id, variant_color = load_labels(jsonl_path)
    rows = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    has_variants = any(
        variant_of(r.get("file_a", ""), variant_id) or variant_of(r.get("file_b", ""), variant_id)
        for r in rows
    )
    transcripts = per_transcript_winrate(rows, variant_id)

    contrasts: list[dict] = []
    variants_in_order: list[str] = []
    if has_variants:
        # Variant order matches Petri sample-id order so contrasts list reads naturally.
        variants_in_order = [variant_id[k] for k in sorted(variant_id.keys(), key=int)]
        counts = aggregate_contrasts(rows, variant_id)
        for x, y in build_contrast_list(variants_in_order):
            wins, total = counts.get((x, y), (0, 0))
            p = wins / total if total else 0.0
            lo, hi = wilson_ci(wins, total)
            contrasts.append({
                "label": f"{x}\nvs {y}" if x != y else f"{x}\nvs self (null)",
                "x_variant": x,
                "y_variant": y,
                "win_rate": p,
                "lo": lo,
                "hi": hi,
                "n": total,
                "color": variant_color.get(x, "#888"),
            })

    comparisons = [
        {
            "file_a": Path(r["file_a"]).name,
            "file_b": Path(r["file_b"]).name,
            "winner": r.get("winner", "?"),
            "reasoning": r.get("reasoning", ""),
            "model": r.get("model", ""),
            "timestamp": r.get("timestamp", "")[:19].replace("T", " "),
        }
        for r in rows
    ]
    return {
        "comparisons": comparisons,
        "transcripts": transcripts,
        "contrasts": contrasts,
        "has_variants": has_variants,
        "variant_id": variant_id,
        "variant_color": variant_color,
        "variants_in_order": variants_in_order,
    }


# ── HTML page ────────────────────────────────────────────────────────────────

HTML_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Results Browser</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 13px; background: #f0f0f0; color: #1a1a1a;
      height: 100vh; display: flex; flex-direction: column; overflow: hidden;
    }

    /* ── header ── */
    #header {
      background: #1a1a2e; color: #e8e8e8;
      padding: 9px 16px; font-size: 13px;
      display: flex; align-items: center; gap: 12px; flex-shrink: 0;
    }
    #header .title { font-weight: 600; letter-spacing: 0.4px; }
    #current-file { color: #8888aa; font-size: 12px; font-family: monospace; }

    /* ── content row ── */
    #content { display: flex; flex: 1; overflow: hidden; }

    /* ── sidebar ── */
    #sidebar {
      width: 210px; min-width: 100px;
      background: #fff; border-right: none;
      display: flex; flex-direction: column; overflow: hidden;
    }
    #sidebar.collapsed { width: 32px !important; min-width: 32px !important; }
    #sidebar.collapsed #sidebar-label { display: none; }
    #sidebar.collapsed #file-list { display: none; }
    #sidebar-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 8px 10px 6px 14px; border-bottom: 1px solid #eee; flex-shrink: 0;
    }
    #sidebar-label {
      font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: #999;
      white-space: nowrap; overflow: hidden;
    }
    #sidebar-collapse-btn {
      background: none; border: none; cursor: pointer;
      color: #aaa; font-size: 13px; padding: 1px 4px; line-height: 1; flex-shrink: 0;
    }
    #sidebar-collapse-btn:hover { color: #444; }
    #file-list { list-style: none; padding: 4px 0; overflow-y: auto; flex: 1; }
    #file-list li {
      padding: 7px 12px; cursor: pointer; font-size: 11.5px;
      color: #555; border-left: 3px solid transparent;
      line-height: 1.5; word-break: break-all;
      transition: background 0.1s;
    }
    #file-list li:hover { background: #f4f6ff; color: #3355cc; }
    #file-list li.active {
      background: #eef1ff; border-left-color: #4466dd;
      color: #2244bb; font-weight: 500;
    }

    /* ── resize handles ── */
    .resizer { flex-shrink: 0; background: #e2e2e2; transition: background 0.1s; z-index: 20; }
    .resizer:hover, .resizer.dragging { background: #a0aaff; }
    .resizer-h { width: 4px; cursor: col-resize; }
    .resizer-v { height: 4px; cursor: row-resize; }

    /* ── main ── */
    #main { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }

    /* ── charts + detail row ── */
    #charts-row {
      display: flex; height: 340px; flex-shrink: 0;
      background: #fff; border-bottom: 1px solid #ddd;
    }
    #charts { display: flex; flex: 1; padding: 10px 10px 0; gap: 6px; min-width: 0; }
    #plot-contrasts { flex: 1; min-width: 0; }
    #plot-scatter    { flex: 1; min-width: 0; }

    /* ── detail panel ── */
    #detail-panel {
      width: 330px; min-width: 150px;
      border-left: none;
      display: flex; flex-direction: column; overflow: hidden;
    }
    #detail-panel > h4 {
      padding: 9px 14px 7px; font-size: 10px; text-transform: uppercase;
      letter-spacing: 1px; color: #999; border-bottom: 1px solid #eee; flex-shrink: 0;
    }
    #detail-content { flex: 1; overflow-y: auto; padding: 12px 14px; }
    .placeholder { color: #bbb; font-style: italic; margin-top: 50px; text-align: center; font-size: 12px; }
    .detail-name { font-weight: 600; font-size: 13px; margin-bottom: 3px; }
    .detail-meta { color: #888; font-size: 11px; margin-bottom: 14px; }
    .comp-item { border-top: 1px solid #eee; padding: 9px 0; }
    .comp-item:first-of-type { border-top: none; }
    .comp-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; gap: 8px; }
    .comp-vs { font-size: 11px; color: #666; font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .comp-badge {
      font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 3px;
      flex-shrink: 0; letter-spacing: 0.5px;
    }
    .badge-won  { background: #e6f4ea; color: #1e7e34; }
    .badge-lost { background: #fdecea; color: #c0392b; }
    .comp-reason { font-size: 12px; line-height: 1.55; color: #333; }

    /* ── table section ── */
    #table-section { flex: 1; overflow-y: auto; background: #fff; }
    #table-header {
      padding: 8px 16px 6px; font-size: 10px; text-transform: uppercase;
      letter-spacing: 1px; color: #999; border-bottom: 1px solid #eee;
      position: sticky; top: 0; background: #fff; z-index: 10;
    }
    table { width: 100%; border-collapse: collapse; }
    thead th {
      padding: 5px 10px; text-align: left; font-size: 11px; font-weight: 600;
      color: #777; border-bottom: 1px solid #e8e8e8;
      position: sticky; top: 31px; background: #fff; z-index: 9;
    }
    tbody tr { cursor: pointer; }
    tbody tr:hover td { background: #f5f7ff; }
    tbody tr.selected td { background: #ebefff; }
    tbody td { padding: 5px 10px; border-bottom: 1px solid #f2f2f2; vertical-align: top; }
    .col-file { font-family: monospace; font-size: 11px; color: #555; white-space: nowrap; }
    .col-winner { font-weight: 700; font-size: 11px; white-space: nowrap; }
    .w-A { color: #1f77b4; }
    .w-B { color: #d62728; }
    .col-reason { font-size: 12px; color: #444; line-height: 1.45; }
    .col-model { font-size: 11px; color: #999; white-space: nowrap; }

    #no-data { color: #bbb; text-align: center; padding: 40px; font-style: italic; }
  </style>
</head>
<body>
<div id="header">
  <span class="title">Results Browser</span>
  <span id="current-file">← select a file</span>
</div>
<div id="content">
  <div id="sidebar">
    <div id="sidebar-header">
      <span id="sidebar-label">Judge Results</span>
      <button id="sidebar-collapse-btn" title="Collapse sidebar">&#171;</button>
    </div>
    <ul id="file-list"></ul>
  </div>
  <div id="sidebar-resizer" class="resizer resizer-h"></div>
  <div id="main">
    <div id="charts-row">
      <div id="charts">
        <div id="plot-contrasts"></div>
        <div id="plot-scatter"></div>
      </div>
      <div id="detail-resizer" class="resizer resizer-h"></div>
      <div id="detail-panel">
        <h4>Detail</h4>
        <div id="detail-content">
          <div class="placeholder">Click a data point<br>or table row</div>
        </div>
      </div>
    </div>
    <div id="hresize" class="resizer resizer-v"></div>
    <div id="table-section">
      <div id="table-header">Comparisons</div>
      <div id="table-container"></div>
    </div>
  </div>
</div>

<script>
'use strict';

let currentData = null;

const PLOTLY_CFG = { responsive: true, displayModeBar: false };

function variantOf(filename) {
  if (!currentData || !currentData.variant_id) return null;
  return currentData.variant_id[filename.split('_')[0]] || null;
}

function variantColor(label) {
  if (!currentData || !currentData.variant_color) return '#888';
  return currentData.variant_color[label] || '#888';
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function shortModel(m) {
  return m.replace('claude-', '').replace(/-\\d{8}$/, '');
}

// ── resize handles ────────────────────────────────────────────────────────────

function makeDragger(id, axis, onDrag, onDone) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener('mousedown', e => {
    e.preventDefault();
    let last = axis === 'x' ? e.clientX : e.clientY;
    el.classList.add('dragging');
    document.body.style.cssText += ';cursor:' + (axis === 'x' ? 'col' : 'row') + '-resize;user-select:none';
    function onMove(e) {
      const pos = axis === 'x' ? e.clientX : e.clientY;
      onDrag(pos - last);
      last = pos;
    }
    function onUp() {
      el.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      if (onDone) onDone();
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

function resizePlots(newHeight) {
  const pc = document.getElementById('plot-contrasts');
  const ps = document.getElementById('plot-scatter');
  if (newHeight !== undefined) {
    if (pc._fullLayout) Plotly.relayout(pc, { height: newHeight });
    if (ps._fullLayout) Plotly.relayout(ps, { height: newHeight });
  } else {
    if (pc._fullLayout) Plotly.Plots.resize(pc);
    if (ps._fullLayout) Plotly.Plots.resize(ps);
  }
}

function initResizers() {
  makeDragger('sidebar-resizer', 'x', delta => {
    const sb = document.getElementById('sidebar');
    if (sb.classList.contains('collapsed')) return;
    sb.style.width = Math.max(100, sb.offsetWidth + delta) + 'px';
    sb.style.minWidth = sb.style.width;
  });

  makeDragger('hresize', 'y', delta => {
    const row = document.getElementById('charts-row');
    row.style.height = Math.max(150, Math.min(700, row.offsetHeight + delta)) + 'px';
  }, () => resizePlots(document.getElementById('charts-row').offsetHeight - 30));

  makeDragger('detail-resizer', 'x', delta => {
    const dp = document.getElementById('detail-panel');
    const w = Math.max(150, Math.min(700, dp.offsetWidth - delta));
    dp.style.width = w + 'px';
    dp.style.minWidth = w + 'px';
  }, () => resizePlots());
}

// ── sidebar collapse ─────────────────────────────────────────────────────────

function initSidebarCollapse() {
  const btn = document.getElementById('sidebar-collapse-btn');
  const sb = document.getElementById('sidebar');
  const resizer = document.getElementById('sidebar-resizer');
  let savedWidth = 210;

  btn.addEventListener('click', () => {
    if (!sb.classList.contains('collapsed')) {
      savedWidth = sb.offsetWidth;
      sb.style.width = '';
      sb.style.minWidth = '';
      sb.classList.add('collapsed');
      resizer.style.display = 'none';
      btn.innerHTML = '&#187;';
      btn.title = 'Expand sidebar';
    } else {
      sb.classList.remove('collapsed');
      sb.style.width = savedWidth + 'px';
      sb.style.minWidth = '100px';
      resizer.style.display = '';
      btn.innerHTML = '&#171;';
      btn.title = 'Collapse sidebar';
    }
  });
}

// ── init ─────────────────────────────────────────────────────────────────────

async function init() {
  initResizers();
  initSidebarCollapse();
  const res = await fetch('/api/files');
  const files = await res.json();
  const ul = document.getElementById('file-list');
  files.forEach(f => {
    const li = document.createElement('li');
    li.textContent = f.name;
    li.addEventListener('click', () => loadFile(f.name, li));
    ul.appendChild(li);
  });
  if (files.length > 0) loadFile(files[0].name, ul.querySelector('li'));
}

async function loadFile(name, li) {
  document.querySelectorAll('#file-list li').forEach(el => el.classList.remove('active'));
  li.classList.add('active');
  document.getElementById('current-file').textContent = name;

  const res = await fetch('/api/data?file=' + encodeURIComponent(name));
  currentData = await res.json();
  renderCharts(currentData);
  renderTable(currentData.comparisons);
  clearDetail();
}

// ── charts ────────────────────────────────────────────────────────────────────

function renderCharts(data) {
  const contrastsEl = document.getElementById('plot-contrasts');
  if (data.has_variants && data.contrasts.length) {
    contrastsEl.style.display = '';
    renderContrastsChart(data.contrasts);
  } else {
    contrastsEl.style.display = 'none';
    Plotly.purge('plot-contrasts');
  }
  renderScatterChart(data.transcripts, data.has_variants);
}

function renderContrastsChart(contrasts) {
  const trace = {
    type: 'bar',
    x: contrasts.map(c => c.label.replace('\\n', '<br>')),
    y: contrasts.map(c => c.win_rate),
    error_y: {
      type: 'data', symmetric: false,
      array:      contrasts.map(c => c.hi - c.win_rate),
      arrayminus: contrasts.map(c => c.win_rate - c.lo),
      color: '#333', thickness: 1.5, width: 5,
    },
    marker: {
      color: contrasts.map(c => c.color), opacity: 0.85,
      line: { color: '#333', width: 0.5 },
    },
    customdata: contrasts,
    text: contrasts.map(c => 'n=' + c.n),
    textposition: 'inside',
    textfont: { color: '#fff', size: 10 },
    hovertemplate: '<b>%{x}</b><br>win rate: %{y:.1%}<br>n=%{customdata.n}<extra></extra>',
  };

  const layout = {
    title: { text: 'Contrast win rates', font: { size: 13 } },
    yaxis: { range: [0, 1.08], title: 'Win rate', tickformat: '.0%' },
    xaxis: { tickfont: { size: 10 } },
    shapes: [halfLine(contrasts.length)],
    height: 310, margin: { t: 38, b: 60, l: 52, r: 12 },
    plot_bgcolor: '#f9f9f9', paper_bgcolor: '#fff',
  };

  Plotly.newPlot('plot-contrasts', [trace], layout, PLOTLY_CFG);
  document.getElementById('plot-contrasts').on('plotly_click', e => {
    showContrastDetail(e.points[0].customdata);
  });
}

function renderScatterChart(transcripts, hasVariants) {
  const byVariant = {};
  transcripts.forEach(t => {
    (byVariant[t.variant] = byVariant[t.variant] || []).push(t);
  });

  const variants = hasVariants
    ? (currentData.variants_in_order || []).filter(v => byVariant[v])
    : Object.keys(byVariant);

  const traces = variants.map((v, vi) => {
    const pts = byVariant[v];
    const half = (pts.length - 1) / 2;
    return {
      type: 'scatter', mode: 'markers',
      name: v === '?' ? 'all' : v,
      x: pts.map((_, i) => vi + (i - half) * (0.28 / Math.max(pts.length, 2))),
      y: pts.map(t => t.win_rate),
      customdata: pts,
      text: pts.map(t => t.name),
      marker: {
        color: variantColor(v), size: 10, opacity: 0.85,
        line: { width: 0.8, color: '#222' },
      },
      hovertemplate: '<b>%{text}</b><br>win rate: %{y:.1%} (%{customdata.wins}/%{customdata.n_comparisons})<extra></extra>',
    };
  });

  const nv = variants.length;
  const layout = {
    title: { text: 'Per-transcript win rate', font: { size: 13 } },
    yaxis: { range: [-0.06, 1.06], title: 'Win rate vs field', tickformat: '.0%' },
    xaxis: hasVariants
      ? { tickvals: variants.map((_, i) => i), ticktext: variants, range: [-0.5, nv - 0.5] }
      : { visible: false, range: [-0.5, 0.5] },
    shapes: [halfLine(nv)],
    height: 310, margin: { t: 38, b: 60, l: 52, r: 12 },
    showlegend: false,
    plot_bgcolor: '#f9f9f9', paper_bgcolor: '#fff',
  };

  Plotly.newPlot('plot-scatter', traces, layout, PLOTLY_CFG);
  document.getElementById('plot-scatter').on('plotly_click', e => {
    showTranscriptDetail(e.points[0].customdata);
  });
}

function halfLine(n) {
  return {
    type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0.5, y1: 0.5,
    line: { dash: 'dash', color: '#bbb', width: 1 },
  };
}

// ── table ─────────────────────────────────────────────────────────────────────

function renderTable(comparisons) {
  const container = document.getElementById('table-container');
  if (!comparisons.length) {
    container.innerHTML = '<div id="no-data">No comparisons</div>';
    return;
  }
  const table = document.createElement('table');
  table.innerHTML = '<thead><tr><th>File A</th><th>File B</th><th>W</th><th>Reasoning</th><th>Model</th></tr></thead>';
  const tbody = document.createElement('tbody');
  comparisons.forEach((c, i) => {
    const tr = document.createElement('tr');
    tr.dataset.idx = i;
    tr.innerHTML =
      '<td class="col-file">' + esc(c.file_a) + '</td>' +
      '<td class="col-file">' + esc(c.file_b) + '</td>' +
      '<td class="col-winner w-' + esc(c.winner) + '">' + esc(c.winner) + '</td>' +
      '<td class="col-reason">' + esc(c.reasoning) + '</td>' +
      '<td class="col-model">' + esc(shortModel(c.model)) + '</td>';
    tr.addEventListener('click', () => {
      clearTableSelection();
      tr.classList.add('selected');
      showComparisonDetail(c);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.innerHTML = '';
  container.appendChild(table);
}

function clearTableSelection() {
  document.querySelectorAll('tbody tr.selected').forEach(r => r.classList.remove('selected'));
}

function highlightTableRows(predicate) {
  clearTableSelection();
  if (!currentData) return;
  document.querySelectorAll('tbody tr').forEach(tr => {
    const c = currentData.comparisons[parseInt(tr.dataset.idx)];
    if (predicate(c)) tr.classList.add('selected');
  });
}

// ── detail panel ─────────────────────────────────────────────────────────────

function clearDetail() {
  document.getElementById('detail-content').innerHTML =
    '<div class="placeholder">Click a data point<br>or table row</div>';
}

function setDetail(html) {
  document.getElementById('detail-content').innerHTML = html;
}

function showTranscriptDetail(transcript) {
  if (!currentData) return;
  const { name, variant, win_rate, wins, n_comparisons } = transcript;

  highlightTableRows(c => c.file_a === name || c.file_b === name);

  const comps = currentData.comparisons.filter(c => c.file_a === name || c.file_b === name);
  const varLabel = variant !== '?' ? ' <span style="color:#888;font-weight:400">(' + esc(variant) + ')</span>' : '';
  let html = '<div class="detail-name">' + esc(name) + varLabel + '</div>'
    + '<div class="detail-meta">'
    + (win_rate * 100).toFixed(1) + '% win rate &nbsp;·&nbsp; ' + wins + '/' + n_comparisons + ' comparisons'
    + '</div>';

  html += comps.map(c => {
    const isA = c.file_a === name;
    const other = isA ? c.file_b : c.file_a;
    const won = (isA && c.winner === 'A') || (!isA && c.winner === 'B');
    return '<div class="comp-item">'
      + '<div class="comp-head">'
      + '<span class="comp-vs">vs ' + esc(other) + '</span>'
      + '<span class="comp-badge ' + (won ? 'badge-won' : 'badge-lost') + '">' + (won ? 'WON' : 'LOST') + '</span>'
      + '</div>'
      + '<div class="comp-reason">' + esc(c.reasoning) + '</div>'
      + '</div>';
  }).join('');

  setDetail(html);
}

function showContrastDetail(contrast) {
  if (!currentData) return;
  const { x_variant: xv, y_variant: yv, label, win_rate, n } = contrast;

  const comps = currentData.comparisons.filter(c => {
    const va = variantOf(c.file_a), vb = variantOf(c.file_b);
    return (va === xv && vb === yv) || (va === yv && vb === xv);
  });
  highlightTableRows(c => {
    const va = variantOf(c.file_a), vb = variantOf(c.file_b);
    return (va === xv && vb === yv) || (va === yv && vb === xv);
  });

  let html = '<div class="detail-name">' + esc(label.replace('\\n', ' ')) + '</div>'
    + '<div class="detail-meta">'
    + xv + ' win rate: ' + (win_rate * 100).toFixed(1) + '% &nbsp;·&nbsp; n=' + n
    + '</div>';

  html += comps.map(c => {
    const va = variantOf(c.file_a);
    const xWon = (va === xv && c.winner === 'A') || (va !== xv && c.winner === 'B');
    return '<div class="comp-item">'
      + '<div class="comp-head">'
      + '<span class="comp-vs">' + esc(c.file_a) + ' vs ' + esc(c.file_b) + '</span>'
      + '<span class="comp-badge ' + (xWon ? 'badge-won' : 'badge-lost') + '">'
      + esc(c.winner) + ' wins</span>'
      + '</div>'
      + '<div class="comp-reason">' + esc(c.reasoning) + '</div>'
      + '</div>';
  }).join('');

  setDetail(html);
}

function showComparisonDetail(c) {
  let html = '<div class="detail-name">' + esc(c.file_a) + ' vs ' + esc(c.file_b) + '</div>'
    + '<div class="detail-meta">'
    + 'Winner: <strong>' + esc(c.winner) + '</strong>'
    + (c.timestamp ? ' &nbsp;·&nbsp; ' + esc(c.timestamp) : '')
    + (c.model ? ' &nbsp;·&nbsp; ' + esc(shortModel(c.model)) : '')
    + '</div>'
    + '<div class="comp-item" style="border-top:none">'
    + '<div class="comp-reason">' + esc(c.reasoning) + '</div>'
    + '</div>';
  setDetail(html);
}

init();
</script>
</body>
</html>
"""

# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, "text/html; charset=utf-8", HTML_PAGE.encode())
        elif parsed.path == "/api/files":
            files = sorted(RESULTS_DIR.glob("*.jsonl"), key=lambda p: p.name)
            body = json.dumps([{"name": p.name} for p in files]).encode()
            self._send(200, "application/json", body)
        elif parsed.path == "/api/data":
            params = parse_qs(parsed.query)
            filename = params.get("file", [""])[0]
            path = (RESULTS_DIR / filename).resolve()
            if not str(path).startswith(str(RESULTS_DIR.resolve())) or not path.is_file():
                self._send(404, "text/plain", b"Not found")
                return
            try:
                data = process_data(path)
                body = json.dumps(data).encode()
                self._send(200, "application/json", body)
            except Exception as e:
                self._send(500, "text/plain", str(e).encode())
        else:
            self._send(404, "text/plain", b"Not found")

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # suppress per-request noise


# ── main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--no-browser", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    url = f"http://localhost:{args.port}"
    server = HTTPServer(("", args.port), Handler)
    print(f"Results browser → {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
