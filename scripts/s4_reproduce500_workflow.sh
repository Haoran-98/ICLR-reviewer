#!/usr/bin/env bash
set -euo pipefail
S4_ROOT=/data_big/iclr-s4/experiments/repro500_qwen38_27b_q3_medium_64k_v2
S4_PYTHON=/data_big/iclr-s4/runtime-dkta/bin/python
S4_SCRIPT="$S4_ROOT/runtime/s4_reproduce500.py"
S4_STATUS="$S4_ROOT/runtime/workflow_status.json"

record_exit() {
  s4_code=$?
  s4_state=failed
  if (( s4_code == 0 )); then s4_state=completed; fi
  printf '{"state":"%s","exit_code":%d,"finished_at":"%s"}\n' \
    "$s4_state" "$s4_code" "$(date --iso-8601=seconds)" > "$S4_STATUS.tmp"
  mv "$S4_STATUS.tmp" "$S4_STATUS"
}
trap record_exit EXIT
printf '{"state":"running","started_at":"%s"}\n' "$(date --iso-8601=seconds)" > "$S4_STATUS.tmp"
mv "$S4_STATUS.tmp" "$S4_STATUS"
for s4_method in taxoadapt context lisa itl; do
  "$S4_PYTHON" "$S4_SCRIPT" run --methods "$s4_method" --device cpu --concurrency 4
done
"$S4_PYTHON" "$S4_SCRIPT" evaluate --concurrency 4
