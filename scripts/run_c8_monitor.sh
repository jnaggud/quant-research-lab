#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export TRADINGVIEW_CDP_PORT="${TRADINGVIEW_CDP_PORT:-9223}"
export PYTHONDONTWRITEBYTECODE=1

SNAPSHOT_ID="$(date +%Y%m%d_%H%M%S)"
MONITOR_DIR="$ROOT/reports/c8_monitor"
DATA_DIR="$MONITOR_DIR/data"
LOG_DIR="$MONITOR_DIR/logs"
mkdir -p "$DATA_DIR" "$LOG_DIR"

LOG_FILE="$LOG_DIR/${SNAPSHOT_ID}.log"
exec >> "$LOG_FILE" 2>&1

TV="node tradingview-mcp/src/cli/index.js"
CHAMPION_TITLE="JD ES 15m C9 Core Forward Refine 200k C1 20260620"

echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] Champion monitor start: ${SNAPSHOT_ID}"

echo "Checking TradingView state"
env TRADINGVIEW_CDP_PORT="$TRADINGVIEW_CDP_PORT" $TV state

echo "Setting symbol ES1! and timeframe 15"
env TRADINGVIEW_CDP_PORT="$TRADINGVIEW_CDP_PORT" $TV symbol ES1!
env TRADINGVIEW_CDP_PORT="$TRADINGVIEW_CDP_PORT" $TV timeframe 15
node scripts/request_tv_history.mjs 10 500
node scripts/export_tv_main_bars.mjs > "$DATA_DIR/es1_15m_${SNAPSHOT_ID}.json"

echo "Refreshing 240m bars"
env TRADINGVIEW_CDP_PORT="$TRADINGVIEW_CDP_PORT" $TV timeframe 240
node scripts/request_tv_history.mjs 10 500
node scripts/export_tv_main_bars.mjs > "$DATA_DIR/es1_240m_${SNAPSHOT_ID}.json"

echo "Refreshing 1D bars"
env TRADINGVIEW_CDP_PORT="$TRADINGVIEW_CDP_PORT" $TV timeframe 1D
node scripts/request_tv_history.mjs 10 500
node scripts/export_tv_main_bars.mjs > "$DATA_DIR/es1_1d_${SNAPSHOT_ID}.json"

echo "Restoring 15m chart and exporting active champion Strategy Tester report"
env TRADINGVIEW_CDP_PORT="$TRADINGVIEW_CDP_PORT" $TV timeframe 15
node scripts/request_tv_history.mjs 10 500
env TRADINGVIEW_CDP_PORT="$TRADINGVIEW_CDP_PORT" node scripts/export_tv_strategy_robust.mjs \
  --target-id 087vOT \
  --target-name "$CHAMPION_TITLE" \
  --max-trades 800 \
  --trade-chunk 100 \
  --max-orders 0 \
  --retries 4 \
  --timeout 9000 \
  --out "$DATA_DIR/tv_c9_c1_report_${SNAPSHOT_ID}.json" \
  > "$DATA_DIR/tv_c9_c1_report_${SNAPSHOT_ID}.stdout.json"

echo "Running champion monitor analyzer"
python3 scripts/c8_monitor_analyze.py \
  --snapshot-id "$SNAPSHOT_ID" \
  --data "$DATA_DIR/es1_15m_${SNAPSHOT_ID}.json" \
  --daily-bars "$DATA_DIR/es1_1d_${SNAPSHOT_ID}.json" \
  --h4-bars "$DATA_DIR/es1_240m_${SNAPSHOT_ID}.json" \
  --tv-report "$DATA_DIR/tv_c9_c1_report_${SNAPSHOT_ID}.json" \
  --exclude-tail-bars 0 \
  --out-dir "$MONITOR_DIR"

echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] Champion monitor complete: ${SNAPSHOT_ID}"
