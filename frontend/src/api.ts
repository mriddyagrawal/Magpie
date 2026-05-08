import type {
  CsvPreview,
  QueryResponse,
  RecentEntry,
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
  // Build the body so the `rewrite` field is OMITTED (not sent as false)
  // when the caller doesn't pass a value. Pydantic on the server side
  // then defaults to None and falls back to the REWRITE env var. If we
  // sent `rewrite: false` here it'd be an explicit override that
  // shadows the .env setting silently. See `src/server.py:QueryRequest`.
  const body: Record<string, unknown> = {
    question,
    top_k: opts.topK ?? 5,
  };
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

export async function fetchTextPreview(path: string): Promise<string> {
  const res = await fetch(`${baseUrl()}/preview?path=${encodeURIComponent(path)}`);
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
  cite_sources_inline?: boolean;  // PR 5 addition
}

export type SearchSettingsPatch = Partial<{
  provider: "local" | "cloud";
  top_k: number;
  rewrite: boolean;
  temperature: number;
  cite_sources_inline: boolean;
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
  default_action: "empty" | "last";
  launch_at_login: boolean;
  show_in_tray: boolean;
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
