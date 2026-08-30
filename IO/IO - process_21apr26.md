# End-to-End Process — 2026-04-21

> Every command you need, in the order you'd run them. Dated snapshot — when
> the CLI surface changes materially, rename this file (`IO - process_XX.md`)
> and keep the old one for history. Companion to
> [Plans/backlog_20Apr26.md](../Plans/backlog_20Apr26.md) and
> [IO - shipped_20Apr26.md](IO%20-%20shipped_20Apr26.md).

---

## TL;DR — happy path

```bash
# 1. Ingest (Stage 1 + auto-Stage-2 push to Qdrant in one command)
uv run python -m src.ingest /path/to/your/corpus -v

# 2. Query
ns
```

That's it for the common case. Everything below is for debugging, inspection,
or opt-outs.

---

## The three operational modes

### Mode A — One-shot ingest (most common)

```bash
uv run python -m src.ingest <DIR>
```

**What happens, in order:**

1. Walks `<DIR>` recursively.
2. Skips files that match `.gitignore` + `.nasignore` + built-in defaults
   (`node_modules/`, `.git/`, `__pycache__/`, `venv/`, `build/`, IDE caches,
   lock files, etc.).
3. Peeks each remaining file cheaply, computes `visual_score` + `sensitivity_score` + `t4_cost`.
4. Dispatches to the right tier worker (T0/T1/T2/T3/T4) — see
   [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md).
5. Writes summary markdowns to `Test Summaries/<hash>_<tier>.md`.
6. Records the full router verdict in the manifest audit trail.
7. **Auto-pushes new/changed entries to Qdrant** via the folded-in Stage 2.

**Final output:**
```
done: 473 considered — T0=0 T1=28 T2=83 T3=203 T4=159 unchanged=0 skipped=2
  errors=0 pruned=0 ignored=7061 gpu=yes t4_used_mb=81.0

pushing new summaries to Qdrant...
qdrant: upserted 314 points, 0 orphans cleaned, 473 total manifest rows
```

| Flag | Effect |
|---|---|
| `-v` / `--verbose` | Print per-file routing decision as each file completes: `[T3] path (visual=2 sens=7 crit=critical)` |
| `--force` | Re-ingest every file regardless of manifest state |
| `--concurrency N` | Max concurrent files (default: 4). Bump to 8-10 if your LLM provider tolerates it |
| `--no-push` | Skip the Stage 2 Qdrant push — useful when Qdrant is down or you're testing locally without creds |

### Mode B — Dry-run routing inspection (no ingest)

Inspect what WOULD happen without writing anything:

```bash
# Single file
uv run python -m src.router /path/to/file.pdf

# Whole directory (default shows first 50 lines + summary)
uv run python -m src.router /path/to/dir

# All files, no truncation
uv run python -m src.router /path/to/dir --limit 0
```

**Use for:**
- Auditing what tier each file will get before committing to an expensive ingest
- Diagnosing why a file went to a tier you didn't expect
- Estimating LLM cost (T3 count × 3-5s per file) before a big corpus

### Mode C — Manual Stage 2 push (rarely needed)

If you ingested with `--no-push` or something went wrong:

```bash
uv run python -m src.stage2 ingest
```

Reads the manifest, embeds only rows with `ingested_at=None`, upserts to
Qdrant. Orphan cleanup runs at the end — any Qdrant point whose manifest row
is gone gets deleted.

`--force` drops + recreates the collection from scratch. **Destructive.**

---

## Querying

### Interactive REPL (recommended)

```bash
ns        # or magpie-repl / nas — same binary
```

- First query ~20s (ColPali model cold-load, cached after).
- Every subsequent query ~2-5s.
- Dot-commands inside the REPL: `.help`, `.rewrite on|off`, `.top-k N`,
  `.clear`.

### One-shot query (fresh model load each time)

```bash
uv run python -m src.pipeline "your question here"
```

Slow if you only ask one question (cold-load every invocation). Use
for scripting or automated eval.

