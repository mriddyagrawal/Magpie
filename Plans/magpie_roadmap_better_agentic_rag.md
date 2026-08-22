# Magpie Roadmap — better agentic RAG

**Author**: Mridul + Claude (planning session 2026-05-07)
**Status**: working document, expect revision
**Scope**: every layer discussed in the planning sessions, ordered by dependency and effort

This document covers seven workstreams, in the order they should ship:

0. Qdrant audit fixes (immediate blockers)
1. World model / PTKB layer
2. Folder context layer
3. Entity graph layer
4. Topic tagging layer
5. Adaptive personalization fusion
6. Multi-step query loop
7. Evaluation infrastructure (iKAT + custom)

Each workstream has: goal, dependencies, design, implementation steps, deliverables, eval, and risks. Read the dependency map first — some of these can ship in parallel, some can't.

---

## Dependency map

```
[0] Audit fixes (blocking — fix now)
        |
        v
[1] World model (foundational — most other layers want it)
        |
        +-----------+-----------+-----------+
        |           |           |           |
        v           v           v           v
[2] Folder    [3] Entity    [4] Topic    (parallel)
    Phase 1   Stage 1       tags
        |           |           |
        |           v           |
        |       [3] Stage 2,3   |
        |           |           |
        +-----------+-----------+
                    |
                    v
        [5] Adaptive fusion (depends on 1+2+3+4)
                    |
                    v
        [6] Multi-step query loop (depends on 5 + world model)
                    |
                    v
        [7] Eval infrastructure (continuous, but headline numbers
             require everything above to be working)
```

Things that can ship independently and in parallel:
- Folder Phase 1 (cheapest, ~1 day)
- Topic tags (cheap addition to existing summary pass)
- World model v0 (independent of everything else; foundational for the rest)

Things with hard ordering:
- Entity Stage 2 needs world model (entity disambiguation requires user context)
- Multi-step loop needs world model + entity graph + adaptive fusion all working
- Eval against iKAT only meaningful once world model + adaptive fusion are in place

Total realistic time to ship the full stack: 8–12 weeks of focused work, assuming you and Rahul split it. Could be faster with cuts; could be slower with quality bars on eval.

---

## Workstream 0 — Qdrant audit fixes

**Goal**: close the silent-correctness and silent-recall-regression bugs surfaced in the audit. Pre-requisite for anything else, because broken retrieval makes every later layer impossible to evaluate.

**Dependencies**: none.

**Estimated time**: 1 day, plus a re-ingest run.

### What's broken

1. **CSV row dedup bug in cross-tier RRF.** Summaries collection has duplicate `source_path` values (one row = one point for CSVs). The `_rrf_merge` function in `search.py:432-471` keys dedup on `source_path` only. Either silently collapses 50 rows of `tax_2025.csv` into 1 result, or fails to dedup at all. Both are wrong.

2. **No payload index on `source_path` for summaries.** Every delete-by-path is a full collection scan. As corpora grow past a few thousand points (and especially with CSV row blowup), this gets slow.

3. **`rescore=True` not pinned on fast_tier (ColPali) search.** Today's Qdrant default is rescore-on, but server-default behavior flips between minor versions. When it flips, ColPali recall regresses with no error. Silent bug.

4. **No retry wrapper on `fast_db.upsert_pages_batch`.** Summaries upserts already have 3-attempt exponential backoff. ColPali points are larger and timeouts are more likely. Risk of silent data loss on long syncs.

### Fixes (concrete steps)

**Step 0.1: Fix RRF key.**

```python
# In search.py _rrf_merge

def _hit_key(hit, tier: str) -> tuple:
    p = hit.payload
    chunk = p.get("chunk_index")
    if tier == "summary" and chunk is not None:
        return ("summary", p["source_path"], chunk)
    elif tier == "fast":
        # fast_tier hits are file-level; use page_num if present, else file
        page = p.get("page_num", -1)
        return ("fast", p["source_path"], page)
    else:
        return (tier, p["source_path"])
```

But wait — the dedup question is subtler than just keying. Decide the semantic:

- **Option A (recommended)**: don't dedup across tiers at all. RRF over union with `(source_path, chunk_index, tier)` keys. Show top-K results regardless of tier. UI groups by `source_path` for display.
- **Option B**: dedup at file level. If both tiers hit `tax_2025.csv`, return one combined result with sub-hits inside. More UX work, more complex code.

Go with Option A for now. Cleaner, less to debug. UI display layer can group by file if it wants.

**Step 0.2: Add payload index on summaries.**

```python
# In src/stage2/db.py after collection creation
client.create_payload_index(
    collection_name=COLLECTION_NAME,
    field_name="source_path",
    field_schema=PayloadSchemaType.KEYWORD,
)
client.create_payload_index(
    collection_name=COLLECTION_NAME,
    field_name="chunk_index",
    field_schema=PayloadSchemaType.INTEGER,
)
```

Run once on existing collection (or destroy and re-ingest if the collection is small).

**Step 0.3: Pin rescore on fast_tier.**

```python
# In src/stage2/fast_db.py search call
client.query_points(
    collection_name=FAST_COLLECTION,
    query=multi_vec,
    limit=limit,
    with_payload=True,
    search_params=SearchParams(
        quantization=QuantizationSearchParams(
            rescore=True,
            oversampling=2.0,  # tune later if recall is fine without it
        ),
    ),
)
```

**Step 0.4: Add retry to ColPali upsert.**

