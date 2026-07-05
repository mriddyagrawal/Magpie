// TS mirrors of the Python server's schemas (src/server.py).

export interface Source {
  path: string;       // repo-relative or absolute
  summary: string;    // snippet shown in the sources list
  score: number;      // 0..1, higher is more relevant
  cited: boolean;     // whether the answer model listed this in sources_used
}

export interface SearchQuery {
  query: string;
  keywords: string[];
}

export interface QueryResponse {
  question: string;
  answer: string;
  sources: Source[];
  search_query: SearchQuery;
  // Not-found state — when the answer pipeline could not find an answer
  // in the retrieved files. The ask bar's State 5 ("Answer not found"
  // with single Add-folder CTA) renders when this is true. See
  // Specs/UI/ask_bar.md.
  not_found: boolean;
  not_found_topic: string;
  sources_scanned_count: number;
  // ORDERED list of paths the answer actually drew from. Inline `[N]`
  // citation markers are 1-based indexes into THIS list (per the
  // src/answer.py prompt contract) — NOT into `sources`, which is the
  // full retrieval candidate list.
  sources_used: string[];
  // The recents.json entry id this ask was just persisted to. Lets the
  // frontend update its in-memory recents list without an extra GET.
  recent_id: string | null;
}

// ---------------------------------------------------------------------------
// Recents — mirror of src/recents.py:RecentEntry
// ---------------------------------------------------------------------------

// The discriminated-union-style Answer shape from the backend. We keep
// it as a flat type rather than a Pydantic-style discriminated union
// because (a) the backend's `Answer` is also flat-with-bool (Plan #25),
// and (b) the renderer just dispatches on `not_found` regardless.
export interface RecentResult {
  answer: string;
  sources_used: string[];
  not_found: boolean;
  not_found_topic: string;
}

export interface RecentEntry {
  id: string;                       // "rec_<12 hex chars>"
  asked_at: string;                 // ISO-8601 with timezone
  question: string;
  rewritten_query: string | null;
  result: RecentResult;
  // True when the search index has been updated since this entry was
  // persisted (computed server-side from manifest.json's mtime). The
  // ask bar uses this to decide between rendering the cached payload
  // (fresh) vs firing a fresh /query (stale). Default false when the
  // backend hasn't been updated to populate the field.
  is_stale?: boolean;
}

export interface StatusResponse {
  ready: boolean;
  indexed_count: number;
  version: string;
  // Settings UI extras (PR 5):
  provider: string;       // "local" | "cloud"
  model: string;          // human-readable model name
  size_mb: number | null; // on-disk Qdrant collection size
}

export interface CsvPreview {
  columns: string[];
  rows: string[][];
  truncated: boolean;
}
