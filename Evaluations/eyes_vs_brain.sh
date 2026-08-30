#!/usr/bin/env bash
# Eyes vs brain: which pixel->text converter, and which reader, on the
# smallest model that still answers correctly. Card + results:
# Evaluations/eyes_vs_brain/README.md (git-ignored with the other dataset
# folders — the results quote ground truths built from personal documents).
#
#   Evaluations/eyes_vs_brain.sh ocr            # CPU only: OCR transcripts + recall (safe while the GPU is busy)
#   Evaluations/eyes_vs_brain.sh eyes           # + VLM transcripts (3B, 450M), transcript recall
#   Evaluations/eyes_vs_brain.sh brain          # reader arms on the image + text blocks
#   Evaluations/eyes_vs_brain.sh eyes brain
#
# Only the `ocr` transcriber is CPU-only. Everything else spawns llama-server
# on the GPU and reads the corpus from the USB disk — coordinate with any
# other session running timed arms first (2026-08-28/29: overlapping jobs
# wrecked both sides' latency numbers). Port range 9300+ so we never share
# one with the 3B arms on 9100 or the 450M arms on 9200.
set -uo pipefail

REPO=/mnt/hardisk/NotAnotherSpotlight
PY=$REPO/.venv/bin/python
OUT=/mnt/astavaknew/magpie-transcripts        # NVMe, not the USB repo disk
MODELS=/mnt/astavaknew/magpie-models
LOGDIR=$REPO/Evaluations/eyes_vs_brain/logs
mkdir -p "$OUT" "$LOGDIR"
cd "$REPO"

declare -A ROOT=( [sem4]=/mnt/hardisk/sem_4 [sem6]=/mnt/hardisk/sem6 [phyll]=/mnt/hardisk/PhyLL [sroie]=/mnt/astavaknew/sroie-corpus )
declare -A DATA=( [sem4]=/mnt/hardisk/magpie-data-sem4 [sem6]=/mnt/hardisk/magpie-data [phyll]=/mnt/hardisk/magpie-data-phyll )
declare -A QPORT=( [sem4]=6437 [sem6]=6433 [phyll]=6439 )   # the existing indexes' Qdrant, from RUNLOG.jsonl

export LLAMA_SERVER_BASE_PORT=9300
export LLAMA_SERVER_STARTUP_TIMEOUT_S=180
export LLAMA_SERVER_PATH=/mnt/hardisk/magpie-data/bin/llama-server
export MAGPIE_FORCE_PROVIDER=local LLM_PROVIDER=local FALLBACK_LLM_PROVIDER=
export HF_HOME=/mnt/hardisk/magpie-data/cache HF_HUB_CACHE=/mnt/hardisk/magpie-data/cache/hub
export FASTEMBED_CACHE_PATH=/mnt/hardisk/magpie-data/cache/fastembed

# the same files every transcriber sees: only the ones the image block asks about
only_files() {  # corpus -> newline list of --only substrings
    $PY - "$1" <<'PYEOF'
import json, sys
qs = json.load(open(f"Evaluations/{sys.argv[1]}/eval_{sys.argv[1]}_vision.json"))
print("\n".join(sorted({k for q in qs for k in q["key_files"]})))
PYEOF
}

transcribe() {  # name backend corpus [env...]
    local name=$1 backend=$2 c=$3; shift 3
    local dir=$OUT/$name-$c
    echo "--- transcripts: $name / $c -> $dir  ($(date '+%H:%M:%S'))"
    while IFS= read -r f; do
        env "$@" MAGPIE_TRANSCRIPTS_DIR="$dir" \
            $PY Evaluations/transcribe_index.py --backend "$backend" --corpus "${ROOT[$c]}" --only "$f"
    done < <(only_files "$c") 2>&1 | tee -a "$LOGDIR/transcribe_$name-$c.log" | grep -vE "^backend=|^done:"
}

recall() {  # corpus name...
    local c=$1; shift
    local args=()
    for n in "$@"; do args+=("$n=$OUT/$n-$c"); done
    echo; echo "=== transcript recall / $c ==="
    $PY Evaluations/transcript_recall.py --questions "Evaluations/$c/eval_${c}_vision.json" \
        --criteria "Evaluations/$c/criteria_vision.json" --corpus "${ROOT[$c]}" "${args[@]}" \
        | tee "$LOGDIR/recall_$c.txt"
}

# SROIE: 60 photographed receipts with ICDAR's own ground truth — every file,
# no --only filter, scored by sroie_recall.py instead of the criteria block.
transcribe_all() {  # name backend [env...]
    local name=$1 backend=$2; shift 2
    local dir=$OUT/$name-sroie
    echo "--- transcripts: $name / sroie -> $dir  ($(date '+%H:%M:%S'))"
    env "$@" MAGPIE_TRANSCRIPTS_DIR="$dir" \
        $PY Evaluations/transcribe_index.py --backend "$backend" --corpus "${ROOT[sroie]}" \
        2>&1 | tee -a "$LOGDIR/transcribe_$name-sroie.log" | tail -2
}

VL3B=(LLAMA_SERVER_MODEL_PATH=/mnt/astavaknew/phyll-models/LFM2.5-VL-3B-Q6_K.gguf LLAMA_SERVER_MMPROJ_PATH=/mnt/astavaknew/phyll-models/mmproj-LFM2.5-VL-3B-Q8_0.gguf)
VL450=(LLAMA_SERVER_MODEL_PATH=$MODELS/LFM2.5-VL-450M-Q8_0.gguf LLAMA_SERVER_MMPROJ_PATH=$MODELS/mmproj-LFM2.5-VL-450m-Q8_0.gguf)

