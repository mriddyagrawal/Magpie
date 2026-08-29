# Retrieval analysis — `20260829T065335Z-receipts-topk2-rerank-off`

Corpus: 148 receipt JPEGs. Golden: 120 questions / 53 answerable pairs + 7 not-found pairs.
Config: `top_k=2` (retrieval **and** generator fan-out), `top_k_retrieval_max=12`,
`rerank=false` (`MAGPIE_RERANK=0`), `rewrite=true`, `fast_search=true`, local LFM2.5-VL-3B, `n_ctx=16384`.

---

## 0. Headline

Retrieval is not the main thing wrong with this run, but it is wrong in four
separable, individually fixable ways — and only one of them is ColQwen's fault.

1. **The reported retrieval numbers are not the ones the generator saw.**
   `metrics.json` scores a diagnostic pass that ran at `k_max=12` with its own
   independent LLM rewrite. True end-to-end hit@1 is **0.726, not 0.783**.
2. **The dominant ranking failure is the query rewriter, not the retriever.**
   The rewrite prompt prepends a wall-clock timestamp; the 3B rewriter treats it
   as part of the question. On 4 questions the entire rewritten query *is* the
   timestamp. Where the date leaks into the query string, hit@1 falls from
   **0.878 → 0.588** even when the vendor name survives.
3. **Every enumeration failure is a `k` failure, not a ranking failure.** ColQwen
   ranked all 5 Wan Sheng receipts at 1–5, 7 of 8 Kedai Papan at 1–7, all 6 Gin
   Kee at 1–6. `top_k=2` throws 60–75% of that away before the generator sees it.
4. **The router's `top_k` widener fires exactly backwards** — never on the three
   enumeration pairs that need it, and on 7 two-to-three-file synthesis questions
   that don't. 4 of those 7 blew past `n_ctx` and returned HTTP 400 with **zero**
   files reaching the generator. Those 4 are the run's 4 "errors".

All supervisor context claims are confirmed by the raw data (§6). One is
sharpened: the pass-to-pass divergence is 100% attributable to rewrite drift, not
to the `fetch_k` asymmetry I initially suspected.

---

## 1. Two passes, two answers

`enrich.py:276` computes `out["retrieval"]` from `ranked_by_id` — i.e. from
`raw/retrieve.jsonl`, the standalone diagnostic pass (`worker.py:391`). That pass
calls `run_search` directly at `k_max=12` **with its own `rewrite_query()` call**.
The generator was fed `raw/answers.jsonl`'s `retrieved`, produced by `ask()`
(`pipeline.py:147`) at `top_k=2` with a *separate* rewrite. The two never share a
query string.

| metric | separate pass (reported) | **end-to-end `ask()` (real)** | Δ |
|---|---|---|---|
| hit@1  | 0.783 | **0.726** | −0.057 |
| hit@2  | 0.858 | **0.821** | −0.038 |
| hit@3  | 0.868 | 0.821 | −0.047 |
| hit@5  | 0.915 | 0.830 | −0.085 |
| hit@12 | 0.934 | 0.830 | −0.104 |
| recall@1 | 0.671 | **0.637** | −0.034 |
| recall@2 | 0.795 | **0.769** | −0.027 |
| recall@5 | 0.891 | 0.772 | −0.119 |
| recall@12 | 0.928 | 0.778 | −0.150 |
| MRR    | 0.838 | **0.776** | −0.062 |
| nDCG@5 | 0.847 | **0.754** | −0.093 |

n = 106 answerable questions in both columns.

**Read the @3/@5/@12 columns with care.** End-to-end, 113 of 120 questions
returned exactly 2 files, so `hit@5` and `hit@12` are almost identical to
`hit@2` by construction — they are not evidence that the deeper ranking is
worse, only that it does not exist. `hit@1`, `hit@2`, MRR and nDCG@5 are the
honest comparisons.

Gold-file rank distribution:

| | rank 1 | 2 | 3 | >3 | missed |
|---|---|---|---|---|---|
| separate pass | 83 | 8 | 1 | 7 | 7 |
| end-to-end | 77 | 10 | — | 1 | **18** |