### Manual Stage 2 search only (no answer generation)

```bash
# Returns paths + scores, no LLM answer step
uv run python -m src.stage2 search "your question" --top-k 5
```

---

## Debug / introspection commands

### "Why did this file route to that tier?"

```bash
uv run python -m src.router /path/to/file.ext
```

Shows `visual_score`, `sensitivity_score`, `criticality` + source, T4 cost
estimate, the decision, and the notes trail.

### "What's in my manifest?"

```bash
uv run python -c "
from src.manifest import Manifest
m = Manifest()
for rel, entry in sorted(m.entries.items()):
    print(f'{\"+\".join(entry.routes):<10}  {rel}')"
```

Or specific queries:

```bash
# Count by tier
uv run python -c "
from src.manifest import Manifest
from collections import Counter
c = Counter()
for e in Manifest().entries.values():
    for t in (e.routes or ['?']):
        c[t] += 1
print(c)"

# Find files that errored / skipped
uv run python -c "
from src.manifest import Manifest
for rel, e in Manifest().entries.items():
    if e.skip_reason:
        print(f'{e.skip_reason:<30}  {rel}')"
```

### "Drop a specific corpus from the index"

```bash
# Example: remove all entries under /mnt/hardisk/sem_4/
uv run python -c "
from src.manifest import Manifest
m = Manifest()
dropped = [r for r in m.paths() if '/mnt/hardisk/sem_4/' in r]
for r in dropped: m.drop(r)
m.save()
print(f'dropped {len(dropped)} entries')"

# Then run Stage 2 ingest — orphan cleanup removes them from Qdrant.
uv run python -m src.stage2 ingest
```

### "Purge everything and start over"

```bash
# 1. Wipe the manifest + summaries
rm -rf "Test Summaries/"
# 2. Drop + recreate Qdrant collection
uv run python -m src.stage2 ingest --force
# 3. Re-ingest your corpus
uv run python -m src.ingest /your/corpus
```

---

## Env vars that matter

| Var | Purpose | Typical values |
|---|---|---|
| `LLM_PROVIDER` | Which LLM backend runs T3 summaries + answer step | `moonshot` / `openrouter` / `ollama` / `local` |
| `MOONSHOT_API_KEY` | If `LLM_PROVIDER=moonshot` | `sk-...` |
| `OPENROUTER_API_KEY` | If `LLM_PROVIDER=openrouter` | `sk-or-...` |
| `OLLAMA_MODEL` | If `LLM_PROVIDER=ollama` | `qwen2.5:3b` (default) |
| `QDRANT_CLUSTER_ENDPOINT` | Qdrant URL | Cloud: `https://<cluster>.qdrant.tech` / local: `http://localhost:6333` |
| `QDRANT_API_KEY` | For Qdrant Cloud (omit for local Docker) | `...` |

See [Plans/Port.md](../Plans/Port.md) for the cloud → local migration path.

---

## Folder-level config

Drop a `.nasconfig.yaml` anywhere under your corpus root. It applies to
every file beneath that folder:

```yaml
# Force Tier 3 (LLM summary) on everything in this folder, regardless of
# content-based sensitivity detection.
accuracy: critical

# Opt out of ColPali entirely for this folder.
colpali: never

# Raise the corpus-wide T4 storage budget from the 5 GB default.
t4_budget_gb_override: 20
```

Deeper-folder configs override shallower ones. Criticality can only be
upgraded, never downgraded — auto-detected critical content ALWAYS gets T3
regardless of config.

---

## `.gitignore` / `.nasignore`

Both are honored the same way `git` itself does: cascading, closest folder
wins. `.nasignore` is the Magpie-specific equivalent for
things `git` tracks but you don't want indexed (e.g. private folders).

**Built-in defaults are also applied** and cannot be un-ignored by user
config:

