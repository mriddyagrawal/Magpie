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
}

export interface StatusResponse {
  llm_provider: string;
  llm_model: string;
  qdrant_provider: string;
  indexed_count: number;
}

export interface CsvPreview {
  columns: string[];
  rows: string[][];
  truncated: boolean;
}
