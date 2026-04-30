# Docs

Research notes for the eval-realism-judge-feature-analysis project.

## Layout

- `notes/` — running research notes, dated scratch entries, thinking-in-progress
- `findings/` — distilled findings, writeups, results that have stabilized
- `refs/` — references, paper notes, code links, quotes

## Editing conventions

This directory is co-edited by Jared and Claude. To avoid edit conflicts:

- **Append-mostly in `notes/`.** New dated entries go at the bottom. Don't restructure old entries.
- **Section ownership markers.** When a file mixes user-owned and Claude-owned content, wrap Claude's region:
  ```
  <!-- claude:start -->
  ...Claude may edit anything here...
  <!-- claude:end -->
  ```
  Everything outside the markers is user-owned and Claude won't touch it without explicit instruction.
- **Commit before Claude doc-editing turns.** Gives a one-command undo: `git checkout -- docs/<file>`.

See `CLAUDE.md` in the repo root for the full set of rules Claude follows.
