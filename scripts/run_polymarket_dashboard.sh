#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export POLYMARKET_DASHBOARD_PORT="${POLYMARKET_DASHBOARD_PORT:-8061}"
exec "${PYTHON:-python3}" -m dashboard.polymarket_dashboard
