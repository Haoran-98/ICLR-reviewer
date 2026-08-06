#!/usr/bin/env python3
"""Refresh the prepared sample prompt without rescanning the full corpus."""

from __future__ import annotations

import json
from pathlib import Path

from smoke_test import SYSTEM_PROMPT, compact_payload, token_count
from token_utils import get_encoder


def main() -> None:
    base = Path(__file__).resolve().parent / "output"
    manifest = [
        json.loads(line)
        for line in (base / "sample_manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    papers = []
    for row in manifest:
        with Path(row["path"]).open(encoding="utf-8") as handle:
            papers.append(compact_payload(json.load(handle)))
    prompt = {
        "system": SYSTEM_PROMPT,
        "task": {
            "research_profile": [
                "domains",
                "tasks",
                "contribution_types",
                "methods",
                "architecture_tags",
                "agent_tags",
                "engineering_tags",
                "evidence_tags",
            ],
            "review_analysis": ["positive_factors", "negative_factors", "unresolved_concerns"],
            "response_events": [
                "reviewer_id",
                "concern",
                "response_action",
                "reviewer_reaction",
                "score_action",
                "effectiveness",
                "confidence",
                "evidence",
            ],
            "counterfactuals": ["treatment", "outcome", "assumptions", "evidence_grade", "confidence"],
        },
        "papers": papers,
    }
    path = base / "smoke_prompt.json"
    path.write_text(
        json.dumps(prompt, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    encoder = get_encoder()
    print(json.dumps({"papers": len(papers), "prompt_tokens": token_count(encoder, prompt)}))


if __name__ == "__main__":
    main()
