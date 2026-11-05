#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_SECRET="${APP_SECRET:-$(python -c 'import secrets; print(secrets.token_urlsafe(48))')}"
export APP_DEMO_MODE=1
export DATABASE_URL="${DATABASE_URL:-sqlite:///$PWD/runtime/estimator.db}"
python -m backend.seed --demo
exec python -m uvicorn backend.app:app --host 127.0.0.1 --port "${PORT:-8000}"
