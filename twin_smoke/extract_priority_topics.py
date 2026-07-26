#!/usr/bin/env python3
"""Extract main-track Agent and Education papers with deterministic rules."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter
from pathlib import Path


AGENT_CORE = {
    "agentic_ai": r"\bagentic\b",
    "llm_agent": r"\b(?:llm|large language model|language model)[- ]?(?:based[- ]?)?agents?\b|\bagents? (?:powered|driven) by (?:llms?|language models?)\b",
    "autonomous_agent": r"\bautonomous (?:ai )?agents?\b",
    "tool_agent": r"\b(?:tool[- ]using|tool[- ]augmented|web|browser|gui|computer[- ]use|software|coding|research) agents?\b",
    "agent_memory": r"\bagent(?:ic)? (?:memory|planning|reasoning|workflow|framework|architecture|evaluation|benchmark)\b",
}
AGENT_ADJACENT = {
    "multi_agent": r"\bmulti[- ]?agents?\b|\bmultiple agents?\b",
    "embodied_agent": r"\bembodied agents?\b",
    "conversational_agent": r"\bconversational agents?\b",
    "collaborative_agent": r"\bcollaborative agents?\b|\bagent collaboration\b",
    "agent_simulation": r"\bagent[- ]based (?:simulation|model(?:ing)?)\b",
}
EDUCATION_CORE = {
    "education": r"\beducation(?:al)?\b|\blearning sciences?\b",
    "tutoring": r"\b(?:intelligent |ai[- ]based |personalized )?tutor(?:ing|s)?\b",
    "pedagogy": r"\bpedagog(?:y|ical|ically)\b|\bclassroom\b|\b(?:school|course|educational) curricul(?:um|a)\b",
    "learning_analytics": r"\blearning analytics\b|\bknowledge tracing\b|\bstudent modeling\b",
}
EDUCATION_ADJACENT = {
    "student_learning": r"\bstudent (?:learning|performance|knowledge|engagement|feedback|assessment|reasoning|solution|writing|code)\b|\blearner (?:performance|engagement|feedback|modeling)\b",
    "teaching_support": r"\bteaching assistant\b|\bteacher (?:feedback|support|intervention|assessment)\b",
    "assessment_grading": r"\b(?:automated|automatic|student|answer|essay) grading\b|\bstudent assessment\b|\bgrade student\b|\bfeedback (?:for|on) (?:students?|learners?|essays?|student writing|student code|answers?)\b",
    "personalized_learning": r"\bpersonalized (?:education|tutoring|learning (?:path|experience|content|system|platform))\b|\badaptive (?:education|tutoring|instruction)\b",
    "misconception": r"\b(?:student|learner|mathematical) misconceptions?\b|\bmisconception detection\b",
}
GENERIC_AGENT = re.compile(r"\bagents?\b", re.I)
DISTILLATION = re.compile(
    r"\bknowledge distillation\b|\bteacher[- ]student (?:network|model|framework|training)\b|"
    r"\bstudent (?:network|model)\b|\bteacher model\b",
    re.I,
)
EDUCATION_CONTEXT = re.compile(
    r"\beducation(?:al)?\b|\btutor(?:ing|s)?\b|\bclassroom\b|\bschool\b|"
    r"\bstudents?\b|\blearners?\b|\bteaching\b|\binstructional\b|"
    r"\bgrading\b|\bstudent assessment\b|\blearning environment\b",
    re.I,
)


def matches(text: str, patterns: dict[str, str]) -> list[str]:
    return [tag for tag, pattern in patterns.items() if re.search(pattern, text, re.I)]


def classify(paper: dict) -> dict:
    keywords = paper.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    title = str(paper.get("title") or "")
    keyword_text = " || ".join(map(str, keywords))
    body = " || ".join(str(value or "") for value in (paper.get("abstract"), paper.get("tldr"), paper.get("primary_area")))
    text = f"{title} || {keyword_text} || {body}"

    agent_core_title = matches(title, AGENT_CORE)
    agent_core_keywords = matches(keyword_text, AGENT_CORE)
    agent_core_body = matches(body, AGENT_CORE)
    agent_adjacent_title = matches(title, AGENT_ADJACENT)
    agent_adjacent_keywords = matches(keyword_text, AGENT_ADJACENT)
    agent_adjacent_body = matches(body, AGENT_ADJACENT)
    agent_core = sorted(set(agent_core_title + agent_core_keywords + agent_core_body))
    agent_adjacent = sorted(set(agent_adjacent_title + agent_adjacent_keywords + agent_adjacent_body))
    agent_core_score = 5 * len(agent_core_title) + 3 * len(agent_core_keywords) + len(agent_core_body)
    agent_adjacent_score = 3 * len(agent_adjacent_title) + 2 * len(agent_adjacent_keywords) + len(agent_adjacent_body)

    education_core_title = matches(title, EDUCATION_CORE)
    education_core_keywords = matches(keyword_text, EDUCATION_CORE)
    education_core_body = matches(body, EDUCATION_CORE)
    education_adjacent_title = matches(title, EDUCATION_ADJACENT)
    education_adjacent_keywords = matches(keyword_text, EDUCATION_ADJACENT)
    education_adjacent_body = matches(body, EDUCATION_ADJACENT)
    education_core = sorted(set(education_core_title + education_core_keywords + education_core_body))
    education_adjacent = sorted(set(education_adjacent_title + education_adjacent_keywords + education_adjacent_body))
    has_education_context = bool(EDUCATION_CONTEXT.search(text))
    if not has_education_context:
        for tag in ("learning_analytics", "pedagogy"):
            education_core_title = [value for value in education_core_title if value != tag]
            education_core_keywords = [value for value in education_core_keywords if value != tag]
            education_core_body = [value for value in education_core_body if value != tag]
            education_core = [value for value in education_core if value != tag]
        education_adjacent_body = []
        education_adjacent = sorted(set(education_adjacent_title + education_adjacent_keywords))
    if DISTILLATION.search(text) and not ({"education", "tutoring"} & set(education_core)):
        education_core_title = [value for value in education_core_title if value not in {"learning_analytics", "pedagogy"}]
        education_core_keywords = [value for value in education_core_keywords if value not in {"learning_analytics", "pedagogy"}]
        education_core_body = [value for value in education_core_body if value not in {"learning_analytics", "pedagogy"}]
        education_core = [value for value in education_core if value not in {"learning_analytics", "pedagogy"}]
    education_core_score = 5 * len(education_core_title) + 3 * len(education_core_keywords) + len(education_core_body)
    education_adjacent_score = 3 * len(education_adjacent_title) + 2 * len(education_adjacent_keywords) + len(education_adjacent_body)

    agent_tier = (
        "core" if agent_core_score >= 2 else
        "adjacent" if agent_adjacent_score >= 2 else
        "generic" if agent_core or agent_adjacent or GENERIC_AGENT.search(text) else None
    )
    education_tier = (
        "core" if education_core_score >= 2 else
        "adjacent" if education_adjacent_score >= 2 else
        "generic" if education_core or education_adjacent else None
    )
    if education_tier in {"adjacent", "generic"} and DISTILLATION.search(text):
        education_tier = None
        education_adjacent = []

    return {
        "agent_tier": agent_tier,
        "agent_tags": agent_core + agent_adjacent,
        "agent_relevance_score": agent_core_score + agent_adjacent_score,
        "education_tier": education_tier,
        "education_tags": education_core + education_adjacent,
        "education_relevance_score": education_core_score + education_adjacent_score,
    }


def infer_paper_type(title: str, abstract: str) -> str:
    text = f"{title} {abstract}".lower()
    if re.search(r"\b(survey|systematic review)\b", text):
        return "survey"
    if re.search(r"\b(theory|theorem|provable|proof)\b", title.lower()):
        return "theory/proof"
    if re.search(r"\b(system|framework|platform|toolkit)\b", title.lower()):
        return "system/tool"
    if re.search(r"\b(benchmark|dataset|evaluation suite)\b", title.lower()):
        return "pure benchmark"
    return "pure method"


def record_for(path: Path, paper: dict, labels: dict) -> dict:
    paper_id = paper.get("openreview_id") or paper.get("forum")
    authors = paper.get("authors") or []
    author_names = [item.get("name") for item in authors if isinstance(item, dict) and item.get("name")]
    affiliations = sorted(
        {
            affiliation
            for item in authors
            if isinstance(item, dict)
            for affiliation in (item.get("affiliations") or [])
        }
    )
    return {
        "openreview_id": paper_id,
        "year": paper.get("year") or int(path.parts[-3]),
        "title": paper.get("title") or "",
        "abstract": paper.get("abstract") or "",
        "tldr": paper.get("tldr") or "",
        "keywords": paper.get("keywords") or [],
        "primary_area": paper.get("primary_area"),
        "decision": paper.get("decision"),
        "accepted_main": bool(paper.get("accepted_main")),
        "authors": author_names,
        "affiliations": affiliations,
        "openreview_url": paper.get("openreview_url") or f"https://openreview.net/forum?id={paper_id}",
        "pdf_url": paper.get("pdf_url"),
        "paper_type": infer_paper_type(paper.get("title") or "", paper.get("abstract") or ""),
        "paper_type_inferred": True,
        **labels,
        "source_path": str(path),
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = [
        "openreview_id", "year", "title", "accepted_main", "decision", "primary_area",
        "paper_type", "agent_tier", "agent_relevance_score", "agent_tags",
        "education_tier", "education_relevance_score", "education_tags",
        "openreview_url", "source_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            item = {key: row.get(key) for key in fields}
            item["agent_tags"] = ";".join(row.get("agent_tags") or [])
            item["education_tags"] = ";".join(row.get("education_tags") or [])
            writer.writerow(item)


def self_test() -> None:
    assert classify({"title": "Tool-Using LLM Agents", "abstract": ""})["agent_tier"] == "core"
    assert classify({"title": "Multi-Agent Reinforcement Learning", "abstract": ""})["agent_tier"] == "adjacent"
    assert classify({"title": "AI Tutoring for Student Learning", "abstract": ""})["education_tier"] == "core"
    assert classify({"title": "Teacher-Student Model Distillation", "abstract": ""})["education_tier"] is None
    assert classify({"title": "Curriculum Learning for Robots", "abstract": ""})["education_tier"] is None
    assert classify({"title": "Unrelated Method", "abstract": "Prior work studies LLM agents."})["agent_tier"] == "generic"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("ICLR_REVIEWS_ROOT", "data/iclr_reviews")),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "priority_agent_education",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    self_test()
    if args.self_test:
        print("self_test ok")
        return

    selected = []
    generic_agent = []
    generic_education = []
    seen = set()
    scanned = Counter()
    for year in (2024, 2025, 2026):
        for path in (args.root / str(year)).rglob("*.json"):
            if path.name == "index.json":
                continue
            paper = json.loads(path.read_text(encoding="utf-8"))
            if paper.get("track") != "main":
                continue
            scanned[year] += 1
            paper_id = paper.get("openreview_id") or paper.get("forum")
            if not paper_id or paper_id in seen:
                continue
            labels = classify(paper)
            if not labels["agent_tier"] and not labels["education_tier"]:
                continue
            seen.add(paper_id)
            record = record_for(path, paper, labels)
            if labels["agent_tier"] == "generic" and labels["education_tier"] not in {"core", "adjacent"}:
                generic_agent.append(record)
            if labels["education_tier"] == "generic" and labels["agent_tier"] not in {"core", "adjacent"}:
                generic_education.append(record)
            if labels["agent_tier"] in {"core", "adjacent"} or labels["education_tier"] in {"core", "adjacent"}:
                selected.append(record)

    order = {"core": 0, "adjacent": 1, None: 2, "generic": 3}
    selected.sort(
        key=lambda row: (
            0 if row["agent_tier"] and row["education_tier"] else 1,
            order[row["agent_tier"]],
            order[row["education_tier"]],
            -row["year"],
            row["title"].lower(),
        )
    )
    generic_agent.sort(key=lambda row: (-row["year"], row["title"].lower()))
    generic_education.sort(key=lambda row: (-row["year"], row["title"].lower()))
    agent = [row for row in selected if row["agent_tier"] in {"core", "adjacent"}]
    education = [row for row in selected if row["education_tier"] in {"core", "adjacent"}]
    intersection = [row for row in selected if row["agent_tier"] in {"core", "adjacent"} and row["education_tier"] in {"core", "adjacent"}]
    agent_core = [row for row in agent if row["agent_tier"] == "core"]
    education_core = [row for row in education if row["education_tier"] == "core"]

    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "papers.jsonl", selected)
    write_jsonl(args.output / "agent_papers.jsonl", agent)
    write_jsonl(args.output / "agent_core_papers.jsonl", agent_core)
    write_jsonl(args.output / "education_papers.jsonl", education)
    write_jsonl(args.output / "education_core_papers.jsonl", education_core)
    write_jsonl(args.output / "agent_education_papers.jsonl", intersection)
    write_jsonl(args.output / "generic_agent_candidates.jsonl", generic_agent)
    write_jsonl(args.output / "generic_education_candidates.jsonl", generic_education)
    write_csv(args.output / "papers.csv", selected)

    summary = {
        "scope": "ICLR 2024-2026 main track only",
        "scanned": {str(year): scanned[year] for year in (2024, 2025, 2026)},
        "selected_unique": len(selected),
        "agent_papers": len(agent),
        "agent_core_papers": len(agent_core),
        "education_papers": len(education),
        "education_core_papers": len(education_core),
        "agent_education_intersection": len(intersection),
        "generic_agent_candidates": len(generic_agent),
        "generic_education_candidates": len(generic_education),
        "by_year": {
            str(year): {
                "agent": sum(row["year"] == year for row in agent),
                "education": sum(row["year"] == year for row in education),
                "intersection": sum(row["year"] == year for row in intersection),
            }
            for year in (2024, 2025, 2026)
        },
        "accepted_main": {
            "agent": sum(row["accepted_main"] for row in agent),
            "education": sum(row["accepted_main"] for row in education),
            "intersection": sum(row["accepted_main"] for row in intersection),
        },
        "classification": "deterministic metadata screening; paper type is heuristic; quality scores deferred",
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    top = intersection + [row for row in agent if row not in intersection][:30] + [row for row in education if row not in intersection][:30]
    lines = [
        "# ICLR Agent and Education Literature Extraction",
        "",
        "Date: 2026-07-20",
        "Purpose: prioritize Agent and Education papers for the digital-twin pipeline.",
        "Source policy: local public ICLR 2024-2026 main-track OpenReview records only; Workshops excluded.",
        "",
        "## Counts",
        "",
        f"- Agent papers: {len(agent)}",
        f"- Agent core papers: {len(agent_core)}",
        f"- Education papers: {len(education)}",
        f"- Education core papers: {len(education_core)}",
        f"- Agent + Education intersection: {len(intersection)}",
        f"- Generic-agent broad candidates kept separately: {len(generic_agent)}",
        f"- Generic-education broad candidates kept separately: {len(generic_education)}",
        "",
        "## Priority Papers",
        "",
        "| Title | Year | Accepted | Agent tier | Education tier | Type | URL |",
        "| --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for row in top:
        title = row["title"].replace("|", "\\|")
        lines.append(
            f"| {title} | {row['year']} | {'Yes' if row['accepted_main'] else 'No'} | "
            f"{row['agent_tier'] or ''} | {row['education_tier'] or ''} | "
            f"{row['paper_type']} | [OpenReview]({row['openreview_url']}) |"
        )
    (args.output / "papers.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    notes = """# Search Notes

- Queries are implemented as public keyword and phrase rules over title, abstract, TLDR, keywords, and primary area.
- Workshop records are excluded by `track == main` before classification.
- Core Agent rules emphasize LLM, autonomous, tool-using, web/GUI, software, memory, planning, and agentic systems.
- Multi-agent, embodied-agent, conversational-agent, and agent-based simulation work is retained as adjacent.
- Generic uses of `agent`, dominated by reinforcement learning, are saved separately for optional recall review.
- Education rules emphasize education, tutoring, pedagogy, classroom, curriculum, learning analytics, knowledge tracing, student learning, assessment, and misconception detection.
- Teacher/student knowledge-distillation phrases are excluded unless explicit education evidence is also present.
- Relevance tiers and paper types are deterministic screening labels, not scientific quality judgments. Insight, completeness, and numeric-evidence scores are intentionally deferred until semantic reading.
- Final priority manifests require deterministic evidence plus Luna semantic confirmation; Luna-only expansions are retained separately for audit.
"""
    (args.output / "search-notes.md").write_text(notes, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
