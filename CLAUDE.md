# Magpie — working notes for Claude

## Pipeline map rule

`docs/PIPELINE.md` is the living map of how a question moves through
Magpie (query path) and how a file gets indexed (index path): Mermaid
figures, a stage table with each stage's default, the env knobs, and a
change log keyed to evaluation runs.

**Whenever a change to `src/` ships on the strength of a positive eval,
update `docs/PIPELINE.md` in the same change.** Positive eval means the
arm's strict score met its pre-registered gate, or beat the baseline arm
on the same dataset and criteria (both are recorded per arm in
`Evaluations/RUNLOG.jsonl` by `Evaluations/runlog.py`), and the change
is being left on by default.

What to update:

1. The Mermaid figure, if a stage was added, removed, moved, or changed
   its default (dashed node = opt-in, solid = on).
2. The stage's row in the stage table, and its knob in the defaults table.
3. A new line in the change log: date, change, dataset, strict score
   before → after, the RUNLOG `note` of the winning arm, commit.
4. If a figure changed, re-render its SVG so local preview matches:
   `bash ~/.claude/skills/render-mermaid/render.sh docs/PIPELINE.md`.

A change that **missed** its gate and stays off still gets a one-line
"tried, did not ship" entry with the number, so the experiment is not
re-run blindly. Figures are only redrawn for changes that ship.

The `run-evaluation` skill carries this as its Step 4. The README's
Architecture section links to the map; keep that link intact.
