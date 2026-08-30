---
name: prepare-harness
description: Prepare this machine for Magpie eval runs - interview for model choices, run the deterministic installer, diagnose failures, and verify with a smoke test. Trigger with /prepare-harness.
---

# Prepare-harness — thin wrapper procedure

The installer is `just prepare-harness` (a deterministic script:
`eval_harness/scripts/prepare_harness.py`). This skill NEVER re-implements an
install step - its job is only what a script cannot do: choose flags with the
owner, diagnose failures, and prove the result with a real smoke run.

## 1. Interview (short)

- **Col model** — default `--col auto` (the machine decides exactly like the
  app: ColQwen2.5 needs ≥8 GB VRAM or ≥24 GB unified memory, else
  ColSmol-500M). Ask only if the owner wants to pin (`qwen` ~7.3 GB,
  `smol` ~1 GB) - e.g. to match another machine's runs (ColQwen and ColSmol
  runs are different retrievers and must not be compared).
- **Answer LLM(s)** — default `--llm lfm` (~3-4 GB). `gemma` is large and
  opt-in; ask only if they plan gemma arms.
- On Linux with a GPU: ask whether to set `LLAMA_SERVER_GPU=cuda-*` for the
  llama-server install.

## 2. Run

    just prepare-harness --check        # first: report state
    just prepare-harness [flags]        # then: install what is missing

Diagnose, don't improvise: disk space, network, HF auth (gated repos ask for
`huggingface-cli login`), partial downloads (rerun - every step is
idempotent). If an install step itself is broken, report it to the owner
rather than hand-installing around it.

## 3. Verify — "prepared" means a run works, not that downloads finished

Register a throwaway 3-5 file corpus (any images/text at hand, or a few
files the owner points to):

    uv run python eval_harness/scripts/register_corpus.py --name smoke --corpus-dir <dir>

Then a smoke run: copy `configs/baseline.json` to a temp config with
`"dataset": "smoke"` (and `"config_name": "smoke"`), then

    uv run python eval_harness/harness/run.py --config <temp-config> --index-only

(index-only proves binaries + col model + qdrant end to end in minutes; a
full 2-question run additionally proves llama-server + the answer LLM if the
owner has the time). Clean up: delete the smoke run dir and
`eval_harness/datasets/smoke/`.

Report the summary table, what was installed vs already present, and hand
back: "ready - next is /magpie-eval" (or what is still missing and why).
