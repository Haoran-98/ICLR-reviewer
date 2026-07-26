#!/usr/bin/env python3
"""Run daily extraction, weekly integration, and monthly README updates."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TWIN = REPO / "twin_smoke"
PUBLIC_PROGRESS = REPO / "automation" / "public" / "progress.json"
YEARS = (2024, 2025, 2026)
DAILY_RATE = 0.0005
GROUP_LABELS = {
    "orchestration": ("Orchestration", "编排"),
    "core_reviewers": ("Core reviewers", "核心审稿组"),
    "extended_reviewers": ("Extended reviewers", "扩展审稿组"),
    "decision_and_audit": ("Decision and audit", "决策与审计"),
}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def run(command: list[str], cwd: Path = REPO) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def state_dir() -> Path:
    return Path(os.environ.get("ICLR_REVIEWER_STATE", Path.home() / ".local/state/iclr-reviewer"))


def reviews_root() -> Path:
    return Path(os.environ.get("ICLR_REVIEWS_ROOT", "data/iclr_reviews")).expanduser().resolve()


def auth_file() -> Path:
    return Path(os.environ.get("ICLR_AUTH_FILE", Path.home() / "auth")).expanduser().resolve()


def load_inventory(state: Path) -> list[dict]:
    path = state / "inventory.jsonl"
    if path.exists():
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    root = reviews_root()
    records = []
    seen = set()
    for year in YEARS:
        for paper_path in sorted((root / str(year)).rglob("*.json")):
            if paper_path.name == "index.json":
                continue
            paper = json.loads(paper_path.read_text(encoding="utf-8"))
            if paper.get("track") != "main":
                continue
            paper_id = paper.get("openreview_id") or paper.get("forum")
            if not paper_id or paper_id in seen:
                raise ValueError(f"missing or duplicate OpenReview ID: {paper_path}")
            seen.add(paper_id)
            records.append({"openreview_id": paper_id, "year": year, "path": str(paper_path)})
    records.sort(key=lambda item: (item["year"], hashlib.sha256(item["openreview_id"].encode()).hexdigest()))
    atomic_write(path, "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records))
    return records


def successful_runs(state: Path) -> list[Path]:
    return sorted(path.parent for path in (state / "daily").glob("*/SUCCESS.json"))


def allocate(records: list[dict], count: int) -> list[dict]:
    if not records or count <= 0:
        return []
    grouped = defaultdict(list)
    for record in records:
        grouped[record["year"]].append(record)
    total = len(records)
    exact = {year: count * len(items) / total for year, items in grouped.items()}
    quotas = {year: math.floor(value) for year, value in exact.items()}
    for year in sorted(grouped, key=lambda value: exact[value] - quotas[value], reverse=True)[: count - sum(quotas.values())]:
        quotas[year] += 1
    return [item for year in sorted(grouped) for item in grouped[year][: quotas[year]]]


def daily(state: Path) -> dict:
    today = date.today().isoformat()
    run_dir = state / "daily" / today
    success_path = run_dir / "SUCCESS.json"
    if success_path.exists():
        return json.loads(success_path.read_text(encoding="utf-8"))

    inventory = load_inventory(state)
    processed_path = state / "processed_ids.txt"
    if processed_path.exists():
        processed = set(processed_path.read_text(encoding="utf-8").splitlines())
    else:
        baseline = TWIN / "output" / "one_percent_main_luna_normalized_results.json"
        payload = json.loads(baseline.read_text(encoding="utf-8")) if baseline.exists() else {"papers": []}
        processed = {item["openreview_id"] for item in payload.get("papers", [])}
        atomic_write(processed_path, "\n".join(sorted(processed)) + ("\n" if processed else ""))
    remaining = [item for item in inventory if item["openreview_id"] not in processed]
    if not remaining:
        return {"date": today, "status": "complete", "papers": 0}
    run_number = len(successful_runs(state))
    previous_target = round(len(inventory) * DAILY_RATE * run_number)
    next_target = round(len(inventory) * DAILY_RATE * (run_number + 1))
    count = min(len(remaining), max(1, next_target - previous_target))
    selected = allocate(remaining, count)
    if not selected:
        return {"date": today, "status": "complete", "papers": 0}

    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    manifest = run_dir / "manifest.jsonl"
    rows = [
        {
            "path": item["path"],
            "openreview_id": item["openreview_id"],
            "year": item["year"],
            "track_group": "main",
            "track": "main",
        }
        for item in selected
    ]
    atomic_write(manifest, "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows))

    filtered = run_dir / "filtered"
    api_output = run_dir / "api_luna"
    run([sys.executable, "python_filter.py", "--manifest", str(manifest), "--output", str(filtered), "--batch-tokens", "90000"], TWIN)
    run([
        sys.executable,
        "run_api_smoke.py",
        "--auth",
        str(auth_file()),
        "--input-dir",
        str(filtered / "batches"),
        "--output-dir",
        str(api_output),
        "--max-output-tokens",
        "16000",
        "--resume",
    ], TWIN)
    run([
        sys.executable,
        "validate_results.py",
        "--input-dir",
        str(api_output),
        "--manifest",
        str(filtered / "main_sample_manifest.jsonl"),
        "--local-records",
        str(filtered / "local_records.json"),
        "--output-dir",
        str(run_dir),
    ], TWIN)
    qa = json.loads((run_dir / "qa_report.json").read_text(encoding="utf-8"))
    if qa.get("errors"):
        raise RuntimeError(f"daily QA failed: {qa['errors']}")

    usage = Counter()
    summary_path = api_output / "summary.json"
    if summary_path.exists():
        for item in json.loads(summary_path.read_text(encoding="utf-8")).get("runs", []):
            usage.update({key: value for key, value in (item.get("usage") or {}).items() if isinstance(value, (int, float))})
    result = {
        "date": today,
        "status": "success",
        "papers": len(selected),
        "by_year": dict(Counter(str(item["year"]) for item in selected)),
        "model": "OPENAI_WEAK_MODEL_ID",
        "usage": dict(usage),
    }
    atomic_write(success_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    processed.update(item["openreview_id"] for item in selected)
    atomic_write(processed_path, "\n".join(sorted(processed)) + "\n")
    return result


def tag_name(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("tag", "name", "value", "domain", "method"):
            if value.get(key):
                return str(value[key]).strip()
    return ""


def weekly(state: Path) -> dict:
    inventory = load_inventory(state)
    items_by_id = {}
    year_by_id = {item["openreview_id"]: item["year"] for item in inventory}
    usage = Counter()
    last_run = None
    baseline_results = TWIN / "output" / "one_percent_main_luna_normalized_results.json"
    baseline_manifest = TWIN / "output" / "one_percent" / "main_filtered" / "main_sample_manifest.jsonl"
    if baseline_results.exists():
        for item in json.loads(baseline_results.read_text(encoding="utf-8")).get("papers", []):
            items_by_id[item["openreview_id"]] = item
    if baseline_manifest.exists():
        for item in (json.loads(line) for line in baseline_manifest.read_text(encoding="utf-8").splitlines()):
            year_by_id[item["openreview_id"]] = item["year"]
    for run_dir in successful_runs(state):
        success = json.loads((run_dir / "SUCCESS.json").read_text(encoding="utf-8"))
        usage.update({key: value for key, value in (success.get("usage") or {}).items() if isinstance(value, (int, float))})
        last_run = success.get("date")
        manifest = [json.loads(line) for line in (run_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
        year_by_id.update({item["openreview_id"]: item["year"] for item in manifest})
        payload = json.loads((run_dir / "normalized_results.json").read_text(encoding="utf-8"))
        for item in payload.get("papers", []):
            items_by_id[item["openreview_id"]] = item

    integrated = state / "integrated" / "normalized_results.jsonl"
    atomic_write(integrated, "".join(json.dumps(items_by_id[key], ensure_ascii=False) + "\n" for key in sorted(items_by_id)))

    tags = Counter()
    effectiveness = Counter()
    score_actions = Counter()
    for item in items_by_id.values():
        tags.update(name for value in item.get("research_tags") or [] if (name := tag_name(value)))
        for outcome in item.get("response_outcomes") or []:
            effectiveness[outcome.get("effectiveness") or "unknown"] += 1
            score_actions[outcome.get("score_action") or "unknown"] += 1
    progress = {
        "generated_on": datetime.now(timezone.utc).isoformat(),
        "daily_rate_percent": DAILY_RATE * 100,
        "corpus_papers": len(inventory),
        "successful_daily_runs": len(successful_runs(state)),
        "analyzed_papers": len(items_by_id),
        "coverage_percent": round(len(items_by_id) / len(inventory) * 100, 4),
        "by_year": dict(Counter(str(year_by_id[key]) for key in items_by_id)),
        "last_daily_run": last_run,
        "usage": dict(usage),
        "top_research_tags": [{"tag": key, "papers": value} for key, value in tags.most_common(20)],
        "response_effectiveness": dict(effectiveness),
        "score_actions": dict(score_actions),
    }
    atomic_write(PUBLIC_PROGRESS, json.dumps(progress, ensure_ascii=False, indent=2) + "\n")
    return progress


def replace_block(text: str, name: str, content: str) -> str:
    start = f"<!-- {name}:START -->"
    end = f"<!-- {name}:END -->"
    if start not in text or end not in text:
        raise ValueError(f"README markers missing: {name}")
    before, remainder = text.split(start, 1)
    _, after = remainder.split(end, 1)
    return before + start + "\n" + content.rstrip() + "\n" + end + after


def render_agents(registry: dict, chinese: bool) -> tuple[str, str]:
    agents = registry["agents"]
    rows = ["| Group | Agent | Purpose | Added |", "|---|---|---|---|"] if not chinese else ["| 分组 | Agent | 作用 | 加入日期 |", "|---|---|---|---|"]
    for group, ids in registry["groups"].items():
        label = GROUP_LABELS[group][1 if chinese else 0]
        for agent_id in ids:
            agent = agents[agent_id]
            rows.append(f"| {label} | `{agent_id}` ({agent['display_name_zh' if chinese else 'display_name']}) | {agent['description_zh' if chinese else 'description']} | {agent['added_on']} |")

    cutoff = date.today() - timedelta(days=30)
    recent = [(agent_id, agent) for agent_id, agent in agents.items() if date.fromisoformat(agent["added_on"]) >= cutoff]
    recent_rows = ["| Agent | Group | Added |", "|---|---|---|"] if not chinese else ["| Agent | 分组 | 加入日期 |", "|---|---|---|"]
    membership = {agent_id: group for group, ids in registry["groups"].items() for agent_id in ids}
    for agent_id, agent in sorted(recent, key=lambda item: (item[1]["added_on"], item[0]), reverse=True):
        label = GROUP_LABELS[membership[agent_id]][1 if chinese else 0]
        recent_rows.append(f"| `{agent_id}` ({agent['display_name_zh' if chinese else 'display_name']}) | {label} | {agent['added_on']} |")
    if not recent:
        recent_rows.append("| No common agents added in the last 30 days | - | - |" if not chinese else "| 最近 30 天没有新增通用 Agent | - | - |")
    return "\n".join(rows), "\n".join(recent_rows)


def render_progress(progress: dict, chinese: bool) -> str:
    if not progress:
        return "No scheduled extraction has completed yet." if not chinese else "自动提取尚未完成首个批次。"
    tokens = progress.get("usage", {}).get("total_tokens", 0)
    if chinese:
        return (
            f"| 指标 | 当前值 |\n|---|---:|\n"
            f"| 每日目标 | {progress['daily_rate_percent']:.2f}% |\n"
            f"| 成功日批次 | {progress['successful_daily_runs']} |\n"
            f"| 已分析论文 | {progress['analyzed_papers']} / {progress['corpus_papers']} |\n"
            f"| 深度分析覆盖率 | {progress['coverage_percent']:.4f}% |\n"
            f"| 累计 tokens | {tokens:,} |\n"
            f"| 最近日批次 | {progress.get('last_daily_run') or 'N/A'} |"
        )
    return (
        f"| Metric | Current value |\n|---|---:|\n"
        f"| Daily target | {progress['daily_rate_percent']:.2f}% |\n"
        f"| Successful daily batches | {progress['successful_daily_runs']} |\n"
        f"| Analyzed papers | {progress['analyzed_papers']} / {progress['corpus_papers']} |\n"
        f"| Deep-analysis coverage | {progress['coverage_percent']:.4f}% |\n"
        f"| Cumulative tokens | {tokens:,} |\n"
        f"| Latest daily batch | {progress.get('last_daily_run') or 'N/A'} |"
    )


def monthly(state: Path, push: bool) -> dict:
    progress = weekly(state)
    registry = json.loads((REPO / "agents/reviewer_groups.json").read_text(encoding="utf-8"))
    for filename, chinese in (("README.md", False), ("README.zh-CN.md", True)):
        path = REPO / filename
        text = path.read_text(encoding="utf-8")
        groups, recent = render_agents(registry, chinese)
        text = replace_block(text, "AGENT_GROUPS", groups)
        text = replace_block(text, "RECENT_AGENTS", recent)
        text = replace_block(text, "AUTOMATION_PROGRESS", render_progress(progress, chinese))
        atomic_write(path, text)

    if push:
        allowed = {"README.md", "README.zh-CN.md", "automation/public/progress.json"}
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, check=True, text=True, capture_output=True).stdout.splitlines()
        unexpected = [line for line in dirty if line[3:] not in allowed]
        if unexpected:
            raise RuntimeError(f"refusing monthly commit with unrelated changes: {unexpected}")
        run(["git", "add", *sorted(allowed)])
        changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode != 0
        if changed:
            run(["git", "commit", "-m", f"Update monthly agent and extraction summary ({date.today().isoformat()})"])
            run(["git", "push", "origin", "main"])
    return progress


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("daily", "weekly", "monthly"))
    parser.add_argument("--push", action="store_true", help="Commit and push monthly README updates")
    args = parser.parse_args()
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True)
    with (state / "automation.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = daily(state) if args.command == "daily" else weekly(state) if args.command == "weekly" else monthly(state, args.push)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
