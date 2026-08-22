import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { Source } from "../types";
import { openInOs, revealInFinder } from "../api";
import { Highlighted } from "./Highlighted";

import "./SourcesCard.css";

interface Props {
  sources: Source[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  highlights: string[];
}

export function SourcesCard({ sources, selectedPath, onSelect, highlights }: Props) {
  const [showAll, setShowAll] = useState(false);

  // Cited sources are the point of this card — surface them first and
  // fold the merely-scanned candidates behind a "show more" row, so
  // the citations are visible without scrolling past a long answer
  // plus four irrelevant retrieval candidates.
  const { cited, rest } = useMemo(
    () => ({
      cited: sources.filter((s) => s.cited),
      rest: sources.filter((s) => !s.cited),
    }),
    [sources],
  );
  // Expand automatically when there are no citations yet (retrieval
  // still running) or when the selected file lives in the folded part.
  const expanded =
    showAll ||
    cited.length === 0 ||
    rest.some((r) => r.path === selectedPath);
  const visible = expanded ? [...cited, ...rest] : cited;

  const selectedIdx = useMemo(
    () => visible.findIndex((s) => s.path === selectedPath),
    [visible, selectedPath]
  );

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!visible.length) return;
      const target = e.target as HTMLElement | null;
      // Don't hijack arrow keys when the user is typing in the question input.
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA") return;

      const curr = selectedIdx; // -1 when nothing selected; ArrowDown from -1 correctly lands on index 0
      if (e.key === "ArrowDown") {
        e.preventDefault();
        onSelect(visible[Math.min(visible.length - 1, curr + 1)].path);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        onSelect(visible[Math.max(0, curr - 1)].path);
      } else if (e.key === "Enter" && selectedPath) {
        if (e.metaKey || e.ctrlKey) {
          e.preventDefault();
          revealInFinder(selectedPath).catch(console.error);
        } else {
          e.preventDefault();
          openInOs(selectedPath).catch(console.error);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [visible, selectedIdx, selectedPath, onSelect]);

  return (
    <div className="sources-card magpie-card">
      <div className="sources-card__header">
        <span className="sources-card__label">SOURCES</span>
        <span className="sources-card__count">
          {cited.length} cited / {sources.length}
        </span>
      </div>
      <ul className="sources-card__list">
        {visible.map((s) => (
          <SourceRow
            key={s.path}
            source={s}
            selected={s.path === selectedPath}
            onClick={() => onSelect(s.path)}
            highlights={highlights}
          />
        ))}
      </ul>
      {cited.length > 0 && rest.length > 0 && (
        <button
          type="button"
          className="sources-card__more"
          onClick={() => setShowAll(!showAll)}
        >
          {expanded ? (
            <>
              <ChevronUp size={12} aria-hidden="true" /> Hide scanned files
            </>
          ) : (
            <>
              <ChevronDown size={12} aria-hidden="true" /> {rest.length} more{" "}
              {rest.length === 1 ? "file" : "files"} scanned, not cited
            </>
          )}
        </button>
      )}
    </div>
  );
}

function SourceRow({
  source,
  selected,
  onClick,
  highlights,
}: {
  source: Source;
  selected: boolean;
  onClick: () => void;
  highlights: string[];
}) {
  const { filename, dir } = splitPath(source.path);
  return (
    <li
      className={`source-row ${selected ? "is-selected" : ""} ${source.cited ? "is-cited" : ""}`}
      onClick={onClick}
    >
      <div className="source-row__head">
        <span className="source-row__icon">{fileIcon(filename)}</span>
        <span className="source-row__name" title={source.path}>
          {filename}
        </span>
        <span className="source-row__score" style={{ color: scoreColor(source.score) }}>
          {source.score.toFixed(2)}
        </span>
      </div>
      <div className="source-row__snippet">
        <Highlighted text={source.summary} tokens={highlights} />
      </div>
      <div className="source-row__dir">{dir}</div>
    </li>
  );
}

function splitPath(path: string): { filename: string; dir: string } {
  // Both separators — Windows paths use `\`.
  const slash = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return slash === -1
    ? { filename: path, dir: "" }
    : { filename: path.slice(slash + 1), dir: path.slice(0, slash) };
}

function fileIcon(filename: string): string {
  const ext = filename.slice(filename.lastIndexOf(".")).toLowerCase();
  if ([".png", ".jpg", ".jpeg", ".webp", ".gif"].includes(ext)) return "IMG";
  if (ext === ".pdf") return "PDF";
  if (ext === ".csv") return "CSV";
  if ([".md", ".markdown"].includes(ext)) return "MD";
  if (ext === ".docx") return "DOC";
  if (ext === ".xlsx") return "XLS";
  return "TXT";
}

function scoreColor(score: number): string {
  if (score >= 0.7) return "var(--score-green)";
  if (score >= 0.4) return "var(--score-amber)";
  return "var(--score-grey)";
}
