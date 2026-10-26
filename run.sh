#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export POLEQ_DB="${POLEQ_DB:-$PWD/.data/library.sqlite3}"
export POLEQ_MODEL="${POLEQ_MODEL:-qwen3:0.6b}"
poleq_ollama_pid=""
trap 'if [[ -n "$poleq_ollama_pid" ]]; then kill "$poleq_ollama_pid" 2>/dev/null || true; fi' EXIT
mkdir -p .data
if ! curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  if [[ -x .runtime/bin/ollama ]]; then
    OLLAMA_NO_CLOUD=true OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS="$PWD/.data/ollama" OLLAMA_NUM_PARALLEL=1 OLLAMA_CONTEXT_LENGTH=4096 .runtime/bin/ollama serve > .data/ollama.log 2>&1 &
    poleq_ollama_pid=$!
  elif command -v ollama >/dev/null; then
    OLLAMA_NO_CLOUD=true OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NUM_PARALLEL=1 OLLAMA_CONTEXT_LENGTH=4096 ollama serve > .data/ollama.log 2>&1 &
    poleq_ollama_pid=$!
  fi
fi
if [[ ! -x .venv/bin/poleq ]]; then
  echo 'Run uv sync first.' >&2
  exit 1
fi
.venv/bin/poleq serve "$@"
