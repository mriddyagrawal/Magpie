# Stage 1 — Summarization: Input / Output

## Full Flow Diagram

```
┌─────────────────────────────┐
│  Raw Document               │
│  (PDF, DOCX, XLSX, image,   │
│   text, code, markdown)     │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 1: File Detection     │
│  IN:  file path or dir path │
│  OUT: list of supported     │
│       file paths            │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 2: Text Extraction    │
│  IN:  single file path      │
│  OUT: raw text string       │
│       (extracted from file) │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 3: Kimi Summarization │
│  IN:  extracted text +      │
│       filename hint         │
│  OUT: FileSummary object    │
│       {title, summary,      │
│        content_type,        │
│        keywords,            │
│        key_entities}        │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 4: Markdown Write     │
│  IN:  FileSummary + path    │
│  OUT: Test Summaries/<hash>.md   │
└─────────────────────────────┘
```

---

## Step 1: File Detection

**Input:** A file path or directory path
```
"Test Content/"
```

**Output:** List of supported files filtered by extension
```
[
  "Test Content/Flight GSP - Hartford Receipt.pdf",
  "Test Content/Artwork Analysis.pdf",
  "Test Content/Book VII - Plato's Republic.pdf",
  "Test Content/Artwork Analysis.docx",
  "Test Content/Copy of Data Science and Machine Learning Club Budget.xlsx"
]
```

---

## Step 2: Text Extraction

**Input:** A single file path
```
Path("Test Content/Flight GSP - Hartford Receipt.pdf")
```

**Output:** Raw text content extracted from the file
```
"Breeze Airways\nFlight Receipt\nConfirmation: X7QK2M\n
Customer Reference: 40-000000000\nDate: March 24, 2026\n
Traveler: Mridul Agrawal, Rahul Ranjan Sah\nTotal: $170.45 USD\n..."
```

| File Type | Extraction Method |
|---|---|
| PDF (text) | `pypdf` → page text |
| PDF (scanned) | `pymupdf` → PNG per page → Kimi vision |
| DOCX | `python-docx` → paragraphs + table cells |
| XLSX | `openpyxl` → CSV rows per sheet |
| Images | Sent directly as binary to Kimi vision |
| Text/Code/MD | Read as UTF-8 |

---

## Step 3: LLM Summarization (Kimi)

**Input:** Extracted text + filename hint → sent to Kimi via PydanticAI Agent
```
"Filename: Flight GSP - Hartford Receipt.pdf\nContent type: pdf\n\n---\n
Breeze Airways\nFlight Receipt\nConfirmation: X7QK2M\n..."
```

**Output:** Structured `FileSummary` Pydantic model
```json
{
  "title": "Breeze Airways Flight Receipt: Greenville-Spartanburg to Bradley",
  "summary": "This receipt documents a $170.45 USD flight booking...",
  "content_type": "pdf",
  "keywords": ["Breeze Airways", "flight", "receipt", "X7QK2M"],
  "key_entities": ["Mridul Agrawal", "Rahul Ranjan Sah", "Breeze Airways"]
}
```

---

## Step 4: Markdown Rendering + Disk Write

**Input:** `FileSummary` object + source file path

**Output:** Markdown file at `Test Summaries/<sha256-first-16-hex>.md`
```markdown
Source: Test Content/Flight GSP - Hartford Receipt.pdf

# Breeze Airways Flight Receipt: Greenville-Spartanburg to Bradley

This receipt documents a $170.45 USD flight booking...

**Content type:** pdf

**Keywords:** Breeze Airways, flight, receipt, X7QK2M

**Key entities:** Mridul Agrawal, Rahul Ranjan Sah, Breeze Airways
```

Filename is deterministic: `sha256(file_bytes)[:16]` — re-running skips already-summarized files.
