#!/usr/bin/env python3
"""Install or replace the current user's ICLR Reviewer cron schedule."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
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

    env = (
        f"ICLR_REVIEWS_ROOT={shlex.quote(str(args.reviews_root.resolve()))} "
        f"ICLR_AUTH_FILE={shlex.quote(str(args.auth_file.resolve()))} "
        f"ICLR_REVIEWER_STATE={shlex.quote(str(args.state_dir.resolve()))}"
    )
    base = f"cd {shlex.quote(str(repo))} && {env} {shlex.quote(sys.executable)} automation/manage.py"
    log = shlex.quote(str((args.state_dir / "automation.log").resolve()))
    block = [
        START,
        f"15 2 * * * {base} daily >> {log} 2>&1",
        f"15 3 * * 0 {base} weekly >> {log} 2>&1",
        f"15 4 1 * * {base} monthly --push >> {log} 2>&1",
        END,
    ]
    payload = "\n".join([*kept, *block]).strip() + "\n"
    subprocess.run(["crontab", "-"], input=payload, text=True, check=True)
    print("installed daily, weekly, and monthly ICLR Reviewer jobs")


if __name__ == "__main__":
    main()
