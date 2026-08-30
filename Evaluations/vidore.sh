#!/usr/bin/env bash
# ViDoRe-style retrieval test: ColSmol (what ships) vs the text tier on OCR
# transcripts vs their fusion, on ColPali's own benchmark pages. Then reader
# arms (OCR text vs pixels) on the subsets that have answers.
#   Evaluations/vidore.sh fast    tatdqa_eval   # qdrant + ColSmol fast tier (CPU, slow)
#   Evaluations/vidore.sh text    tatdqa_eval   # text tier from OCR transcripts (after transcribe_index)
#   Evaluations/vidore.sh score   infovqa       # retrieval-only table
#   Evaluations/vidore.sh answer  infovqa_train # oracle reader arms: ocr vs pixels (100 questions)
# Corpora live on the NVMe (/mnt/astavaknew/vidore/<subset>); data dirs and
# Qdrant homes too. Card: Evaluations/vidore/README.md.
set -uo pipefail
REPO=/mnt/hardisk/NotAnotherSpotlight; PY=$REPO/.venv/bin/python; cd "$REPO"
QDRANT_BIN=/mnt/astavaknew/magpie-qdrant/qdrant
declare -A PORT=( [infovqa]=6481 [infovqa_train]=6483 [tatdqa_eval]=6485 [tatdqa]=6487 )
LOGDIR=$REPO/Evaluations/vidore/logs; mkdir -p "$LOGDIR"

export LLAMA_SERVER_BASE_PORT=9300 LLAMA_SERVER_STARTUP_TIMEOUT_S=180
export LLAMA_SERVER_PATH=/mnt/hardisk/magpie-data/bin/llama-server
export MAGPIE_FORCE_PROVIDER=local LLM_PROVIDER=local FALLBACK_LLM_PROVIDER=
export HF_HOME=/mnt/hardisk/magpie-data/cache HF_HUB_CACHE=/mnt/hardisk/magpie-data/cache/hub
export FASTEMBED_CACHE_PATH=/mnt/hardisk/magpie-data/cache/fastembed
export LLAMA_SERVER_MODEL_PATH=/mnt/astavaknew/phyll-models/LFM2.5-VL-3B-Q6_K.gguf
export LLAMA_SERVER_MMPROJ_PATH=/mnt/astavaknew/phyll-models/mmproj-LFM2.5-VL-3B-Q8_0.gguf

env_for() {  # subset
    export MAGPIE_DATA_DIR=/mnt/astavaknew/magpie-data-vidore-$1
    export QDRANT_CLUSTER_ENDPOINT=http://127.0.0.1:${PORT[$1]}
    export MAGPIE_TRANSCRIPTS_DIR=/mnt/astavaknew/magpie-transcripts/ocr-vidore-$1
}
qdrant_up() {  # subset
    local home=/mnt/astavaknew/qdrant-vidore-$1 port=${PORT[$1]}
    curl -sf "http://127.0.0.1:$port/collections" >/dev/null && return 0
    mkdir -p "$home/storage"
    QDRANT__STORAGE__STORAGE_PATH="$home/storage" QDRANT__SERVICE__HOST=127.0.0.1 \
    QDRANT__SERVICE__HTTP_PORT="$port" QDRANT__SERVICE__GRPC_PORT="$((port + 1))" \
        nohup "$QDRANT_BIN" > "$home/qdrant.log" 2>&1 &
    for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$port/collections" >/dev/null && return 0; sleep 1; done
    echo "qdrant on $port did not come up"; return 1
}

# ColSmol runs through the NVMe venv: the shared .venv's transformers package
# lost its __init__ in the 2026-08-29 disk drop (ImportError on colpali_engine).
PYFAST=/mnt/astavaknew/nas-venv/bin/python
fast() {  # ColPali fast tier only, driven file by file (the walker ranks T3 over T4 and never runs T4)
    local c=$1; env_for "$c"; qdrant_up "$c" || return 1
    mkdir -p "$MAGPIE_DATA_DIR"
    echo "--- [$c] fast tier (ColSmol, $(nproc) cpus) $(date '+%H:%M:%S')"
    $PYFAST Evaluations/vidore_fast_index.py --corpus /mnt/astavaknew/vidore/$c/pages 2>&1 | grep -vE "Loading weights" | tee "$LOGDIR/fast_$c.log" | tail -3
}
text() {  # text tier from the OCR transcripts (run after transcribe_index finished for the subset)
    local c=$1; env_for "$c"; qdrant_up "$c" || return 1
    echo "--- [$c] text tier from OCR transcripts $(date '+%H:%M:%S')"
    $PY Evaluations/vidore_text_index.py --index 2>&1 | tail -2
}
index() { fast "$1" && text "$1"; }
score() {
    local c=$1; env_for "$c"
    $PY Evaluations/vidore_retrieval.py --questions /mnt/astavaknew/vidore/$c/eval_$c.json \
        --out Evaluations/vidore/retrieval__$c.json 2>&1 | tee "$LOGDIR/score_$c.log" | tail -8
}
answer() {  # oracle reader arms on 100 questions: OCR text vs pixels
    local c=$1; env_for "$c"
    local q=/mnt/astavaknew/vidore/$c/eval_${c}_100.json crit=/mnt/astavaknew/vidore/$c/criteria.json
    for arm in ocr pixels; do
        local out=Evaluations/vidore/answers__${c}__$arm.json
        echo "--- [$c] reader arm $arm $(date '+%H:%M:%S')"
        if [ $arm = ocr ]; then export MAGPIE_TRANSCRIPTS_DIR=/mnt/astavaknew/magpie-transcripts/ocr-vidore-$c; else export MAGPIE_TRANSCRIPTS_DIR=/mnt/astavaknew/empty-transcripts; fi
        $PY Evaluations/oracle_answer.py --provider local --corpus /mnt/astavaknew/vidore/$c --questions "$q" --answers "$out" 2>&1 | tee "$LOGDIR/answer_${c}_$arm.log" | grep -vE "^\[|kv-cache|hallucinated" | tail -3
        $PY Evaluations/score_criteria.py --criteria "$crit" "$out" | tail -2
    done
    pkill -f "llama-server .*[-]-port 93"; sleep 2
}
phase=$1; shift
for c in "$@"; do $phase "$c"; done
