import { useState } from "react";
import { previewImageUrl } from "../../api";

export function PdfPreview({ path }: { path: string }) {
  const [page, setPage] = useState(0);
  const [atEnd, setAtEnd] = useState(false);

  const handlePrev = () => {
    setAtEnd(false);
    setPage((p) => Math.max(0, p - 1));
  };
  const handleNext = () => {
    setPage((p) => p + 1);
  };

  return (
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
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-secondary)" }}>
          page {page + 1}
        </span>
        <button onClick={handleNext} disabled={atEnd} style={btnStyle} type="button">
          next →
        </button>
      </div>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  color: "var(--text-secondary)",
  padding: "5px 10px",
  borderRadius: 8,
  background: "rgba(255,255,255,0.05)",
};
