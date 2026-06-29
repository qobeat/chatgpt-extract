#!/usr/bin/env bash

run_perf() {
cd ~/dev/WSL/chatgpt-extract/chatgpt-extract && source .env 2>/dev/null
DR="${RECONSTRUCTOR_DATA_ROOT:-$HOME/chatgpt-reconstructor-data}"
echo "===== PERF ====="
./gpt metrics perf "$DR"/runs/cmp-0628-*/summarize_trace.jsonl --json
echo "===== QUALITY + ACCURACY (ref=codex) ====="
./gpt metrics quality "$DR"/runs/cmp-0628-*/reconstructed_projects.json --correctness ref=cmp-0628-codex --json
echo "===== REGENERATE model_benchmarks.json ====="
./gpt gen-model-benchmarks --runs 'cmp-0628-*' --reference ref=cmp-0628-codex
echo "===== GENERATED FILE ====="
cat config/generated/model_benchmarks.json
}

run_quality() {
    cd ~/dev/WSL/chatgpt-extract/chatgpt-extract && source .env 2>/dev/null
    DR="${RECONSTRUCTOR_DATA_ROOT:-$HOME/chatgpt-reconstructor-data}"

    echo "===== A) TOP CPU/MEM PROCESSES ====="
ps -eo pid,ppid,%cpu,%mem,etime,comm --sort=-%cpu | head -15
echo "----- cursor / node / agent processes -----"
ps -eo pid,%cpu,%mem,etime,args --sort=-%cpu | grep -iE 'cursor|\.cursor-server|node|ollama|python' | grep -v grep | head -25

echo; echo "===== B) SWEEP STATE ====="
echo "-- our processes still running? --"
ps -eo pid,etime,args | grep -E 'bench_sweep|summarize\.py|bench_monitor' | grep -v grep || echo "(none running)"
echo "-- RESULT lines --"
grep -E "^RESULT|PREFLIGHT FATAL|MANUAL FIX|sweep done|BUDGET" "$DR/benchmark_cmp-0628.log" 2>/dev/null | tail -20 || echo "(no sweep log)"
echo "-- cmp-0628 run dirs --"
ls -1 "$DR/runs" 2>/dev/null | grep cmp-0628 || echo "(no runs)"
echo "-- codex/claude item counts --"
for m in codex claude; do
  f="$DR/runs/cmp-0628-$m/reconstructed_projects.json"
  [ -f "$f" ] && echo "$m: $(grep -o '"n_items"[^,]*' "$f" | head -1)  failed=$(grep -o '"n_failed"[^,]*' "$f" | head -1)" || echo "$m: MISSING"
done

echo; echo "===== C) OLLAMA / GPU HEALTH ====="
ollama ps 2>&1
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader 2>&1

echo; echo "===== D) CODE FILES PRESENT ====="
ls -la scripts/bench_monitor.py scripts/bench_sweep.sh 2>&1 | awk '{print $5, $9}'
}

run_regen() {
    cd ~/dev/WSL/chatgpt-extract/chatgpt-extract && source .env 2>/dev/null
    DR="${RECONSTRUCTOR_DATA_ROOT:-$HOME/chatgpt-reconstructor-data}"
    ./gpt gen-model-benchmarks --runs 'cmp-0628-*' --reference ref=cmp-0628-codex
}

run_diag() {
    cd ~/dev/WSL/chatgpt-extract/chatgpt-extract && source .env 2>/dev/null
    DR="${RECONSTRUCTOR_DATA_ROOT:-$HOME/chatgpt-reconstructor-data}"
    ./gpt diagnose "$DR/runs/cmp-0628-*/export.zip"
}



case "$1" in   
    "perf") run_perf; continue;;
    "quality") run_quality; continue;;
    "regen") run_regen; continue;;
    "diag") run_diag; continue;;
    *) echo "Usage: $0 [perf|quality|regen|diag]"; exit 1;;
esac
    "quality") run_quality; continue;;
    "regen") run_regen;;
    "diag") run_diag;;
    *) echo "Usage: $0 [perf|quality|regen|diag]"; exit 1;;
esac