# Method, integrity gates, and limitations

## Why this file exists

Every number in [README.md](README.md) depends on the arms being genuinely identical except
for arrangement. This documents what was checked, what was found, and what remains
uncertain. The limitations section is not boilerplate — read it before quoting a number.

---

## Configuration

| | POPE run | HotpotQA run (LFM) | HotpotQA run (Gemma) |
|---|---|---|---|
| model | LFM2.5-VL-3B **Q6_K** + mmproj Q8_0 | same | Gemma 4 26B A4B (25.2B total / 3.8B active) |
| runtime | llama.cpp **b10502** (`0adcc3bb5`) | same, rebuilt from source | OpenRouter → DeepInfra (pinned) |
| backend | Metal, Apple M1 Max | CUDA, RTX 4090 | provider-side |
| decoding | greedy argmax, bare sampler chain | same | `temperature: 0`, `seed: 0` |
| n_ctx | 4096 | 24576 | provider default (262k) |
| generations | 1,500 | 3,000 | 1,500 |
| wall clock | 18.9 min | 35 min | 6.3 min |
| errors | 0 | 0 | 0 |

llama.cpp was pinned to Magpie's exact shipped build so the ctypes struct layouts port
unchanged between machines, and so the comparison reflects what users actually run.

## Token-order control

Ordering was **not** controlled through a chat template. For the vision runs, components
were placed via llama.cpp's `mtmd` media marker, which splits text at the marker and
interleaves the encoded image chunk exactly there. For the text runs, each component was
**tokenized independently and the token IDs concatenated**, which makes the arms exact
anagrams by construction rather than by luck at BPE boundaries.

The chat template was inspected rather than trusted: LFM2.5-VL's `parse_content` macro
iterates the content list in order and concatenates, with no image hoisting — so the model
card's written example and its code samples were never in conflict, they simply show two
different orderings.

## Integrity gates

Each of these would have invalidated the results had it failed.

| gate | result |
|---|---|
| **Anagram assertion** — STI/STD and SIT/SDT must have identical token counts | **PASS 500/500** on every run, in both grammar arms |
| **Token-ID multiset identity** — not just equal counts, the same tokens | **PASS** (verified on the vision runs where token IDs were dumpable) |
| **STDT length accounting** — `STDT = STD + Q` exactly | **PASS 500/500** |
| **Blank-image control** — replace the image with flat grey | accuracy **0.958 → 0.458**, yes-rate → **0.000**. The image is genuinely driving answers |
| **Image constant across arms** — image token count identical in all arms per item | **PASS 500/500** (counts vary 128–256 across items by dynamic resolution, but never within an item) |
| **Platform cross-check** — Metal vs CUDA chunk dump | byte-identical: `[TEXT 30][IMAGE 120][TEXT 6] = 156` on both |
| **Provider pinning** (Gemma) | all 1,500 requests confirmed served by DeepInfra; `allow_fallbacks: false` |
| **Item-set reproducibility** | the 500 HotpotQA items were rebuilt from seed on a second machine; id set, question text, and length bins all matched |

The blank-image control is the load-bearing one. A silently dropped image would produce a
plausible table where all arms scored the same — a null result for entirely the wrong
reason.

## Scoring

Free-text answers cannot be string-matched honestly. Token-F1 systematically punishes
verbose answers independent of correctness, and the two models differ enormously in
verbosity (Gemma averages 114 characters per answer; LFM averages 34). Scoring on F1 would
have measured answer length.

**Final protocol** (used for the headline numbers): all 3,000 HotpotQA answers — both
models, all orderings — were pooled, shuffled, stripped of model and ordering labels, and
judged by **12 independent Claude Opus 5 readers** working from a single byte-identical
[rubric](data/judging-rubric.md). No judge could tell which model wrote an answer.

The rubric's first rule is explicit: *answer length is not evidence of correctness.*
Judges returned a reason code per item, which produced the failure-mode breakdown.

**Style-bias check:** across the pool, judges marked 1,749 answers correct, split 975
verbose / 774 terse — tracking the input mix rather than favouring either style. Several
judges independently reported near-even terse/verbose correctness splits within their own
batches.

An earlier pass used Sonnet 5 on an escalated subset only (F1-ambiguous items plus low-F1
items containing the gold string). That protocol had an asymmetry — 66.7% of Gemma's
answers reached a judge versus 20.3% of LFM's — so it was replaced. Both sets of verdicts
are preserved in `data/` for comparison. **The uniform re-judging strengthened every
finding rather than weakening it.**

## Statistics

- **McNemar exact test**, two-sided, on discordant pairs only — the appropriate test for
  paired binary outcomes.
- **Paired bootstrap**, 5,000 resamples, resampling items so each item contributes all its
  arms together.
- Per-item correctness is paired across orderings: same items, same order, every time.

---

## Limitations

**Statistical power on POPE.** At the observed discordance rates, n=500 resolves only
±0.012 to ±0.024. Effects smaller than about two points are invisible. "No detectable
effect" is supported; "no effect" is stronger than the data allows. Three of the five
reference models had effects inside that blind spot.

**Length bins are confounded with difficulty.** Longer HotpotQA contexts carry more
distractor passages, so some degradation with length is the task getting harder, not just
the question getting distant. The *relative* gap between orderings within each bin remains
a fair comparison; the curve's steepness mixes both causes.

**Cross-model comparison is not on matched hardware.** LFM ran on llama.cpp Q6_K we built;
Gemma ran on DeepInfra's stack at their quantization. Pinning held quantization constant
*within* the Gemma run, but the two models are not on equal footing. The **ordering**
findings are unaffected — those are within-model comparisons where every arm shares a
backend.

**No token-level verification for Gemma.** Through a chat API only string-level anagrams
can be guaranteed. Circumstantial support is strong: the provider's reported input token
counts came back identical for STD and SDT on all 500 items.

**One task shape.** HotpotQA is multi-hop retrieval over Wikipedia paragraphs. POPE is
binary object hallucination. Neither is Magpie's actual workload, which is mostly
single-hop extraction from a user's own documents. **These numbers do not predict Magpie's
production accuracy** — Magpie's own eval harness measures that.

**POPE carries label noise.** See RePOPE (arXiv:2504.15707). Some scored errors are
correct answers against wrong labels.

**Two models is not a trend.** We now know the ordering effect is not universal. We do not
know which of the two models is typical.

**Greedy only.** Magpie ships at non-zero temperature. Ordering effects under sampling are
untested.

**Judge agreement was spot-checked, not measured.** 14 verdicts from the earlier Sonnet
pass were audited by hand with 14/14 agreement. No formal inter-rater reliability was
computed across the Opus judges.

---

## Known bug found during this work

`llama_sampler_sample()` already calls `llama_sampler_accept()` internally
(`src/llama-sampler.cpp`). Calling accept again double-advances stateful samplers and
empties the grammar stack with `Unexpected empty grammar stack after accepting piece`.

This was present in the POPE harness too but harmless there — a bare greedy sampler is
stateless, so the extra accept was a no-op. It only surfaces once a grammar joins the
chain. **The POPE numbers are unaffected.**

Also worth knowing: ggml's Metal backend aborts during interpreter shutdown if the model
and context aren't explicitly freed first, producing a spurious crash report *after* all
work is complete and flushed. Fixed by explicit teardown in reverse construction order
plus `os._exit(0)`; see `code/harness.py::close`.
