import type { QueryResponse, StatusResponse, CsvPreview } from "./types";

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
  const res = await fetch(`${baseUrl()}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      top_k: opts.topK ?? 5,
      rewrite: opts.rewrite ?? false,
    }),
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