Refactor the existing summaries retry into a shared decorator, apply to both upsert paths:

```python
# src/stage2/qdrant_retry.py (new file)
def with_retry(max_attempts: int = 3, base_delay: float = 1.0):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except (qdrant_client.http.exceptions.ResponseHandlingException,
                        httpx.TimeoutException) as e:
                    if attempt == max_attempts - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Qdrant upsert attempt {attempt+1} failed, retrying in {delay}s: {e}")
                    time.sleep(delay)
        return wrapper
    return decorator
```

Apply to `db.upsert_summaries` and `fast_db.upsert_pages_batch`.

### Tertiary fixes (do while you're in there)

- Add a stderr warning when `QDRANT_PROVIDER=local` ("Local provider active — fast_tier quantization disabled")
- Add `client.create_snapshot()` on a daily schedule with retention of last 3
- Quantization on summaries: add `ScalarQuantization(int8, always_ram=False)` for the dense vectors. ~4× memory win, negligible recall loss on MiniLM.

### Eval

After fixes:
- Re-run the same query set you have now (if any) and verify result counts haven't dropped
- Pick a CSV with >10 rows, query for content from row 17 specifically, verify it returns
- Delete a file with 100+ chunk points, time the operation before/after the payload index (should drop from seconds to milliseconds)

### Risks

- The RRF key change *will* alter ranking. Existing user expectations of result order may shift. Probably an improvement but worth a sanity check.
- Re-ingest may be required if you destroy and recreate the summaries collection to add the payload index. Time-box it; communicate to beta users if needed.

### Deliverables

- [ ] Fixed `_rrf_merge` with tier-aware keys
- [ ] Payload indexes on summaries `source_path` + `chunk_index`
- [ ] Rescore pinned on fast_tier search
- [ ] Shared retry decorator on both upsert paths
- [ ] (Optional) Scalar int8 quantization on summaries dense vectors
- [ ] (Optional) Snapshot policy
- [ ] Smoke test that exercises CSV rows + RRF dedup
- [ ] Updated audit doc reflecting fixes

---

## Workstream 1 — World model / PTKB layer

**Goal**: give Magpie a structured representation of *who the user is* and *what's currently active in their life* that retrieval can query at runtime. This is the foundation for almost everything else.

**Dependencies**: Workstream 0 done.

**Estimated time**: 1–1.5 weeks for v0.

### Background

Academic name: PTKB (Personal Text Knowledge Base). Formalized in TREC iKAT 2023. Consistent finding across the literature: **adaptive injection beats always-on, human-edited profiles beat LLM-extracted ones, profile-statement ranking before injection is critical.**

The most useful operational pattern is Lyzr Cognis's **two-scope split**: USER (cross-session, persistent) and CONTEXT (session/temporal, decays).

### Schema

Two SQLite tables (or one with a `scope` column — your call). Schema below in YAML for clarity but represent however suits Magpie's stack.

**USER scope (persistent, mostly user-edited):**

```yaml
identity:
  name: str
  email: str
  preferred_pronouns: str (optional)

role:
  primary: enum [student, professional, researcher, hybrid]
  secondary: list[role] (optional — student + side-business owner)

institution:
  name: str (e.g. Furman University)
  type: enum [university, company, school, other]
  jurisdiction: str (e.g. SC, USA — for legal/calendar context)

persistent_entities:
  known_people:
    - canonical_name: str
      aliases: list[str]
      relationship: str (e.g. "professor", "co-founder", "sister")
  known_orgs:
    - canonical_name: str
      aliases: list[str]
      role: str
  known_locations:
    - name: str
      address: str (optional)

preferences:
  default_scope: enum [all, work, personal]
  privacy_level: enum [strict, normal, permissive]
  date_format: str
  timezone: str
```

**CONTEXT scope (auto-derived, decays):**

```yaml
temporal:
  current_semester: str (e.g. "Spring 2026")
  semester_dates: [start_date, end_date]
  current_quarter: str (for business users)
  current_week: int

active_entities:
  enrolled_courses:
    - code: str (e.g. "CSC 223")
      name: str
      professor: str
      schedule: str
      added_at: datetime  # for decay weighting
  active_orgs:
    - name: str
      user_role: str
      added_at: datetime
  active_projects:
    - name: str
      collaborators: list[str]
      added_at: datetime

recent_session:  # rolling buffer
  - query: str
    timestamp: datetime
    top_results: list[source_path]
  # last N=20 entries, decay weight applied

corpus_state:
  total_files_indexed: int
  files_by_top_folder: dict[str, int]
  last_full_sync: datetime
```

### Implementation

**Step 1.1: Storage layer.**

SQLite is correct here, not a separate service. You already have local-first storage. Put it at `~/Library/Application Support/magpie/world_model.db`.

```python
# src/world_model/store.py

class WorldModelStore:
    def get_user_scope(self) -> UserScope: ...
    def update_user_scope(self, **fields) -> None: ...
    def get_context_scope(self) -> ContextScope: ...
    def update_context_scope(self, **fields) -> None: ...
    def append_recent_query(self, query: str, results: list[str]) -> None: ...
    def get_recent_queries(self, n: int = 20, decay: bool = True) -> list[RecentQuery]: ...
```

Schema versioning matters from day one. Add a `schema_version` field; write a migrator.

**Step 1.2: Onboarding UI.**

