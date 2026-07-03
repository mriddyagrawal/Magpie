import { previewKindFor, revealInFinder, openInOs } from "../api";
import { ImagePreview } from "./previews/ImagePreview";
import { PdfPreview } from "./previews/PdfPreview";
import { CsvPreview } from "./previews/CsvPreview";
import { TextPreview } from "./previews/TextPreview";

import "./PreviewCard.css";

interface Props {
  path: string | null;
  highlights: string[];
}

export function PreviewCard({ path, highlights }: Props) {
  if (!path) {
    return (
      <div className="preview-card magpie-card preview-card--empty">
        <div className="preview-card__empty-text">
          Select a source to preview it here.
        </div>
      </div>
    );
  }

  const kind = previewKindFor(path);
  const filename = path.slice(path.lastIndexOf("/") + 1);

  return (
    <div className="preview-card magpie-card">
      <div className="preview-card__header">
        <div className="preview-card__filename">
          <span className="preview-card__icon">{fileLabel(path)}</span>
          <span className="preview-card__name">{filename}</span>
          <span className="preview-card__dir">~/{path}</span>
        </div>
        <div className="preview-card__actions">
          <button
            className="preview-card__btn"
            onClick={() => openInOs(path).catch(console.error)}
            title="Open in default app (Enter)"
          >
            ↗ open
          </button>
          <button
            className="preview-card__btn"
            onClick={() => revealInFinder(path).catch(console.error)}
            title="Reveal in Finder (⌘+Enter)"
          >
            ↺ reveal in finder
          </button>
        </div>
      </div>
      <div className="preview-card__body">
        {kind === "image" && <ImagePreview path={path} />}
        {kind === "pdf" && <PdfPreview path={path} />}
        {kind === "csv" && <CsvPreview path={path} highlights={highlights} />}
        {kind === "text" && <TextPreview path={path} highlights={highlights} />}
        {kind === "unsupported" && (
          <div className="preview-card__unsupported">
            No inline preview for this file type. Use "open" to view it in the default app.
          </div>
        )}
      </div>
    </div>
  );
}

function fileLabel(path: string): string {
  const ext = path.slice(path.lastIndexOf(".")).toLowerCase();
  const map: Record<string, string> = {
    ".png": "PNG", ".jpg": "JPG", ".jpeg": "JPG", ".webp": "WEBP", ".gif": "GIF",
    ".pdf": "PDF", ".csv": "CSV", ".md": "MD", ".markdown": "MD",
    ".docx": "DOCX", ".xlsx": "XLSX", ".txt": "TXT", ".json": "JSON",
  };
  return map[ext] ?? (ext.slice(1).toUpperCase() || "FILE");
}
