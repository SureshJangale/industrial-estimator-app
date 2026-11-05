#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -z "${APP_SECRET:-}" ]; then
  echo 'ERROR: Set a persistent APP_SECRET in environment; do not use the demo launcher.' >&2
  exit 1
fi
export APP_ENV=production
export DATABASE_URL="${DATABASE_URL:-sqlite:///$PWD/runtime/estimator.db}"
exec python -m uvicorn backend.app:app --host "${APP_HOST:-127.0.0.1}" --port "${PORT:-8000}"
