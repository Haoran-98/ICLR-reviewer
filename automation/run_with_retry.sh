#!/usr/bin/env bash

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AUTH_FILE="${ICLR_AUTH_FILE:-$HOME/auth}"
PYTHON="${PYTHON:-/usr/bin/python3}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-100}"
RETRY_SECONDS="${RETRY_SECONDS:-60}"
TASK="${1:-}"

case "$TASK" in
    daily|weekly|monthly) ;;
    *) printf 'retry_runner=invalid_task task=%s\n' "$TASK" >&2; exit 2 ;;
esac

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    (
        set -e
        source "$AUTH_FILE"
        : "${OPENAI_BASE_URL:?Missing OPENAI_BASE_URL}"
        : "${OPENAI_API_KEY:?Missing OPENAI_API_KEY}"
        : "${OPENAI_WEAK_MODEL_ID:?Missing OPENAI_WEAK_MODEL_ID}"
        cd "$ROOT"
        "$PYTHON" automation/manage.py "$TASK" --push
    )
    status=$?
    if [ "$status" -eq 0 ]; then
        printf 'retry_runner=success task=%s attempt=%s/%s\n' "$TASK" "$attempt" "$MAX_ATTEMPTS"
        exit 0
    fi
    printf 'retry_runner=failed task=%s attempt=%s/%s status=%s retry_in=%ss\n' \
        "$TASK" "$attempt" "$MAX_ATTEMPTS" "$status" "$RETRY_SECONDS" >&2
    [ "$attempt" -lt "$MAX_ATTEMPTS" ] && sleep "$RETRY_SECONDS"
done

exit "$status"