Of the 18 end-to-end misses, **4 are the HTTP-400 rows** (§5) where retrieval
results were discarded with the failed generation, so 14/102 are true ranking
misses.

### Why the two passes disagree

Top-2 differs on **17 of 106** answerable questions (ordered list); 14 differ as
a *set*. Excluding the 4 error rows, 13 of 102 differ.

**Every single one of those 17 also has a different rewritten query.** Zero
divergences occurred with an identical rewrite. Across the 116 non-errored rows,
**41 (35%) of rewrites differ between the two passes**, and 23 of those 41 differ
*only* in date/time tokens — the diagnostic pass ran at 03:00–03:03 EDT, the
answer pass at 03:07–03:31, and the clock string is inside the prompt.

The starkest case is `rcpt-a-01-typed`. The two rewrites are byte-identical
except that the diagnostic pass emitted one extra keyword, `"03:00"`. That single
clock token changed the rank-2 file from `receipt_X51006008206.jpg` to
`receipt_X51005806718.jpg`. The retrieval stack is measurably sensitive to a
token that carries no information about the user's question.

> **Reproducibility consequence:** this run cannot be replayed. Re-running it at a
> different wall-clock minute produces different queries and therefore different
> rankings. The `golden_sha` / `index_params_hash` stamps do not cover this.

---

## 2. Breakdowns

### By answer type

| type | n | hit@1 sep → **e2e** | hit@2 sep → **e2e** | recall@2 sep → **e2e** | nDCG@5 sep → **e2e** |
|---|---|---|---|---|---|
| extractive | 80 | 0.800 → **0.775** | 0.875 → **0.875** | 0.875 → **0.875** | 0.875 → **0.838** |
| synthesis | 20 | 0.650 → **0.450** | 0.750 → **0.550** | 0.617 → **0.475** | 0.704 → **0.479** |
| enumeration | 6 | 1.000 → **1.000** | 1.000 → **1.000** | 0.328 → **0.328** | 0.954 → **0.553** |

Extractive retrieval is essentially fine and essentially unaffected by which pass
you measure. Synthesis collapses end-to-end (−0.20 hit@1) because 4 of its 20
questions are the HTTP-400 rows. Enumeration has **perfect hit@1 and 0.33
recall@2** — the retriever finds the right vendor every time and the fan-out
discards the rest.

### By difficulty

| difficulty | n | hit@1 sep → **e2e** | recall@2 sep → **e2e** | nDCG@5 sep → **e2e** |
|---|---|---|---|---|
| easy | 40 | 0.925 → **0.900** | 0.950 → **0.950** | 0.950 → **0.932** |
| medium | 40 | 0.675 → **0.650** | 0.800 → **0.800** | 0.799 → **0.745** |
| hard | 26 | 0.731 → **0.577** | 0.550 → **0.441** | 0.762 → **0.497** |

"hard" is exactly the multi-file slice (identical n and identical numbers), so
difficulty here is a proxy for gold-source count, not for question subtlety.

### By `requires.multi_file`

| | n | hit@1 sep → **e2e** | recall@2 sep → **e2e** | recall@12 sep | nDCG@5 sep → **e2e** |
|---|---|---|---|---|---|
| false | 80 | 0.800 → **0.775** | 0.875 → **0.875** | 0.950 | 0.875 → **0.838** |
| true | 26 | 0.731 → **0.577** | 0.550 → **0.441** | 0.861 | 0.762 → **0.497** |

The `recall@12 = 0.861` on multi-file is the important number: **the ranking
already contains 86% of the required evidence within 12 candidates.** The
end-to-end 0.441 is almost entirely the `k=2` cap, not the ranker.

---

## 3. The phrasing gap is a rewriter gap

Reported `by_phrasing` (from the diagnostic pass): typed hit@1 0.698 vs full
0.868 — a 17-point gap. End-to-end it is typed 0.660 vs full 0.792.

Paired by `pair_id`, **9 of 53 pairs diverge** at k=2 in either pass. In **8 of
the 9 the `full` phrasing wins**; only `rcpt-a-06` goes the other way.

