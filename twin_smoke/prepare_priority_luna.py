#!/usr/bin/env python3
"""Prepare compact Luna batches for Agent/Education relevance screening."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from token_utils import get_encoder


INSTRUCTIONS = """Return JSON only as {"papers":[...]}, exactly one item per input ID.
For each paper return: openreview_id, agent_relevance, education_relevance,
agent_tags, education_tags, rationale. Relevance must be core, adjacent, or no.
Core means the topic is a central research contribution. Adjacent means a direct
application, evaluation, or enabling method. No means only incidental wording,
an ML metaphor, teacher-student distillation, curriculum learning, generic
reinforcement-learning agent terminology, or an unrelated use of assessment.
Agent includes LLM/autonomous/tool/web/GUI/embodied agents, agent memory and
planning, multi-agent systems, and agent evaluation. Education includes actual
teaching, learning, students, tutoring, classrooms, knowledge tracing,
educational content, and educational assessment. Keep tags to at most 6 short
strings and rationale to at most 24 words. Do not infer from acceptance status."""


def tokens(encoder, value: object) -> int:
    return len(encoder.encode_ordinary(json.dumps(value, ensure_ascii=False, separators=(",", ":"))))


def main() -> None:
    parser = argparse.ArgumentParser()
    base = Path(__file__).resolve().parent / "output" / "priority_agent_education"
    parser.add_argument("--input", type=Path, default=base / "papers.jsonl")
    parser.add_argument("--output", type=Path, default=base / "luna_batches")
    parser.add_argument("--batch-tokens", type=int, default=180000)
    args = parser.parse_args()

    encoder = get_encoder()
    papers = []
    for line in args.input.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        papers.append(
            {
                "openreview_id": row["openreview_id"],
                "title": row["title"],
                "abstract": row["abstract"],
                "keywords": row["keywords"],
                "python_agent_tier": row["agent_tier"],
                "python_education_tier": row["education_tier"],
            }
        )

    batches = []
    current = []
    current_tokens = tokens(encoder, {"instructions": INSTRUCTIONS, "papers": []})
    for paper in papers:
        paper_tokens = tokens(encoder, paper)
        if current and current_tokens + paper_tokens > args.batch_tokens:
            batches.append(current)
            current = []
            current_tokens = tokens(encoder, {"instructions": INSTRUCTIONS, "papers": []})
        current.append(paper)
        current_tokens += paper_tokens
    if current:
        batches.append(current)

    args.output.mkdir(parents=True, exist_ok=True)
    for old in args.output.glob("batch_*_prompt.json"):
        old.unlink()
    prompt_tokens = 0
    for index, batch in enumerate(batches, 1):
        prompt = {"instructions": INSTRUCTIONS, "papers": batch}
        prompt_tokens += tokens(encoder, prompt)
        (args.output / f"batch_{index:02d}_prompt.json").write_text(
            json.dumps(prompt, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    summary = {"papers": len(papers), "batches": len(batches), "prompt_tokens": prompt_tokens}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