```
.git/  .hg/  .svn/
__pycache__/  *.pyc  .pytest_cache/  .mypy_cache/  .ruff_cache/  .tox/
.venv/  venv/  env/  *.egg-info/
node_modules/  .next/  .nuxt/
target/  bin/  obj/
build/  dist/  out/  .output/
.idea/  .vscode/  .vs/  *.swp
.DS_Store  Thumbs.db  desktop.ini
Test Summaries/
.ipynb_checkpoints/
package-lock.json  yarn.lock  pnpm-lock.yaml  poetry.lock  uv.lock
Cargo.lock  Gemfile.lock  go.sum
```

---

## Supported file types (as of this date)

| Category | Extensions | Tier paths |
|---|---|---|
| Text | `.txt .md .markdown .log` | T1 (small) / T0 (huge) |
| Code | `.py .js .ts .tsx .jsx .go .rs .java .c .cpp .h .hpp .cs .rb .swift .kt .sh .sql` | T1 / T0 |
| Config | `.json .yaml .yml .toml` | T1 / T0 |
| Data | `.csv` | T1 (<1k rows) / T2 (<100k) / T0 (huge) |
| Documents | `.pdf .docx .xlsx .xlsm` | T2 text-native / T3 if critical / T3+T4 if image-heavy |
| **Slides** | `.pptx` | **T2 text-heavy / T2+T4 image-heavy** (T4 uses `pool_factor=2` per [backlog G4](../Plans/backlog_20Apr26.md)) |
| **Web** | `.html .htm` | **T2 via trafilatura boilerplate stripping** |
| **Notebooks** | `.ipynb` | **T2 (stdlib json cell extraction, outputs skipped)** |
| Images | `.png .jpg .jpeg .webp .gif` | T4 (normal) / skip (thumbnails) |
| Video sidecars | `.alt` | Stage 3 (per-scene Qdrant points) |

Unsupported extensions are silently skipped — `.mp4 .mov .mp3 .zip` etc. all
just pass through without peeks. Video needs a `.alt` sidecar via Stage 3.

---

## Common failure modes + fixes

### "No results that match my query / wrong files surfacing"

1. Did you run Stage 2 push? If you used `--no-push` or an older workflow,
   `uv run python -m src.stage2 ingest`. From 2026-04-21 forward, `src.ingest`
   auto-pushes.
2. Are stale entries from an old corpus dominating? Drop them (see above
   debug snippet) and re-ingest.
3. Is ColPali cold-loading every time? Use the REPL (`ns`) — one-shot
   `python -m src.pipeline "..."` reloads the model on every call.

### "`AttributeError: 'FileSummary' object has no attribute 'output'`"

Historical bug from tier3 double-unwrapping. Fixed 2026-04-21. If you see it
after this date, your repo is stale — `git pull` + re-run.

### "errors=N for T3 files"

Usually a missing API key. Set `LLM_PROVIDER` + the matching `*_API_KEY` in
`.env`. Rerun — walker sees T3 rows with `summary_file=None` and retries just
those files.

### "ingest takes forever"

Expected cost for a 500-file mixed corpus with GPU:
- Router peeks: ~8 min (one-shot I/O)
- T1/T2: ~5 min (fast CPU embed + parse)
- T3: 3-5s per file × N — this is the bulk of your wall-clock
- T4: ~1s per page on GPU, 10s per page on CPU

If T3 count is higher than you expected, the `uv run python -m src.router
<dir>` dry-run will show you why *before* you burn the LLM budget.

---

## Related docs

- [Plans/Indexing Tiers.md](../Plans/Indexing%20Tiers.md) — tier definitions + router rubric
- [Plans/backlog_20Apr26.md](../Plans/backlog_20Apr26.md) — everything still owed
- [IO - shipped_20Apr26.md](IO%20-%20shipped_20Apr26.md) — what's landed in code
- [Plans/Port.md](../Plans/Port.md) — cloud → local Ollama migration
- [IO - CLI.md](IO%20-%20CLI.md) — REPL dot-command reference