| pair | vendor | sep typed → full | e2e typed → full |
|---|---|---|---|
| rcpt-a-06 | Yong Tat Hardware | 1 → **miss** | 1 → **miss** |
| rcpt-b-04 | Ben's Independent Grocer | 4 → 1 | miss → 1 |
| rcpt-b-06 | Premio Stationery | 11 → 1 | miss → 1 |
| rcpt-c-09 | Restoran Wan Sheng | 6 → 2 | miss → 2 |
| rcpt-c-10 | Kedai Buku New Acheivers | miss → 1 | miss → miss¹ |
| rcpt-d-02 | Bakalima (Dengkil) | 3 → 2 | miss → 2 |
| rcpt-d-03 | Kaison Furnishing | 5 → 1 | miss → 1 |
| rcpt-d-09 | Kedai Papan Yew Chuan | miss → 1 | miss → miss¹ |
| rcpt-e-04 | Super Seven Cash & Carry | 4 → 2 | miss → 2 |

¹ the `full` member is an HTTP-400 row (§5), not a ranking miss.

### The mechanism: the terse phrasing loses the vendor name in the rewrite

Every one of these questions names its vendor in the raw user text. Measuring how
often a vendor token survives into `rewritten_query.query + keywords`:

| phrasing | vendor token survives |
|---|---|
| full | **44/44 = 100%** |
| typed | **36/43 = 84%** |

The 7 losses, all `typed`:

| qa_id | user typed | rewriter produced | gold rank (sep) |
|---|---|---|---|
| `rcpt-b-06-typed` | `premio battery invoice no` | `battery invoice current date time` | **11** |
| `rcpt-c-09-typed` | `wan sheng march which one more expensive` | `March 2026 which is more expensive` | **6** |
| `rcpt-d-02-typed` | `bakalima dengkil petrol how many litres` | `how many liters of petrol are in a gallon?` | 3 |
| `rcpt-c-10-typed` | `kedai buku new acheivers both bills added up` | `current date and time Saturday 2026-08-29 03:02 EDT` | **miss** |
| `rcpt-d-09-typed` | `kedai papan 21 march both bills together` | `current date and time Saturday 2026-08-29 03:02 EDT` | **miss** |
| `rcpt-c-06-typed` | `gin kee cement pasir gst amount` | `current date and time Saturday 2026-08-29 03:01 EDT` | 1 (rescued by keywords) |
| `rcpt-a-02-typed` | `f&p phamacy what date` | `Farmers Drug Pharmacy store opening date` (hallucinated vendor) | 2 |

`rcpt-d-02-typed` deserves separate mention: the rewriter did not rewrite the
query at all, it **answered a general-knowledge question it invented**
("how many liters of petrol are in a gallon?"), discarding both "bakalima" and
"dengkil". This is the rewrite prompt's "Do not answer the question" instruction
failing on a 3B model.

This is not ColQwen preferring verbose queries. It is a 3B rewriter that needs
enough surrounding natural language to recognize which token is the entity. The
typed phrasings are exactly the phrasings a real user types.

### The date injection: yes, it pollutes retrieval

The rewrite prompt's user message begins
`"Current date and time: Saturday, 2026-08-29 03:01 EDT\n\n"` before the
question. The model treats it as content to be searched for.

- **55/120** diagnostic rewrites put a date/time token in `keywords`
  (confirmed — supervisor figure exact).
- **25/120** put one in the `query` string itself.
- **4/120** produced a query that is *nothing but* the timestamp.
- On average **14.4%** of every keyword list is consumed by date noise; on 14
  questions it is ≥40% of the slots.
- `_search_fast_tier` concatenates `query + " " + keywords` before encoding, so
  every one of these tokens reaches ColQwen.

Effect on the diagnostic pass (n=106 answerable):

| date pollution | n | hit@1 | hit@2 | MRR |
|---|---|---|---|---|
| none | 59 | **0.864** | 0.915 | 0.911 |
| keywords only | 26 | 0.808 | **0.923** | 0.865 |
| in the query string | 21 | **0.524** | **0.619** | 0.597 |

