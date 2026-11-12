#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export ICLR_PYTHON="${ICLR_PYTHON:-$PWD/.venv/bin/python}"
export ICLR_DATA_DIR="${ICLR_DATA_DIR:-$PWD/.local-data}"
test -x "$ICLR_PYTHON"
test -f "$ICLR_DATA_DIR/website/generated/sample.json" || test -f web/public/generated/sample.json
exec npm --prefix web run dev -- --port "${ICLR_WEB_PORT:-5174}" --strictPort
