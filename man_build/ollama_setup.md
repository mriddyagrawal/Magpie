# Local LLM via Ollama — Arch Linux + CUDA Setup

Setup for running a local vision-capable LLM alongside ColPali. No API
cost, works offline, your documents and queries never leave the machine.

## 1. Install Ollama + CUDA runtime

Arch has official packages — no curl-pipe-sh needed:

```bash
sudo pacman -S ollama-cuda
sudo systemctl enable --now ollama
ollama --version   # sanity check
```

The `ollama-cuda` package pulls in CUDA runtime bits; for AMD GPUs use
`ollama-rocm` instead, for CPU-only use plain `ollama`.

## 2. Store models on /mnt/hardisk (out of the home partition)

Models are big (~2 GB per 3B vision model). Put them on roomy storage
the same way we did for HuggingFace.

```bash
sudo mkdir -p /mnt/hardisk/ollama-models
sudo chown ollama:ollama /mnt/hardisk/ollama-models

sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_MODELS=/mnt/hardisk/ollama-models"
EOF

sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Verify:

```bash
systemctl show ollama | grep OLLAMA_MODELS
# should print:  Environment=OLLAMA_MODELS=/mnt/hardisk/ollama-models
```

## 3. Pull a vision-capable model

For your 5.7 GB VRAM (shared with ColPali's ~1 GB):

```bash
ollama pull qwen2.5vl:3b
```

~2 GB download, fits comfortably. Alternatives:

| Model tag | Size | VRAM | Notes |
|---|---|---|---|
| `qwen2.5vl:3b` | 2.0 GB | ~2.5 GB | **Recommended** — best 3B vision |
| `qwen2.5vl:7b` | 4.5 GB | ~5 GB | Too tight with ColPali loaded |
| `minicpm-v` | 4.4 GB | ~5 GB | Strong vision, tight VRAM |
| `llava:7b` | 4.5 GB | ~5 GB | Older architecture, marginal |
| `qwen2.5vl:72b` | 40 GB | ~45 GB | Obviously no |

Verify it's stored on hardisk:

```bash
du -sh /mnt/hardisk/ollama-models/*
```

## 4. Switch the app to Ollama

Edit `.env`:

```bash
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5vl:3b
# OLLAMA_BASE_URL=http://localhost:11434/v1   # default, optional
# OLLAMA_API_KEY=                              # not needed
```

Verify:

```bash
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from src.llm import active_provider, active_model_name
print(f'provider: {active_provider().name}')
print(f'model:    {active_model_name()}')
"
```

Expected:
```
provider: ollama
model:    qwen2.5vl:3b
```

## 5. Smoke test

```bash
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from src.llm import build_agent
from pydantic import BaseModel

class Greeting(BaseModel):
    message: str

agent = build_agent('Reply with a greeting.', Greeting, None)
result = agent.run_sync(['Hello!'])
print(result.message)
"
```

First call is slow (~5-10s model load into VRAM). Subsequent calls are
~10-30 tokens/sec. Ollama auto-unloads after ~5 min of inactivity.

## 6. Use it with the app

```bash
uv run ns --sync=/path/to/docs --summary-only --concurrency 2
uv run ns                          # REPL — queries also use Ollama now
```

Concurrency note: one GPU means one inference at a time. `--concurrency 2`
doesn't help much because Ollama queues requests serially per model.
Benefit of `--concurrency` >1 comes from overlapping PDF-read / image-
prep with the ongoing forward pass. `--concurrency 2` is the sweet spot.

## 7. Juggling ColPali + LLM on the same GPU

Ollama auto-unloads idle models. ColPali is Python-resident until you
exit the process. Flow during `ns --sync`:

```
fast tier runs → ColPali loaded, ~1 GB VRAM used
                 Ollama idle → 0 VRAM used
summary tier runs → first Ollama call loads qwen2.5vl:3b, ~2.5 GB used
                    total in-flight: ~3.5 GB / 5.7 GB OK
query tier runs → same Ollama model stays hot for ~5 min
                  ColPali re-loads if a ns REPL call hits fast tier
```

If you OOM, drop to `qwen2.5vl:3b-q4_0` (smaller quant) or restart
between tiers.

## 8. Trade-offs vs cloud

| Metric | Ollama (local) | OpenRouter Gemini 2.0 | Moonshot Kimi |
|---|---|---|---|
| Per-file summarize speed | 15-45s (slow) | ~5s | ~5s |
| Quality on long docs | moderate | high | high |
| Cost | $0 | $0 free tier | $$ |
| Rate limits | none | ~20 RPM | ~50 RPM paid |
| Offline | ✅ | ❌ | ❌ |
| Privacy | ✅ fully local | ⚠️ content to OpenRouter | ⚠️ content to Moonshot |

## 9. Back out

Flip `LLM_PROVIDER` back to `openrouter` or `moonshot` in `.env`. Ollama
keeps running as a daemon but nothing calls it. Disable if you want:

```bash
sudo systemctl disable --now ollama
```
