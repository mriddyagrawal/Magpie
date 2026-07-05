import type {
  CsvPreview,
  QueryResponse,
  RecentEntry,
  SearchQuery,
  Source,
  StatusResponse,
} from "./types";
import { invoke } from "@tauri-apps/api/core";

// Tauri's shell injects `window.__MAGPIE_PORT__` at startup, reading it from
// the Python sidecar's first stdout line. 8765 is the dev fallback when the
// sidecar is started separately via `uvicorn --port 8765`.
declare global {
  interface Window {
    __MAGPIE_PORT__?: number;
  }
}

function baseUrl(): string {
  const port = window.__MAGPIE_PORT__ ?? 8765;
  return `http://127.0.0.1:${port}`;
}

/** Translate opaque fetch failures ("Failed to fetch") into copy the
 *  user can act on. Settings tabs pass every caught error through this
 *  before showing it in an error banner, so a dead engine produces a
 *  loud, honest message instead of silence or jargon. */
export function friendlyError(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  if (/failed to fetch|load failed|networkerror/i.test(msg)) {
    return "Couldn't reach Magpie's engine — your change was not saved. It usually comes back within a few seconds; then try again.";
  }
  return msg;
}

export interface HistoryTurn {
  question: string;
  answer: string;
}

export async function postQuery(
  question: string,
  opts: {
    topK?: number;
    rewrite?: boolean;
    /** Conversational context: last N (question, answer) pairs sent to
     *  the LLM so follow-ups resolve references. Empty/omit for a
     *  single-shot ask. Lifetime is the caller's concern; the API
     *  client just forwards. */
    history?: HistoryTurn[];
  } = {}
): Promise<QueryResponse> {
  // Build the body so `top_k` and `rewrite` are OMITTED (not sent as
  // some hardcoded default) when the caller doesn't pass a value.
  // Pydantic on the server side then defaults to None and falls back
  // to the persisted setting (Settings → Search & AI's Top K slider /
  // Rewrite toggle, both surfaced via `effective_settings()`). If we
  // sent a hardcoded `top_k: 5` here it'd silently shadow the user's
  // Settings choice. See `src/server.py:QueryRequest`.
  const body: Record<string, unknown> = { question };
  if (opts.topK !== undefined) {
    body.top_k = opts.topK;
  }
  if (opts.rewrite !== undefined) {
    body.rewrite = opts.rewrite;
  }
  if (opts.history && opts.history.length > 0) {
    body.history = opts.history;
  }
  const res = await fetch(`${baseUrl()}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`query failed: ${res.status} ${await res.text()}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// /query/stream — SSE streaming variant
// ---------------------------------------------------------------------------
//
// Same inputs as `postQuery`, but yields a typed event stream so the
// caller can paint the sources card the moment retrieval finishes —
// before the answer LLM call returns — and append answer text as
// chunks arrive. Wire format defined in `src/server.py:query_stream`
// block comment.
//
// The emitted shape:
//
//   `sources`         — fires once after retrieval. Frontend renders
//                       the sources card with `cited: false` placeholders.
//   `not_found_topic` — fires when the answer pipeline declares not-found.
//                       Terminal branch: no `answer_chunk` / `sources_used`
//                       follow. Frontend transitions to the not-found card.
//   `answer_chunk`    — fires N times during the answer phase, each
//                       carrying a slice of the answer text. Caller
//                       appends `text` to its in-progress buffer.
//                       Phase 1: this fires exactly once with the full
//                       answer; Phase 2 will fire many times as tokens
//                       stream from the LLM.
//   `sources_used`    — fires once after the final `answer_chunk` with
//                       the cited paths. Frontend reconciles the
//                       `cited` flag on its sources state here.
//   `done`            — terminal. Fires last in every successful and
//                       error stream. Carries `recent_id` for the
//                       persisted recents entry.
//   `error`           — retrieval or answer threw. Followed by `done`.
//
// Usage:
//   const buffer: string[] = [];
//   for await (const ev of postQueryStream(question)) {
//     switch (ev.type) {
//       case 'sources':         setSources(ev.sources); break;
//       case 'not_found_topic': setView({ kind: 'not_found', topic: ev.topic }); break;
//       case 'answer_chunk':    buffer.push(ev.text); setAnswer(buffer.join('')); break;
//       case 'sources_used':    setCited(ev.paths); break;
//       case 'error':           setError(ev.detail); break;
//       case 'done':            setRecentId(ev.recentId); break;
//     }
//   }

export interface StreamSourcesEvent {
  type: "sources";
  sources: Source[];
  searchQuery: SearchQuery;
  rewrittenQuery: string | null;
  sourcesScannedCount: number;
}

export interface StreamNotFoundTopicEvent {
  type: "not_found_topic";
  topic: string;
}

export interface StreamAnswerChunkEvent {
  type: "answer_chunk";
  text: string;
}

export interface StreamSourcesUsedEvent {
  type: "sources_used";
  paths: string[];
}

export interface StreamDoneEvent {
  type: "done";
  recentId: string | null;
}

export interface StreamErrorEvent {
  type: "error";
  detail: string;
  phase: "retrieval" | "answer";
}

export type StreamEvent =
  | StreamSourcesEvent
  | StreamNotFoundTopicEvent
  | StreamAnswerChunkEvent
  | StreamSourcesUsedEvent
  | StreamDoneEvent
  | StreamErrorEvent;

/** Parse one SSE frame (without the trailing blank line) into a typed
 *  StreamEvent, or `null` if the frame doesn't carry one of our known
 *  event names. Unknown event types are silently dropped — the wire is
 *  forward-compatible with future backend additions. */
function parseSseFrame(raw: string): StreamEvent | null {
  let event = "";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      // SSE allows multiple data: lines per frame; spec joins them with
      // \n. Our backend always emits a single data: line per frame, but
      // we honor the spec to stay compatible with proxy reformatters.
      dataLines.push(line.slice(5).trimStart());
    }
    // Comment lines (lines starting with ":") and unknown fields ignored.
  }
  const data = dataLines.join("\n");
  if (!event) return null;
  let payload: any;
  try {
    payload = JSON.parse(data);
  } catch {
    return null;
  }
  switch (event) {
    case "sources":
      return {
        type: "sources",
        sources: payload.retrieved ?? [],
        searchQuery: payload.search_query ?? { query: "", keywords: [] },
        rewrittenQuery: payload.rewritten_query ?? null,
        sourcesScannedCount: payload.sources_scanned_count ?? 0,
      };
    case "not_found_topic":
      return { type: "not_found_topic", topic: payload.topic ?? "" };
    case "answer_chunk":
      return { type: "answer_chunk", text: payload.text ?? "" };
    case "sources_used":
      return { type: "sources_used", paths: payload.paths ?? [] };
    case "done":
      return { type: "done", recentId: payload.recent_id ?? null };
    case "error":
      return {
        type: "error",
        detail: payload.detail ?? "Something went wrong.",
        phase: payload.phase === "retrieval" ? "retrieval" : "answer",
      };
    default:
      return null;
  }
}

