# Stage 3 — Videos (and other "too-big-to-read" files)

> **Status:** v0 scratch pad. Not the polished Stage 1 / Stage 2 plans yet —
> better versions will follow. Capture now so we can build and iterate.

## The core problem

The current pipeline's answer step re-reads **the whole source file** for any
question (see `answer.py:build_content_blocks`). That's fine for a 30-page
PDF. It's infeasible for a 63 MB `.mov`:

- Video bytes can't be fed to a text/vision LLM in any useful way per-question.
- Frame-by-frame vision on demand would be wildly expensive.
- The information the user actually asks about (who is in the video, what
  happens, when) is *semantic*, not pixel-level — so we don't need the
  bytes at answer time if we've already extracted the semantics once.

## The chosen route — `.alt` as content (not a summary pointer)

For any file too large to read directly, ship a **sidecar file**
(`<video>.alt`) that is itself a compact, structured, text artifact
capturing everything answerable about the source:

- metadata (filename, hash, path, duration, codec)
- one-liner + full prose summary
- **scenes** with timecodes, descriptions, setting, mood
- themes, quotes, search tokens
- optional thumbnails

The `.alt` plays **two roles in a single file**:

| Role | Consumer | Notes |
|---|---|---|
| Discovery artifact | Stage 2 ingest (Qdrant) | its prose becomes the embedded summary |
| Content artifact   | Stage 4 answer | `Source:` points at the `.alt`; answer step reads the YAML directly |

The underlying `.mov` / `.mp4` is **never read by the pipeline at query
time**. It's referenced for the user's benefit (clickable link, citation)
but the `.alt` is authoritative for Q&A.

This generalizes: any too-big file (large archives, raw datasets, multi-GB
logs) can ship an `.alt` sidecar and flow through the same pipeline
unmodified.

## Pathways we considered

1. **Vision embedding models (InternVideo / VideoCLIP).**
   Rejected for v1 — different vector space, GPU required, breaks the
   existing MiniLM + BM25 stack. Revisit if we add a visual-similarity
   search surface.

2. **Whisper-only transcript embedding.**
   Misses visual content (a dance, a banner, audience reactions). Useful
   **complement** for lecture / podcast videos, not a replacement for
   `.alt`. Add later as a companion `.transcript.vtt` that emits additional
   Qdrant points alongside the `.alt`.

3. **Per-keyframe CLIP search.**
   Good for "find the frame where X appears on screen" — a different
   query surface than "what is this video about." Phase 3.

4. **Read the whole `.mov` at answer time with a video-capable LLM.**
   Fails on cost and latency. Even Gemini video comprehension would
   burn hundreds of tokens per question per video. Not viable for scale.

5. **`.alt` as content (chosen).**
   One-time generation cost. Cheap to embed, cheap to read at answer
   time, works for arbitrary video length, generalizes to other
   "too-big" file types.

## Refinements to the format / pipeline

### 1. Per-scene Qdrant points

If the `.alt` includes a `scenes:` list, emit **one Qdrant point per scene**
(payload includes `timecode`) in addition to one file-level point. This
lets queries like "when does the second dancer join?" resolve to
`00:30`, not just "somewhere in IMG_9556.MOV".

Mirrors how CSV ingest already works (one point per row via
`upsert_csv_rows`). Minimal change to Stage 2: new dispatch for `.alt`
sources.

### 2. `Source:` points at the `.alt`, not the video

- Answer step reads `.alt` text successfully (it's just YAML/text).
- Answer step would fail on the `.mov` bytes.
- The `.alt`'s own `source.local_path` field still tells the user / UI
  where the real video lives for playback / citation.

### 3. Hard-skip videos without an `.alt`

If the pipeline encounters a `.mp4` / `.mov` / `.mkv` / `.webm` without a
sibling `.alt`, log loudly and skip. Silent skips produce invisible gaps
in the index. A future `ns alt <video>` helper can auto-generate `.alt`
from ffprobe + keyframe sampling + vision LLM, but that is out of scope
for v1.

### 4. Hashing / change detection

Use the existing `Manifest` machinery: keyed on `.alt` path, byte size
for change detection. When the `.alt` changes (re-generated), Stage 2
re-ingests automatically.

## Scale considerations

- Generation is the only expensive step, and it's **one-time per video**.
  Cached on disk as a 2–5 KB text file, git-diffable, re-usable across
  machines.
- Embedding a 2 KB YAML is cheap — same cost as embedding any other
  summary markdown.
- Per-scene chunking increases point count by ~5–30× per video, but each
  point's vector payload is still tiny. Qdrant scales to millions of
  points without issue.
- The `.alt` format is LLM-generable (per the prior design session) —
  a small pipeline of `ffprobe` + keyframe grid + single vision-LLM
  call produces a usable `.alt` in seconds.

## Module layout (v1)

```
src/stage3/
├── __init__.py
├── __main__.py          # CLI: python -m src.stage3 index <path>
├── alt.py               # .alt YAML → AltDocument dataclass
├── transcode.py         # AltDocument → ParsedSummary(file-level + per-scene)
└── index.py             # walk dir, find .alt files, register in manifest
```

Pipeline wiring:

```
.alt files on disk
   │
   ▼
src/stage3 index  ──►  Test Summaries/<hash>_video.md   (file-level)
                  ──►  Test Summaries/<hash>_s00_00.md  (per-scene)
                  ──►  _manifest.json rows
   │
   ▼
src/stage2 ingest  (unchanged — picks up new summaries from manifest)
   │
   ▼
Qdrant (summaries collection, per-scene + file-level points)
   │
   ▼
src/pipeline ask  (unchanged — Source: .alt, answer step reads YAML)
```

## What's NOT in v1

- Auto-generating `.alt` from raw video bytes (`ns alt <video>`).
- Whisper transcript companions.
- Per-keyframe CLIP search.
- A dedicated "Test Videos" walker mode for Stage 1 (Stage 3 owns video
  discovery).
- Video playback / UI integration — we return `source.local_path` in
  answers and that's it.

## Open questions

1. Should `Source:` for a per-scene point include the timecode
   (`Source: path/to/IMG_9556.alt#00:30`) so the answer step can slice
   into just that scene? v1 keeps it simple (no fragment; answer step
   reads the whole `.alt`).
2. Should `.alt` files be discovered automatically by Stage 1 too, or
   only by Stage 3's dedicated walker? v1 uses a dedicated walker to
   keep concerns separate.
3. Deduplication: if multiple scenes of the same video get retrieved,
   we currently feed the same `.alt` to the answer step N times. A
   simple path-set dedup at the retrieval boundary fixes this; worth
   doing but not blocking.
