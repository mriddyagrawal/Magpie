import type { QueryResponse, StatusResponse, CsvPreview } from "./types";
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

export async function postQuery(
  question: string,
  opts: { topK?: number; rewrite?: boolean } = {}
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

export async function getShortcut(): Promise<string> {
  const res = await fetch(`${baseUrl()}/settings/shortcut`);
  if (!res.ok) return "Alt+Space";
  const data = await res.json();
  return data.shortcut ?? "Alt+Space";
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
