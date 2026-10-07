#!/usr/bin/env bash
# Resume an existing download manifest. This script does not create a data entitlement.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
: "${DATABENTO_API_KEY:?Export DATABENTO_API_KEY before downloading}"
export DATABENTO_ROOT="${DATABENTO_ROOT:-data/databento}"
PY="${PYTHON:-python3}"
LOG="${DOWNLOAD_LOG:-$DATABENTO_ROOT/keepalive.log}"
mkdir -p "$(dirname "$LOG")"
remaining() {
  "$PY" -c 'import json,os,pathlib; m=json.loads((pathlib.Path(os.environ["DATABENTO_ROOT"])/"manifest.json").read_text()); print(sum(j["state"]!="downloaded" for j in m["jobs"].values()))'
}
while true; do
  rem=$(remaining) || exit 1
  if [ "$rem" -le 0 ]; then
    echo "All jobs downloaded" | tee -a "$LOG"
    break
  fi
  echo "$(date '+%F %T') $rem jobs remaining" | tee -a "$LOG"
  "$PY" -u scripts/simple_download.py --workers 1 >> "$LOG" 2>&1
  sleep 30
done
