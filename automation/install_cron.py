#!/usr/bin/env python3
"""Install or replace the current user's ICLR Reviewer cron schedule."""

from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path


START = "# BEGIN ICLR REVIEWER AUTOMATION"
END = "# END ICLR REVIEWER AUTOMATION"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviews-root", type=Path, required=True)
    parser.add_argument("--auth-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".local/state/iclr-reviewer")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    args.state_dir.mkdir(parents=True, exist_ok=True)
    current = subprocess.run(["crontab", "-l"], text=True, capture_output=True).stdout.splitlines()
    kept = []
    skipping = False
    for line in current:
        if line == START:
            skipping = True
            continue
        if line == END:
            skipping = False
            continue
        if not skipping:
            kept.append(line)

    retry = shlex.quote(str((repo / "automation" / "run_with_retry.sh").resolve()))
    log = shlex.quote(str((args.state_dir / "automation.log").resolve()))
    block = [
        START,
        "CRON_TZ=Asia/Shanghai",
        f"15 2 * * * ICLR_AUTH_FILE={shlex.quote(str(args.auth_file.resolve()))} ICLR_REVIEWS_ROOT={shlex.quote(str(args.reviews_root.resolve()))} ICLR_REVIEWER_STATE={shlex.quote(str(args.state_dir.resolve()))} {retry} daily >> {log} 2>&1",
        f"15 3 * * 0 ICLR_AUTH_FILE={shlex.quote(str(args.auth_file.resolve()))} ICLR_REVIEWS_ROOT={shlex.quote(str(args.reviews_root.resolve()))} ICLR_REVIEWER_STATE={shlex.quote(str(args.state_dir.resolve()))} {retry} weekly >> {log} 2>&1",
        f"15 4 1 * * ICLR_AUTH_FILE={shlex.quote(str(args.auth_file.resolve()))} ICLR_REVIEWS_ROOT={shlex.quote(str(args.reviews_root.resolve()))} ICLR_REVIEWER_STATE={shlex.quote(str(args.state_dir.resolve()))} {retry} monthly >> {log} 2>&1",
        END,
    ]
    payload = "\n".join([*kept, *block]).strip() + "\n"
    subprocess.run(["crontab", "-"], input=payload, text=True, check=True)
    print("installed daily, weekly, and monthly ICLR Reviewer jobs")


if __name__ == "__main__":
    main()
