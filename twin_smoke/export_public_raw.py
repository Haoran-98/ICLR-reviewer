#!/usr/bin/env python3
"""Export a public title/abstract catalog grouped by ICLR year and topic."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path


YEARS = (2024, 2025, 2026)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("raw"))
    return parser.parse_args()


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def export_year(root: Path, output: Path, year: int) -> dict:
    records = []
    seen = set()
    for path in sorted((root / str(year)).rglob("*.json")):
        paper = json.loads(path.read_text(encoding="utf-8"))
        if paper.get("track") != "main":
            continue
        paper_id = clean_text(paper.get("openreview_id"))
        if not paper_id or paper_id in seen:
            raise ValueError(f"missing or duplicate OpenReview ID: {path}")
        seen.add(paper_id)
        records.append({
            "year": year,
            "topic": clean_text(paper.get("primary_area")) or clean_text(paper.get("area_dir")) or "unknown",
            "topic_slug": clean_text(paper.get("area_dir")) or "unknown",
            "title": clean_text(paper.get("title")),
            "abstract": clean_text(paper.get("abstract")),
            "keywords": paper.get("keywords") if isinstance(paper.get("keywords"), list) else [],
            "openreview_id": paper_id,
            "openreview_url": clean_text(paper.get("openreview_url")),
        })

    year_dir = output / str(year)
    topic_dir = year_dir / "topics"
    topic_dir.mkdir(parents=True, exist_ok=True)
    index_path = year_dir / "papers.jsonl.gz"
    with index_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            for record in sorted(records, key=lambda item: (item["topic_slug"], item["title"].casefold())):
                compressed.write((json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode())

    grouped = defaultdict(list)
    for record in records:
        grouped[record["topic_slug"]].append(record)

    topics = []
    for slug, papers in sorted(grouped.items()):
        display_name = papers[0]["topic"]
        topic_path = topic_dir / f"{slug}.md"
        lines = [f"# ICLR {year}: {html.escape(display_name)}", "", f"论文数：{len(papers)}", ""]
        for paper in sorted(papers, key=lambda item: item["title"].casefold()):
            lines.extend([
                f"## {html.escape(paper['title'])}",
                "",
                f"OpenReview: {paper['openreview_url']}",
                "",
                html.escape(paper["abstract"]),
                "",
            ])
        topic_path.write_text("\n".join(lines), encoding="utf-8")
        topics.append({"topic": display_name, "slug": slug, "papers": len(papers), "file": f"topics/{slug}.md"})

    readme = [f"# ICLR {year}", "", f"主会论文数：{len(records)}", "", "| 主题 | 论文数 | 题目与摘要 |", "|---|---:|---|"]
    for topic in topics:
        readme.append(f"| {topic['topic']} | {topic['papers']} | [查看]({topic['file']}) |")
    readme.extend(["", "机器可读索引：[`papers.jsonl.gz`](papers.jsonl.gz)", ""])
    (year_dir / "README.md").write_text("\n".join(readme), encoding="utf-8")

    payload = index_path.read_bytes()
    return {
        "year": year,
        "papers": len(records),
        "topics": topics,
        "index_file": f"{year}/papers.jsonl.gz",
        "index_bytes": len(payload),
        "index_sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for child in args.output.iterdir():
        if child.name != "README.md":
            shutil.rmtree(child) if child.is_dir() else child.unlink()

    years = [export_year(args.input, args.output, year) for year in YEARS]
    manifest = {
        "schema_version": "2.0",
        "generated_on": date.today().isoformat(),
        "scope": "ICLR 2024-2026 main-track title and abstract catalog; Workshops excluded",
        "fields": ["year", "topic", "topic_slug", "title", "abstract", "keywords", "openreview_id", "openreview_url"],
        "years": years,
        "total_papers": sum(item["papers"] for item in years),
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"exported {manifest['total_papers']} title/abstract records")


if __name__ == "__main__":
    main()
