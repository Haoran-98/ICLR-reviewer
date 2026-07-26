#!/usr/bin/env python3
"""Run the prepared 45-paper smoke payload through Codex in two balanced batches."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import tiktoken


OUTPUT_INSTRUCTIONS = """Do not use tools. Return one compact JSON object:
{"papers":[...]}. Include exactly one item per input paper, preserving openreview_id.
Each item must contain: openreview_id, research_tags (max 12 strings),
positive_factors (max 5 strings), negative_factors (max 8 strings),
response_outcomes (max 8 objects with reviewer_id, effectiveness, score_action,
confidence), and counterfactuals (max 3 objects with treatment, outcome,
assumptions, evidence_grade, confidence). Use empty arrays when evidence is absent.
Do not repeat paper text or invent score changes. Output JSON only."""


def token_count(encoder, value) -> int:
    return len(
        encoder.encode_ordinary(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        )
    )


def prepare_batches(prompt: dict, encoder, count: int) -> list[dict]:
    batches = [{"papers": [], "tokens": 0} for _ in range(count)]
    weighted = sorted(
        ((token_count(encoder, paper), paper) for paper in prompt["papers"]),
        reverse=True,
        key=lambda item: item[0],
    )
    for tokens, paper in weighted:
        batch = min(batches, key=lambda item: item["tokens"])
        batch["papers"].append(paper)
        batch["tokens"] += tokens
    return batches


def run_batch(prompt_text: str, output_dir: Path, index: int, model: str) -> dict:
    raw_path = output_dir / f"batch_{index:02d}_events.jsonl"
    result_path = output_dir / f"batch_{index:02d}_result.json"
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--json",
        "--model",
        model,
        "-c",
        'model_reasoning_effort="low"',
        "-",
    ]
    completed = subprocess.run(
        command,
        input=prompt_text,
        text=True,
        capture_output=True,
        timeout=900,
        check=False,
    )
    raw_path.write_text(completed.stdout, encoding="utf-8")
    usage = None
    final_text = None
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            usage = event.get("usage")
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            final_text = item.get("text")
    parsed = None
    if final_text:
        try:
            parsed = json.loads(final_text)
        except json.JSONDecodeError:
            pass
        result_path.write_text(final_text, encoding="utf-8")
    return {
        "batch": index,
        "exit_code": completed.returncode,
        "usage": usage,
        "valid_json": parsed is not None,
        "result_papers": len((parsed or {}).get("papers", [])),
        "stderr_tail": completed.stderr[-1000:],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "smoke_prompt.json",
    )
    parser.add_argument("--batches", type=int, default=2)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    output_dir = args.input.parent / "llm"
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt = json.loads(args.input.read_text(encoding="utf-8"))
    encoder = tiktoken.get_encoding("o200k_base")
    batches = prepare_batches(prompt, encoder, args.batches)

    prepared = []
    for index, batch in enumerate(batches, start=1):
        body = {
            "system": prompt["system"],
            "task": prompt["task"],
            "output_instructions": OUTPUT_INSTRUCTIONS,
            "papers": batch["papers"],
        }
        path = output_dir / f"batch_{index:02d}_prompt.json"
        path.write_text(
            json.dumps(body, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        prepared.append(
            {
                "batch": index,
                "papers": len(batch["papers"]),
                "payload_tokens": batch["tokens"],
                "prompt_tokens": token_count(encoder, body),
                "path": str(path),
            }
        )

    summary = {"prepared": prepared, "runs": []}
    print(json.dumps({"prepared": prepared}, ensure_ascii=False, indent=2), flush=True)
    if args.run:
        for item in prepared:
            prompt_text = Path(item["path"]).read_text(encoding="utf-8")
            result = run_batch(prompt_text, output_dir, item["batch"], args.model)
            result["model"] = args.model
            summary["runs"].append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
