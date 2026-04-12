# Stage 2 — Search: Input / Output

## Full Flow Diagram

### Ingestion (one-time)

```
┌─────────────────────────────┐
│  Summaries/*.md             │
│  (from Stage 1)             │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 1: Parse              │
│  IN:  summary .md files     │
│  OUT: ParsedSummary objects │
│       {source_path, title,  │
│        summary, content_type│
│        keywords,            │
│        key_entities}        │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 2: Embed              │
│  IN:  title + summary +     │
│       keywords (combined)   │
│  OUT: dense vector (384-dim)│
│       sparse vector (BM25)  │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 3: Store in Qdrant    │
│  IN:  dense vec, sparse vec,│
│       payload {summary,     │
│       source_path}          │
│  OUT: point upserted in     │
│       Qdrant Cloud          │
└─────────────────────────────┘
```

### Search (per query)

```
┌─────────────────────────────┐
│  User Question              │
│  "how much was the flight?" │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 4: Kimi Query Rewrite │
│  IN:  raw user question     │
│  OUT: SearchQuery           │
│       {query: "flight       │
│        receipt booking cost"│
│        keywords: ["flight", │
│        "receipt", "cost"]}  │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 5: Embed Query        │
│  IN:  rewritten query +     │
│       keywords (combined)   │
│  OUT: dense vector (384-dim)│
│       sparse vector (BM25)  │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 6: Hybrid Search      │
│  IN:  dense vec, sparse vec │
│  OUT: top-5 results ranked  │
│       by RRF fusion score   │
│                             │
│  Qdrant internally:         │
│  ┌────────┐  ┌────────┐    │
│  │ Dense  │  │ Sparse │    │
│  │ Search │  │ Search │    │
│  └───┬────┘  └───┬────┘    │
│      └─────┬─────┘         │
│            ▼               │
│     RRF Fusion             │
│     (merge rankings)       │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Final Output               │
│  Per result:                │
│  ┌────────────────────────┐ │
│  │ summary: "This receipt │ │
│  │  documents a $170.45..."│ │
│  │ path: "Test Content/   │ │
│  │  Flight GSP..."        │ │
│  │ score: 0.87            │ │
│  └────────────────────────┘ │
│  × up to 5 results         │
└─────────────────────────────┘
```

---

## Step-by-Step Detail

### Step 1: Parse Summaries

**Input:** `Summaries/*.md` files (produced by Stage 1)
```
Summaries/8c2bbf673a91ef8d.md
```

**Output:** `ParsedSummary` object
```python
ParsedSummary(
    source_path="Test Content/Flight GSP - Hartford Receipt.pdf",
    title="Breeze Airways Flight Receipt: Greenville-Spartanburg to Bradley",
    summary="This receipt documents a $170.45 USD flight booking...",
    content_type="pdf",
    keywords=["Breeze Airways", "flight", "receipt", "X7QK2M"],
    key_entities=["Mridul Agrawal", "Rahul Ranjan Sah", "Breeze Airways"],
    summary_file="Summaries/8c2bbf673a91ef8d.md",
)
```

---

### Step 2: Embed Summaries

**Input:** Combined text string per summary
```
"Breeze Airways Flight Receipt: Greenville-Spartanburg to Bradley This receipt documents a $170.45 USD flight booking... Breeze Airways, flight, receipt, X7QK2M"
```

**Output:** Two vectors
```
dense:  [0.023, -0.114, 0.087, ...]   # 384 floats (MiniLM)
sparse: indices=[42, 187, 301, ...]    # BM25 term IDs
        values=[1.2, 0.8, 0.5, ...]   # BM25 term weights
```

---

### Step 3: Store in Qdrant

**Input:** Vectors + payload
```python
PointStruct(
    id="a3f8...",                        # deterministic from filename
    vector={
        "dense": [0.023, -0.114, ...],   # 384-dim
        "sparse": SparseVector(...)       # BM25
    },
    payload={
        "summary": "This receipt documents a $170.45...",
        "source_path": "Test Content/Flight GSP - Hartford Receipt.pdf",
    },
)
```

**Output:** Point stored in Qdrant Cloud collection `summaries`

---

### Step 4: Kimi Query Rewrite

**Input:** Raw user question
```
"how much was the flight?"
```

**Output:** Structured `SearchQuery` from Kimi
```json
{
  "query": "flight receipt booking transaction total cost amount",
  "keywords": ["flight", "receipt", "cost", "Breeze Airways"]
}
```

---

### Step 5: Embed Query

**Input:** Combined rewritten query + keywords
```
"flight receipt booking transaction total cost amount flight receipt cost Breeze Airways"
```

**Output:** Two vectors (same models as ingestion)
```
dense:  [0.041, -0.098, 0.112, ...]   # 384 floats (MiniLM)
sparse: indices=[42, 187, 556, ...]    # BM25 term IDs
        values=[1.5, 0.9, 0.3, ...]   # BM25 term weights
```

---

### Step 6: Hybrid Search in Qdrant

**Input:** Dense vector + sparse vector + top_k=5

**Internal process:**
- Dense search → ranks by cosine similarity
- Sparse search → ranks by BM25 score
- RRF fusion → merges both rankings into one

**Output:** Top 5 results
```
--- Result 1 (score: 0.8704) ---
Path:    Test Content/Flight GSP - Hartford Receipt.pdf
Summary: This receipt documents a $170.45 USD flight booking
         transaction dated March 24, 2026...

--- Result 2 (score: 0.3211) ---
Path:    Test Content/Copy of Data Science and Machine Learning Club Budget.xlsx
Summary: This spreadsheet tracks the Fall 2024 financial budget...

...up to 5 results
```
