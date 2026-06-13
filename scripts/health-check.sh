#!/usr/bin/env bash
set -euo pipefail

URL="${BTXPOOL_HEALTH_URL:-http://127.0.0.1:8080/api/health}"

python3 - "$URL" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=10) as response:
    health = json.load(response)

capacity = health.get("capacity") or {}
problems = []
if not health.get("ready"):
    chain = health.get("chain") or {}
    problems.append(chain.get("last_error") or "pool has no current mining job")
if health.get("unresolved_payouts"):
    problems.append(f"{health['unresolved_payouts']} unresolved payouts")
if float(capacity.get("verifier_utilization_percent") or 0) >= 80:
    problems.append(
        f"verifier queue at {capacity['verifier_utilization_percent']}%"
    )
if int(capacity.get("verifier_overload_rejections") or 0) > 0:
    problems.append(
        f"{capacity['verifier_overload_rejections']} overload rejections"
    )

if problems:
    print("BTX pool degraded:", "; ".join(problems))
    raise SystemExit(1)

print(
    "BTX pool ready:",
    f"{capacity.get('authorized_sessions', 0)} miners,",
    f"{capacity.get('verifier_pending', 0)} shares pending",
)
PY
