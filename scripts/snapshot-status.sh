#!/usr/bin/env bash
set -euo pipefail

DATADIR="${BTX_DATADIR:-$HOME/.bitcoin}"
LOG="$DATADIR/debug.log"

if [[ ! -f "$LOG" ]]; then
  echo "BTX debug log not found: $LOG" >&2
  exit 1
fi

python3 - "$LOG" <<'PY'
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

pattern = re.compile(
    r"^(\S+) \[background validation\] UpdateTip: .* height=(\d+)"
)
points = []
for line in Path(sys.argv[1]).read_text(errors="replace").splitlines():
    match = pattern.search(line)
    if not match:
        continue
    points.append(
        (
            datetime.fromisoformat(match.group(1).replace("Z", "+00:00")),
            int(match.group(2)),
        )
    )

if not points:
    print("No background validation progress records found")
    raise SystemExit(0)

latest_time, latest_height = points[-1]
target_height = 128_605
remaining = max(0, target_height - latest_height)
sample = points[-min(6, len(points)):]
elapsed = (sample[-1][0] - sample[0][0]).total_seconds()
advanced = sample[-1][1] - sample[0][1]
rate = advanced / elapsed if elapsed > 0 else 0

print(
    f"background validation: {latest_height:,}/{target_height:,} "
    f"({latest_height / target_height * 100:.1f}%)"
)
if rate > 0 and remaining:
    eta_seconds = remaining / rate
    eta = datetime.now(timezone.utc).timestamp() + eta_seconds
    eta_dt = datetime.fromtimestamp(eta, timezone.utc)
    print(
        f"recent rate: {rate * 3600:,.0f} blocks/hour; "
        f"estimated completion: {eta_dt:%Y-%m-%d %H:%M UTC}"
    )
elif remaining == 0:
    print("historical validation has reached the snapshot base height")
else:
    print("not enough recent progress data for an ETA")
PY
