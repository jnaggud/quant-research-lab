#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export TRADINGVIEW_CDP_PORT="${TRADINGVIEW_CDP_PORT:-9223}"
export PYTHONDONTWRITEBYTECODE=1

SNAPSHOT_ID="$(date +%Y%m%d_%H%M%S)"
MONITOR_DIR="$ROOT/reports/c7_monitor"
DATA_DIR="$MONITOR_DIR/data"
LOG_DIR="$MONITOR_DIR/logs"
mkdir -p "$DATA_DIR" "$LOG_DIR"

LOG_FILE="$LOG_DIR/${SNAPSHOT_ID}.log"
exec >> "$LOG_FILE" 2>&1

TV="node tradingview-mcp/src/cli/index.js"

echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] C7 monitor start: ${SNAPSHOT_ID}"

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

echo "Restoring 15m chart and exporting active C7 Strategy Tester report"
env TRADINGVIEW_CDP_PORT="$TRADINGVIEW_CDP_PORT" $TV timeframe 15
node scripts/request_tv_history.mjs 10 500
node scripts/export_tv_c5_strategy_data.mjs 087vOT 'JD ES 15m C7 Constrained Refine C1' > "$DATA_DIR/tv_c7_report_${SNAPSHOT_ID}.json"

echo "Running monitor analyzer"
python3 scripts/c7_monitor_analyze.py \
  --snapshot-id "$SNAPSHOT_ID" \
  --data "$DATA_DIR/es1_15m_${SNAPSHOT_ID}.json" \
  --daily-bars "$DATA_DIR/es1_1d_${SNAPSHOT_ID}.json" \
  --h4-bars "$DATA_DIR/es1_240m_${SNAPSHOT_ID}.json" \
  --tv-report "$DATA_DIR/tv_c7_report_${SNAPSHOT_ID}.json" \
  --exclude-tail-bars 1 \
  --out-dir "$MONITOR_DIR"

echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] C7 monitor complete: ${SNAPSHOT_ID}"
