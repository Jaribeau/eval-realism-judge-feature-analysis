# Project: eval-realism-judge-feature-analysis

Systematic decomposition of what Petri's LLM realism judge responds to.

## Project Plan and Logs
- `project-plan.md` is the live source of truth for the project plan, experimental design, current status, and next steps.
- As we make progress, update `project-plan.md` with new progress or updates to the project plan.
- As we make progress, add research log notes in `docs/research-log.md`, especially to track progress milestones and decisions made.
- If you update `project-plan.md`, always add a brief summary of the change in `docs/research-log.md`
- Do not modify previous logs unless explicity asked.

## Working with markdown docs

The `docs/` directory contains research notes that the user edits in parallel with Claude. To prevent overwriting the user's in-progress edits, follow these rules for any `.md` file under `docs/` (and for `project-plan.md`, `README.md`, and any other markdown in the repo root):

1. **Never use the `Write` tool on existing markdown files.** Use `Edit` only. `Write` on a file you read minutes ago will silently clobber any edits the user made in the meantime. `Write` is ok for new files.
2. **Re-`Read` immediately before any `Edit`.** Even if you read the file earlier in the conversation, read it again right before editing so your `old_string` matches what's actually on disk.
3. **If the file looks different than you expected, stop and ask.** Unfamiliar sections, reordered content, or new headings likely mean the user edited it — don't try to "reconcile" by rewriting.
4. **Prefer appending to restructuring.** For running notes (logs, journals, findings), add new dated entries at the bottom rather than reorganizing existing content.

## Docs layout

- `docs/notes/` — running research notes, dated entries, scratch thinking
- `docs/findings/` — distilled findings and writeups
- `docs/refs/` — references, links, quotes from papers/code
- `project-plan.md` — top-level plan (user-owned; Claude edits only on request)

## Writing
- When writing text, be concise. 
- Leave out information that is implied, obvious, or unnessecary.
