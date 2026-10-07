#!/usr/bin/env bash
# Generate portable templates. Installation is explicit and macOS-only.
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-python3}" scripts/configure_launchd.py "$@"