Controlling for vendor loss, so the two effects are not confounded:

| vendor lost | date in query | n | hit@1 | hit@2 |
|---|---|---|---|---|
| no | no | 82 | **0.878** | 0.939 |
| no | **yes** | 17 | **0.588** | 0.706 |
| yes | no | 3 | 0.000 | 0.333 |
| yes | yes | 4 | 0.250 | 0.250 |

**Verdict:** date tokens in the *keyword list* are close to harmless — 0.808 vs
0.864 hit@1, and hit@2 is a wash. Date text in the *query string* costs ~29
points of hit@1 on its own, independent of vendor loss (0.878 → 0.588, n=17).
The `rcpt-a-01-typed` rank flip from a lone `"03:00"` keyword shows the effect is
real even at the margin. The date preamble should be stripped from the rewrite
prompt, or the rewriter instructed to exclude it — it exists to resolve relative
dates ("last Tuesday"), which none of these 120 questions use.

---

## 4. Failure analysis — why ColQwen preferred what it preferred

19 questions had the gold file missed or ranked >2 in at least one pass. I opened
the gold image and the images that outranked it for the decisive cases.

### Cause A — the rewriter destroyed the query (7 questions)

Covered in §3. On these, ColQwen was handed a query with no entity in it and
returned a plausible ranking *for the query it was given*. `rcpt-c-09-typed`
("March 2026 which is more expensive") returned
`receipt_X51005337867.jpg` at rank 1 — an **Oldtown White Coffee guest check
dated 22 Mar 18** whose largest, boldest glyphs are `Table:5 / 1` and
`Amount Due 30.25`. With the vendor stripped, "March" + "more expensive" maps
almost perfectly onto a March-dated bill with the largest-typeface amount in the
corpus. That is correct behavior on a destroyed query.

### Cause B — category match beats identity match (4 questions)

**`rcpt-d-05-typed` / `rcpt-d-05-full` — "AA Pharmacy, cash or card?"**
Gold `receipt_X51005719823.jpg` was missed from the top 12 in **both** passes and
**both** phrasings. Rank 1 in every case: `receipt_X51005719895.jpg`.

I read both. The gold is `AA PHARMACY`, Kepong 52100 KL, items IBUPROFEN /
FEBRICOL-RX / NOFLUX. The winner is `GREEN LANE PHARMACY SDN BHD`, Kepong Baru
52100 KL, items AMOXICAP / **NOFLUX** / **IBUPROFEN** / **FEBRICOL-RX** — three of
the four SKUs are literally the same products, same postcode, same document
class. And the winner carries an explicit block reading
`PAYMENT: / TOTAL PAYMENT / CHANGE / > MASTER`, a near-verbatim match for the
query keywords `payment method, cash, card`. The gold's only discriminator is the
two-glyph token `AA` in a thin dot-matrix face — the weakest possible visual
signal in a ColPali patch grid. ColQwen matched the document *category* and the
*keyword layout* correctly and had essentially nothing to go on for identity.

**`rcpt-a-06-full` — "What did I pick up at Yong Tat Hardware?"**
Gold `receipt_X51005442343.jpg` missed from the top 12; rank 1
`receipt_X51005663323.jpg` = **KOH SENG HARDWARE**. Both are hardware receipts;
"HARDWARE" is the only token in the query that ColQwen can read at scale, and the
winner renders it in bold double-strike caps across the full page width. See also
Cause D — this gold is the faintest file in the corpus.

### Cause C — multi-sibling vendor with a numeric discriminator (5 questions)

**`rcpt-b-04-typed` — "bens grocer 8 mar cash or card"**
Gold `receipt_X51005444041.jpg`, rank 4 (sep) / missed (e2e). Rank 1:
`receipt_X51005444040.jpg` — consecutive scan ID, **the same Ben's Independent
Grocer store**, dated 09/03/18 instead of 08/03/18, RM133.70 instead of RM81.
Identical B.I.G. logo block, identical layout, identical typeface. The full
phrasing supplied `RM81` and still landed rank 1 only because it also supplied
`Ben's Independent Grocer` as a full string.

