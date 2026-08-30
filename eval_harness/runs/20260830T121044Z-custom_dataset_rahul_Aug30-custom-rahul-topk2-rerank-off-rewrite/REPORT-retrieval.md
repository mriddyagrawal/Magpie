# RETRIEVAL REPORT

Run: `20260830T121044Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-rewrite`
Baseline for every comparison: `20260830T095758Z-custom_dataset_rahul_Aug30-custom-rahul-topk2-rerank-off-norewrite`
Single-knob ablation, verified from both `run.json`s: **rewrite ON vs OFF is the only differing parameter.** Same golden set (`golden_sha 0ebcdcbcdf109adb`, 120 items / 60 pairs), same backend (`cca67570`), same mounted index (`index_store.key 66974090bdcd62e6`, `hit: true`, built under the same sha — so the 25-file indexing loss documented in the baseline reports is byte-identically present here), `top_k=2`, `top_k_retrieval_max=12`, rerank OFF, solo gate structurally off, 545-file all-visual corpus, summary/BM25 tier structurally empty.

Scope: retrieval quality only. Answer correctness is another agent's lane; it appears below only where retrieval physically determined it.

---

## Executive summary

**The rewrite knob cost 7.7 points of hit@1 (0.933 -> 0.856 on the n=104 replay pool), and effectively all of that is one defect, not "rewriting is bad": the 3B rewriter's prompt begins with a wall-clock line ("Current date and time: Sunday, 2026-08-30 08:NN EDT"), and on 16 of 60 typed phrasings the model rewrote *the timestamp* instead of (or in addition to) the question.** Seven scored questions had their entire query replaced by date/time text; for all seven, gold — rank 1 in the baseline — fell out of the *entire* top-12, because ColQwen dutifully retrieved the corpus's most date/time-dense pages instead (degraded receipts with printed date-time stamps, fax cover sheets with "Date:/Time: ... EST" headers, and a slide deck about hourly tweet timing; I opened the files and verified this).

The report's central finding is the survivor mechanism (section 4): among the 12 scored echo rows, **whether gold survived is perfectly predicted (12/12) by whether any real question content survived anywhere in the concatenated ColQwen query string** — `run_search` feeds the fast tier `sq.query + " " + " ".join(sq.keywords)` (`src/stage2/search.py:849`), and on this corpus that concatenation is the *only* place keywords act, because their dedicated sparse prefetch targets the structurally empty summary tier. The 5 survivors were not "identical garbage queries that somehow won" — the supervisor's premise is wrong there — they are rows where the rewriter emitted date text *plus* the real terms, and the real terms kept winning rank 1 while the date tokens visibly dragged ranks 2-6 toward receipts.

Excluding the echo rows, rewrite is a wash at rank 1: paired over 86 answerable non-echo rows, 1 improved / 2 worsened / 83 unchanged. The one improvement is `rcpt-05-typed` (5 -> 1) — the baseline's *only* genuine ranking failure, fixed because the rewrite added the document-type words the terse query lacked, even though the rewritten query contains a hallucinated `[shop_name]` template placeholder. The two worsened are the `rcpt-08` pair (1 -> 3, both phrasings — the rewrite genericized a Mr DIY query into all-purpose purchase vocabulary). On the typed slice — the vague-phrasing proxy for docket hypothesis H2-prime — rewrite moves hit@1 by **-13.5 points with the echo rows in, and exactly 0.0 points with them out.** The measured "rewrite hurts" is the bug, not the concept; but the bug is real, shipped-code behavior, and it fires on the query style real users type.

---

## 0. Structural context, re-verified for this run

The three structural facts from the baseline retrieval report hold identically here; I re-verified them on this run's artifacts rather than assuming:

- **Pure ColQwen ranking.** All **1439/1439** ranked hits in `raw/retrieve.jsonl` carry `tier: "fast"`; zero summary-tier or both-tier hits.
- **Rank-degenerate scores.** Every score equals `1/(60+rank)` to within 1e-9 (1439/1439). Rerank off (`MAGPIE_RERANK=0` in `run.json.env_snapshot`; `rerank: false` in params) means fusion order *is* ColQwen's MaxSim order, and no score carries magnitude information.
- **Two retrieval passes.** `retrieval` (n=104) = the k_max=12 sweep in `raw/retrieve.jsonl`; `retrieval_end_to_end` (n=101) = what `ask()` returned at top_k=2. n=104 = 120 minus the 16 `nf-*` items that carry no gold by design.

What is new in this run: the answer pass made **120 rewrite LLM calls** (`raw/appdata/logs/llm-2026-08-30T12-10-46Z.log`: 120 requests with `response_format.json_schema.name == "SearchQuery"`, alongside 120 answer requests), and the retrieval sweep **replayed** each recorded `(final_query, keywords)` instead of rewriting again (`eval_harness/harness/worker.py:424-458`, `query_source: "replayed_from_answer_pass"` on 117/120 sweep rows). Rewrite cost p50 1.17 s / mean 1.22 s per query (`latency_s.rewrite` in `answers_enriched.json`); end-to-end p50 total latency was nevertheless slightly *lower* than baseline (14.3 s vs 15.4 s), i.e. the rewrite tax is real but below generation noise.

---

## 1. Headline metrics (verified)

All values recomputed from `answers_enriched.json` per-row blocks; they match `metrics.json` to three decimals.

### 1.1 Replay pool (sweep at k_max=12), n=104 per arm

| metric | rewrite (this run) | norewrite (baseline) | delta |
|---|---|---|---|
| hit@1 | **0.856** | 0.933 | -0.077 |
| hit@3 | 0.875 | 0.933 | -0.058 |
| hit@5 | 0.875 | 0.942 | -0.067 |
| hit@12 | 0.875 | 0.942 | -0.067 |
| MRR | **0.862** | 0.935 | -0.073 |
| nDCG@5 | **0.845** | 0.922 | -0.077 |
| recall@1 | **0.751** | 0.808 | -0.058 |
| recall@3 | 0.825 | 0.894 | -0.069 |
| recall@5 | 0.839 | 0.919 | -0.080 |
| recall@12 | 0.861 | 0.936 | -0.075 |

