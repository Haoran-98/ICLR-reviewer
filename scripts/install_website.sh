#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-web.txt
npm --prefix web ci
.venv/bin/python scripts/install_demo_assets.py "$@"
export TIKTOKEN_CACHE_DIR="${TIKTOKEN_CACHE_DIR:-${ICLR_DATA_DIR:-$PWD/.local-data}/tokenizer-cache}"
.venv/bin/python -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")'
printf 'Next: .venv/bin/python scripts/init_web_account.py --username root\nThen: ./scripts/run_website.sh\n'
