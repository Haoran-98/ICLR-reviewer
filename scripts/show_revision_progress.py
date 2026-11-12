#!/usr/bin/env python3
"""Show OpenReview revision-backfill status and completion progress."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from .deployment_paths import DB_STATE, OPENREVIEW_TOKEN
except ImportError:
    from deployment_paths import DB_STATE, OPENREVIEW_TOKEN
from typing import Any


STATE_DIR = DB_STATE
CHECKPOINT = STATE_DIR / "revision_backfill_checkpoint.json"
REPORT = STATE_DIR / "revision_backfill_report.json"
LOG = STATE_DIR / "revision_backfill.log"
TOKEN_FILE = OPENREVIEW_TOKEN
DATABASE_URL = os.environ.get(
    "ICLR_DATABASE_URL", "host=127.0.0.1 port=55432 dbname=iclr_reviewer"
)
RENEW_COMMAND = "python3 scripts/get_openreview_token_with_code.py"
BACKFILL_MARKER = "database/iclr_database.py revision-backfill"
CRON_MARKER = "iclr_database.py revision-backfill"
PAGE_SIZE = 1_000
PAGES_PER_BATCH = 16

# Totals returned by the OpenReview conference-domain edit endpoint when this
# backfill was initialized. They make the monitor read-only and rate-limit free.
YEAR_TOTALS = {2024: 159_508, 2025: 324_902, 2026: 395_224}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def iso_timestamp(epoch: int | float | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).astimezone().isoformat(timespec="seconds")


def token_status(now: float) -> dict[str, Any]:
    result: dict[str, Any] = {"state": "missing", "path": str(TOKEN_FILE)}
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        issued = int(claims.get("iat") or 0)
        expires = int(claims.get("exp") or 0)
        remaining = expires - int(now)
        if remaining <= 0:
            state = "expired"
        elif remaining <= 3600:
            state = "renewal_due"
        else:
            state = "valid"
        result.update({
            "state": state,
            "issued_at": iso_timestamp(issued),
            "expires_at": iso_timestamp(expires),
            "remaining_seconds": remaining,
        })
    except (OSError, IndexError, ValueError, json.JSONDecodeError):
        if TOKEN_FILE.exists():
            result["state"] = "invalid"
    return result


def active_process() -> dict[str, Any]:
    for cmdline_path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            command = cmdline_path.read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            if BACKFILL_MARKER not in command:
                continue
            pid = int(cmdline_path.parent.name)
            fields = (cmdline_path.parent / "stat").read_text().split()
            started_ticks = int(fields[21])
            uptime = float(Path("/proc/uptime").read_text().split()[0])
            elapsed = max(0, int(uptime - started_ticks / os.sysconf("SC_CLK_TCK")))
            return {"running": True, "pid": pid, "elapsed_seconds": elapsed, "command": command}
        except (OSError, ValueError, IndexError):
            continue
    return {"running": False, "pid": None, "elapsed_seconds": None, "command": None}


def cron_status() -> dict[str, Any]:
    try:
        text = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=5, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        text = ""
    line = next(
        (line.strip() for line in text.splitlines() if CRON_MARKER in line and not line.lstrip().startswith("#")),
        None,
    )
    return {"enabled": line is not None, "entry": line}


def database_counts() -> dict[str, Any]:
    try:
        import psycopg

        with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT count(*), count(DISTINCT note_id)
                FROM raw.openreview_edit
            """)
            stored, note_ids = cur.fetchone()
            cur.execute("""
                SELECT count(*) FROM raw.openreview_revision_probe WHERE status='success'
            """)
            probes = cur.fetchone()[0]
            cur.execute("""
                SELECT count(*) FROM (
                    SELECT review_id FROM core.review_revision
                    GROUP BY review_id HAVING count(*) > 1
                ) revisions
            """)
            multi_revision = cur.fetchone()[0]
        return {
            "available": True,
            "stored_edit_envelopes": int(stored),
            "distinct_review_note_ids": int(note_ids),
            "successful_revision_probes": int(probes),
            "multi_revision_reviews": int(multi_revision),
        }
    except Exception as error:  # Monitoring must still work when PostgreSQL is down.
        return {"available": False, "error": f"{type(error).__name__}: {error}"}


def recent_error() -> str | None:
    try:
        with LOG.open("rb") as handle:
            handle.seek(max(0, LOG.stat().st_size - 64 * 1024))
            lines = handle.read().decode(errors="replace").splitlines()
    except OSError:
        return None
    return next(
        (line.strip() for line in reversed(lines) if line.strip().startswith(("RuntimeError:", "OpenReviewException:"))),
        None,
    )


