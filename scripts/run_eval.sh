#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
CHAT_URL="${CHAT_URL:-${API_URL}/chat}"
HEALTH_URL="${HEALTH_URL:-${API_URL}/health}"

python3 - <<PY
import sys
import urllib.request

url = "${HEALTH_URL}"
try:
    with urllib.request.urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"health returned {response.status}")
except Exception as exc:
    print(f"Eval server check failed: {url} ({exc})", file=sys.stderr)
    print("Start the API first, e.g.: python3 -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000", file=sys.stderr)
    raise SystemExit(1)
PY

python3 scripts/run_eval.py --api-url "${CHAT_URL}" --save-report "$@"