The discriminators here — a two-digit day-of-month and a three-digit amount — are
exactly the glyph classes a patch-level visual retriever reads worst. This
pattern also drives `rcpt-e-04` (Super Seven: gold `746203`, winners `763958` and
`746207`), `rcpt-c-03` (LA Stationery), and the Kedai Papan Yew Chuan family — the
diagnostic top-6 for `rcpt-d-09-full` is
`[724552, 724628, 724611, 724625, 724624, 724622]`, six consecutive-ID invoices
from the same lumber yard. There are **8** Kedai Papan receipts in the corpus.

### Cause D — faint / low-fill scans (corpus-level legibility prior)

I measured ink density (fraction of pixels below luminance 150 after downsampling
to 100px wide) for all 148 files and cross-tabbed against retrieval frequency.

| ink quartile | median ink | mean top-12 appearances | mean top-2 appearances | never in any top-2 |
|---|---|---|---|---|
| Q1 (faintest) | 0.0031 | 7.43 | **1.11** | **17 / 37** |
| Q2 | 0.0149 | 7.84 | 1.41 | 9 / 37 |
| Q3 | 0.0345 | 11.73 | **2.32** | 8 / 37 |
| Q4 (heaviest) | 0.0856 | 11.92 | 1.65 | 10 / 37 |

Spearman(ink, top-12 appearances) = 0.22; Spearman(ink, top-2) = 0.28. Modest but
consistent: **44 of 148 files never entered any question's top 2 across 120
queries**, and their median ink (0.0148) is a third below the corpus median
(0.0227).

The two golds this actually killed:

- `receipt_X51005442343.jpg` (Yong Tat Hardware) — **ink = 0.0000**, the faintest
  page in the corpus. It is an A4 flatbed scan where the receipt occupies only
  the top ~35% of the page and the remaining two-thirds are blank white. ColPali
  resizes the whole page onto a fixed patch grid, so this receipt's text is
  encoded at roughly a third of the effective resolution of a tightly-cropped
  thermal receipt.
- `receipt_X51005719823.jpg` (AA Pharmacy) — ink = 0.0083, vs 0.0227 median.

The mirror image is a set of **hub attractors** that ColQwen ranks highly for
almost anything:

| file | vendor | top-12 appearances (of 120) | top-2 |
|---|---|---|---|
| `receipt_X51005268408.jpg` | 99 Speed Mart | **42 (35%)** | 5 |
| `receipt_X51005757220.jpg` | — | 40 | 2 |
| `receipt_X51006008206.jpg` | Burger King KLIA | 37 | **16** |
| `receipt_X51006248253.jpg` | — | 36 | 5 |

I opened the top two. `X51005268408` is the only receipt printed in blue
dot-matrix on tinted paper — very high local contrast, textbook receipt layout.
`X51006008206` is a pristine, unskewed, black-on-white laser-clean Burger King
receipt, arguably the most legible page in the corpus; it took rank 1 eight times
and appears in 13% of all top-2 lists. It beat the gold on both LA Stationery
questions. Only **64 distinct files ever took rank 1** across 120 questions.