eyes_ocr() {   # CPU only — the part that can run while the GPU is busy
    for c in sem4 sem6; do transcribe ocr ocr "$c"; done
    transcribe_all ocr ocr
    for c in sem4 sem6; do recall "$c" ocr; done
    $PY Evaluations/sroie_recall.py --corpus "${ROOT[sroie]}" ocr=$OUT/ocr-sroie | tee "$LOGDIR/recall_sroie.txt"
}

eyes() {
    [ -d "$OUT/ocr-sem6" ] || eyes_ocr
    for c in sem4 sem6; do transcribe vlm3b vlm "$c" "${VL3B[@]}"; done
    transcribe_all vlm3b vlm "${VL3B[@]}"
    pkill -f "llama-server .*[-]-port 93" ; sleep 3
    for c in sem4 sem6; do transcribe vlm450m vlm "$c" "${VL450[@]}"; done
    transcribe_all vlm450m vlm "${VL450[@]}"
    pkill -f "llama-server .*[-]-port 93" ; sleep 3
    for c in sem4 sem6; do recall "$c" ocr vlm3b vlm450m; done
    $PY Evaluations/sroie_recall.py --corpus "${ROOT[sroie]}" \
        ocr=$OUT/ocr-sroie vlm3b=$OUT/vlm3b-sroie vlm450m=$OUT/vlm450m-sroie | tee "$LOGDIR/recall_sroie.txt"
}

# reader arms: oracle retrieval (Evaluations/oracle_answer.py hands the
# reader each question's key files — the block's images are T4-only in the
# sem6 index and absent from the sem4 manifest, so a full-pipeline arm would
# measure retrieval misses, not reading). Same transcripts for every reader
# (EYES, default ocr: the strongest complete column and the cheapest). phyll
# is the text no-regression block.
EYES=${EYES:-ocr}
arm() {  # label corpus questions criteria [env...]
    local label=$1 c=$2 q=$3 crit=$4; shift 4
    local answers=Evaluations/$c/eval_answer_$(basename "$q" .json | sed 's/^eval_//')__oracle_${label}.json
    echo; echo "--- reader arm $label / $c  ($(date '+%H:%M:%S'))"
    env "$@" MAGPIE_TRANSCRIPTS_DIR="$OUT/$EYES-$c" \
        $PY Evaluations/oracle_answer.py --provider local --corpus "${ROOT[$c]}" \
        --questions "$q" --answers "$answers" 2>&1 | tee "$LOGDIR/arm_${label}_$c.log" | grep -vE "^\[|^  note:"
    $PY Evaluations/score_criteria.py --criteria "$crit" "$answers" | tail -3
    env "$@" MAGPIE_DATA_DIR="${DATA[$c]}" \
        $PY Evaluations/runlog.py --dataset "$c" --answers "$answers" --criteria "$crit" \
        --note "eyes-vs-brain ORACLE reader arm $label (key files handed to the reader, no retrieval), transcripts=$EYES" 2>&1 | tail -1
}

brain() {
    # label, then the env that selects the reader. Cheapest first. The
    # text-only readers keep a vision fallback registered for any image
    # without a transcript (none expected with EYES=ocr).
    local -a readers=(
        "qwen05  LLAMA_SERVER_TEXT_MODEL=text-only LOCAL_MODEL=Qwen/Qwen2.5-0.5B-Instruct-GGUF LOCAL_QUANT=q8_0"
        "lfm12   LLAMA_SERVER_TEXT_MODEL=text-only LOCAL_MODEL=LiquidAI/LFM2.5-1.2B-Instruct-GGUF LOCAL_QUANT=Q8_0"
        "qwen15  LLAMA_SERVER_TEXT_MODEL=text-only LOCAL_MODEL=Qwen/Qwen2.5-1.5B-Instruct-GGUF LOCAL_QUANT=q8_0"
        "qwen3b  LLAMA_SERVER_TEXT_MODEL=text-only LOCAL_MODEL=Qwen/Qwen2.5-3B-Instruct-GGUF LOCAL_QUANT=q6_k"
        "vl3b    LLAMA_SERVER_MODEL_PATH=/mnt/astavaknew/phyll-models/LFM2.5-VL-3B-Q6_K.gguf LLAMA_SERVER_MMPROJ_PATH=/mnt/astavaknew/phyll-models/mmproj-LFM2.5-VL-3B-Q8_0.gguf"
    )
    for r in "${readers[@]}"; do
        # shellcheck disable=SC2206
        local parts=($r); local label=${parts[0]}; local envs=("${parts[@]:1}")
        envs+=(LLAMA_SERVER_VISION_MODEL=lfm25-vl-vision LOCAL_MMPROJ_REPO=LiquidAI/LFM2.5-VL-3B-GGUF)
        arm "$label" sem6 Evaluations/sem6/eval_sem6_vision.json Evaluations/sem6/criteria_vision.json "${envs[@]}"
        arm "$label" sem4 Evaluations/sem4/eval_sem4_vision.json Evaluations/sem4/criteria_vision.json "${envs[@]}"
        arm "$label" phyll Evaluations/phyll/eval_phyll.json Evaluations/phyll/criteria_v2.json "${envs[@]}"
        pkill -f "llama-server .*[-]-port 93" ; sleep 3
    done
}

for phase in "$@"; do
    case $phase in
        ocr) eyes_ocr ;;
        eyes) eyes ;;
        brain) brain ;;
        *) echo "unknown phase $phase (ocr|eyes|brain)"; exit 2 ;;
    esac
done
