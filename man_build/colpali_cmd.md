# ColPali Fast-Tier Build — Command Runbook

Steps to get the ColPali / ColQwen fast-tier indexing stack running from a
fresh clone on Linux (Arch). Assumes `uv` installed and a working Python 3.11.

See `Plans/IO - Colpali.md` for the design.

## 1. Install dependencies

Added to `pyproject.toml`: `colpali-engine>=0.3`.

```bash
uv sync
```

## 2. Point HuggingFace cache at large-disk storage

ColPali weights are 1-6 GB. Put them on a roomy partition, not `~/.cache`.

```bash
# Adjust path to a partition with ≥10 GB free.
mkdir -p /mnt/hardisk/hf-cache/hub
echo 'export HF_HOME=/mnt/hardisk/hf-cache' >> ~/.config/zsh/.zshrc
source ~/.config/zsh/.zshrc
echo $HF_HOME    # sanity: should print /mnt/hardisk/hf-cache
```

zsh users with ZDOTDIR set to `~/.config/zsh/` must edit that rc file, NOT
`~/.zshrc`. Check with `echo $ZDOTDIR`.

## 3. (Optional) Relocate any pre-existing downloads

```bash
mv ~/.cache/huggingface/hub/models--vidore--colSmol-500M \
   /mnt/hardisk/hf-cache/hub/ 2>/dev/null
mv ~/.cache/huggingface/hub/models--vidore--colqwen2.5-v0.2 \
   /mnt/hardisk/hf-cache/hub/ 2>/dev/null
```

## 4. Smoke-test the model loader

```bash
uv run python -m src.stage1_fast /mnt/hardisk/sem_4/furmanclpqr.png
```

First run downloads weights. Subsequent runs load in ~5s from disk.

**Hardware fallback rules** (auto-applied in `src/stage1_fast/device.py`):

| Condition                 | Model              | VRAM / RAM needed |
|---------------------------|--------------------|-------------------|
| CUDA ≥ 8 GB VRAM          | ColQwen2.5-v0.2    | ~6 GB VRAM        |
| CUDA < 8 GB VRAM          | ColSmol-500M       | ~1 GB VRAM        |
| Apple MPS                 | ColQwen2.5-v0.2    | ~8 GB unified     |
| CPU                       | ColSmol-500M       | ~2 GB RAM         |

**Expected output** (ColSmol on CUDA):

```
────────────────────────────────────────────────────────────────────────
  Fast-tier model: vidore/colSmol-500M
  Device:          cuda | VRAM x.x/x.x GB free
  Dtype:           float16   Batch size: 2
  Cache location:  /mnt/hardisk/hf-cache
────────────────────────────────────────────────────────────────────────
loaded in 5.2s
encoded in 0.35s (0.35s/page)
  output shape: (1, ~500, 128)
  dtype:        torch.float16
```

## 5. Troubleshooting

**`CUDA out of memory` during model load.**
GPU too small for ColQwen. Device detection should auto-fall-back to
ColSmol; if it doesn't, check `torch.cuda.mem_get_info()` output.

**`'Idefics3Processor' object has no attribute 'process_images'`.**
Using `transformers.AutoProcessor` instead of `colpali_engine`'s processor.
`src/stage1_fast/model.py` must import `ColQwen2_5_Processor` /
`ColIdefics3Processor` from `colpali_engine.models`.

**Banner shows `Cache location: /home/$USER/.cache/huggingface`** despite
setting `HF_HOME`.
The shell that ran `uv` didn't inherit the env var. Either `source` the rc
in that shell, open a new terminal, or run inline:

```bash
HF_HOME=/mnt/hardisk/hf-cache uv run python -m src.stage1_fast <path>
```

**Model loads but `encode_images` hangs.**
First-call JIT compilation can take 10-30s on CUDA. If it's >60s something
else is wrong — check `nvidia-smi` for zombie processes holding VRAM.
