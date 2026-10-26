#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo 'Python environment missing. Run: uv sync' >&2
  exit 1
fi
if [[ ! -d node_modules ]]; then
  echo 'Frontend dependencies missing. Run: npm ci' >&2
  exit 1
fi
if ! command -v node >/dev/null 2>&1; then
  echo 'Node.js 20+ is required to validate LaTeX and run frontend tests.' >&2
  exit 1
fi

.venv/bin/python -m unittest discover -s tests -v
npm test