This is a **query-independent document-quality prior** riding on ColQwen's MaxSim
scores. It is the one failure class that is genuinely the retriever's, and the
one the cross-encoder rerank stage would normally be positioned to correct —
except that the rerank stage scores against the constant placeholder string
`"(visual match — page N)"` (`search.py:553`, product bug #1), which is why it
was turned off for this run in the first place.

### Cause E — golden-set under-specification, not a retrieval error (2 questions)

**`rcpt-e-10` — "Altogether, how much did I spend at Mr DIY across those March
trips?"** Gold is 3 files; the typed variant missed all 3 from the top 12. Rank 1
was `receipt_X51005719898.jpg`, which I opened: it is
**`MR. D.I.Y.(KUCHAI) SDN BHD`, dated 19-03-18** — a Mr D.I.Y. receipt, in March.
Gold `receipt_X51005757308.jpg` is `MR. D.I.Y. (M) SDN BHD (IOI PUCHONG)`,
21-03-18. Retrieval found the right vendor and the right month; the golden set
silently restricts to 3 of ≥4 Mr D.I.Y. March receipts and the question ("those
March trips") never says which. **This should not be scored as a retrieval miss.**
Flagging for the golden-set owner — the same shape may affect other
`vendor + month` questions.

### Summary table — all 19 problem questions

| qa_id | gold rank sep / e2e | cause |
|---|---|---|
| `rcpt-a-06-full` | miss / miss | B (hardware category) + D (ink 0.000) |
| `rcpt-b-04-typed` | 4 / miss | C (B.I.G. sibling, 1 day apart) |
| `rcpt-b-06-typed` | 11 / miss | A (vendor "premio" dropped) |
| `rcpt-b-09-typed` | 1 / **err** | F (context overflow, §5) |
| `rcpt-b-09-full` | 1 / **err** | F |
| `rcpt-c-03-typed` | 4 / miss | C (LA Stationery sibling) + hub attractor |
| `rcpt-c-03-full` | miss / miss | C + hub attractor `X51006008206` |
| `rcpt-c-09-typed` | 6 / miss | A (vendor "wan sheng" dropped) |
| `rcpt-c-10-typed` | miss / miss | A (query = timestamp) |
| `rcpt-c-10-full` | 1 / **err** | F |
| `rcpt-d-02-typed` | 3 / miss | A (rewriter answered a trivia question) |
| `rcpt-d-03-typed` | 5 / miss | A/date-in-query ("Kaison mall current date and time") |
| `rcpt-d-05-typed` | miss / miss | B (Green Lane Pharmacy) + D (ink 0.008) |
| `rcpt-d-05-full` | miss / miss | B + D |
| `rcpt-d-09-typed` | miss / miss | A (query = timestamp) + C (8 siblings) |
| `rcpt-d-09-full` | 1 / **err** | F |
| `rcpt-e-04-typed` | 4 / miss | C (Super Seven siblings) + keyword padding |
| `rcpt-e-10-typed` | miss / miss | **E (golden-set under-specification)** |
| `rcpt-e-10-full` | 4 / 4 | E |

---

## 5. Multi-file, enumeration, and the `k=2` ceiling

### The ceiling

26 questions (13 pairs) have ≥2 gold sources. With the `k` actually used
end-to-end, the mean structural recall ceiling is **0.678**; achieved end-to-end
recall is **0.479**. Only **0.199 of the shortfall is ranking**; the rest is the
fan-out.

Per-question, for the three enumeration pairs:

| qa_id | gold files | k used | recall ceiling | gold ranks in the diagnostic top-12 |
|---|---|---|---|---|
| `rcpt-en-01-typed` | 5 | 2 | **0.40** | 1, 2, 3, 4, 5 |
| `rcpt-en-01-full` | 5 | 2 | **0.40** | 1, 2, 3, 4, 5 |
| `rcpt-en-02-typed` | 8 | 2 | **0.25** | 1, 2, 3, 4, 5, 6, 7 |
| `rcpt-en-02-full` | 8 | 2 | **0.25** | 1, 2, 3, 4, 5, 6, 7, 11 |
| `rcpt-en-03-typed` | 6 | 2 | **0.33** | 1, 2, 3, 4, 5, 6 |
| `rcpt-en-03-full` | 6 | 2 | **0.33** | 1, 2, 3, 6, 8, 11 |

**ColQwen's vendor clustering on these is close to flawless.** `rcpt-en-01` puts
all five Restoran Wan Sheng receipts at ranks 1–5. `rcpt-en-03-typed` puts all six
Gin Kee receipts at ranks 1–6. `rcpt-en-02-typed` puts 7 of 8 Kedai Papan invoices
at ranks 1–7. Enumeration hit@1 is 1.000 and nDCG@5 is 0.954 in the diagnostic
pass. Then `top_k=2` discards 60–75% of it, and end-to-end nDCG@5 drops to 0.553.

`k` sweep on the diagnostic ranking:

| slice | n | R@1 | R@2 | R@3 | R@5 | R@8 | R@12 |
|---|---|---|---|---|---|---|---|
| all answerable | 106 | 0.671 | 0.795 | 0.830 | 0.891 | 0.908 | 0.928 |
| single-gold | 80 | 0.800 | 0.875 | 0.887 | 0.938 | 0.938 | 0.950 |
| multi-gold (≥2) | 26 | 0.275 | 0.550 | 0.652 | 0.747 | 0.817 | 0.861 |
| **enumeration** | 6 | 0.164 | **0.328** | 0.492 | 0.764 | **0.931** | 0.979 |

`k=8` would take enumeration recall from 0.33 to **0.93** with the *existing*
ranking. No retrieval change required.

### The widener fires backwards

`run_search` widens `top_k` when `classify_and_config` returns `LIST_ALL`. It
fired **7 times** in the answer pass (`worker_answer.log`), each logged as
`query_class=list_all top_k 2→12 (local backend cap; cfg wanted 30)`. I ran the
classifier over all 120 golden questions to identify them:

| widened question | answer_type | gold files | outcome |
|---|---|---|---|
| `rcpt-a-09-typed` | synthesis | 2 | 12 files retrieved, answered |
| `rcpt-a-10-full` | synthesis | 2 | 12 files retrieved, answered |
| `rcpt-e-10-full` | synthesis | 3 | 12 files retrieved, answered |
| `rcpt-b-09-typed` | synthesis | 3 | **HTTP 400** |
| `rcpt-b-09-full` | synthesis | 3 | **HTTP 400** |
| `rcpt-c-10-full` | synthesis | 2 | **HTTP 400** |
| `rcpt-d-09-full` | synthesis | 2 | **HTTP 400** |

**None of the six enumeration questions was classified `LIST_ALL`.** The
classifier does not recognize `how many times wan sheng`,
`biggest kedai papan bill`, or `gin kee january dates` as enumeration — so the one
mechanism designed to solve the recall ceiling never engaged on the only three
pairs that needed it.

Meanwhile it fired on 7 "add up / altogether" synthesis questions needing 2–3
files, handed each 12 receipt images to a 16384-token context, and 4 of them
overflowed. From `raw/worker_answer.log`:

```
send_error: request (18817 tokens) exceeds the available context size (16384 tokens)
send_error: request (18839 tokens) exceeds the available context size (16384 tokens)
send_error: request (18636 tokens) exceeds the available context size (16384 tokens)
send_error: request (20974 tokens) exceeds the available context size (16384 tokens)
```

Four errors in the log, four `HTTPStatusError: 400` rows in `answers.jsonl`, and
the set of widened questions partitions exactly into 3 survivors + 4 failures.
**These 4 questions had perfect retrieval** — gold at ranks 1/1/1 and 1,2,3 in the
diagnostic pass — and the generator received nothing. The `LOCAL_MAX_TOP_K=12`
cap was sized for LFM2.5-VL's *declared* 128K context, not for the 16K actually
opened, and nothing reconciles the two.

---

## 6. Verification of supervisor context

**Claim 1 — metrics come from the separate pass; hit@1 0.726 vs 0.783; top-2
differs on 17/106.** CONFIRMED exactly. `enrich.py:276`
(`ret = ranked_by_id.get(qa_id)`) reads `retrieve.jsonl`. My independent
recomputation reproduces 0.783/0.858 from `retrieve.jsonl` and 0.726/0.821 from
`answers.jsonl`. Ordered top-2 differs on 17/106 answerable (14 as an unordered
set; 13 of the 17 are non-error rows).

**Claim 2 — the summary tier indexed nothing; all 1440 hits are tier `fast`.**
CONFIRMED. `worker_index_result.json`: 148/148 manifest entries have
`summary_file: null` and `fast_indexed_at` set; `summary_tier_note:
"no supported files found"`. All **1440/1440** diagnostic hits and **262/262**
end-to-end hits carry `tier: "fast"`. `_rrf_merge` therefore fuses one non-empty
list with one empty list, and RRF degenerates to a rank rewrite of ColQwen's
ordering. There is no lexical/BM25 signal anywhere in this run — which is why the
vendor-name losses in §3 are unrecoverable: nothing else was looking for the
string.

**Claim 3 — scores are pure RRF reciprocals; top1–top2 margin identical on all
120.** CONFIRMED, and stronger than stated: `score − 1/(60+rank) == 0` for
**all 1440** hits with zero residual, and the top1−top2 margin is exactly
`0.00026441` on all 120 diagnostic rows *and* all 116 end-to-end rows. Score
magnitude carries literally zero information beyond rank. A corollary worth
recording: **no absolute-score abstention threshold is possible in this
configuration**, which is a structural contributor to the 0.786 false-answer rate
on the 14 not-found probes — retrieval returns 2 files with identical scores for
a question about a vendor that does not exist in the corpus.

**Claim 4 — gold rank 1=83, 2=8, 3=1, >3=7, missed=7.** CONFIRMED exactly
(diagnostic pass, 106 answerable).

**Claim 5 — the gate never fired, and this is structural.** CONFIRMED, and it
is over-determined three times over:

1. `gate_to_solo` (`search.py:923`) early-returns before any margin check when
   `_rerank_enabled()` is false, and `MAGPIE_RERANK=0` is in `env_snapshot`.
2. Even past that, `LOCAL_SOLO_MARGIN=0` and the function returns unchanged for
   `threshold <= 0`.
3. Even past *that*, `LOCAL_SOLO_KEEP` defaults to 2 and `top_k=2`, so a firing
   gate would return `retrieved[:2]` — a no-op.

`grep -c "solo-gate" raw/worker_answer.log` = **0**. And the measured margin is
0.00026441 against a 2.0 threshold — four orders of magnitude short, exactly as
the docstring predicts for the RRF scale. This is not a bug; `fire_rate: 0.0` is
correctly reporting a deliberately disabled component, and `run.json` already
stamps `solo_gate_structurally_off: true`.

**One correction to a hypothesis of my own.** I expected a second divergence
mechanism between the passes: with rerank off, `fetch_k = top_k`
(`search.py:836`), so the answer path asks Qdrant for only 4 ColQwen candidates
(`fetch_k * 2`) against the diagnostic pass's 24, and `_RESCORE_PARAMS` uses
quantized search with `oversampling=2.0` — so the top-2 of a limit-4 search need
not equal the first 2 of a limit-24 search. **The data does not support this.**
All 17 divergent rows also had a different rewritten query, and zero divergences
occurred with an identical rewrite. The `fetch_k` asymmetry remains a latent
reproducibility hazard worth noting, but it explains none of the observed
divergence in this run.

---

## 7. What to change, in expected-value order

1. **Strip the date preamble from the rewrite prompt** (or add an explicit
   "never include the current date in the query or keywords" instruction). Costs
   nothing, recovers ~29 points of hit@1 on the 17 affected questions, and makes
   runs reproducible.
2. **Raise `top_k` for enumeration to ≥8.** `recall@8 = 0.931` on the existing
   enumeration ranking vs `0.328` at k=2. This is the single largest recall win
   available and requires no model change.
3. **Fix the classifier so it recognizes the enumeration pairs**
   (`how many times X`, `biggest X bill`, `X january dates`) and **stop widening
   two-file "add up" synthesis questions** — or gate widening on a token budget
   derived from the actually-opened `n_ctx`, not the declared one. Four questions
   with perfect retrieval returned nothing.
4. **Guard the rewriter against entity loss.** A post-rewrite check that every
   capitalized/rare token from the raw question survives into `query` or
   `keywords` would have caught all 7 vendor drops and the trivia-answer
   regression, at negligible cost.
5. **Get a text tier onto this corpus.** With the summary tier empty there is no
   lexical fallback at all; every Cause A/B/C failure is a case where an exact
   vendor-string match would have been decisive.
6. **Fix the rerank placeholder bug (#1)** so the cross-encoder can be turned back
   on. It is the natural place to correct the document-quality prior in §4 Cause D.
7. **Re-adjudicate `rcpt-e-10`** (and audit for sibling `vendor + month`
   questions) — the current gold penalizes correct retrieval.
