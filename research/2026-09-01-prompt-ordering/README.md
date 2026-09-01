# Prompt ordering: three experiments

**Date:** 2026-09-01
**Model under test:** LFM2.5-VL-3B Q6_K (the model Magpie ships) — plus Gemma 4 26B A4B as a comparison
**Status:** Complete. Findings below are measured, not estimated.

---

## The question

Inside a single user turn we can arrange the system prompt (S), the question (T), and
the content — an image (I) or a document (D) — in different orders. Does the arrangement
change how often the model is right?

Three orderings, written in token order, with generation beginning after the last element:

| name | arrangement |
|---|---|
| `STI` / `STD` | system → **question** → content |
| `SIT` / `SDT` | system → content → **question** |
| `STIT` / `STDT` | system → **question** → content → **question** |

The prior comes from **arXiv 2607.15565**, which tested the `SIT → STIT` comparison on five
vision-language models and found it a wash or worse three times (Qwen3-VL −0.001,
LLaVA −0.003, Qwen2.5-VL −0.086) and positive twice (Gemma +0.027, InternVL3 +0.010).
We expected a null. On short prompts we got one. On long ones we did not.

---

## Findings

### 1. On short prompts, ordering does nothing

500 paired POPE items, one image, ~156-token prompts. LFM2.5-VL-3B Q6_K.

| ordering | accuracy | F1 |
|---|---|---|
| STI | 0.8960 | 0.8844 |
| SIT | 0.9080 | 0.8996 |
| STIT | 0.9080 | 0.8996 |

`SIT → STIT` — the comparison the paper cares about — came out at **exactly zero**
(McNemar `p = 1.0000`, 6 discordant pairs splitting 3–3). `STI → SIT` was `+0.012`,
`p = 0.238`, also null.

**But the manipulation was doing something.** STI produced a capitalized `Yes`/`No` on
**96.4%** of items; SIT on **2.0%**. Ordering swung the surface form almost completely
while leaving correctness untouched. At short context, ordering is a *style* variable,
not a *grounding* variable — and if anything downstream case-matches on `"Yes"`, ordering
will silently break it.

📄 [Full report](reports/01-pope-vision-ordering.html)

### 2. On long documents, ordering is worth up to 30 points

Same three orderings, 500 LongBench HotpotQA items (documents up to ~16k tokens),
same model.

| ordering | accuracy |
|---|---|
| STD — question first | 0.4060 |
| SDT — document first | 0.5580 |
| STDT — question both ends | **0.6060** |

`STD → SDT` = **+15.2 points**, `p = 6.8×10⁻¹⁰`.
`STD → STDT` = **+20.0 points**, `p = 6.9×10⁻¹⁹`.

**The effect is a function of context length.** Below 4k tokens it is a clean null —
discordant pairs split 14 against 15. Above 8k it is enormous:

| context | STD (question first) | STDT (question both) | gap |
|---|---|---|---|
| 0–4k words | 0.667 | 0.675 | +0.8 |
| 4–8k | 0.407 | 0.571 | +16.4 |
| 8k+ | **0.280** | **0.593** | **+31.3** |

Question-first accuracy falls from 0.667 to 0.280 as documents grow; document-first holds.
Long context does not dilute the question — it **strands** it.

This reconciles finding 1 rather than contradicting it. POPE prompts were 156 tokens,
far below even the null bin. The two results are two points on one curve.

📄 [Full report](reports/02-longcontext-ordering.html)

### 3. The optimal ordering **reverses** on a different model

Same 500 items, same prompt, same decoding — Gemma 4 26B A4B instead.

| ordering | Gemma 4 26B A4B | LFM2.5-VL-3B |
|---|---|---|
| STD — question first | **0.7820** | 0.4060 |
| SDT — document first | 0.6740 | 0.5580 |
| STDT — question both | 0.7700 | **0.6060** |

| model | `STD → SDT` | p |
|---|---|---|
| LFM2.5-VL-3B | **+15.2** | 6.8×10⁻¹⁰ |
| Gemma 4 26B A4B | **−10.8** | 3.9×10⁻⁸ |

**The identical change helps one model and hurts the other**, both at overwhelming
significance. For Gemma, `STD → STDT` is a flat null (`p = 0.43`) — it does not care about
the repeat, only that the question comes *first*. Exact mirror of LFM.

**Why:** Gemma barely degrades with length (question-first: 0.846 → 0.782 from short to
long). LFM collapses (0.667 → 0.280). Document-first was *rescuing* a question LFM
couldn't hold across 12,000 tokens. Once a model can retain the question, seeing it first
becomes better — it can read *for* the answer. LFM never gets that benefit.

📄 [Full report](reports/03-cross-model-transfer.html)

### 4. Magpie's GBNF grammar has no effect on accuracy

Tested on/off across all three orderings, 3,000 generations.