First-run flow asks 5–7 questions:
1. What's your name?
2. What's your primary role? [student, professional, researcher, mixed]
3. What's your institution / company?
4. (If student) What semester are you in? (Spring 2026 / Fall 2026 / etc.)
5. (If student) What courses are you taking? (autocomplete from common course codes if Furman is detected)
6. What organizations are you actively involved with?
7. Where do most of your files live? (folder picker — confirms scope)

Skip any answer; partial profile still works.

**Step 1.3: Auto-suggest from indexed content.**

Background job that scans the index periodically and proposes additions. Examples:
- Folder named `CSC 223 Spring 2026` → suggest course
- Email signature with "Treasurer, Furman Asia Association" → suggest org + role
- Calendar events from Moodle (if integrated) → suggest semester dates

Suggestions go to a "Review" inbox in settings. User confirms/denies. **Never auto-add without confirmation** — the research is clear that LLM-extracted profiles introduce noise.

**Step 1.4: Profile editing UI.**

Settings page where every USER-scope field is editable. CONTEXT-scope has its own section ("Active right now"). User can manually rotate semesters, archive old courses, etc.

Provide an "Export profile" button (JSON download) and "Import profile" — both for backups and for the eventual cross-device sync feature.

**Step 1.5: Inject into query rewriter.**

The query rewriter currently does plain query expansion. Extend to:

```python
def rewrite_query(query: str, world_model: WorldModel) -> RewriteResult:
    # 1. Resolve temporal references using world_model.context.temporal
    # 2. Detect entity gaps (e.g. "the test" — which test?) and fill from
    #    world_model.context.active_entities
    # 3. Apply preferences (scope filter, etc.)
    # 4. Generate three reformulations:
    #    - "neutral" (no personalization)
    #    - "personalized" (full world model context)
    #    - "selective" (only profile statements relevant to this query)
    return RewriteResult(neutral=..., personalized=..., selective=...)
```

The three reformulations feed Workstream 5 (adaptive fusion). For v0, use just the "selective" rewrite and inject it into the existing query path.

**Step 1.6: Decay weighting.**

For CONTEXT scope, multi-valued fields (`recent_session`, `enrolled_courses` over time) need recency weighting. Use exponential decay:

```python
def decay_weight(added_at: datetime, half_life_days: float = 30.0) -> float:
    age_days = (datetime.now() - added_at).total_seconds() / 86400
    return 0.5 ** (age_days / half_life_days)
```

Different fields want different half-lives:
- `recent_session.queries`: 1 day
- `active_entities.enrolled_courses`: 90 days (one semester)
- `active_orgs`: 180 days
- `active_projects`: 60 days

### Eval

