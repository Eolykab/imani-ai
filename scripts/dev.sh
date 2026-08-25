#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT
PYTHONPATH=backend uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
npm --prefix frontend run dev &
wait