export async function* postQueryStream(
  question: string,
  opts: {
    topK?: number;
    rewrite?: boolean;
    history?: HistoryTurn[];
  } = {}
): AsyncGenerator<StreamEvent, void, unknown> {
  // Body construction mirrors postQuery: omit fields we don't have so
  // the server's effective_settings() is the source of truth.
  const body: Record<string, unknown> = { question };
  if (opts.topK !== undefined) body.top_k = opts.topK;
  if (opts.rewrite !== undefined) body.rewrite = opts.rewrite;
  if (opts.history && opts.history.length > 0) body.history = opts.history;

  const res = await fetch(`${baseUrl()}/query/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const detail = res.ok ? "no response body" : await res.text();
    throw new Error(`query/stream failed: ${res.status} ${detail}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  // Frames are separated by blank lines (\n\n). Stream chunks may split
  // a frame, so we accumulate into `buf` and flush whole frames on each
  // \n\n boundary. Anything trailing stays in `buf` for the next chunk.
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      // Flush any final frame that didn't have a trailing \n\n. Real
      // backends usually emit it; this is defense-in-depth.
      if (buf.trim().length > 0) {
        const ev = parseSseFrame(buf);
        if (ev) yield ev;
      }
      return;
    }
    buf += decoder.decode(value, { stream: true });
    let sep = buf.indexOf("\n\n");
    while (sep !== -1) {
      const frame = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      const ev = parseSseFrame(frame);
      if (ev) yield ev;
      // `done` is terminal — caller can break, but the server also
      // closes the response right after, so the outer reader.read()
      // will return done=true on the next iteration.
      sep = buf.indexOf("\n\n");
    }
  }
}

export async function getStatus(): Promise<StatusResponse> {
  const res = await fetch(`${baseUrl()}/status`);
  if (!res.ok) throw new Error(`status failed: ${res.status}`);
  return res.json();
}

/** For images and PDFs — the frontend uses this URL directly as an `<img src>`. */
export function previewImageUrl(path: string, page = 0): string {
  return `${baseUrl()}/preview?path=${encodeURIComponent(path)}&page=${page}`;
}

