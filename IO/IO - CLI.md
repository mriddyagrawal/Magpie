# CLI (notspotlight) — Input / Output

## Full Flow Diagram

```
┌─────────────────────────────┐
│  User launches CLI          │
│  $ notspotlight / ns / nas  │
│  $ just chat                │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 1: Banner + REPL      │
│  IN:  terminal session      │
│  OUT: banner with suggested │
│       questions, prompt ">"  │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 2: User Input         │
│  IN:  keystroke stream      │
│  OUT: question string       │
│       OR dot-command         │
│       OR exit signal         │
└─────────────┬───────────────┘
              │
         ┌────┴────┐
         │         │
    question   dot-command
         │         │
         │         ▼
         │    ┌─────────────────────┐
         │    │  Handle Command     │
         │    │  IN:  ".rewrite on" │
         │    │  OUT: setting change│
         │    │       printed to    │
         │    │       terminal      │
         │    └─────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Step 3: Query Construction │
│  IN:  raw question string   │
│  OUT: SearchQuery           │
│       (rewrite=off by       │
│       default: raw passthru)│
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 4: Embed Query        │
│  IN:  query + keywords      │
│  OUT: dense vec (384-dim)   │
│       sparse vec (BM25)     │
│  DISPLAY:                   │
│    ✓ Query embedded (0.3s)  │
│      dense vector: 384 dims │
│      sparse terms: 5 active │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 5: Qdrant Search      │
│  IN:  dense + sparse vecs   │
│  OUT: top-k SearchResults   │
│  DISPLAY:                   │
│    ✓ Qdrant searched (0.2s) │
│      results: 5 documents   │
│      #1: [0.871] Flight.pdf │
│      #2: [0.342] Avelo.pdf  │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 6: Read + Answer      │
│  IN:  question + file paths │
│  OUT: Answer {answer,       │
│       sources_used}         │
│  DISPLAY:                   │
│    ✓ Answer generated (5s)  │
│      sources cited: 1 file  │
│      → Flight GSP...pdf     │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 7: Display Results    │
│  IN:  PipelineResult        │
│  OUT: formatted terminal    │
│       output                │
│                             │
│  ┌ Retrieved Documents ──┐  │
│  │ #  Score  Path        │  │
│  │ 1  0.871  Flight.pdf  │  │
│  │ 2  0.342  Avelo.pdf   │  │
│  └───────────────────────┘  │
│  ╭─ Answer ──────────────╮  │
│  │ The flight cost        │  │
│  │ $170.45 USD total...   │  │
│  ╰───────────────────────╯  │
│  Sources used:              │
│    → Flight GSP...pdf       │
│                             │
│  Total: 5.6s                │
└─────────────┬───────────────┘
              │
              ▼
        Back to Step 2
        (REPL loop)
```

---

## Step-by-Step Detail

### Step 1: Banner + REPL Init

**Input:** Terminal session launch
```
$ notspotlight
```

**Output:** Banner with version, instructions, and suggested questions
```
╭───────────────────────────────────────────╮
│ NotAnotherSpotlight  v0.1.0               │
│ Type your question. .help for commands.   │
│                                           │
│ Try asking:                               │
│   How much was the flight to Hartford?    │
│   What is Plato's education system?       │
│   How much did the DS/ML club spend?      │
╰───────────────────────────────────────────╯
```

Loads: `.env` (credentials), `~/.notspotlight_history` (past queries)

---

### Step 2: User Input

**Input:** Keystroke stream (prompt_toolkit handles editing, history recall)

**Output:** One of three types:

| Input Type | Example | Action |
|---|---|---|
| Question | `how much was the flight?` | → Step 3 |
| Dot-command | `.rewrite on`, `.top-k 3`, `.help`, `.clear` | Handle immediately |
| Exit | `exit`, `quit`, `Ctrl+D` | End REPL |

---

### Step 3: Query Construction

**Input:** Raw question string
```
"how much was the flight?"
```

**Output (rewrite off — default):**
```python
SearchQuery(query="how much was the flight?", keywords=[])
```

**Output (rewrite on):**
```python
SearchQuery(
    query="flight receipt booking transaction total cost",
    keywords=["flight", "receipt", "cost", "Breeze Airways"]
)
```

**Display:**
```
✓ Using raw query (rewrite off)
  query: how much was the flight?
```

---

### Step 4: Embed Query

**Input:** Combined query + keywords string
```
"how much was the flight?"
```

**Output:** Dense vector (384 floats) + sparse vector (term indices + weights)

**Display:**
```
✓ Query embedded (0.3s)
  dense vector: 384 dims
  sparse terms: 5 active terms
```

---

### Step 5: Qdrant Hybrid Search

**Input:** Dense vector + sparse vector + top_k setting

**Output:** Ranked list of `SearchResult(summary, path, score)`

**Display:**
```
✓ Qdrant searched (0.2s)
  results: 5 documents
    #1: [0.871] Test Content/Flight GSP - Hartford Receipt.pdf
    #2: [0.342] Test Content/Avelo Airlines Receipt.pdf
    #3: [0.121] Test Content/Club Budget.xlsx
```

---

### Step 6: Read Source Documents + Generate Answer

**Input:** Question + top-k file paths

**Internal:** `src/content.py` reads the actual source files (PDF text, DOCX, XLSX, images), then Kimi generates a grounded answer citing specific sources.

**Output:**
```python
Answer(
    answer="The flight to Hartford (Bradley) cost $170.45 USD total...",
    sources_used=["Test Content/Flight GSP - Hartford Receipt.pdf"]
)
```

**Display:**
```
✓ Answer generated (5.1s)
  sources cited: 1 files
    → Test Content/Flight GSP - Hartford Receipt.pdf
```

---

### Step 7: Display Results

**Input:** `PipelineResult` (retrieved docs + answer + sources)

**Output:** Formatted terminal output using rich:

```
  Total: 5.6s

┌─ Retrieved Documents ─────────────────────────────┐
│ #   Score   Path                                   │
│ 1   0.871   Test Content/Flight GSP - Hartford...  │
│ 2   0.342   Test Content/Avelo Airlines Receipt... │
└────────────────────────────────────────────────────┘

╭─ Answer ───────────────────────────────────────────╮
│ The flight to Hartford (Bradley) cost $170.45 USD  │
│ total. It was a Breeze Airways flight (X7QK2M)     │
│ booked on March 24, 2026, for two travelers:       │
│ Mridul Agrawal and Rahul Ranjan Sah.               │
╰────────────────────────────────────────────────────╯

Sources used:
  → Test Content/Flight GSP - Hartford Receipt.pdf
```

---

## Dot-Commands Reference

| Command | Input | Output |
|---|---|---|
| `.help` | (none) | Prints command table |
| `.rewrite on` | (none) | Sets rewrite=True, prints confirmation |
| `.rewrite off` | (none) | Sets rewrite=False, prints confirmation |
| `.rewrite` | (none) | Prints current rewrite setting |
| `.top-k 3` | integer | Sets top_k=3, prints confirmation |
| `.top-k` | (none) | Prints current top_k value |
| `.clear` | (none) | Clears terminal screen |
