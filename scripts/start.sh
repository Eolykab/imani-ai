#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test -f frontend/dist/index.html || npm --prefix frontend run build
exec env PYTHONPATH=backend uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
