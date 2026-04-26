import { useEffect, useState } from "react";
import { fetchTextPreview } from "../../api";
import { Highlighted } from "../Highlighted";

export function TextPreview({ path, highlights }: { path: string; highlights: string[] }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setText(null);
    setError(null);
    fetchTextPreview(path).then(setText).catch((e: Error) => setError(e.message));
  }, [path]);

  if (error) return <div style={{ color: "#ff8e8e" }}>{error}</div>;
  if (text === null) return <div style={{ color: "var(--text-dim)" }}>loading…</div>;

  return (
    <pre
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        lineHeight: 1.55,
        color: "var(--text-primary)",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        margin: 0,
      }}
    >
      <Highlighted text={text} tokens={highlights} />
    </pre>
  );
}
