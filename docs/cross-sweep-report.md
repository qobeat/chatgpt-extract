# Cross-sweep model report (ADOS Project States)

- Geometry: `GEOM-chatgpt-extract` · version(s): 1
- Workloads: 2 · states: 19
- Scores are comparable **only within a workload** (different sweeps ran different input sets); this report never averages across workloads.

Columns → coordinates: Compl%=`COORD-B-COMPLETION`, Acc%=`COORD-B-ACCURACY`, Depth%=`COORD-B-DEPTH`, Schema%=`COORD-B-SCHEMA`, s/item=`COORD-B-SPEED`, Wh/item=`COORD-B-ENERGY`

## Workload: `jun2026-perf` (3 model(s))

| Model | Compl% | Acc% | Depth% | Schema% | s/item | Wh/item |
|---|---|---|---|---|---|---|
| codex | 100 | — | 99 | 100 | 25.6 | — |
| ollama:gemma3:1b | 96 | — | 26 | 8 | 3.7 | 0.231 |
| ollama:gemma4:31b | 95 | — | 96 | 95 | 38.4 | 3.503 |

## Workload: `oct2024-cmp` (16 model(s))

| Model | Compl% | Acc% | Depth% | Schema% | s/item | Wh/item |
|---|---|---|---|---|---|---|
| claude | 100 | — | 98 | 100 | 24.5 | — |
| codex | 100 | — | 99 | 100 | 15.2 | — |
| cursor:composer-2.5 | 100 | — | 99 | 100 | 18.7 | — |
| cursor:composer-2.5-fast | 100 | — | 98 | 100 | 12.7 | — |
| ollama:gemma3:1b | 89 | — | 21 | 7 | 3.6 | 0.239 |
| ollama:gemma4:31b | 93 | — | 90 | 93 | 39.0 | 2.912 |
| ollama:gpt-oss:20b | 85 | — | 78 | 85 | 22.0 | 1.856 |
| ollama:llama3.1:8b | 96 | — | 59 | 96 | 7.3 | 0.540 |
| ollama:qwen2.5-coder:1.5b | 93 | — | 67 | 93 | 3.5 | 0.252 |
| ollama:qwen2.5-coder:14b | 93 | — | 65 | 93 | 14.1 | 1.059 |
| ollama:qwen2.5-coder:3b | 93 | — | 56 | 93 | 4.5 | 0.378 |
| ollama:qwen2.5-coder:7b | 93 | — | 72 | 93 | 7.6 | 0.614 |
| ollama:qwen2.5vl:7b | 93 | — | 67 | 93 | 7.6 | 0.577 |
| ollama:qwen3.6:27b | 93 | — | 88 | 93 | 29.7 | 2.360 |
| ollama:qwen3.6:35b | 93 | — | 79 | 93 | 20.3 | 1.086 |
| ollama:qwen3:8b | 93 | — | 85 | 93 | 8.8 | 0.696 |