### 1.2 End-to-end (top_k=2 answer pass), n=101 per arm

| metric | rewrite | norewrite | delta |
|---|---|---|---|
| hit@1 | **0.851** | 0.931 | -0.079 |
| MRR | 0.858 | 0.931 | -0.073 |
| nDCG@5 | 0.825 | 0.896 | -0.071 |
| recall@1 | 0.748 | 0.807 | -0.060 |

`retrieval_divergence`: `n_comparable=101`, `n_query_differs=0`, `n_top1_differs=2` — section 9.

**The whole gap is 10 rows.** Per-qa first-gold-rank flips over the 104-row replay pool: **worse on 9** (`arch-05-typed` 1->None, `phone-09-typed` 1->None, `study-04-typed` 1->None, `viz-02-typed` 1->None, `viz-07-typed` 1->None, `viz-08-typed` 1->None, `viz-10-typed` 1->None, `rcpt-08-typed` 1->3, `rcpt-08-full` 1->3), **better on 1** (`rcpt-05-typed` 5->1), same on 94. Arithmetic check: net -8 rank-1 items / 104 = -7.7 points = the observed hit@1 delta. Note that `metrics.json`'s mean `first_gold_rank` (1.044 vs baseline 1.041) looks unchanged only because it averages rows where gold was *found*; the damage is seven golds not found at all.

Note also hit@3 = hit@5 = hit@12 = 0.875 in this run: when the echo loses gold, it does not demote it — **it removes it from the entire 12-deep window** (section 4).

---

## 2. The date echo: mechanism (required analysis 1)

### 2.1 Where the wall clock enters the prompt

The rewrite prompt itself is clean — `REWRITE_SYSTEM_PROMPT` (`src/stage2/search.py:52-67`) contains no date. The wall-clock text is injected by the shared agent plumbing in `src/llm.py`:

- `_timestamp_prefix()` (`src/llm.py:318-326`) returns `"Current date and time: " + now.strftime('%A, %Y-%m-%d %H:%M %Z')` — evaluated **per call**, local time.
- `_prepend_timestamp()` (`src/llm.py:329-330`) puts that string as the **first element** of every message list, for every agent whose output type is not in `_NO_TIMESTAMP_OUTPUTS = {"FileSummary"}` (`src/llm.py:340`). `SearchQuery` is not in the set, so **every rewrite call gets the timestamp**.
- `_flatten_message_for_local()` (`src/llm.py:1034-1092`) joins all string parts with `"\n\n"` and appends a JSON-only instruction. The rewriter's entire user turn is therefore:

  `Current date and time: Sunday, 2026-08-30 08:NN EDT\n\n<question>\n\nRespond with a single valid JSON object that matches the requested schema. ...`

  The user's actual question is the *middle* line, sandwiched between two instruction-shaped lines.

Two aggravators, both in shipped code: the system prompt explicitly instructs the model to "include the user's specific values verbatim (names, amounts, **dates**, ...)" (`search.py:57`) — and the only date in the entire context is the harness's own timestamp. And the comment block right at the injection site (`src/llm.py:333-339`) already documents this exact failure class for the summarizer: *"at index time it is just a plausible-looking date sitting in the context, and a 3B copies it"* — measured on sem_4, which is why `FileSummary` was exempted. The rewriter was left on the timestamped list. This bug was predicted by the code's own comments; `run.json._notes.rewrite` likewise stamps it as a "KNOWN RISK, deliberately measured."

### 2.2 Verbatim request/response pairs (from `raw/appdata/logs/llm-2026-08-30T12-10-46Z.log`)

Model `LiquidAI/LFM2.5-VL-3B-GGUF::Q6_K`, strict JSON-schema output, temperature 0. System prompt trimmed (it is the `REWRITE_SYSTEM_PROMPT` quoted above, byte-identical on all 120 calls).

**Total replacement — `viz-02-typed`** (request `req-1788091874641-5a00`, 12:11:14Z):

```
USER:     Current date and time: Sunday, 2026-08-30 08:11 EDT

          vaccines important for children chart lowest country

          Respond with a single valid JSON object that matches the requested schema. ...
RESPONSE: {"query": "current date and time Sunday 2026-08-30 08:11 EDT",
           "keywords": ["today's date", "current time", "EDT", "time zone", "date and time"]}
```

**Total replacement, different question, near-identical output — `arch-05-typed`** (12:19:34Z):

```
USER:     Current date and time: Sunday, 2026-08-30 08:19 EDT

          coke sodium leaflet tomato juice vs diet coke mg per serving
          ...
RESPONSE: {"query": "current date and time Sunday 2026-08-30 08:19 EDT",
           "keywords": ["today's date", "current time", "EDT", "time zone", "date and time"]}
```

Two completely different questions produced byte-identical outputs modulo the minute — the model attended to line 1 and discarded line 2 entirely. `nf-01-typed` ("passport scan", 12:40:33Z) produced the same query with a different keyword flavor (`["date","time","current","2026-08-30","EDT","UTC","UTC-4","timezone","timestamp"]`).

**Hybrid (the survivor shape) — `study-08-typed`** (12:27:53Z):

```
USER:     Current date and time: Sunday, 2026-08-30 08:27 EDT

          biosensor deck food industry pie chart what % was biosensors
          ...
RESPONSE: {"query":"current date and time Sunday 2026-08-30 08:27 EDT biosensor deck food
           industry pie chart percentage of biosensors",
           "keywords":["today's date","2026-08-30","EDT","biosensor market","food industry",
           "pie chart","market share","percentage", ... 16 items]}
```

