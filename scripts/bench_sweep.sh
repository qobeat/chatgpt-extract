#!/usr/bin/env bash
# bench_sweep.sh — run the model benchmark over the fixed oct2024 workload (27
# bundles, num_ctx=16384) with GPU health monitoring, then leave the per-run
# artifacts for `gpt metrics` / `gpt gen-model-benchmarks`.
#
# Per model:
#   1. GPU preflight (ollama only): bench_monitor.py check --warm asserts the
#      model loads ON the GPU (not a CPU spill). On FATAL it tries an autofix
#      (sudo systemctl restart ollama) and re-checks; if it still can't run on
#      GPU it SKIPS the model and prints the manual fix, then continues.
#   2. Run `gpt summarize` (local models add --meter-power for measured Wh/item).
#   3. While it runs, bench_monitor.py watch samples every 30 s (CPU spill,
#      GPU idle, VRAM full, error lines) into a health trace.
#   4. If the watcher saw a FATAL (e.g. a mid-run CPU spill), restart Ollama
#      BEFORE the next model so one bad model cannot poison the rest.
#
# Cloud reference models (codex, claude) run with NO web search (provider
# default) and a TOKEN-EQUIVALENT budget cap (--budget-usd) so a plan-metered
# run cannot blow past ~$5 of equivalent tokens.
#
# Usage:
#   scripts/bench_sweep.sh [PREFIX] [MODE]
#     PREFIX  run-label prefix (default: cmp-0628)
#     MODE    local | cloud | all   (default: all)
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$REPO/.env" 2>/dev/null || true
DATA="${RECONSTRUCTOR_DATA_ROOT:-$HOME/chatgpt-reconstructor-data}"
SRC="$DATA/runs/oct2024"
STORE="$SRC/store"
BUNDLES="$SRC/bundles"

PREFIX="${1:-cmp-0628}"
MODE="${2:-all}"
NUM_CTX=16384
INTERVAL=30
BUDGET_USD=5
LOGDIR="$DATA/benchlogs_${PREFIX}"
HEALTHDIR="$DATA/health_${PREFIX}"
SUMLOG="$DATA/benchmark_${PREFIX}.log"
mkdir -p "$LOGDIR" "$HEALTHDIR"
MON="$REPO/scripts/bench_monitor.py"
PY="${PYTHON:-python3}"

# provider|model|short   (empty model = let the signed-in CLI pick its default).
LOCAL_MODELS=(
  "ollama|qwen2.5-coder:1.5b|qwen25c-1.5b"
  "ollama|qwen2.5-coder:3b|qwen25c-3b"
  "ollama|qwen2.5-coder:7b|qwen25c-7b"
  "ollama|qwen2.5-coder:14b|qwen25c-14b"
  "ollama|qwen2.5vl:7b|qwen25vl-7b"
  "ollama|qwen3:8b|qwen3-8b"
  "ollama|llama3.1:8b|llama31-8b"
  "ollama|gemma3:1b|gemma3-1b"
  "ollama|gpt-oss:20b|gptoss-20b"
  "ollama|qwen3.6:27b|qwen36-27b"
  "ollama|qwen3.6:35b|qwen36-35b"
  "ollama|gemma4:31b|gemma4-31b"
)
# codex first: it is the accuracy reference key for `gpt compare`.
CLOUD_MODELS=(
  "codex||codex"
  "claude||claude"
)

log() { echo "$*" | tee -a "$SUMLOG"; }

run_one() {
  local prov="$1" model="$2" short="$3" metered="$4"
  local label="${PREFIX}-${short}"
  local rlog="$LOGDIR/${short}.log"
  local mlog="$LOGDIR/${short}.monitor.log"
  local health="$HEALTHDIR/${short}.jsonl"

  log ""
  log "---- [$prov] ${model:-<default>} -> $label  $(date -Is) ----"

  # 1) GPU preflight for local models.
  if [ "$prov" = "ollama" ]; then
    if ! "$PY" "$MON" check --model "$model" --num-ctx "$NUM_CTX" --warm --autofix \
         2>&1 | tee -a "$SUMLOG"; then
      log "PREFLIGHT FATAL for $model — could not place on GPU."
      log "   MANUAL FIX: sudo systemctl restart ollama   (then re-run: scripts/bench_sweep.sh $PREFIX local)"
      log "RESULT prov=$prov model=$model label=$label exit=preflight_skip"
      return 0
    fi
  fi

  # 2) launch summarize in the background, capture its PID.
  local args=(summarize --provider "$prov" --store "$STORE" --bundles "$BUNDLES"
              --run-label "$label" --num-ctx "$NUM_CTX" --no-preflight --yes)
  [ -n "$model" ] && args+=(--model "$model")
  [ "$metered" = "1" ] && args+=(--meter-power)
  if [ "$prov" != "ollama" ]; then
    # Cloud reference: cap token-equivalent spend; web search already off.
    args+=(--budget-usd "$BUDGET_USD")
  fi

  local t0 t1 rc mrc
  t0=$(date +%s)
  "$REPO/gpt" "${args[@]}" >"$rlog" 2>&1 &
  local spid=$!

  # 3) watch GPU health every INTERVAL seconds for ollama runs only.
  local mpid=""
  if [ "$prov" = "ollama" ]; then
    "$PY" "$MON" watch --model "$model" --pid "$spid" --interval "$INTERVAL" \
        --log "$rlog" --health-out "$health" >"$mlog" 2>&1 &
    mpid=$!
  fi

  wait "$spid"; rc=$?
  t1=$(date +%s)
  mrc=0
  if [ -n "$mpid" ]; then wait "$mpid"; mrc=$?; fi

  log "RESULT prov=$prov model=${model:-<default>} label=$label exit=$rc secs=$((t1-t0)) monitor=$mrc"
  tail -n 1 "$rlog" 2>/dev/null | sed 's/^/   last: /' | tee -a "$SUMLOG" >/dev/null

  # 4) a FATAL during the run (CPU spill / host down) — try to recover before
  #    the next model so it cannot inherit a degraded host.
  if [ "$mrc" = "2" ]; then
    log "   monitor saw FATAL during $model — attempting recovery before next model"
    "$PY" "$MON" check --autofix 2>&1 | tee -a "$SUMLOG" || \
      log "   MANUAL FIX REQUIRED: sudo systemctl restart ollama"
  fi
}

log "==== sweep start $(date -Is) prefix=$PREFIX mode=$MODE src=$SRC ===="
"$PY" "$MON" check 2>&1 | tee -a "$SUMLOG"

if [ "$MODE" = "local" ] || [ "$MODE" = "all" ]; then
  for entry in "${LOCAL_MODELS[@]}"; do
    IFS='|' read -r prov model short <<<"$entry"
    run_one "$prov" "$model" "$short" 1
  done
fi
if [ "$MODE" = "cloud" ] || [ "$MODE" = "all" ]; then
  for entry in "${CLOUD_MODELS[@]}"; do
    IFS='|' read -r prov model short <<<"$entry"
    run_one "$prov" "$model" "$short" 0
  done
fi

log ""
log "==== sweep done $(date -Is) ===="
log "Next: ./gpt metrics perf    \"$DATA\"/runs/${PREFIX}-*/summarize_trace.jsonl"
log "      ./gpt metrics quality \"$DATA\"/runs/${PREFIX}-*/reconstructed_projects.json --correctness ref=${PREFIX}-codex"
log "      ./gpt gen-model-benchmarks --runs '${PREFIX}-*' --reference ref=${PREFIX}-codex"