| ordering | Δ accuracy | p |
|---|---|---|
| STD | +0.006 | 0.375 |
| SDT | +0.010 | 0.359 |
| STDT | −0.008 | 0.388 |

All null, one negative. The grammar restricts *what can be emitted*, not what was
comprehended.

It does fix structure, and that is reason enough to keep it: left unconstrained the model
drops out of JSON on **19% of SDT** and **9% of STDT** responses. A response Magpie cannot
parse is a failed answer regardless of what the model knew.

**A near-miss worth recording:** on raw token-F1 the grammar looked like a +3.6 point win.
It isn't. Grammar-off answers are verbose, and F1 punishes verbosity independent of
correctness — *"Based on the provided text, Brent Roger Wilkes was connected to the scandal
involving Randy 'Duke' Cunningham"* scores F1 `0.07` against gold *"Duke Cunningham"*, while
the terse grammar-constrained version scores `0.80`. Both are correct. Automatic scoring
alone would have shipped a finding that was purely about answer length.

### 5. The two models fail in completely different ways

All 3,000 answers judged under one uniform rubric, with reason codes:

| failure mode | Gemma 4 26B | LFM2.5-VL-3B |
|---|---|---|
| `WRONG_ENTITY` — asserts a different answer | 90 | **462** |
| `NOT_FOUND` — declines to answer | **160** | 5 |
| `NUMERIC_MISS` — wrong number or date | 27 | **119** |
| `POLARITY` — yes/no answered backwards | 10 | 38 |
| `SHOTGUN` — lists candidates without choosing | 24 | 6 |
| `HEDGE`, `PARTIAL`, `WRONG_RELATION`, other | 76 | 85 |

**LFM confabulates; Gemma abstains.** LFM asserts a wrong entity on 31% of items — five
times Gemma's rate — while Gemma says "not found" 32 times more often than LFM.

For a tool that answers questions about a user's own files, this asymmetry matters more
than the headline accuracy gap. A confident wrong answer about your own W-2 is worse than
"I couldn't find that."

---

## What this changes for Magpie

**1. Put the question after the document.** Worth ~15 points overall and ~31 points on
documents past 8k tokens, on the model we actually ship. It is *also* the ordering that
lets a KV prefix cache be reused across many questions about the same files — so the
cheapest-to-serve arrangement and the most accurate one are the same. No trade-off.

**2. Re-measure ordering whenever the model changes.** This is the finding with the longest
shelf life. Magpie already swapped its local model once (Gemma 4 E4B → LFM2.5-VL-3B,
2026-08). Carrying prompt ordering forward across such a swap, on the assumption that it's
a property of prompts rather than of models, would have cost roughly **11 points** in the
Gemma direction.

**3. Keep the grammar — for parseability, not accuracy.** And don't let a token-F1 metric
tell you otherwise.

**4. The context-window ceiling is a quality question, not a resource one.** KV cache
measures ~16 KB/token on this model and prefill time scales with tokens *processed*, not
window *allocated* — so a wider window is nearly free. What degrades is the answer.

**5. Long documents are where a cloud escalation path would earn its cost.** At 8k+ tokens
LFM scores 0.280 question-first where Gemma scores 0.782.

---

## Reproducing

Everything needed is in this directory. See [METHOD.md](METHOD.md) for integrity gates,
exact configurations, and the honest limitations.

```
reports/     the three full reports (open in a browser)
data/        per-item outputs and the judging rubric
code/        the harness — ctypes bindings to llama.cpp, runners, analysis
```

Item sets are regenerated deterministically from a fixed seed; the 500 HotpotQA items were
rebuilt from scratch on a second machine and verified to match by id, question text, and
length bin.

## Citation

The prior this work tests against:

> *Prompt component ordering in vision-language models.* arXiv:2607.15565.
> Tested `SIT → STIT` across five VLMs; found no consistent benefit
> (Qwen3-VL −0.001, LLaVA −0.003, Qwen2.5-VL −0.086, Gemma +0.027, InternVL3 +0.010).

Our finding 1 replicates that null on a sixth model. Findings 2 and 3 extend it: the null
holds only in the short-context regime the paper tested, and the effect is model-specific
rather than a property of prompting.

Datasets:

- POPE — Li et al., *Evaluating Object Hallucination in Large Vision-Language Models*, [arXiv:2305.10355](https://arxiv.org/abs/2305.10355) (via `lmms-lab/POPE`)
- LongBench — Bai et al., *LongBench: A Bilingual, Multitask Benchmark for Long Context Understanding*, [arXiv:2308.14508](https://arxiv.org/abs/2308.14508) (via `zai-org/LongBench`)
- RePOPE — Neuhaus & Hein, *RePOPE: Impact of Annotation Errors on the POPE Benchmark*, [arXiv:2504.15707](https://arxiv.org/abs/2504.15707) — relevant because POPE carries label noise