The echoed timestamps match each call's wall clock (e.g. the 12:11:14Z request echoes "08:11" — UTC-4), confirming `_timestamp_prefix()` is evaluated per call and the per-row HH:MM differences in the echoed queries are exactly the answer pass's execution timeline (08:11 -> 08:40 EDT).

### 2.3 Extent of contamination (all 120 rows classified)

- **16/60 typed** `final_query` contain the phrase "current date and time"; **0/60 full**. The 16 match the supervisor's list exactly. But they split into two materially different classes:
  - **10 pure replacements** — no question content anywhere in the query: `arch-05`, `nf-01`, `phone-09`, `study-04`, `study-10`, `viz-02`, `viz-07`, `viz-08`, `viz-10` (timestamp string) and `nf-08` (bare "current date and time").
  - **6 hybrids** — date text *plus* real question terms in the query: `nf-03` ("lease agreement current date and time"), `study-02`, `study-06`, `study-08`, `study-09`, `viz-05`. Three of the 16 (`nf-03`, `nf-08`, `study-06`) carry the phrase without any HH:MM.
- **18 further rows** (13 typed, 5 full: `phone-09-full`, `rcpt-02-full`, `rcpt-04-full`, `rcpt-07-full`, `rcpt-09-full`) have wall-clock tokens spliced into an otherwise-real query — e.g. `rcpt-04-full` "Shell V-Power fuel fill-up **2026-08-30 08:33 EDT** liters cost", or `nf-07-typed` "vaccination certificate issued **today 2026-08-30**" (the model asserting the user's document was issued on the run date). Total: **34/120 final_query strings carry wall-clock text.** None of these 18 partial rows changed first_gold_rank; on this corpus the spliced tokens were survivable noise — with one perverse exception noted in section 8 (`nf-05-typed`).
- **Keywords: 41/120 lists contain "2026-08-30" or "Sunday"** (the supervisor's definition — count confirmed exactly), rising to **51/120** under the full wall-clock vocabulary (adds EDT/UTC/today/"current time"/timezone/etc.).
- `rewritten: true` on **117/120**; the 3 false are `phone-05-typed`, `phone-11-full`, `study-03-full`, whose answer rows errored (HTTP 400, same rows as baseline) before recording any `search_query`. Exactly **6** rewrites returned the question unchanged up to case/punctuation (`nf-02-typed`, `nf-06-typed`, `nf-07-full`, `rcpt-01-typed`, `study-03-typed`, `viz-06-typed`).

### 2.4 What triggers it — candidate discriminators tested against all 60 typed

The between-phrasings pattern is absolute: full phrasings — capitalized, punctuated, interrogative sentences ("Which country appears in both...?") — echoed **0/60**; typed phrasings — lowercase unpunctuated keyword strings — echoed **16/60** fully plus 13 more partially. The rewriter fails specifically on input that does not look like a sentence, i.e. exactly the register the feature exists to help.

*Within* the typed slice, every surface discriminator I tested fails to separate echo from non-echo:

| feature | echo (n=16) | non-echo (n=44) |
|---|---|---|
| words, median (range) | 9.5 (2-14) | 9.0 (1-18) |
| chars, median | 58 | 54.5 |
| ends with "?" | 0/16 | 0/44 (no typed query has one) |
| any uppercase | 0/16 | 1/44 |
| any digit | 2/16 | 7/44 |
| starts with an interrogative word | 0/16 | 1/44 |

Counterexample pairs kill every simple story: "passport scan" (2w) echoed while "wedding invitation" (2w), "python notes" (2w) and the one-word "transcript" did not; "chem notes" echoed, "training loss curve" did not; the 14-word `study-06-typed` echoed (hybrid) while the 18-word `phone-11-typed` did not. Length, case, digits, and interrogative shape are all ruled out as the 16-vs-44 separator.

The honest characterization: **conditional on the typed register, the echo is a deterministic per-prompt lottery.** Temperature is 0 and each prompt is unique (timestamp minute + question), so each row reproducibly either anchors on line 1 or on line 2 of the user turn; which way a given prompt tips is not predictable from any feature of the question I could measure. The practical consequence is that you cannot pre-screen questions to dodge this — the fix has to remove the timestamp from the rewrite call (it serves no purpose there; the rewriter never needs to resolve "today") or validate the rewrite output against the question (section 11).

---

## 3. Damage accounting

The nine worsened rows and their categories, sweep basis:

| qa_id | category | base rank | this run | gold in top-12? |
|---|---|---|---|---|
| viz-02-typed | charts | 1 | none | no |
| viz-07-typed | infographics | 1 | none | no |
| viz-08-typed | infographics | 1 | none | no |
| viz-10-typed | diagrams | 1 | none | no |
| arch-05-typed | documents | 1 | none | no |
| study-04-typed | notes_handwritten | 1 | none | no |
| phone-09-typed | photos | 1 | none | no |
| rcpt-08-typed | receipts_degraded | 1 | 3 | yes |
| rcpt-08-full | receipts_degraded | 1 | 3 | yes (2 of 3 golds) |

The seven echo losses are total: gold absent from all 12 returned candidates, so no plausible k rescues them. Downstream, all seven delivered zero gold to the generator; their verdicts moved from {2 partial, 3 wrong, 2 false_abstain} in the baseline to {4 wrong, 3 false_abstain} here — the echo converted the two partial credits this slice had into nothing (answer lane's story; noted here because retrieval fully determined it).

---

## 4. The survivors (required analysis 2 — the mechanism)

### 4.1 The puzzle, restated precisely — and the supervisor's premise corrected

Five scored echo rows kept first_gold_rank = 1 exactly as in the baseline: `viz-05-typed`, `study-02-typed`, `study-06-typed`, `study-08-typed`, `study-09-typed`. (`study-10-typed` is excluded: its gold was never indexed, so it is None -> None in both arms — though its baseline top-6 was the correct `CseGyan-Cpp-Notes-*` neighborhood and this run's is the date-attractor set, so it *would* have been a loss.) The supervisor framed this as "identical query string differing only in HH:MM — what distinguishes survivors?"

**The premise is false, and correcting it *is* the answer.** The survivors' queries were never the bare timestamp. Verbatim from `answers_enriched.json` / `raw/retrieve.jsonl` (identical, since the sweep replays):

| row | final_query | outcome |
|---|---|---|
| viz-05-typed | "current date and time Sunday 2026-08-30 08:12 EDT **country armed forces share chart teaching time chart**" | rank 1 kept |
| study-02-typed | "**oops concepts mind map C++ notes** current date and time Sunday 2026-08-30 08:24 EDT" | rank 1 kept |
| study-06-typed | "**train validation test bars 1+ 1- 2+ 2-** current date and time" | rank 1 kept |
| study-08-typed | "current date and time Sunday 2026-08-30 08:27 EDT **biosensor deck food industry pie chart percentage of biosensors**" | rank 1 kept |
| study-09-typed | "current date and time Sunday 2026-08-30 08:28 EDT **attention figure with phi(q) phi(k) prefix sum outer product**" | rank 1 kept |
| arch-05-typed (loser, for contrast) | "current date and time Sunday 2026-08-30 08:19 EDT" | gold gone |

The same split holds in the keywords: the seven losers' keyword lists are **pure date/time vocabulary with zero question words** (lexical overlap with the question: 0 content words in 7/7 — e.g. `viz-10-typed`: `["today","date","time","August 30 2026","EDT","current","date and time"]` for a question about leaf diagrams), while all five survivors' lists carry real terms (`study-09-typed`: `[...,"attention figure","phi(q)","phi(k)","prefix sum","outer product"]`).

### 4.2 The mechanism: one concatenated string, one populated tier

How do keywords and query enter ranking on this corpus? Read from `src/stage2/search.py`, verified against the artifacts:

- The fast tier is queried with a **single string**: `query_text = (sq.query + " " + " ".join(sq.keywords)).strip()` (`search.py:849`), encoded by ColQwen and matched via MaxSim.
- Keywords' only *other* consumer is a dedicated sparse prefetch **on the summary tier** (`search.py:407-417`) — which is structurally empty here (0 summary-tier hits in 1439). So on this corpus the supervisor's "keywords leg in fusion" does not exist as a separate vote; **keywords act purely as extra words appended to the ColQwen query text.**

So the effective ColQwen query for a loser is ~12 tokens of pure date/time/timezone text, and for a survivor it is the same date text **plus** the question's content terms. ColQwen's MaxSim scores a document by summing, over query tokens, each token's best patch match. Content tokens ("biosensor", "phi(q)", "mind map") have high-contrast best-matches only on the right documents and keep discriminating regardless of the appended noise; date tokens match *every* page that prints a date, best of all the pages that are *mostly* dates. When content tokens exist, they decide rank 1; when the query is 100% date tokens, nothing discriminates except date-density.

**Separation is perfect, 12/12 on the scored echo rows:** 7/7 rows with zero content anywhere in the concatenated string lost gold from the whole top-12; 5/5 rows with content anywhere kept gold at rank 1. No row dissociates the two carriers (there is no pure-date query with contentful keywords, nor the reverse — the 3B either ignored the question in both fields or in neither), so the query leg and keyword leg cannot be individually credited; what the data establishes is the disjunction: content-tokens-present-anywhere <=> survived. ColQwen tie-behavior plays no role — none of these rows involve tied (duplicate) candidates, and the survivors won outright, not by tie-break.

### 4.3 The date attractor set — verified by opening the files

If the mechanism above is right, the losers should all retrieve the same documents — the corpus's most date/time-dense pages — regardless of their (ignored) underlying question. They do. Across the 10 pure-echo rows' top-5 slots (50 slots), five files dominate: `bad_receipt_005.jpg` (9 appearances), `bad_receipt_022.jpg` (8), `doc_5403.jpg` (7), `doc_5400.jpg` (7), `deck_025.pdf` (7). I opened them:

- `bad_receipt_005.jpg` (receipts_degraded): a tax-invoice receipt whose most prominent field row is `Date : 09/01/2019 8:01:11 PM` — a printed date *and* clock time.
- `doc_5400.jpg` and `doc_5403.jpg` (documents): two DesignWrite **fax cover sheets** with bold header fields `Date: January 22, 2001 / Time: 4:15 PM EST` and `Date: January 19, 2005 / Time: 8:45 EST` — literally pages whose salient text is "Date", "Time", and a timezone abbreviation one glyph away from "EDT".
- `deck_025.pdf` (slides): a "most active hours" Twitter-timing deck — an hourly bar chart with hours 00-23 and the printed string `Timezone: America/Los_Angeles`.

This is ColQwen behaving *correctly on a garbage query*: asked for "current date and time ... EDT", it returned the pages that are about dates, clock times, and timezones. Retrieval did not fail; it was aimed at the wrong target. (Notably the attractor set contains no `notes_iam` file — relevant for section 8.)

### 4.4 Dose-response: the date tokens pull even when they lose

The survivors show the same force acting below rank 1, which is what elevates 4.2 from a correlation to a mechanism:

- `study-06-typed`: gold `arxiv_017.png` stays rank 1, but ranks 2-6 become `receipt_025.jpg` and four `bad_receipt_*` files (baseline ranks 2-6: `arxiv_018`, `screen_24509`, and receipt-adjacent files only from rank 4).
- `viz-05-typed` (two golds, both rel=2): `chart_002.jpg` rank 1, but the second gold `chart_036.jpg` drops 2 -> 4 behind a scene photo and `info_034.jpg`; recall@3 1.0 -> 0.5.
- `study-02-typed`: acceptable-source pages `CseGyan-Cpp-Notes-5/-6` pushed down; recall@5 0.75 -> 0.5, nDCG@5 0.82 -> 0.70.
- `study-08-typed` and `study-09-typed`: fully intact (their content-keyword lists are the two longest, 14 and 8 content terms).

So: date tokens exert a uniform receipt/fax-ward pull on every echoed query; question tokens, when present, out-vote them at rank 1; gold disappears exactly when there are no question tokens left to vote. Verified end to end against the sweep rankings in `raw/retrieve.jsonl`.

---

## 5. `rcpt-08` (required analysis 3): the one non-echo ranking regression

Multi-gold enumeration item: gold = 3 Mr DIY receipts (`bad_receipt_002.jpg`, `bad_receipt_004.jpg`, `bad_receipt_027.jpg`, all rel=2 in `qrels.tsv`). Both phrasings slid 1 -> 3. Side-by-side (sweep, top of list; G = gold):

| arm | query (verbatim) | keywords | top ranks |
|---|---|---|---|
| base typed | "how much did i spend at mr diy altogether" | [] | **G**`bad_receipt_002` 1, `screen_24454` 2, ... |
| this run typed | "total amount spent at Mr DIY" | [Mr DIY, total spent, spent, total cost, transaction history] | `receipt_009` 1, `receipt_036` 2, **G**`bad_receipt_002` 3 |
| base full | "Adding up all my Mr D.I.Y. receipts, how much did I spend there in total?" | [D.I] | **G**`002` 1, **G**`004` 2, ..., **G**`027` 8 |
| this run full | "Mr D.I.Y. receipts total spent" | [Mr D.I.Y., receipts, total spent, spent amount, transaction history] | `receipt_036` 1, `receipt_009` 2, **G**`004` 3, ..., **G**`002` 7, `027` **absent** |

**What outranked gold:** `receipt_009.jpg` and `receipt_036.jpg` — receipts_phone files, *not* Mr DIY, i.e. same-genre distractors. **Worse rewrite, not noise:** two *independently produced* rewrites (typed and full inputs differ completely) converged on near-identical generic purchase vocabulary ("total spent", "total cost/spent amount", "transaction history") and slid the same direction in both — a coincidence tie-noise cannot produce, especially on a corpus where ranking is otherwise deterministic (94/104 rows byte-stable across arms). The mechanism reads directly off the strings: the baseline queries carry idiosyncratic tokens ("altogether", the full sentence's "Adding up all my ... receipts") and little else, so "mr diy" does the discriminating; the rewrites *dilute* the brand token with 4-5 generic receipt-vocabulary terms that match every prototypical receipt in the corpus, and prototypical receipts won. It is the exact inverse of `rcpt-05-typed`, where adding document-type vocabulary ("receipt", "invoice") to a query that *lacked any* document cue fixed the ranking (baseline had matched "shop" to photographs of shops). Same lever, opposite sign: **rewrite vocabulary helps when the raw query under-specifies the document type and hurts when it already contained a discriminative token that the added genre-vocabulary dilutes.**

Materiality: both rcpt-08 rows are LIST_ALL-widened to 12 files end-to-end (section 7.3), so gold still reached the generator in both arms; the measurable retrieval loss is rank-1/recall (`rcpt-08-full` recall@12 1.0 -> 0.667: third gold `bad_receipt_027` left the top-12 entirely).

---

## 6. Rewrite's effect excluding the echo (required analysis 4)

### 6.1 Paired per-qa deltas, answerable non-echo pool

Pool: 104 scored minus 13 scored echo rows minus the 5 remaining index-dead rows (`rcpt-07` pair, `study-05` pair; `study-10-typed` is already in the echo set) = **86 rows** with a defined pairing.

- **Improved: 1** — `rcpt-05-typed` (5 -> 1).
- **Worsened: 2** — `rcpt-08-typed`, `rcpt-08-full` (both 1 -> 3).
- **Unchanged: 83.**

Pool metrics: hit@1 0.977 vs baseline 0.988 (net one item), MRR 0.984 vs 0.991, recall@5 0.963 vs 0.975, nDCG@5 0.969 vs 0.978. Below rank 1, the *complete* list of non-echo rows where any sweep metric moved (there are only six):

| row | what moved | cause |
|---|---|---|
| rcpt-05-typed | hit@1 0->1, MRR 0.2->1.0 | the fix (section 5) |
| rcpt-08-typed / -full | hit@1 1->0; full recall@12 1.0->0.667 | genre-vocabulary dilution (section 5) |
| viz-05-full | recall@3/5/12 1.0->0.5, nDCG@5 1.0->0.61 | **intent narrowing**: the question asks for the country in *both* the armed-forces chart *and* the teaching-time chart; the rewrite is "Our World in Data armed forces personnel share of population 1985" — the second chart was deleted, and gold `chart_036.jpg` (base rank 2) left the top-12. hit@1 unaffected. |
| study-02-full | recall@5 0.75->0.5 | acceptable-source pages reshuffled within the Cpp-Notes series; gold stays rank 1 |
| viz-11-typed | nDCG@5 0.873->0.747 | reordering among the 9 byte-identical diagram twins; cosmetic |

`viz-05-full` matters: it is a second, echo-independent failure shape of the same underlying weakness — **the 3B rewriter drops part of the input's intent** (there the timestamp displaced the whole question; here one half of a two-target question displaced the other). Multi-target/comparison questions are structurally exposed to it.

### 6.2 Verdict on "rewrite hurts retrieval on this corpus"

At rank 1: **entirely the echo bug.** Removing echo rows leaves a 1-fix-vs-2-loss residual that nets to one item in 86 and would not survive any significance test. Below rank 1: a small genuine residual harm on multi-gold items (rcpt-08-full, viz-05-full, study-02-full lose deep recall; one large offsetting fix on rcpt-05) — real, mechanistically explained, and small next to the echo.

### 6.3 H2-prime (docket, `eval_harness/PLAN.md`)

H2-prime predicts: *"rewrite changes hit@1 on vague phrasings by >=10 points"*, to be tested on >=64 vague phrasings. Typed is this dataset's vague proxy. Measured, sweep basis:

| pool | n/arm | rewrite | norewrite | delta |
|---|---|---|---|---|
| typed, all scored | 52 | 0.788 | 0.923 | **-13.5 pts** |
| typed, minus index-dead | 49 | 0.837 | 0.980 | **-14.3 pts** |
| typed, minus index-dead minus echo | 37 | 0.973 | 0.973 | **0.0 pts** |
| full, all scored (contrast) | 52 | 0.923 | 0.942 | -1.9 pts |

The >=10-point threshold is cleared — in the harmful direction — and **100% of the effect is the echo defect**: the with-echo and without-echo cells differ by 14 points, and the without-echo cell is exactly zero (each arm misses one different item there: baseline `rcpt-05-typed`, this run `rcpt-08-typed`). Two pre-registration caveats: n=49-52 typed is below H2-prime's >=64-question floor, and this is a single corpus (docket §6 requires two before generalizing). The right reading for the docket: *H2-prime's magnitude bar is met by a defect in the rewrite implementation, not by rewriting per se; the intended-behavior effect on vague phrasings measures 0.0 points on this corpus.*

---

## 7. Clean pool and standard tables (required analyses 5-6)

### 7.1 Clean pool, baseline supervisor's exact exclusion

Definition replicated from the baseline SUPERVISOR-REPORT / REPORT-retrieval §1.3: drop the 6 never-indexed-gold rows (`rcpt-07` pair — `receipt_040.jpg`; `study-05` pair — `electric-charge-and-field-9.pdf`; `study-10` pair — `CseGyan-Cpp-Notes-17/18/19.pdf`) and the structurally recall-capped `viz-11` pair -> **n=96**.

| pool | n | arm | hit@1 | hit@5 | MRR | nDCG@5 | recall@1 | recall@5 |
|---|---|---|---|---|---|---|---|---|
| clean | 96 | **rewrite** | **0.906** | 0.927 | **0.913** | 0.899 | 0.811 | 0.898 |
| clean | 96 | norewrite | 0.990 | 1.000 | 0.992 | 0.980 | 0.873 | 0.984 |
| clean, non-echo | 84 | rewrite | 0.976 | 1.000 | 0.984 | 0.973 | 0.882 | 0.972 |
| clean, non-echo | 84 | norewrite | 0.988 | 0.988 | 0.990 | 0.981 | 0.878 | 0.985 |
| clean, e2e | 93 | rewrite | 0.903 | — | 0.910 | 0.887 | 0.810 | — |
| clean, e2e | 93 | norewrite | 0.989 | — | 0.989 | 0.964 | 0.875 | — |

(My recompute of the baseline's clean pool from its own `answers_enriched.json` reproduces its published 0.990 / 0.992 exactly; nDCG@5 recomputes to 0.980 vs the 0.982 printed in its report — a 0.002 discrepancy attributable to rounding, immaterial.)

Reading: the baseline's clean pool had **one** rank-1 miss in 96; this run has **nine** — and they are precisely the 7 echo losers plus the `rcpt-08` pair. On the 84 clean non-echo rows the two arms are statistically the same system (one differing miss each way). Ranking capability did not change; query integrity did.

### 7.2 Phrasing and category

Typed vs full is section 6.3's table. Per category (sweep, as-scored, hit@1 — clean-pool caveats as in the baseline report):

| category | n | rewrite | norewrite | delta | scored echo rows in category |
|---|---|---|---|---|---|
| charts | 10 | 0.900 | 1.000 | -0.100 | 2 (viz-02 lost, viz-05 survived) |
| diagrams | 4 | 0.750 | 1.000 | -0.250 | 1 (viz-10 lost) |
| documents | 6 | 0.833 | 1.000 | -0.167 | 1 (arch-05 lost) |
| figures | 6 | 1.000 | 1.000 | 0 | 2 (study-06, study-09 both survived) |
| infographics | 8 | 0.750 | 1.000 | -0.250 | 2 (viz-07, viz-08 lost) |
| notes_handwritten | 10 | 0.500 | 0.600 | -0.100 | 3 (study-04 lost; study-02 survived; study-10 dead) |
| photos | 6 | 0.833 | 1.000 | -0.167 | 1 (phone-09 lost) |
| receipts_degraded | 8 | 0.750 | 0.875 | -0.125 | 0 (rcpt-08 pair lost, rcpt-05-typed fixed) |
| receipts_phone | 10 | 0.800 | 0.800 | 0 | 0 (deficit is index-dead rcpt-07 in both arms) |
| scans_multipage | 8 | 1.000 | 1.000 | 0 | 0 |
| scene_text | 8 | 1.000 | 1.000 | 0 | 0 |
| screenshots | 8 | 1.000 | 1.000 | 0 | 0 |
| slides | 6 | 1.000 | 1.000 | 0 | 1 (study-08 survived) |
| tables_fr | 6 | 1.000 | 1.000 | 0 | 0 |

Every category delta is exactly its echo-loss (or rcpt-08/rcpt-05) count — no category moved for any other reason. The five categories with echo survivors or no echoes are unchanged at 1.000.

### 7.3 Gate and widener: structurally off, phantom counted

- **Actual solo-gate firings: 0.** `rerank=false` makes `gate_to_solo()` return its input at the first branch (`_rerank_enabled()` check; `search.py:567-579`, gate at `:923ff`), `run.json` stamps `solo_gate_structurally_off: true`, and `LOCAL_SOLO_MARGIN=0` would disable it a second time.
- **`metrics.json solo_gate.fire_rate: 0.042` is the known phantom** — `enrich.py` infers "gated" from answer-pass-returned-1-file-while-sweep-had-more. The 5 phantom rows (`arch-04-full`, `arch-06-typed`, `study-03-typed`, `study-08-full`, `study-08-typed`) are all the multi-page-PDF collapse documented in the baseline report (fetch 4 page-points -> all in one PDF -> dedup to one file): single files `scan_mtnh0227.pdf`, `scan_gzyh0227.pdf`, `deck_022.pdf`, `deck_027.pdf` x2, each with the telltale `solo_margin_observed: 0.0` (an RRF adjacent-rank difference, not a cross-encoder margin). Baseline had 6 phantoms; `arch-04-typed` left the set here because its *rewritten* query pulled `bad_receipt_032.jpg` into the 4-point fetch window, breaking the collapse — direct proof the "fire rate" tracks retrieval composition, not any gate.
- **Widener (`enumerate_lists`) fired on the identical 7 rows in both arms** (`arch-06-full`, `nf-06-full`, `phone-05-full`, `phone-07-typed`, `rcpt-01-full`, `rcpt-08-typed`, `rcpt-08-full`): the query classifier runs on the raw `question` (`run_search(question=...)`, `search.py:771-816`), not the rewritten query, so routing is rewrite-invariant by construction. This is why rcpt-08 still delivered gold end-to-end despite the rank slide.

---

## 8. notes_iam distractor pressure (required analysis 7)

30 indexed IAM handwriting strips, zero golden items — any hit is a false positive by construction.

| window | rewrite (this run) | norewrite |
|---|---|---|
| top-1 | **0**/120 | 1/120 |
| top-2 | **0**/240 | 1/240 |
| top-5 | 0/600 | 3/600 |
| top-12 | 6/1439 (6 queries) | 10/1437 (10 queries) |
| delivered to generator (e2e) | 1 slot (`nf-06-full`, a widened 12-file row) | 1 slot (`nf-05-typed`) |

Distractor pressure did not worsen under rewrite; it nominally shrank. Two reasons, both mechanistic rather than reassuring: (a) the date-echo attractor is receipts and fax cover sheets (section 4.3), not handwriting — IAM strips do not print dates prominently — so the bug's garbage went elsewhere; (b) the baseline's single top-2 false positive, `nf-05-typed` ("transcript" -> `note_004.png`, the most defensible IAM hit in the baseline), disappeared *because of* the bug: its query was rewritten to "August 30 2026 time", which retrieves `bad_receipt_005.jpg` and friends instead. One false positive was traded for a different one, not fixed. The 6 remaining top-12 IAM appearances (`arch-01-typed` r12, `nf-06-full` r11, `nf-06-typed` r8, `study-04-full` r8, `viz-02-full` r12, `viz-05-full` r6) are all handwriting-adjacent queries (notes, figures, charts), never receipts or tables — the genre separation observed in the baseline holds.

---

## 9. Replay integrity (required analysis 8)

- **`n_query_differs = 0` — confirmed** (`retrieval_query_matched` true on all 101 comparable rows). The composed-mode replay did what it was built for: `phase_retrieve` re-ranks the answer pass's recorded `(final_query, keywords)` verbatim (`eval_harness/harness/worker.py:424-458`), so both passes ranked the same — including the same garbage — strings. The docstring records why this exists: a second live rewrite had been measured diverging on 45/120 questions *because of the wall-clock prompt text*, i.e. the harness already routed around the nondeterminism side of this bug; this run measured the quality side.
- **3 rows had nothing to replay** (`phone-05-typed`, `phone-11-full`, `study-03-full`: HTTP-400 answer rows, no recorded query — hence n_comparable=101, not 104). The sweep gave them a fresh rewrite (`query_source: "own_rewrite"`; exactly 3 SearchQuery calls in `raw/appdata/logs/llm-2026-08-30T12-45-43Z.log`, all timestamped 08:45 EDT). None echoed; all three rank normally in the sweep. They are in the n=104 pool on their own-rewrite queries — a small basis asymmetry to remember if anyone diffs those three rows across arms.
- **`n_top1_differs = 2` — both are `viz-11`, and it is duplicate tie-breaking, not instability.** `viz-11-typed`: sweep top-1 `diagram_010.jpg` vs e2e `diagram_011.jpg`; `viz-11-full`: sweep `diagram_010.jpg` vs e2e `diagram_005.jpg`. All are members of the 9-copy byte-identical twin group (`diagram_003..011`; baseline report §6.5): identical bytes -> identical ColQwen embeddings -> exactly tied MaxSim, and the two passes query at different pool sizes (k_max=12 -> limit 24 vs top_k=2 -> limit 4), which orders exact ties differently. The baseline showed the same 2 rows with a different pair of twins (`diagram_006` vs `_011`). Not temperature-0 rewrite nondeterminism — the queries were byte-identical by construction — and no information about ranking quality. Everywhere ties are breakable, the retriever is deterministic: 94/104 rows have byte-identical gold ranks across two runs made 2.5 hours apart.

---

## 10. Caveats

1. **The echo characterization is one model, one prompt, one corpus**: LFM2.5-VL-3B Q6_K under strict-schema decoding at temp 0. The 16/60 rate is not a universal constant; treat it as an existence-and-mechanism result. (The receipts-era measurement of 45/120 rewrite divergence, cited in `worker.py`, independently corroborates the instability class.)
2. **Keywords' sparse-prefetch consumer is untested here** (empty summary tier). On a mixed text corpus, the 41-51 date-contaminated keyword lists would get a *dedicated BM25 vote* (`search.py:407-417`) — the blast radius of this bug on production-shaped corpora is plausibly larger than measured.
3. **Attribution inside ColQwen is inferential.** Scores are rank-degenerate (§0), so claims like "genre vocabulary diluted the brand token" (rcpt-08) rest on cross-phrasing consistency and the visible retrieved sets, not on score margins. The echo mechanism itself does not suffer this: 12/12 separation plus the verified attractor files is not a margin argument.
4. **Golden set is SILVER / model-authored** (0 human-verified), unchanged from baseline; unchanged caveats about `viz-11` twins and |relevant|>2 recall caps apply to all recall/nDCG columns.
5. Deltas here are per-item exact (same golden set, same index, paired rows); no significance test will bless 1-vs-2-item residuals, and none is claimed.

## 11. What to fix (retrieval lane, ranked)

1. **Add `"SearchQuery"` to `_NO_TIMESTAMP_OUTPUTS` (`src/llm.py:340`).** The rewriter has no legitimate use for "today" (it resolves nothing time-relative; it *invents* dates — `nf-07-typed`, `rcpt-04-full`), and the codebase already exempted `FileSummary` for this exact 3B-copies-the-date failure. One line; removes the entire 14-point typed-slice loss mechanically.
2. **Validate rewrites against the question.** `rewrite_query()` already substitutes the raw question when the parse fails (`search.py:110-111`); extend the same fallback to "zero content-word overlap between rewrite+keywords and the question" — that predicate separates the 7 losers from everything else in this run with no false positives.
3. **Strip pure date/time tokens from `keywords` before the `search.py:849` concatenation** (defense in depth; also protects the future BM25 path per caveat 2).
4. **Multi-target preservation**: `viz-05-full` shows the rewriter deleting one of two named targets. Either instruct "preserve every named document/chart/entity" in `REWRITE_SYSTEM_PROMPT` or keep rewrite off for comparison-classified queries (the comparative regex at `search.py:887` already exists).
5. Keep the production default (rewrite off locally) until 1-2 land; this run is direct evidence for the `search.py:988` comment that motivated that default ("the 3B rewriter replaced questions rather than cleaning them").

---

## 12. Verdicts on supervisor claims

| # | Claim | Verdict |
|---|---|---|
| 1 | "16/60 typed final_query were REPLACED ENTIRELY by 'current date and time Sunday 2026-08-30 HH:MM EDT' (per-row timestamps differ); 0/60 full; affected list [16 qa_ids]" | **MODIFIED.** The list of 16, the all-typed restriction, 0/60 full, and the differing per-row timestamps are all confirmed exactly. But only 9 were replaced entirely by the timestamp string (+1 by the bare phrase, `nf-08-typed`); **6 of the 16 retained real question content alongside the date text** (`nf-03`, `study-02`, `study-06`, `study-08`, `study-09`, `viz-05` — three of these carry no HH:MM at all). That distinction is not pedantry: it is the entire survivor mechanism (§4). A further 18 rows (13 typed, 5 full) have date tokens spliced into otherwise-real queries — the contamination is 34/120 queries, wider than the claim implies, though only the total replacements cost rank-1 gold. |
| 2 | "41/120 keyword lists contain a date token ('2026-08-30' or 'Sunday')" | **CONFIRMED** — exactly 41 under that definition; 51 under full wall-clock vocabulary (EDT/UTC/today/'current time'/timezone). |
| 3 | Gold-rank flips: worse on 9 [list], better on 1 (rcpt-05-typed 5->1, baseline's only genuine ranking failure, fixed despite a literal '[shop_name]' placeholder) | **CONFIRMED** — every qa_id and both rank values verified; the `[shop_name]` and `on 2026-08-30` artifacts are verbatim in the logged rewrite response, and the fix mechanism (added "receipt"/"invoice"/"chocolate bars" vocabulary curing the baseline's shop-photo confusion) is established in §5. |
| 4 | "rewritten flag true on 117/120; roughly 6 rewrites returned the question unchanged" | **CONFIRMED** — 117 exactly (the 3 false are HTTP-400 rows that recorded no query at all, not declined rewrites), and exactly 6 unchanged-up-to-case/punctuation. |
| 5 | Survivors puzzle: "identical query string differing only in HH:MM"; candidate explanations "keywords leg still carrying real terms into fusion" / "ColQwen tie-behavior" | **PREMISE REFUTED, MECHANISM RESOLVED.** Survivor queries were *not* identical to loser queries — every survivor's final_query itself retains question content, and every loser's is pure date text (12/12 separation, §4.1-4.2). The keywords intuition is half-right with a wrong mechanism: keywords do carry the surviving terms too, but on this corpus they enter ranking **only** by string-concatenation into the ColQwen query (`search.py:849`) — their "fusion leg" (the sparse prefetch) targets the empty summary tier and never voted. Query and keyword legs never dissociate in the data, so neither can be solely credited. ColQwen tie-behavior is irrelevant — no ties are involved (§4.2). |
| 6 | "study-10-typed's gold was never indexed — excluded" from the survivor analysis | **CONFIRMED** (None->None in both arms). Worth recording: its baseline top-6 was the correct Cpp-Notes neighborhood and this run's is the date-attractor set — it would have been an 8th loss. |
| 7 | Headline: hit@1 0.856 vs 0.933, MRR 0.862 vs 0.935, nDCG@5 0.845 vs 0.922, recall@1 0.751 vs 0.808, e2e hit@1 0.851 vs 0.931 | **CONFIRMED** to three decimals by independent recompute from per-row artifacts. |
| 8 | "metrics.json retrieval_divergence.n_query_differs=0 should confirm the replay" | **CONFIRMED** — 0/101; plus the 3-row own-rewrite fallback asymmetry documented in §9. |
| 9 | solo_gate.fire_rate is a phantom | **CONFIRMED** — 0 actual firings, 5 phantom rows, all multi-page-PDF collapses; the phantom count even *changed* (6->5) because a rewritten query altered the fetch-window composition of `arch-04-typed` (§7.3), which is conclusive that the metric measures retrieval composition, not gating. |

**Bottom line.** Ranking capability is unchanged between the arms — on clean non-echo rows both sit at ~0.98 hit@1, and every category without an echoed query is identical. What this arm measured is a query-integrity defect: a per-call timestamp, prepended by shared plumbing to a rewriter that was explicitly instructed to preserve dates, deterministically replaces terse typed questions ~27% of the time (16 full + 13 partial of 60) and costs rank-1 gold precisely when no question token survives the rewrite. Fix the injection, and this corpus's evidence says rewrite ON would measure within one item of rewrite OFF — with one real fix (rcpt-05) and one real regression (rcpt-08) left to argue about.