def collect() -> dict[str, Any]:
    now = time.time()
    checkpoint = load_json(CHECKPOINT, {"years": {}})
    report = load_json(REPORT, {})
    process = active_process()
    cron = cron_status()
    token = token_status(now)
    years: dict[str, Any] = {}
    processed_total = 0
    latest_update = None

    for year, total in YEAR_TOTALS.items():
        state = checkpoint.get("years", {}).get(str(year), {})
        processed = min(int(state.get("edits_seen") or 0), total)
        processed_total += processed
        latest_update = max(filter(None, (latest_update, state.get("updated_at"), state.get("completed_at"))), default=None)
        years[str(year)] = {
            "processed_edits": processed,
            "total_edits": total,
            "percent": round(processed * 100 / total, 2),
            "pages": int(state.get("pages") or 0),
            "complete": bool(state.get("complete")),
            "updated_at": state.get("updated_at"),
        }

    grand_total = sum(YEAR_TOTALS.values())
    remaining = grand_total - processed_total
    pages_remaining = math.ceil(remaining / PAGE_SIZE)
    batches_remaining = math.ceil(pages_remaining / PAGES_PER_BATCH)
    complete = all(item["complete"] for item in years.values())
    if complete:
        status, detail, action = "complete", "All conference years are complete.", None
    elif process["running"]:
        status, detail, action = "running", "A revision-backfill process is active.", None
    elif token["state"] in {"missing", "invalid", "expired", "renewal_due"}:
        status = "blocked"
        detail = f"OpenReview token state: {token['state']}."
        action = RENEW_COMMAND
    elif cron["enabled"]:
        status, detail, action = "waiting", "Waiting for the next hourly cron batch.", None
    else:
        status = "stopped"
        detail = "No active process and no enabled revision-backfill cron entry."
        action = "python3 database/iclr_database.py revision-backfill"

    return {
        "generated_at": iso_timestamp(now),
        "status": status,
        "detail": detail,
        "action": action,
        "process": process,
        "cron": cron,
        "token": token,
        "years": years,
        "overall": {
            "processed_edits": processed_total,
            "total_edits": grand_total,
            "remaining_edits": remaining,
            "percent": round(processed_total * 100 / grand_total, 2),
        },
        "estimate": {
            "pages_remaining": pages_remaining,
            "hourly_batches_remaining": batches_remaining,
            "hours_after_resume": batches_remaining,
            "basis": f"{PAGES_PER_BATCH} pages/hour, {PAGE_SIZE} edits/page",
        },
        "database": database_counts(),
        "latest_batch_at": report.get("generated_at") or latest_update,
        "recent_error": recent_error(),
        "paths": {"checkpoint": str(CHECKPOINT), "log": str(LOG), "report": str(REPORT)},
    }


def duration(seconds: int | None) -> str:
    if seconds is None:
        return "n/a"
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{sign}{hours}h {minutes:02d}m {seconds:02d}s"


def progress_bar(percent: float, width: int = 30) -> str:
    filled = min(width, max(0, round(percent * width / 100)))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def render(data: dict[str, Any]) -> str:
    overall = data["overall"]
    lines = [
        f"ICLR revision backfill | {data['generated_at']}",
        f"STATUS: {data['status'].upper()} - {data['detail']}",
        f"OVERALL {progress_bar(overall['percent'])} {overall['percent']:.2f}% "
        f"({overall['processed_edits']:,}/{overall['total_edits']:,})",
    ]
    for year, item in data["years"].items():
        suffix = "complete" if item["complete"] else "pending"
        lines.append(
            f"  {year} {progress_bar(item['percent'], 20)} {item['percent']:6.2f}% "
            f"({item['processed_edits']:,}/{item['total_edits']:,}) {suffix}"
        )
    process = data["process"]
    token = data["token"]
    estimate = data["estimate"]
    lines.extend([
        f"PROCESS: {'running' if process['running'] else 'not running'}"
        + (f" | PID {process['pid']} | elapsed {duration(process['elapsed_seconds'])}" if process["running"] else ""),
        f"CRON: {'enabled' if data['cron']['enabled'] else 'disabled'}",
        f"TOKEN: {token['state']} | expires {token.get('expires_at') or 'n/a'} | "
        f"remaining {duration(token.get('remaining_seconds'))}",
        f"ETA AFTER RESUME: ~{estimate['hourly_batches_remaining']} hourly batches "
        f"(~{estimate['hours_after_resume']} h; normalization follows)",
    ])
    database = data["database"]
    if database["available"]:
        lines.append(
            "DATABASE: "
            f"{database['stored_edit_envelopes']:,} stored edits | "
            f"{database['distinct_review_note_ids']:,} review notes | "
            f"{database['multi_revision_reviews']:,} multi-revision reviews | "
            f"{database['successful_revision_probes']:,} probes"
        )
    else:
        lines.append(f"DATABASE: unavailable | {database['error']}")
    lines.append(f"LATEST BATCH: {data['latest_batch_at'] or 'n/a'}")
    if data["recent_error"]:
        lines.append(f"RECENT ERROR: {data['recent_error']}")
    if data["action"]:
        lines.append(f"ACTION: {data['action']}")
    lines.extend([
        f"CHECKPOINT: {data['paths']['checkpoint']}",
        f"LOG: {data['paths']['log']}",
    ])
    return "\n".join(lines)


def self_test() -> None:
    assert progress_bar(0, 4) == "[----]"
    assert progress_bar(50, 4) == "[##--]"
    assert progress_bar(100, 4) == "[####]"
    assert duration(3661) == "1h 01m 01s"
    assert sum(YEAR_TOTALS.values()) == 879_634
    print("self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--watch", type=float, metavar="SECONDS", help="refresh continuously")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    try:
        while True:
            data = collect()
            output = json.dumps(data, ensure_ascii=False, indent=2) if args.json else render(data)
            if args.watch and os.isatty(1):
                print("\033[2J\033[H", end="")
            print(output, flush=True)
            if not args.watch:
                return
            time.sleep(max(1, args.watch))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
