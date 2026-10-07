#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONDONTWRITEBYTECODE=1

SUMMARY_DIR="$ROOT/reports/c8_monitor/morning"
mkdir -p "$SUMMARY_DIR"

python3 scripts/c8_morning_summary.py