- Manual smoke: does "what's on the test tomorrow" route correctly?
- Cold start: install fresh, run common queries, measure quality vs. fully-populated profile.
- Profile drift: simulate a stale profile (last semester's courses), measure how badly retrieval degrades.

### Risks

- **Cold start.** New users have empty profiles. Build graceful fallback — when no profile, system behaves identically to today's Magpie.
- **Maintenance burden.** Users won't update profiles. Mitigate: auto-update what you can from auth-tokens (Moodle, Google Calendar), nudge at semester boundaries.
- **Privacy.** This is a structured profile of the user's life. Local-only is fine; the moment you offer cloud sync, encryption-at-rest becomes mandatory.

### Deliverables

- [ ] `world_model.db` schema + SQLite store
- [ ] Onboarding UI (first-run + skippable)
- [ ] Auto-suggest background job + Review inbox
- [ ] Profile editing settings page
- [ ] Three-reformulation query rewriter
- [ ] Decay weighting on CONTEXT fields
- [ ] Export/import buttons
- [ ] Schema versioning + migrator

---

## Workstream 2 — Folder context layer

**Goal**: capture the user's *organizational intent* by treating folder structure as deliberate metadata. Cheap, high-precision when present, gracefully degrades when absent.

**Dependencies**: Workstream 0.

**Estimated time**: 1 day for Phase 1, 1 week for Phase 2 if pursued.

### Phase 1 — Folder context as payload (do this immediately)

Every Qdrant point already has `source_path`. The folder tree is encoded in it for free. Materialize three derived fields at index time:

```python
def derive_folder_fields(source_path: str, root: str) -> dict:
    rel = os.path.relpath(source_path, root)
    parts = os.path.dirname(rel).split(os.sep)
    parts = [p for p in parts if p and p != "."]
    return {
        "folder_path": os.path.dirname(rel),
        "folder_segments": parts,
        "folder_text": " ".join(parts),  # for BM25/embedding
        "folder_depth": len(parts),
    }
```

Add to payload on both summaries and fast_tier upserts. Add payload indexes:

```python
client.create_payload_index(COLLECTION_NAME, "folder_path", PayloadSchemaType.KEYWORD)
client.create_payload_index(COLLECTION_NAME, "folder_segments", PayloadSchemaType.KEYWORD)  # array index
```

Now you can:
- Filter by folder: `Filter(must=[FieldCondition(key="folder_segments", match=MatchValue(value="Furman Asia Association"))])`
- Have BM25 pick up folder names as keywords (via `folder_text` if you concat it into the embedded text, or as a separate sparse field)
- Compute folder-level stats trivially

**Cost**: ~1 day of work, almost no operational risk.

### Phase 2 — Folder summaries (only if Phase 1 leaves clear gaps)

Don't build this preemptively. Build it only if you observe queries that Phase 1 + entity graph + topic tags can't answer.

Approach:
- Generate folder summary recursively bottom-up from existing file summaries
- Embed each folder summary as a point in a new `folders` collection
- At retrieval, run a fourth query path; folder hits boost child files

**Risk**: works only when folder structure is good. Median user has messy folders. Mitigate by computing a "folder informativeness score" (TF-IDF of folder name + intra-folder embedding coherence) and zeroing the boost for low-informativeness folders.

### corpus_role tagging (within Phase 1, manually)

Add a `corpus_role` field, user-editable, default `active`:
- `active` — current course material, current project files
- `reference` — bylaws, syllabi (without dates), department info, manuals
- `archival` — prior semesters, completed projects
- `personal` — medical/legal/financial private docs

Retrieval treats them differently (covered in Workstream 5). User assigns at folder level, propagates to children. Provide a UI that lets users batch-assign by folder.

### Eval

- Run a query like "Diwali receipts" before and after folder fields are in payload. The folder-aware version should rank `Furman Asia Association/Receipts/Diwali 2026/*` files much higher.
- Test that filtering by `corpus_role=active` excludes archival folders correctly.

### Risks

- Users with flat folder structure get little benefit. That's fine — graceful degrade.
- Path encodings differ by OS (Windows backslashes). Normalize at ingest.

### Deliverables

- [ ] Folder field derivation in upsert paths (both collections)
- [ ] Payload indexes on folder fields
- [ ] `folder_text` integrated into embedded content or sparse vector
- [ ] `corpus_role` field + UI for batch assignment
- [ ] (Phase 2, deferred) folder summary generation + new `folders` collection

---

## Workstream 3 — Entity graph layer

**Goal**: give Magpie structured knowledge of the people, courses, orgs, events, and topics in the user's corpus, so queries can resolve entities ("the FAA budget") and traverse relations ("who's the treasurer").

**Dependencies**: World model (Workstream 1) for entity disambiguation. Workstream 0.

**Estimated time**: 4–6 weeks across all stages.

### Background

gbrain's BrainBench shows the graph layer is load-bearing: graph-disabled gbrain loses 31 P@5 points. Validates the work. But gbrain's mechanism (extract from canonical Markdown) doesn't apply — Magpie has to extract from messy real files. Approach: extract from your existing vision-LLM file summaries, not raw files.

### Entity types (Magpie-specific, not gbrain's VC-flavored set)

- **Person** — professors, TAs, club members, family
- **Course** — code, name, professor, schedule
- **Org/Group** — clubs, departments, lab teams
- **Event** — exam, deadline, meeting, social event
- **Topic/Concept** — Dijkstra, MST, budget, gala (lighter weight)
- **Document** — files themselves
- **Date** — first-class extractable

Don't add more types until the existing ones are working well. Schema sprawl is a real failure mode.

### Stage 1 — Structured payload extraction

**Time**: ~1 week.

Extend the existing per-file vision-LLM summary pass to also emit structured entity references. Output schema:

```json
{
  "summary": "...",
  "entities": {
    "persons": [{"name": "Aanya Sharma", "role_hint": "Treasurer"}],
    "orgs": [{"name": "Furman Asia Association", "alias": "FAA"}],
    "courses": [{"code": "CSC 223", "name": "Data Structures"}],
    "events": [{"name": "Diwali 2026 Cultural Night", "date": "2026-10-25"}],
    "topics": ["budget", "cultural events"],
    "dates": [{"text": "March 12, 2026", "iso": "2026-03-12", "kind": "approval"}],
    "amounts": [{"value": 4200, "currency": "USD"}]
  }
}
```

Store entire `entities` object as Qdrant payload. Add per-field indexes for hot ones:

```python
client.create_payload_index(COLLECTION_NAME, "entities.persons[].name", KEYWORD)
client.create_payload_index(COLLECTION_NAME, "entities.orgs[].name", KEYWORD)
client.create_payload_index(COLLECTION_NAME, "entities.courses[].code", KEYWORD)
```

Now queries can filter by entity directly. "Files mentioning Aanya Sharma" is now a payload filter, not a vector search.

**Use a small fast model for extraction**, not Gemma 4 E4B. LFM2.5-350M is purpose-built for this. Add as a second loadable model behind your `LocalLLM` interface (already on the to-do list from Workstream 1's prep).

**Test cases**:
- Extract entities from a known FAA budget PDF; verify Aanya, FAA, $4200, March 12 all appear
- Extract from an empty/scanned-only doc; verify graceful empty extraction
- Extract from a CSV with 1000 rows; verify performance (extraction per-row would be insane — extract once per file, summarized)

### Stage 2 — Entity coalescing

**Time**: ~2 weeks.

Stage 1 produces *mentions*. Stage 2 produces *canonical entities*. Two "Rahul" mentions might be the same person or different people.

Build an entity store (separate SQLite DB):

```sql
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,  -- person, org, course, event, etc.
    canonical_name TEXT NOT NULL,
    metadata JSON
);

CREATE TABLE entity_aliases (
    entity_id TEXT,
    alias TEXT,
    confidence REAL,
    PRIMARY KEY (entity_id, alias)
);

CREATE TABLE entity_mentions (
    entity_id TEXT,
    source_path TEXT,
    chunk_index INTEGER,
    raw_text TEXT,
    extracted_at DATETIME
);
```

**Coalescing algorithm** (heuristic v1, before considering ML):

1. Exact name match on canonical name → same entity
2. Alias match → same entity (maintain alias table)
3. Embedding similarity > threshold + same type → likely same entity, ask user (or auto-merge if conf > 0.95)
4. Disambiguation via world model: "Rahul mentioned in CSC 223 folder + world_model.persistent_entities[Rahul Menon, co-founder, FAA President]" → same Rahul

Provide a UI for manual entity merge/split. Users will catch mistakes; let them fix them.

**This is where the world model dependency is critical**. Without it, every "Rahul" looks the same. With it, "Rahul Menon = FAA President = my co-founder" anchors the canonical entity.

### Stage 3 — Typed relations

**Time**: ~1.5 weeks.

Extract relations between entities, not just entities themselves. Update the LFM2.5 extraction prompt to also produce:

```json
{
  "relations": [
    {"subject": "Aanya Sharma", "predicate": "holds_role", "object": "Treasurer", "of": "Furman Asia Association"},
    {"subject": "Rahul Menon", "predicate": "approved", "object": "FAA Q3 Budget", "on": "2026-03-12"},
    {"subject": "user", "predicate": "enrolled_in", "object": "CSC 223"}
  ]
}
```

Store in entity store:

```sql
CREATE TABLE entity_relations (
    id INTEGER PRIMARY KEY,
    subject_entity_id TEXT,
    predicate TEXT,
    object_entity_id TEXT,
    metadata JSON,  -- date, source, confidence
    source_path TEXT
);
```

Predicate vocabulary (start small, expand as needed):
- `holds_role` (Person → Role @ Org)
- `member_of` (Person → Org)
- `enrolled_in` (Person → Course)
- `taught_by` (Course → Person)
- `scheduled_on` (Event → Date)
- `mentions` (Document → Entity)
- `approved` (Person → Document/Decision)
- `attended` (Person → Event)

Now retrieval can do graph traversal:
- "Who's the FAA treasurer" → traverse `holds_role(?, Treasurer, FAA)` → Aanya Sharma → return her files
- "When's the next FAA event" → query entities of type=event, where related-org=FAA, date >= today, sort by date asc

### Stage 4 — Graph-aware retrieval integration

**Time**: ~1 week.

Add a fourth retrieval track (after vector, BM25, fast_tier) that runs graph traversal queries.

Graph hits enter the same RRF fusion. Workstream 5 handles weighting.

### Eval

- Build a small test corpus of 50 PDFs covering FAA, courses, taxes
- Hand-label expected entities per file
- Measure entity extraction precision/recall on Stage 1
- Hand-label entity equivalences (which Rahul = which Rahul); measure coalescing accuracy on Stage 2
- For Stage 3 + 4, evaluate retrieval quality on graph-friendly queries vs. vector-only baseline

### Risks

- **Schema design takes longer than coding.** Allocate explicit time for "what's our person schema" before writing extraction code.
- **Coreference is hard.** Don't aim for 100% accuracy. Aim for 80% with a UI escape hatch.
- **LFM2.5-350M may not be capable enough for relation extraction.** Have a fallback to LFM2.5-1.2B if extraction quality is poor.
- **Graph queries can be slow on large corpora.** Index aggressively; consider denormalizing common traversals into payload.

### Deliverables

- [ ] LFM2.5-350M loaded behind LocalLLM interface
- [ ] Stage 1: extended summary schema, payload extraction, payload indexes
- [ ] Stage 2: entity store schema, coalescing pipeline, manual merge/split UI
- [ ] Stage 3: relation extraction, predicate vocabulary doc, relation store
- [ ] Stage 4: graph retrieval track in fusion
- [ ] Test corpus + eval harness

---

## Workstream 4 — Topic tagging layer

**Goal**: capture *conceptual groupings* that cross folder/entity boundaries. Files belong to multiple topics simultaneously. Cheap to build, narrower value than entities.

**Dependencies**: Workstream 0. Can be built in parallel with World model and Entity graph.

**Estimated time**: 3 days for v0, plus ongoing tag normalization.

### Approach

LLM-derived topic tags during the existing per-file summary pass. Skip HDBSCAN. Cluster instability is a real failure mode and the tag-vocabulary approach sidesteps it.

### Implementation

**Step 4.1: Extend summary schema.**

Add `topics: list[str]` to the structured summary output. Prompt the model to emit 3–5 short topic tags representing conceptual groupings.

**Step 4.2: Store as Qdrant payload + index.**

```python
client.create_payload_index(COLLECTION_NAME, "topics", PayloadSchemaType.KEYWORD)  # array
```

Now `Filter(should=[FieldCondition(key="topics", match=MatchValue(value="faa_finance"))])` works.

**Step 4.3: Tag vocabulary normalization.**

Tags will drift. `"faa_finance"`, `"FAA financial matters"`, `"FAA budgeting"` will all appear.

Periodic normalization job:
1. Embed all observed tags
2. Cluster the tags (k-means or HDBSCAN — small enough that instability isn't a problem at the *tag* level)
3. Assign canonical name per cluster (LLM-generated label)
4. Build alias table: `"FAA financial matters"` → `"faa_finance"`
5. At query time, expand tag queries through aliases

This runs nightly or on-demand. Tag vocab is small (hundreds, not millions) so it's cheap.

**Step 4.4: Multi-tag retrieval.**

Files with multiple tags get multi-membership "for free" — `topics: ["faa_governance", "faa_finance", "org_policies"]` is just an array field. No special handling needed.

### Eval

- Sanity check: read 20 file summaries with tags; do tags look reasonable?
- Query "policies that cover both finance and governance" → should return the org-policy file (tagged with both)

### Risks

- **Tag drift before normalization runs.** Acceptable; users can manually tag-edit if they care.
- **LLM produces vague tags** ("documents", "stuff"). Mitigate via prompt: "Avoid generic tags. Tags should be specific concepts."
- **Tag explosion.** If users have niche topics, tag vocab can balloon. Cap suggested tags per file at 5; force re-use over invention.

### Deliverables

- [ ] Updated summary schema with `topics` field
- [ ] Topic payload index
- [ ] Nightly tag normalization job
- [ ] Tag alias table + query expansion
- [ ] (Optional) UI for manual tag management

---

## Workstream 5 — Adaptive personalization fusion

**Goal**: combine all retrieval signals (vector, BM25, fast_tier, world model, entity graph, topic, folder, corpus_role) into a single ranking that adapts to the query type.

**Dependencies**: Workstreams 1, 2, 3, 4 at v0. Workstream 0 fixes are prerequisite for any meaningful eval.

**Estimated time**: 1 week for v0, ongoing tuning.

### Background

APCIR (2025) showed that adaptive personalization beats one-size-fits-all. Mo et al. found that always-injecting the full profile *hurts* retrieval. The win is: classify each query for personalization need, then weight signals accordingly.

### Architecture

```
Query
  |
  v
Adaptive personalization classifier
  - features: query length, entity references, temporal references,
              first-person pronouns, command verbs, etc.
  - output: weights per signal
  |
  v
Multi-track retrieval (parallel):
  - Vector (existing)
  - BM25 (existing)
  - Fast tier / ColPali (existing)
  - Folder filter (Workstream 2)
  - Entity graph traversal (Workstream 3)
  - Topic match (Workstream 4)
  - World-model-personalized rewrite (Workstream 1)
  |
  v
Weighted RRF fusion (extends existing two-layer RRF)
  - per-track weights from classifier
  - corpus_role filter applied here
  |
  v
Cross-encoder rerank (existing, adjusted top-K)
  |
  v
Result list
```

### Classifier design

Start dead simple. Heuristics first.

```python
def personalization_weights(query: str, world_model: WorldModel) -> dict[str, float]:
    weights = {
        "vector": 1.0,
        "bm25": 1.0,
        "fast_tier": 0.5,
        "entity_graph": 0.0,
        "topic": 0.5,
        "folder_boost": 0.5,
        "world_model_track": 0.0,
    }

    # Personalization signals
    if has_first_person(query):  # "my", "our", "I"
        weights["world_model_track"] = 1.0
        weights["entity_graph"] = 1.0

    if has_temporal_reference(query):  # "tomorrow", "last week"
        weights["world_model_track"] = 1.0  # for temporal resolution

    if has_entity_reference(query, world_model):  # mentions "FAA", a course code, etc.
        weights["entity_graph"] = 1.0

    if has_topical_intent(query):  # "what about X", "things related to Y"
        weights["topic"] = 1.0

    # Visual / document-heavy detection
    if has_visual_intent(query):  # "image of", "in the receipt", etc.
        weights["fast_tier"] = 1.5

    return weights
```

This is a 100-line function and it'll get you 80% of the value. Replace with a learned classifier later if needed.

### Weighted RRF

Existing RRF gives uniform weight per track. Extend to weighted:

```python
def weighted_rrf(track_results: dict[str, list[Hit]],
                 weights: dict[str, float],
                 k: int = 60) -> list[Hit]:
    scores = defaultdict(float)
    for track, hits in track_results.items():
        w = weights.get(track, 1.0)
        if w == 0:
            continue
        for rank, hit in enumerate(hits, start=1):
            key = hit_key(hit)
            scores[key] += w * (1.0 / (k + rank))
    # Sort by score, return hits
```

### corpus_role gating

Apply at fusion time, not retrieval time:

```python
if query_scope == "active":
    # Suppress archival/personal hits unless they have very high score
    for hit in candidates:
        if hit.payload.get("corpus_role") == "archival":
            hit.score *= 0.3
        elif hit.payload.get("corpus_role") == "personal" and not query_is_personal(query):
            hit.score *= 0.1
```

### Eval

- TREC iKAT 2024 dataset eval (see Workstream 7) is the headline number
- Custom eval: hand-label 50–100 queries with expected results, measure P@5 and R@5 with and without adaptive fusion
- Ablation: turn off each track individually, measure delta

### Risks

- **Over-tuning the classifier.** Start with simple heuristics; resist the urge to hand-engineer 30 rules. Add complexity only when ablations show specific gaps.
- **Weight tuning is endless.** Pick reasonable defaults, eval, accept the local optimum, ship. Don't get stuck.
- **Latency.** Six retrieval tracks running in parallel is more compute. Make sure they actually run in parallel (asyncio.gather), not sequentially.

### Deliverables

- [ ] Personalization classifier (heuristic v1)
- [ ] Weighted RRF implementation
- [ ] Six retrieval tracks running in parallel
- [ ] corpus_role gating at fusion time
- [ ] Ablation toolkit (turn tracks on/off via config)
- [ ] Eval harness (custom + iKAT)

---

## Workstream 6 — Multi-step query loop

**Goal**: enable Magpie to iterate write→retrieve→write, so complex queries get decomposed and refined rather than answered in one shot.

**Dependencies**: Workstreams 1, 3, 5 working. Don't start before these are stable.

**Estimated time**: 2 weeks.

### Why this depends on everything else

Multi-step loops without world model + entity graph are weaker than single-shot. The loop's *purpose* is to:
1. Detect entity gaps in the query
2. Resolve them via world model + graph
3. Re-query with the resolved entities
4. Synthesize

Without good entity resolution, the loop just adds latency.

### Architecture

```
Query
  |
  v
Plan: parse intent, identify gaps
  - "what's on the test tomorrow"
  - gaps: which test? (course unknown)
  |
  v
Resolve gaps:
  - temporal: "tomorrow" → 2026-05-08
  - course: world_model.enrolled_courses ∩ courses_with_test_on(2026-05-08)
  - if exactly one match → resolved
  - if multiple → ask user (or pick most-recent-active)
  |
  v
Retrieve with resolved entities (Workstream 5)
  |
  v
Check sufficiency:
  - did we get usable context?
  - if no, broaden query, retry
  - if yes, proceed
  |
  v
Synthesize answer with citations
  |
  v
(optional) Verify: do citations support answer?
```

### Implementation

Use a small structured-output model for the planning loop. LFM2.5-1.2B is good here — it's fast and tool-calling-tuned.

**Plan format** (constrained via JSON schema):

```json
{
  "intent": "factual_lookup" | "synthesis" | "comparison" | "action",
  "entities_referenced": [...],
  "entities_implicit": [...],  // gaps
  "temporal_constraints": {...},
  "scope_filter": "active" | "all" | ...,
  "needs_external_search": false
}
```

Then a resolver step that fills `entities_implicit` from world model + entity graph.

### Looping logic

```python
async def multi_step_query(query: str, max_steps: int = 3) -> Answer:
    state = QueryState(original=query)
    for step in range(max_steps):
        plan = await plan_query(state)
        if plan.has_gaps():
            resolved = await resolve_gaps(plan, world_model, entity_graph)
            if not resolved.complete:
                if resolved.can_ask_user:
                    return AskUser(resolved.clarification_question)
                # otherwise, best-guess and proceed
            state.update(resolved)

        results = await retrieve(state, weights=personalization_weights(state))

        if sufficient(results):
            return await synthesize(state, results)
        else:
            state.broaden()  # adjust filters, expand entities

    return await synthesize(state, results, partial=True)
```

### When to ask the user vs. pick best guess

Don't ask too often — annoying. Heuristic: ask only when there are 2+ candidates and confidence between them is close (within 20%). Otherwise pick the highest-confidence option and indicate the assumption in the answer ("Assuming you mean CSC 223 — let me know if you meant a different course").

### Eval

- Curate a set of "complex" queries that require multi-step (the "test tomorrow" class)
- Measure end-to-end success rate vs. single-shot baseline
- Measure average steps used (should be ≤ 2 for most queries)
- Latency budget: total response time under 4 seconds for typical queries

### Risks

- **Loop runaway.** Hard cap on steps. Always.
- **Latency explosion.** Each step is a model call. Three steps × 1s each = 3s before retrieval starts. Mitigate via aggressive caching of plans for similar queries, and by using LFM2.5-350M for planning when possible.
- **User experience confusion.** If the system asks clarifying questions, make sure the UI handles it well — don't lose the user.

### Deliverables

- [ ] Query plan schema (JSON-schema-constrained)
- [ ] Plan generation via LFM2.5
- [ ] Gap resolver (uses world model + entity graph)
- [ ] Sufficiency checker
- [ ] Loop driver with step cap + state machine
- [ ] Clarification UX (when to ask, how to ask)
- [ ] Eval set + harness

---

## Workstream 7 — Evaluation infrastructure

**Goal**: have *real, repeatable, defensible* numbers for Magpie's retrieval quality. This is what differentiates Magpie from every other "we have RAG" startup in front of investors, OSV reviewers, and YC partners.

**Dependencies**: builds incrementally as other workstreams ship. Set up the harness early, populate as features land.

**Estimated time**: 2 weeks initial, ongoing maintenance.

### Two parallel eval tracks

**Track A — TREC iKAT.**

The defensible academic benchmark. Use the iKAT 2024 dataset (it's open).

Setup:
1. Download iKAT 2024 corpus + topics + qrels
2. Wrap Magpie's retrieval pipeline as an iKAT-compatible system
3. Implement the three iKAT sub-tasks:
   - PTKB statement ranking
   - Passage ranking
   - Response generation
4. Submit runs against published TREC submissions for comparison

What you get out of it:
- Defensible NDCG@10, MAP, Recall@1000 numbers
- Comparison against academic baselines (BM25, dense retrievers, hybrid)
- Headline data for OSV/YC: "we score X on iKAT 2024, comparable to top academic submissions"
- A real ablation framework

Caveat: iKAT corpus is web passages, not personal files. Some signal won't transfer perfectly. Worth running anyway because it's the standard.

**Track B — Custom Magpie eval.**

A hand-curated eval that reflects Magpie's actual use cases.

Setup:
1. Build a fictional "user" with a mock corpus (~500 files): student persona, course materials, org docs, personal docs
2. Hand-label 100 queries with expected results, organized by category:
   - Simple factual ("what's in the FAA bylaws")
   - Entity-resolution ("what did Aanya approve")
   - Temporal ("what's due this week")
   - Multi-source synthesis ("what's on the test tomorrow")
   - Cross-corpus ("anything about Diwali")
3. Define metrics: P@5, R@5, NDCG@10, MRR, plus Magpie-specific: coverage of cited sources in synthesized answers
4. Build a runner that executes all 100 queries and emits a scorecard
5. Run on every PR; track regression

This is the eval that actually drives product decisions because it reflects real user queries.

### Key metric design

Beyond standard IR metrics, track Magpie-specific quality:

- **Citation accuracy**: when synthesizing an answer, is every claim supported by a cited source?
- **Source coverage**: did the answer use the *full set* of relevant sources, or just one?
- **Personalization lift**: with vs. without world model, how much does retrieval improve on personalized queries?
- **Latency p50/p99**: per-query end-to-end
- **Index size**: per-file overhead in MB
- **Cold start**: query quality on day-1 (empty world model) vs. day-30 (populated)

### Ablation framework

Make every layer toggleable in config:

```yaml
retrieval:
  vector: true
  bm25: true
  fast_tier: true
  folder_boost: true
  entity_graph: true
  topic: true
  world_model: true
```

Run the full eval suite with each layer disabled in turn. Produce a table: which layer contributes how much, on which query categories. This is the data that justifies your architectural decisions.

### Risks

- **Eval bias toward what you've built.** Mitigate by including queries you *expect to fail* and tracking when they start succeeding.
- **iKAT not transferring.** Real risk; have Track B as backup.
- **Maintenance burden.** Custom eval needs labels updated as system changes. Budget time for this.

### Deliverables

- [ ] iKAT 2024 corpus + topics downloaded and integrated
- [ ] iKAT-compatible system wrapper for Magpie
- [ ] Three sub-task runners (PTKB ranking, passage ranking, response gen)
- [ ] Mock user corpus + 100-query custom eval
- [ ] Ablation toolkit (layer toggles)
- [ ] Scorecard generator (run on every PR)
- [ ] Headline metrics doc (the "Magpie scores X on iKAT" deck slide)

---

## Cross-cutting concerns

### Logging, observability, debuggability

Every retrieval should emit structured logs with:
- Query, rewrites, weights, per-track results, fusion output, final ranking
- Decisions made (which entities resolved, which gaps remained)
- Latency breakdown per stage

This is what you'll need to debug "why did this query return weird results." Build it from day one.

Use OpenTelemetry or even just structured JSON logs to a local file. Don't ship logs externally without explicit user opt-in.

### Configuration

All tunables (RRF_K, decay half-lives, fusion weights, model paths, etc.) in one config file. Hot-reloadable in dev, restart-required in prod.

### Versioning

Schema migrations from day one for:
- World model SQLite
- Entity store SQLite
- Qdrant collection schemas
- Tag vocabulary

Make every breaking change a versioned migration. Ship a migration tool that runs on app startup.

### Privacy

The world model + entity graph is high-stakes data. Local-only by default. If you ever offer cloud sync:
- Encrypt at rest with a user-derived key (passphrase or device key)
- Document data retention clearly
- Comply with relevant regulations (FERPA if Moodle integration, GDPR for EU users)

### Bundling

llama-cpp-python with prebuilt platform wheels (Mac Metal, Win/Linux CUDA + Vulkan + CPU) is the right install path. Document install per platform in README. Test on Win + Linux explicitly before any non-Mac beta release.

Models to bundle or auto-download:
- LFM2.5-350M (extraction, planning)
- LFM2.5-1.2B (medium tasks)
- Gemma 4 E4B (synthesis)
- MiniLM-L6 (dense embeddings — already have)
- ColPali (visual — already have)

Total ~6 GB of models. Auto-download on first run, cache locally, verify SHAs.

---

## Suggested 12-week schedule (one example, adjust to your reality)

| Week | Workstream | Deliverable |
|------|-----------|-------------|
| 1 | 0 (audit fixes) | RRF key fix, payload indexes, rescore pin, retry wrapper |
| 1–2 | 7 (eval infra) | Custom mock corpus + 100-query baseline scorecard |
| 2 | 2 (folder Phase 1) | Folder fields in payload, indexes |
| 2–3 | 4 (topics) | topics field in summary schema, payload index, normalization v0 |
| 3–4 | 1 (world model) | SQLite store, onboarding UI, profile editing, query rewrite injection |
| 5–6 | 3 Stage 1 | LFM2.5-350M loaded, structured payload extraction |
| 6 | 7 | First iKAT run, custom eval ablation |
| 7–8 | 3 Stage 2 | Entity coalescing, manual merge UI |
| 8–9 | 3 Stage 3 | Typed relations, relation store |
| 9 | 5 | Adaptive fusion, weighted RRF, corpus_role gating |
| 10 | 5+7 | Tuning, ablation studies, eval scorecard refresh |
| 11–12 | 6 | Multi-step query loop |
| 12 | 7 | Final eval pass, headline numbers, OSV/YC pitch deck |

This is 90% effort allocation; reserve 10% for bugs, beta user feedback, and unexpected work.

---

## What success looks like at the end

- iKAT 2024 numbers competitive with academic baselines (NDCG@10 within 5 points of top submissions)
- Custom eval shows 30+ point P@5 improvement over baseline (vector-only) Magpie
- Demo: "what's on the test tomorrow" answers correctly with full citations
- Demo: "FAA budget approver" answers correctly via entity graph
- Demo: "things related to Diwali" surfaces receipts + planning docs + photos via topic + folder
- Cold-start (empty profile) still works at baseline quality; full profile shows clear lift
- All ablations show every layer contributes positive value

That's the OSV/YC pitch. That's also a defensible product. The work is large but each step is small, well-scoped, and individually shippable.

---

*End of document. Update as workstreams progress.*
