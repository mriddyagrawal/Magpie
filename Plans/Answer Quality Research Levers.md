# Answer-quality research levers — literature review mapped to our measured failures

Written 2026-08-27, after reading `Evaluations/college_data/REPORT.md`
end to end plus `CONTINUE.md`. Retrieval iteration is closed (CONTINUE §7);
this document is only about the READING side — why the 3B fumbles the
answer when the right file is in front of it, and what the published
research says to do about it.

Everything here is framed as a pre-registered experiment per house rule 2
(one variable, gate written before the run). Nothing has been run yet.

## The one-paragraph summary

Our local failure is not one problem, it is four, and they have very
different prognoses. Three of the four have a direct, measured
intervention in the literature that we have NOT tried. The fourth —
assembling an answer across several files — is the one thing the
literature does not solve at 3B scale, and we have now refuted it five
times ourselves (routed v1-v5, all 14/40). We should stop paying for
that one with prompt iterations and pay for it with a product decision
instead.

## Failure classes, from our own evals

| # | Class | Evidence in REPORT.md | Prognosis |
| --- | --- | --- | --- |
| A | **Sampling variance** — 8 of 40 questions flip correct↔wrong between identical runs | n=3 = {15, 11, 11}, "coin-flip band (~8 questions)" | Fixable, cheap, untried |
| B | **Confident fabrication** — right file present, invented content | 7/15 at baseline; "hallucinated a professor never in the corpus" (n=3 run 3) | Fixable, untried at the right layer |
| C | **Number/row garbling** — right file, wrong figure or wrong row | q25 "right file, wrong ROW (total vs taxable income)"; 'Covnell'; 83,229.50 vs 83,285 | Fixable, untried |
| D | **Cross-doc assembly** — enumeration and comparison | routed v1-v5 all 14/40; map-reduce lane 0/8 five times | **Capacity-bound. Stop iterating.** |

Class A is upstream of everything: while ~8 questions are coin flips, no
single-run comparison of any other lever can clear the noise floor. That
alone makes it the first thing to fix.

---

## L1 — Sampler hygiene (class A)

**We are running LFM2.5-VL-3B at temperature 0.7 with llama.cpp's stock
samplers. Liquid AI's own model card recommends temperature 0.1, min_p
0.15, repetition_penalty 1.05 for this family.** We pass no min_p, no
repetition penalty, no top_k, no seed — `_build_request_body`
(`src/inference/local_llm.py:333`) sends only `temperature`,
`chat_template_kwargs`, `max_tokens`, `response_format`, and
`llama_server_pool._build_argv` passes only `--temp`.

The 2026-08-24 rejection of temperature 0.2 does not rule this out — it
is confounded four ways: n=1, 15 questions, before the solo gate /
context budget / transcripts / password fix, and crucially **without
min_p or a repetition penalty**. The failure it recorded ("a lone `{`",
"a 726s loop") is the classic signature of low temperature with a flat
tail and no repetition penalty, which is exactly what min_p 0.15 and
repeat_penalty 1.05 exist to prevent. We rejected the temperature and
kept the actual cause.

