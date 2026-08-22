import { useEffect, useState } from "react";
import { fetchCsvPreview } from "../../api";
import type { CsvPreview as CsvPreviewData } from "../../types";
import { Highlighted } from "../Highlighted";

export function CsvPreview({ path, highlights }: { path: string; highlights: string[] }) {
  const [data, setData] = useState<CsvPreviewData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    fetchCsvPreview(path).then(setData).catch((e: Error) => setError(e.message));
  }, [path]);

  if (error) return <div style={{ color: "#ff8e8e" }}>{error}</div>;
  if (!data) return <div style={{ color: "var(--text-dim)" }}>loading…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
      {data.truncated && (
        <div style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
          (truncated to first 500 rows)
        </div>
      )}
      <div style={{ overflowX: "auto", border: "1px solid var(--border-soft)", borderRadius: 8 }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12, fontFamily: "var(--font-mono)", minWidth: "100%" }}>
          <thead>
            <tr>
              {data.columns.map((col) => (
                <th
                  key={col}
                  style={{
                    textAlign: "left",
                    padding: "8px 12px",
                    borderBottom: "1px solid var(--border-soft)",
                    color: "var(--text-secondary)",
                    fontWeight: 500,
                    whiteSpace: "nowrap",
                    background: "rgba(0,0,0,0.25)",
                    position: "sticky",
                    top: 0,
                  }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, i) => (
              <tr key={i} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                {row.map((cell, j) => (
                  <td
                    key={j}
                    style={{
                      padding: "6px 12px",
                      color: "var(--text-primary)",
                      verticalAlign: "top",
                      maxWidth: 360,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={cell}
                  >
                    <Highlighted text={cell} tokens={highlights} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
