import { useEffect, useState } from "react";
import { fetchTextPreview, previewImageUrl } from "../../api";
import { Highlighted } from "../Highlighted";

/**
 * PDF preview with two views:
 *   - Page: rendered page image + prev/next pager (the original view)
 *   - Text: extracted text with the answer's evidence terms highlighted
 *     — "where in the paper does this answer come from". Rendered
 *     pages are rasterized images, so highlighting is only possible
 *     here. True on-page highlight boxes are a v2 (needs per-word
 *     coordinates from the extractor).
 *
 * Defaults to Text when there are highlight terms to show (the user
 * just asked a question — evidence is the interesting view), Page
 * otherwise.
 */
export function PdfPreview({
  path,
  highlights = [],
}: {
  path: string;
  highlights?: string[];
}) {
  const [view, setView] = useState<"page" | "text">(
    highlights.length > 0 ? "text" : "page",
  );
  const [page, setPage] = useState(0);
  const [atEnd, setAtEnd] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [textError, setTextError] = useState<string | null>(null);

  // Reset pager + text cache when the file changes.
  useEffect(() => {
    setPage(0);
    setAtEnd(false);
    setText(null);
    setTextError(null);
  }, [path]);

  // Lazy-fetch extracted text the first time the Text view is shown.
  useEffect(() => {
    if (view !== "text" || text !== null || textError !== null) return;
    fetchTextPreview(path, "text")
      .then(setText)
      .catch((e: Error) => setTextError(e.message));
  }, [view, text, textError, path]);

  const handlePrev = () => {
    setAtEnd(false);
    setPage((p) => Math.max(0, p - 1));
  };
  const handleNext = () => {
    setPage((p) => p + 1);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "stretch", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 4 }}>
        <button
          onClick={() => setView("text")}
          style={view === "text" ? activeToggleStyle : btnStyle}
          type="button"
          title="Extracted text with answer terms highlighted"
        >
          Text
        </button>
        <button
          onClick={() => setView("page")}
          style={view === "page" ? activeToggleStyle : btnStyle}
          type="button"
          title="Rendered page"
        >
          Page
        </button>
      </div>

      {view === "text" ? (
        textError ? (
          <div style={{ color: "#ff8e8e", fontSize: 12 }}>{textError}</div>
        ) : text === null ? (
          <div style={{ color: "var(--text-dim)", fontSize: 12 }}>loading…</div>
        ) : (
          <pre
            style={{
              fontFamily: "var(--font-body)",
              fontSize: 12,
              lineHeight: 1.6,
              color: "var(--text-primary)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              margin: 0,
            }}
          >
            <Highlighted text={text} tokens={highlights} />
          </pre>
        )
      ) : (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
          <img
            key={`${path}:${page}`}
            src={previewImageUrl(path, page)}
            alt={`${path} page ${page + 1}`}
            style={{ maxWidth: "100%", objectFit: "contain", borderRadius: 8 }}
            onLoad={() => setAtEnd(false)}
            onError={() => {
              setAtEnd(true);
              setPage((p) => Math.max(0, p - 1));
            }}
          />
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <button onClick={handlePrev} disabled={page === 0} style={btnStyle} type="button">
              ← prev
            </button>
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              page {page + 1}
            </span>
            <button onClick={handleNext} disabled={atEnd} style={btnStyle} type="button">
              next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  fontSize: 11,
  color: "var(--text-secondary)",
  padding: "5px 10px",
  borderRadius: 8,
  background: "rgba(255,255,255,0.05)",
};

const activeToggleStyle: React.CSSProperties = {
  ...btnStyle,
  color: "var(--text-primary)",
  background: "rgba(255,255,255,0.14)",
};
