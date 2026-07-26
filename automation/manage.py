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
PUBLIC_ACTIVITY = REPO / "automation" / "public" / "activity.json"
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


def public_run(run_dir: Path) -> dict:
    success = json.loads((run_dir / "SUCCESS.json").read_text(encoding="utf-8"))
    normalized = {
        item["openreview_id"]: item
        for item in json.loads((run_dir / "normalized_results.json").read_text(encoding="utf-8")).get("papers", [])
    }
    papers = []
    for item in (json.loads(line) for line in (run_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()):
        paper = json.loads(Path(item["path"]).read_text(encoding="utf-8"))
        result = normalized.get(item["openreview_id"], {})
        tags = [name for value in result.get("research_tags") or [] if (name := tag_name(value))][:3]
        papers.append({
            "openreview_id": item["openreview_id"],
            "year": item["year"],
            "title": paper.get("title") or item["openreview_id"],
            "primary_topic": paper.get("primary_area") or "unknown",
            "openreview_url": paper.get("openreview_url") or f"https://openreview.net/forum?id={item['openreview_id']}",
            "research_tags": tags,
        })
    return {"date": success["date"], "papers": papers}


def agents_added(registry: dict, start: date, end: date) -> list[dict]:
    membership = {agent_id: group for group, ids in registry["groups"].items() for agent_id in ids}
    return [
        {
            "agent_id": agent_id,
            "display_name": agent["display_name"],
            "display_name_zh": agent["display_name_zh"],
            "group": membership[agent_id],
            "added_on": agent["added_on"],
        }
        for agent_id, agent in sorted(registry["agents"].items())
        if start <= date.fromisoformat(agent["added_on"]) <= end
    ]


def build_activity(state: Path, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    recent_start = as_of - timedelta(days=2)
    current_monday = as_of - timedelta(days=as_of.weekday())
    week_end = current_monday - timedelta(days=1)
    week_start = week_end - timedelta(days=6)
    registry = json.loads((REPO / "agents/reviewer_groups.json").read_text(encoding="utf-8"))
    runs = {}
    for run_dir in successful_runs(state):
        run_date = date.fromisoformat(run_dir.name)
        if recent_start <= run_date <= as_of or week_start <= run_date <= week_end:
            runs[run_date] = public_run(run_dir)

    recent_days = []
    for offset in range(3):
        day = as_of - timedelta(days=offset)
        recent_days.append({
            "date": day.isoformat(),
            "papers": runs.get(day, {}).get("papers", []),
            "agents": agents_added(registry, day, day),
        })

    weekly_papers = [paper for day, run_data in runs.items() if week_start <= day <= week_end for paper in run_data["papers"]]
    weekly_tags = Counter(tag for paper in weekly_papers for tag in paper["research_tags"])
    activity = {
        "generated_on": datetime.now(timezone.utc).isoformat(),
        "recent_days": recent_days,
        "previous_week": {
            "start": week_start.isoformat(),
            "end": week_end.isoformat(),
            "paper_count": len(weekly_papers),
            "by_year": dict(Counter(str(paper["year"]) for paper in weekly_papers)),
            "top_research_tags": [{"tag": tag, "papers": count} for tag, count in weekly_tags.most_common(10)],
            "agents": agents_added(registry, week_start, week_end),
        },
    }
    return activity


def markdown_text(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_daily_activity(activity: dict, chinese: bool) -> str:
    lines = ["## 最近 3 天新增" if chinese else "## New in the Last 3 Days", ""]
    for index, day in enumerate(activity["recent_days"]):
        papers = day["papers"]
        agents = day["agents"]
        if chinese:
            summary = f"{day['date']} - 新分析 {len(papers)} 篇论文，新增 {len(agents)} 个通用 Agent"
        else:
            summary = f"{day['date']} - {len(papers)} newly analyzed papers, {len(agents)} common Agents added"
        lines.append(f"<details{' open' if index == 0 else ''}>")
        lines.append(f"<summary>{summary}</summary>")
        lines.append("")
        if papers:
            lines.extend([
                "| 年份 | 论文 | 主题 | 研究标签 |" if chinese else "| Year | Paper | Topic | Research tags |",
                "|---:|---|---|---|",
            ])
            for paper in papers:
                title = markdown_text(paper["title"])
                topic = markdown_text(paper["primary_topic"])
                tags = markdown_text(", ".join(paper["research_tags"]) or "-")
                lines.append(f"| {paper['year']} | [{title}]({paper['openreview_url']}) | {topic} | {tags} |")
        else:
            lines.append("当天没有公开新增论文。" if chinese else "No public paper additions on this day.")
        if agents:
            label = "新增通用 Agent：" if chinese else "Common Agents added: "
            names = ", ".join(f"`{agent['agent_id']}` ({agent['display_name_zh' if chinese else 'display_name']})" for agent in agents)
            lines.extend(["", label + names])
        lines.extend(["", "</details>", ""])
    return "\n".join(lines).rstrip()


def render_weekly_activity(activity: dict, chinese: bool) -> str:
    week = activity["previous_week"]
    heading = "## 上周新增" if chinese else "## Added Last Week"
    period = f"{week['start']} - {week['end']}"
    if not week["paper_count"] and not week["agents"]:
        message = f"**{period}：** 没有公开新增内容。" if chinese else f"**{period}:** No public additions."
        return f"{heading}\n\n{message}"
    years = ", ".join(f"{year}: {count}" for year, count in sorted(week["by_year"].items())) or "-"
    tags = ", ".join(f"{item['tag']} ({item['papers']})" for item in week["top_research_tags"]) or "-"
    lines = [
        heading,
        "",
        "| 周期 | 新分析论文 | 年份分布 | 高频研究标签 |" if chinese else "| Period | Newly analyzed papers | Year distribution | Top research tags |",
        "|---|---:|---|---|",
        f"| {period} | {week['paper_count']} | {markdown_text(years)} | {markdown_text(tags)} |",
    ]
    if week["agents"]:
        label = "新增通用 Agent：" if chinese else "Common Agents added: "
        names = ", ".join(f"`{agent['agent_id']}`" for agent in week["agents"])
        lines.extend(["", label + names])
    return "\n".join(lines)


def refresh_readmes(state: Path) -> dict:
    progress = weekly(state)
    activity = build_activity(state)
    atomic_write(PUBLIC_ACTIVITY, json.dumps(activity, ensure_ascii=False, indent=2) + "\n")
    registry = json.loads((REPO / "agents/reviewer_groups.json").read_text(encoding="utf-8"))
    for filename, chinese in (("README.md", False), ("README.zh-CN.md", True)):
        path = REPO / filename
        text = path.read_text(encoding="utf-8")
        groups, recent = render_agents(registry, chinese)
        text = replace_block(text, "DAILY_ACTIVITY", render_daily_activity(activity, chinese))
        text = replace_block(text, "WEEKLY_ACTIVITY", render_weekly_activity(activity, chinese))
        text = replace_block(text, "AGENT_GROUPS", groups)
        text = replace_block(text, "RECENT_AGENTS", recent)
        atomic_write(path, text)
    return progress


def publish(command: str) -> None:
    allowed = {"README.md", "README.zh-CN.md", "automation/public/activity.json", "automation/public/progress.json"}
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, check=True, text=True, capture_output=True).stdout.splitlines()
    unexpected = [line for line in dirty if line[3:] not in allowed]
    if unexpected:
        raise RuntimeError(f"refusing automated commit with unrelated changes: {unexpected}")
    run(["git", "add", *sorted(allowed)])
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode != 0
    if changed:
        run(["git", "commit", "-m", f"Update {command} ICLR Reviewer activity ({date.today().isoformat()})"])
        run(["git", "push", "origin", "main"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("daily", "weekly", "monthly"))
    parser.add_argument("--push", action="store_true", help="Commit and push public README and activity updates")
    args = parser.parse_args()
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True)
    with (state / "automation.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        daily_result = daily(state) if args.command == "daily" else None
        result = refresh_readmes(state)
        if args.push:
            publish(args.command)
        if daily_result is not None:
            result = daily_result
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