export async function fetchCsvPreview(path: string): Promise<CsvPreview> {
  const res = await fetch(`${baseUrl()}/preview?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`csv preview failed: ${res.status}`);
  return res.json();
}

export async function fetchTextPreview(path: string, mode?: "text"): Promise<string> {
  const modeParam = mode ? `&mode=${mode}` : "";
  const res = await fetch(`${baseUrl()}/preview?path=${encodeURIComponent(path)}${modeParam}`);
  if (!res.ok) throw new Error(`text preview failed: ${res.status}`);
  return res.text();
}

export async function openInOs(path: string): Promise<void> {
  const res = await fetch(`${baseUrl()}/open?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`open failed: ${res.status}`);
}

export async function revealInFinder(path: string): Promise<void> {
  const res = await fetch(`${baseUrl()}/reveal?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`reveal failed: ${res.status}`);
}

export async function pickFolder(): Promise<string | null> {
  try {
    return await invoke<string | null>("pick_folder");
  } catch {
    return null;
  }
}

export async function pickFile(): Promise<string | null> {
  try {
    return await invoke<string | null>("pick_file");
  } catch {
    return null;
  }
}

export interface IngestStatus {
  running: boolean;
  done: boolean;
  error: string | null;
  path: string | null;
  files_total: number;
  files_done: number;
  current_file: string | null;
  elapsed_s: number | null;
  stopped: boolean;
  // "idle" | "scanning" | "indexing". Frontend uses this to label the
  // status pill differently during the scan phase (no per-file
  // progress yet). Backwards-compat: missing field → "idle".
  phase?: "idle" | "scanning" | "indexing";
}

export interface IndexPlanFolder {
  path: string;
  enabled: boolean;
  total: number;       // candidate files under this root
  remaining: number;   // candidates not yet in the manifest
}

export interface IndexPlan {
  folders: IndexPlanFolder[];
  grand_total: number;
  grand_remaining: number;
}

/** Read-only preview of what /index/sync would do. Walks each enabled
 * root and returns per-folder counts. Cached server-side for 10s. */
export async function getIndexPlan(): Promise<IndexPlan> {
  const res = await fetch(`${baseUrl()}/index/plan`);
  if (!res.ok) throw new Error(`index/plan failed: ${res.status}`);
  return res.json();
}

export async function startIngest(path: string): Promise<void> {
  const res = await fetch(`${baseUrl()}/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function getIngestStatus(): Promise<IngestStatus> {
  const res = await fetch(`${baseUrl()}/ingest/status`);
  if (!res.ok) throw new Error(`ingest/status failed: ${res.status}`);
  return res.json();
}

export async function stopIngest(): Promise<void> {
  await fetch(`${baseUrl()}/ingest/stop`, { method: "POST" });
}

export interface FolderEntry {
  path: string;
  enabled: boolean;
  // Settings → Data tab (PR 5):
  display_name?: string | null;     // user-friendly label override
  files: number;                     // count from manifest
  size_bytes: number;                // sum of entry.size for files under this root
  last_read_at: string | null;       // ISO; max ingested_at across the folder
}

export async function getFolders(): Promise<{ folders: FolderEntry[]; ingest_running: boolean }> {
  const res = await fetch(`${baseUrl()}/settings/folders`);
  if (!res.ok) throw new Error(`settings/folders failed: ${res.status}`);
  return res.json();
}

export async function addFolder(path: string): Promise<{ status: string }> {
  const res = await fetch(`${baseUrl()}/settings/folders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function removeFolder(path: string): Promise<void> {
  const res = await fetch(`${baseUrl()}/settings/folders?path=${encodeURIComponent(path)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await res.text());
}

export interface FolderPatchBody {
  path: string;
  enabled?: boolean;
  display_name?: string | null;
}

export async function patchFolder(body: FolderPatchBody): Promise<{
  status: string; path: string; enabled: boolean; display_name: string | null;
}> {
  const res = await fetch(`${baseUrl()}/settings/folders`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getShortcut(): Promise<string> {
  const res = await fetch(`${baseUrl()}/settings/shortcut`);
  if (!res.ok) return "Alt+Space";
  const data = await res.json();
  return data.shortcut ?? "Alt+Space";
}

export async function putShortcut(shortcut: string): Promise<void> {
  const res = await fetch(`${baseUrl()}/settings/shortcut`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shortcut }),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ---------------------------------------------------------------------------
// Settings — Search & AI tab
// ---------------------------------------------------------------------------

export interface SearchSettings {
  provider: string;       // "local" | "cloud"
  model: string;
  top_k: number;
  rewrite: boolean;
  temperature: number;
  cite_sources_inline: boolean;
  enumerate_lists: boolean;
}

export type SearchSettingsPatch = Partial<{
  provider: "local" | "cloud";
  top_k: number;
  rewrite: boolean;
  temperature: number;
  cite_sources_inline: boolean;
  enumerate_lists: boolean;
}>;

export async function getSearchSettings(): Promise<SearchSettings> {
  const res = await fetch(`${baseUrl()}/settings/search`);
  if (!res.ok) throw new Error(`settings/search failed: ${res.status}`);
  return res.json();
}

export async function patchSearchSettings(patch: SearchSettingsPatch): Promise<SearchSettings> {
  const res = await fetch(`${baseUrl()}/settings/search`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface ProvidersInfo {
  local: { available: boolean; model: string; downloaded: boolean };
  cloud: { available: boolean; model: string; configured: boolean; provider?: string };
}

export async function getProviders(): Promise<ProvidersInfo> {
  const res = await fetch(`${baseUrl()}/settings/search/providers`);
  if (!res.ok) throw new Error(`settings/search/providers failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Settings — Shortcut & App tab
// ---------------------------------------------------------------------------

export interface AppSettings {
  theme: "system" | "light" | "dark";
  accent: "ink" | "amber" | "jade" | "rose";
  launch_at_login: boolean;
}

export type AppSettingsPatch = Partial<AppSettings>;

export async function getAppSettings(): Promise<AppSettings> {
  const res = await fetch(`${baseUrl()}/settings/app`);
  if (!res.ok) throw new Error(`settings/app failed: ${res.status}`);
  return res.json();
}

export async function patchAppSettings(patch: AppSettingsPatch): Promise<AppSettings> {
  const res = await fetch(`${baseUrl()}/settings/app`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ---------------------------------------------------------------------------
// Diagnostics — "Why isn't this indexed?"
// ---------------------------------------------------------------------------

export interface WhyNotResponse {
  path: string;
  resolved_path: string | null;
  indexed: boolean;
  reason: string;
}

export async function diagnosticsWhyNot(path: string): Promise<WhyNotResponse> {
  const url = new URL(`${baseUrl()}/diagnostics/why-not`);
  url.searchParams.set("path", path);
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`why-not failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Settings — Exclusions sub-panel (Data tab)
// ---------------------------------------------------------------------------

export interface ExclusionsResponse {
  paths: string[];
  globs: string[];
}

export async function getExclusions(): Promise<ExclusionsResponse> {
  const res = await fetch(`${baseUrl()}/settings/exclusions`);
  if (!res.ok) throw new Error(`settings/exclusions failed: ${res.status}`);
  return res.json();
}

export async function addExclusion(body: { path?: string; glob?: string }): Promise<{ status: string }> {
  const res = await fetch(`${baseUrl()}/settings/exclusions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function removeExclusion(type: "path" | "glob", value: string): Promise<void> {
  const res = await fetch(
    `${baseUrl()}/settings/exclusions?type=${type}&value=${encodeURIComponent(value)}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error(await res.text());
}

// ---------------------------------------------------------------------------
// Index — global Sync / Reindex buttons
// ---------------------------------------------------------------------------

export interface IndexJobResponse {
  status: string;  // "started"
  kind: string;    // "sync" | "reindex"
}

export async function runSync(): Promise<IndexJobResponse> {
  const res = await fetch(`${baseUrl()}/index/sync`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function runReindex(): Promise<IndexJobResponse> {
  const res = await fetch(`${baseUrl()}/index/reindex`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ---------------------------------------------------------------------------
// /recents — the user's last N questions, with cached results
// ---------------------------------------------------------------------------
// Backs the ask bar's RECENT panel (Specs/UI/ask_bar.md State 2). Replaying
// a recent calls `getRecent(id)` and re-renders the answer card from the
// cached payload without firing a fresh /query call.

export async function getRecents(): Promise<RecentEntry[]> {
  const res = await fetch(`${baseUrl()}/recents`);
  if (!res.ok) throw new Error(`recents failed: ${res.status}`);
  const data = await res.json();
  return (data.recents ?? []) as RecentEntry[];
}

export async function getRecent(id: string): Promise<RecentEntry | null> {
  const res = await fetch(`${baseUrl()}/recents/${encodeURIComponent(id)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`recent ${id} failed: ${res.status}`);
  return res.json();
}

/** File-extension router — drives which preview component is rendered. */
export type PreviewKind = "image" | "pdf" | "csv" | "text" | "unsupported";

export function previewKindFor(path: string): PreviewKind {
  const ext = path.slice(path.lastIndexOf(".")).toLowerCase();
  if ([".png", ".jpg", ".jpeg", ".webp", ".gif"].includes(ext)) return "image";
  if (ext === ".pdf") return "pdf";
  if (ext === ".csv") return "csv";
  if ([".md", ".markdown", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx",
       ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".rb",
       ".swift", ".kt", ".sh", ".sql", ".json", ".yaml", ".yml", ".toml"].includes(ext))
    return "text";
  return "unsupported";
}
