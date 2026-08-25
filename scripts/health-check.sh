#!/usr/bin/env bash
set -euo pipefail
curl --fail --silent "${PIPILOT_URL:-http://localhost:8000}/api/health"
printf '\n'