Supporting literature: Renze & Guven measured a 12.4% linear decline in
mean accuracy from t=0 to t=0.9 on problem-solving
([arXiv:2402.05201](https://arxiv.org/pdf/2402.05201)); the standing
practical consensus for extraction/compliance work is greedy or
near-greedy decoding. Our answer step is an extraction task wearing a
generation costume.

Feasibility: llama-server's `/v1/chat/completions` accepts `min_p`,
`top_k`, `repeat_penalty`, `seed` and the DRY sampler family as extra
body fields ([server
README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)),
so this is a few lines in `_build_request_body` plus constants on
`ModelProfile.args` — no env-flag mechanism required, which was the part
the owner declined mid-edit on 2026-08-26. Sampler settings are a
property of the MODEL, not a user preference, so they belong in the
profile next to the existing `temperature: float = DEFAULT_TEMPERATURE`.

**Pre-registered gate.** Single variable: sampler set = {temp 0.15,
min_p 0.15, repeat_penalty 1.05, seed fixed}. Run the 40-set n=3.
PASS = median ≥ 14/40 (current median 11, +3 clears the ±2 band)
**OR** the coin-flip band shrinks from 8 questions to ≤ 4 with median
≥ 12. Report both numbers either way — variance reduction is a real
product win even at flat accuracy, because it is what makes every
later experiment measurable.

---

## L2 — Extract-then-write, with verbatim verification in code (classes B + C)

This is the highest-value untried lever and the closest match in the
literature to "robust retrieval, fumbled answer".

Two papers say the same thing from different directions:

- **Attribute First, then Generate** (Slobodkin et al., ACL 2024 —
  [arXiv:2403.17104](https://arxiv.org/abs/2403.17104)) decomposes
  generation into content selection → sentence planning → generation,
  so the selected source segments *are* the attributions. Orders of
  magnitude shorter citations, ~50% less human verification time, no
  loss of generation quality.
- **VerbatimRAG**
  ([blog](https://huggingface.co/blog/adaamko/verbatimrag),
  [arXiv:2605.21102](https://arxiv.org/pdf/2605.21102)) goes further:
  the model only *selects* spans and a template composes them, so
  "every number, every fact, every claim in the response is directly
  traceable to the source text." Their framing is the important part —
  **extraction is a classification task, not a generation task**; the
  model never emits tokens that approximate source content, which is
  precisely how 83,285 becomes 83,229.50.

Why this is not our failed map-reduce. The maps in routed v1-v5 were
free-form paraphrase, so garbles propagated and the reduce got a crowd
of prose findings. Here:

1. **Call 1 (per file, or one call over the solo-gated file):** emit
   quoted spans only, each a literal copy from the file.
2. **Code verifies every span is a substring of the context** (after
   whitespace/case normalization). Non-matching spans are DROPPED, not
   argued with. This is the v3 mechanical-reduce lesson applied at the
   right layer: give the judgment job to code, never to the 3B.
3. **Call 2 sees only the surviving quotes** — ~10 short strings,
   maybe 500 tokens, zero distractors. This is the condition our own
   reading-isolation ladder showed the 3B handles near-perfectly, and
   it is reached *without* needing a ≥2.0 retrieval margin, so it
   covers the ~76% of questions the solo gate never fires on.
4. Any number in the final answer that does not appear in a surviving
   quote is stripped or flagged by code (see L3).

Cost: one extra call, but call 2 is tiny; net latency should be close
to flat versus today's single big-context call.

**Pre-registered gate.** 40-set n=3 (run on top of whatever L1 lands,
as the new baseline). PASS = median ≥ baseline + 3. Secondary metric to
report regardless: % of answers whose every numeral is present in a
verified quote.

---

## L3 — Deterministic grounding audit (classes B + C, and a new instrument)

**GenAudit** (Krishna et al., 2024 —
[arXiv:2402.12566](https://arxiv.org/abs/2402.12566), MIT-licensed
[code](https://github.com/kukrishna/genaudit)) fact-checks a model
output against its reference document, highlighting unsupported spans
and suggesting edits; human raters found errors substantially faster
with it. The industrial version of the same idea is a rule-based
guardrail: numeric normalization (K/M/B, currency, thousands
separators), date parsing, and entity presence checks against the
context, with no second model in the loop.

Concretely for us, post-answer and zero LLM calls: pull every numeral,
currency amount, date, and capitalized multi-word entity out of
`answer`, and check each one appears in the assembled context under
normalization. Our own report is a list of things this catches:
"invented a pendulum problem", "read benchmark numbers off the SAT
report as scores", "hallucinated a professor never in the corpus",
"quoted 477,431 vs 477,331".

**Build this first, ship it second.** Run as a pure measurement pass
over the eval answer JSONs we already have on disk (35+ files in
`Evaluations/college_data/`) it costs nothing, needs no model, and
produces a metric we do not currently have: *unsupported-token rate*.
That number is retroactively computable for every run in REPORT.md,
which turns a pile of historical runs into a second axis of evidence.
Only after we can measure it should we decide whether an unsupported
numeral downgrades an answer to not-found, or merely marks it
"unverified" in the UI.

No gate needed for the measurement pass — it cannot regress anything.
The gate belongs on the enforcement step, once we know the base rate.

---

## L4 — A real verifier instead of a 3B self-check (class B)

Card 1 in `Local Answer Quality Plan.md` is "a second cheap call: quote
the sentence supporting this." Our own five reduce/filter runs say the
3B cannot be trusted with a judgment job — v4's filter dropped supported
items, kept unsupported ones, and fabricated a URL. Asking the same
model to grade itself is the same bet.

**MiniCheck** (Tang et al., EMNLP 2024 —
[arXiv:2404.10774](https://arxiv.org/abs/2404.10774)) is the
alternative: purpose-trained grounding checkers where the 770M
Flan-T5 variant reaches GPT-4-level accuracy on LLM-AggreFact at ~400×
lower cost. `lytang/MiniCheck-Flan-T5-Large` and the smaller
`lytang/MiniCheck-DeBERTa-v3-Large` are **MIT licensed**.

Shipping check (per `shipping-assumptions`): this adds **no new Python
dependency** — we already ship `torch` (CPU wheel, routed through the
pytorch-cpu index), `sentence-transformers`, and a cross-encoder
reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`,
`src/stage2/rerank.py`). It is the same class of artifact we already
download and run. Cost is a model download (~0.4-0.8 GB depending on
variant) and CPU inference time per claim, on machines that are already
running a cross-encoder.

Two uses, and the second may matter more than the first:

1. **Answer-time gate** — claims that fail the checker get dropped or
   the answer abstains.
2. **An independent eval judge.** REPORT.md's standing caveat is that
   "the same assistant authored ground truths and judged answers", with
   Mridul's blind spot-check as the only mitigation. A MiniCheck
   faithfulness score is reproducible, model-independent, and can be
   computed over every historical run. It does not replace strict
   binary correctness — it measures a different thing (is the answer
   supported) — but it is the first number in this project that no
   assistant's judgment is in the loop for.

**Pre-registered gate** (for use 1 only): PASS = median 40-set strict
does not regress AND the unsupported-token rate from L3 falls by ≥ 40%.
Use 2 needs no gate — it is instrumentation.

---

## L5 — Reframe the "8B model" card: specialist, not bigger generalist (all classes)

Card 2 in the plan is an 8B swap. The 2026 literature suggests a
cheaper, better-aimed version of that bet.

- **OCC-RAG** ([arXiv:2606.00683](https://arxiv.org/abs/2606.00683))
  ships 0.6B and 1.7B models mid-trained on ~3M synthetic multi-hop,
  context-faithful QA examples with **literal-quote citations and
  calibrated abstention baked into the output format**. They match or
  exceed general-purpose models 2-6× their size on HotpotQA, MuSiQue,
  TAT-QA, ConFiQA. The paper's thesis is directly ours: *faithfulness
  is a training-curriculum property, not a scale property.*
- **B1ade v2** (1B,
  [arXiv:2607.27506](https://arxiv.org/html/2607.27506v1)) reports the
  top faithfulness score in its comparison at 33% fewer parameters than
  Qwen-1.5B.

The unlock is our own transcript decision. Since 2026-08-26 the answer
stage reads *text transcripts* of scanned PDFs, not pixels
(`content.py transcript_for`). The answering model therefore no longer
needs eyes. That splits the role cleanly:

- **LFM2.5-VL-3B stays as the index-time transcriber** (vision, where
  it is measurably good — cloud went 0→7/12 reading its transcripts).
- **A grounding-specialised text SLM answers**, at 0.6-1.7B — less
  VRAM than today, not more, leaving headroom to keep the VLM resident.

This is a bigger change than L1-L4 and should come after them, but it
is a materially different — and cheaper — proposition than "try an 8B",
and worth putting to the owner as the replacement for card 2.

---

## L6 — Test the answer grammar (classes A + D)

Our local answer call runs under a strict GBNF grammar compiled from the
`Answer` schema (`LocalAgent._response_format`). **Let Me Speak Freely?**
(Tam et al., EMNLP 2024 —
[arXiv:2408.02442](https://arxiv.org/pdf/2408.02442)) measured that
format restrictions degrade reasoning, that constrained decoding
(JSON-mode) is the most restrictive tier, and that the mitigation is
**NL-to-Format**: answer in natural language first, convert to the
schema in a second step.

We have circumstantial evidence for this locally — the degenerate
generations at temperature 0.2 appeared *under the grammar*. Worth one
clean run: free-text answer, structure recovered by a tiny second call
or by code. One variable, cheap, and it interacts with L1 (test after
L1 lands, not simultaneously).

---

## L7 — Two-signal abstention (product-level)

**Sufficient Context** (Joren et al., ICLR 2025 —
[arXiv:2411.06037](https://arxiv.org/abs/2411.06037),
[prompts](https://github.com/hljoren/sufficientcontext)) separates "is
the answer inferable from this context" from "did the model answer
correctly", and lifts selective accuracy 2-10 points by combining a
sufficiency label with self-rated confidence in a small logistic head.
Their key finding for us: **small models hallucinate or abstain wrongly
even when context IS sufficient** — Mistral 3 and Gemma 2 behave exactly
like our 3B.

Our solo gate is already a one-signal version of this (retrieval margin
≥ 2.0 → 93% right file). The upgrade is a second, answer-time signal —
surviving-quote count from L2, or mean logprob, both available — and,
because the small-model finding says the model itself cannot be trusted
to abstain, the gate should govern **escalation** (offer the cloud path,
with consent) rather than only refusal. That is a product surface, not
just a threshold.

---

## What the literature says NOT to spend time on

| Idea | Verdict | Why |
| --- | --- | --- |
| Context-aware / contrastive decoding (CAD, DoLa, AdaCAD) | **Park it** | CAD ([Shi et al.](https://arxiv.org/pdf/2312.14335)) contrasts logits with and without context — real gains on faithfulness, but it needs logit-level access. llama-server exposes none of it; adopting it means moving the answer path off llama-server. Revisit only if we ever run llama-cpp-python in-process again. |
| Blanket self-consistency (sample K, majority vote) | **Only as a signal, not a selector** | "When Self-Consistency Backfires" ([arXiv:2608.11403](https://arxiv.org/html/2608.11403)) measured majority voting *reducing* per-problem accuracy on 56.6% (Qwen2.5-7B) and 65.7% (Llama-3-8B) of hard problems. Use disagreement across samples as an abstention/escalation trigger; do not use the majority answer as the answer. |
| More doc2query variants | **Closed, and the literature agrees** | Three strikes on our side; generic-question pollution is the documented failure mode of the technique. Revival needs a stronger generator, not another filter. |
| More reduce-prompt iterations | **Closed** | Five runs, one number (14/40). |
| Chain-of-Note ([arXiv:2311.09210](https://arxiv.org/abs/2311.09210)) | **Already have it** | Per-document reading notes = our map stage, which already works ("the maps extract fine"). CoN's win is noise robustness, which is class B/C — L2 delivers the same idea with verification attached. |

---

## Class D: the honest answer

Nothing in the reading literature fixes multi-document assembly at 3B.
Every technique above is about *noise robustness* and *attribution* —
the two things that scale binds least. Assembly is where scale actually
binds, and we have five runs saying so.

But there is a finding of ours worth re-reading as a product question,
not an eval verdict. The v3 mechanical reduce **raised fact recall
against ground truth** — q40 2→3 of 4 dates, q26 1→2 of 2 versions, q14
2→4 schools — and scored 0/8 strict only because "a dump with
attribution is not an answer."

For an eval, correct. For a small-business owner asking "which schools
did I submit forms to", an attributed evidence table (file → extracted
fact, with the file openable) may be a *better* product than one
confidently wrong sentence — and it is the shape our machinery already
produces most accurately. That is the owner's call, and it is the
cheapest available win on the class we otherwise cannot solve.

---

## Recommended order

| Order | Lever | Effort | Risk | Why here |
| --- | --- | --- | --- | --- |
| 1 | L3 measurement pass | ~2h | none | New metric over runs we already have; no model, no gate, cannot regress |
| 2 | L1 sampler hygiene | ~1h + n=3 run | low | Variance is upstream of measuring everything else |
| 3 | L2 extract-then-write | ~1 day + n=3 | medium | Biggest untried lever on the two biggest failure classes |
| 4 | L6 grammar A/B | ~2h + n=3 | low | Cheap, one variable, interacts with L1 |
| 5 | L4 MiniCheck | ~half day | low | No new deps; also fixes the self-judging eval caveat |
| 6 | L7 two-signal abstention | design | medium | Needs L2's quote count to exist first |
| 7 | L5 specialist SLM | ~1 day + full eval | high | Replaces the 8B card; owner-gated |

## Sources

- Slobodkin et al., *Attribute First, then Generate* (ACL 2024) — https://arxiv.org/abs/2403.17104
- VerbatimRAG — https://huggingface.co/blog/adaamko/verbatimrag · https://arxiv.org/pdf/2605.21102
- Tang et al., *MiniCheck* (EMNLP 2024) — https://arxiv.org/abs/2404.10774
- Krishna et al., *GenAudit* (2024) — https://arxiv.org/abs/2402.12566
- Joren et al., *Sufficient Context* (ICLR 2025) — https://arxiv.org/abs/2411.06037
- Tam et al., *Let Me Speak Freely?* (EMNLP 2024) — https://arxiv.org/pdf/2408.02442
- Yu et al., *Chain-of-Note* (EMNLP 2024) — https://arxiv.org/abs/2311.09210
- Wang et al., *Astute RAG* (ACL 2025) — https://arxiv.org/abs/2410.07176
- Liu et al., *Lost in the Middle* (TACL 2024) — https://arxiv.org/pdf/2307.03172 *(already applied — reversal + question sandwich in `answer.py`)*
- Renze & Guven, *The Effect of Sampling Temperature on Problem Solving* — https://arxiv.org/pdf/2402.05201
- *When Self-Consistency Backfires* — https://arxiv.org/html/2608.11403
- *OCC-RAG* — https://arxiv.org/abs/2606.00683
- *B1ade v2 / minimalist RAG SLMs* — https://arxiv.org/html/2607.27506v1
- Shi et al., *Context-aware Decoding* — https://arxiv.org/pdf/2312.14335
- LFM2.5 recommended sampling params — https://unsloth.ai/docs/models/tutorials/lfm2.5
- llama-server parameters — https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

---

# Measured, 2026-08-27 (same day)

The plan above was written from the literature. Then the levers were
actually built and run against a new instrument (`Evaluations/sem6/`, 25
questions over the owner's indexed semester-6 archive, deterministic
regex scoring). What the measurement found changed the ranking, because
three bugs sat *underneath* every lever in the plan.

| Finding | Where | Effect |
| --- | --- | --- |
| `response_format` is a silent no-op on llama-server b9049 — structured output was never enforced on the local path | `src/inference/gbnf.py` (new) | baseline arm: **25 of 25 answers discarded**, several of them factually correct |
| `Answer` declared `not_found` first, so under a grammar the model committed to a refusal as its opening token and wrote the correct answer underneath | `src/answer.py` | 8 of the first 12 answers blanked; after the reorder, 1 of 25 |
| The grammar permitted raw control characters in strings, so a rambling model produced unrepairable output | `src/inference/gbnf.py`, `src/llm.py` | 2 of 25 lost |
| The JSON drift rescue required a key the model never wrote | `src/llm.py` | rescued 0 of 25 drifted payloads; now rescues them, and this is permanent value for **cloud**, which has no grammar |

**Result: 0/25 → 17/25 strict.**

## What this does to the plan's ranking

- **L1 (sampler hygiene) shipped** — and its own test had already been
  written by a previous session, in a test file that had been failing to
  import for weeks. Secondary effect not in the plan: at temp 0.7 with no
  min_p and no repetition penalty the model rambles to the token cap on
  most questions; the sampler set is a large **latency** win too.
- **L3 (deterministic grounding audit) shipped**, both as an eval tool
  (`Evaluations/grounding_audit.py`) and as a runtime guard
  (`src/grounding.py`, called from `answer.py`). On the `full` arm it
  flagged exactly 2 numbers out of 109 and both were genuine fabrications,
  with zero false positives.
- **L6 (drop the answer grammar) is refuted for this build.** The plan
  suspected the grammar of degrading reasoning, following Tam et al. The
  measurement says the opposite here, because the grammar was never
  running: 0/25 without it, 17/25 with it. Tam et al.'s finding is about a
  constraint that costs quality; ours was a constraint that did not exist.
- **L2 (extract-then-write) is untested and now less urgent.** The
  failures it targets — fabrication and figure garbling — dropped to 2
  fabrications and a handful of misreadings once answers stopped being
  thrown away. Re-rank it after `college_data` is re-measured.
- **L4, L5, L7 unchanged.**

## The general lesson

Every lever in the original plan assumed the pipeline delivered what the
model produced. Three of the four bugs above are in the delivery path, not
the reasoning path, and no amount of prompt or model work would have moved
them. Before the next model-side lever, check that the plumbing carries
what the current model already produces.
