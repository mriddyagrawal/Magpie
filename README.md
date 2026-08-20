# Magpie

**Ask questions about your own files. Get answers, with the sources cited.**

Magpie is a Spotlight-style window that sits on top of your filesystem. Hit `⌥Space`, ask something in plain English, and get an answer grounded in your actual documents — receipts, contracts, course catalogs, meeting notes, scanned PDFs — with clickable links to the files it used.

Your files never leave your machine.

<!-- TODO: replace with a real screenshot of the running app.
     Specs/UI/*.png are design mockups, not captures of the shipped build. -->

---

## The problem

Every desktop search tool works the same way: you type keywords, it matches filenames and maybe some content. That's fine when you remember the exact word. It falls apart the moment you ask a real question.

- *"How much was that flight to Hartford last March?"*
- *"Which course teaches relativity?"*
- *"What's our club's policy on guest voting?"*

Spotlight can find a file whose *name* contains "Hartford," but it can't read the receipt and tell you the total. It can list every course catalog PDF, but it can't scan their contents and return the one covering relativity. The information is on your machine. The search tool just doesn't understand it.

Magpie is the "chat with your documents" experience — but pointed at your own filesystem instead of a curated upload.

---

## Download

**[Latest release →](https://github.com/mriddyagrawal/Magpie/releases/latest)**

| Platform | File |
|---|---|
| macOS (Apple silicon) | `Magpie_0.1.0_aarch64.dmg` |
| Windows 10/11 (x64) | `Magpie_0.1.0_x64-setup.exe` or `.msi` |
| macOS (Intel) | Not built — GitHub retired the Intel CI runner |
| Linux | Not in this beta ([why](docs/DEVELOPMENT.md#linux)) |

### macOS: the first launch is blocked

The beta is **unsigned and un-notarized**, so macOS quarantines it. This is expected. Either:

```bash
xattr -dr com.apple.quarantine /Applications/Magpie.app
```

…or open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway**.

### Windows

SmartScreen will warn you. Click **More info → Run anyway**.

---

## First run

1. Press **`⌥Space`** to summon the window (`Alt+Space` on Windows).
2. Open **Settings → Data → Add folder** and point it at something real.
3. Wait for the folder to finish indexing — the row shows live progress.
4. Press `⌥Space` again and ask a question.

**The first question needs an internet connection.** Magpie downloads ~90 MB of embedding models on first use, then works from cache. Indexing large folders also downloads a visual model (500 MB–2 GB) the first time it meets a scanned PDF or image.

### Shortcuts

| Key | Action |
|---|---|
| `⌥Space` (global) | Summon the window from any app |
| `Enter` | Submit the question |
| `Esc` | Collapse to resting state; again to hide |
| `↑` / `↓` | Move through sources, preview follows |
| `Enter` on a source | Open in the default app |
| `⌘Enter` on a source | Reveal in Finder |

Magpie hides whenever it loses focus, like Spotlight. `⌥Space` brings it back.

---

## What works in this beta

| | Status |
|---|---|
| Indexing folders, live progress, resume | ✅ |
| Asking questions, cited answers, file previews | ✅ |
| Text, PDF, DOCX, XLSX, CSV, code, Markdown | ✅ |
| Scanned PDFs and images (visual search) | ✅ |
| Cloud answers | ✅ ships with a shared key — see [Privacy](#privacy) |
| **Local / offline model** | ❌ not bundled in this build |
| Auto-update | ❌ off; download new versions manually |
| Code signing | ❌ unsigned, hence the launch warnings |
| Linux | ❌ not built |

**About the local model:** Magpie fully supports running inference on-device, but the ~2 GB `llama-server` runtime isn't bundled in the installer yet and there's no in-app downloader. Selecting **Settings → Local** will tell you it isn't set up and point you back to Cloud. If you're running from source, `just install-llama-server` gets you offline inference today.

---

## Privacy

What stays local, always:

- **Your files.** Never uploaded, never copied into another store.
- **The index.** Qdrant runs as a local binary on loopback. Magpie *hard-errors* if pointed at a remote cluster — this is enforced in code, not policy.
- **All embedding and ranking.** Four models run inside the app: MiniLM (dense), BM25 (sparse), ColPali (visual), and a cross-encoder (reranking). None of them ever call out.

What leaves the machine, in Cloud mode only:

- **Your question**, if query rewriting is on.
- **The contents of the files retrieved to answer it**, sent to the LLM provider.

That second one is the real boundary — worth knowing before you point Magpie at anything sensitive. In Local mode nothing leaves at all.

> **On the bundled key:** this beta ships with a shared, spend-capped OpenRouter key against a free-tier model so it works out of the box. It's extractable from the binary — assume it's public, and don't rely on it for anything private. Bring-your-own-key and a hosted backend are both planned.

---

## How it works

**1 · Understand each file.** Files are routed through five tiers by cost. Small text and code are embedded directly. PDFs, DOCX and XLSX get their text extracted. Only files that genuinely need it — receipts, contracts, scanned documents — get an LLM-generated structured summary. Scanned pages and images go to a visual model that embeds the rendered page. Huge files are registered and searched on demand with ripgrep instead of being embedded.

**2 · Make it searchable.** Everything gets two representations: a **dense embedding** for meaning, so "pay the landlord" finds "rent payment"; and a **sparse BM25 vector** for exact tokens, so `PHY-312` and `$143.50` stay findable literally. Both are fused at query time.

**3 · Answer.** Your question is optionally rewritten into a keyword-rich query, embedded, and searched against both tiers. Results are merged, reranked, and the *actual source files* are read and sent to a model, which answers and cites what it used.

### Design principles

**The filesystem is the source of truth.** Files are indexed, never copied. Delete a file and the next sync removes its summary and index entry.

**Incremental by default.** A manifest tracks every file. Adding one file to a folder of thousands re-processes exactly one file.

**Two embeddings beat one.** Dense handles synonyms; BM25 handles identifiers. Each alone has blind spots.

**Summaries for prose, rows for tables.** A 3-sentence summary indexes a receipt well. A 1,700-row course catalog is indexed per row, so individual courses stay findable.

**Cite everything.** Every answer names the files it relied on, as clickable paths.

---

## Build from source

```bash
git clone https://github.com/mriddyagrawal/Magpie.git
cd Magpie
just sync-environment     # Python deps via uv
just qdrant-install       # local vector database binary
cd frontend && pnpm install
```

Then run the dev loop:

```bash
just qdrant-up                                        # terminal 1
uv run uvicorn src.server:app --port 8765 --reload    # terminal 2
cd frontend && pnpm tauri dev                         # terminal 3
```

Full setup, LLM provider configuration, local inference, packaging, and the release process are documented in **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)**.

---

## Project layout

```
src/                 Python backend
  server.py          FastAPI app — the entire HTTP surface
  ingest/            Five-tier indexing pipeline + walker
  router.py          Which tier does a given file deserve?
  stage2/            Embeddings, Qdrant, hybrid search, reranking
  answer.py          Grounded answer synthesis with citations
  inference/         Local llama-server subprocess pool
  config/            Settings, secrets, indexing rules
frontend/            Tauri (Rust shell) + React UI
  src-tauri/         Process supervision, global shortcut, windows
server/              Optional hosted LLM proxy (Fly.io)
cli/                 Legacy terminal REPL — see DEVELOPMENT.md
```

---

## Status

Magpie is a **beta**. It has been installed and run by a handful of people; expect rough edges, and please open an issue when you find one.
