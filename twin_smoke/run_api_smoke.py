#!/usr/bin/env python3
"""Run prepared smoke batches through the low-cost Responses API model."""

from __future__ import annotations

import argparse
import json
import os
import shlex
from pathlib import Path

from openai import OpenAI


def load_auth(path: Path) -> dict[str, str]:
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith("export "):
            continue
        assignment = shlex.split(line[len("export ") :])
        if len(assignment) != 1 or "=" not in assignment[0]:
            continue
        key, value = assignment[0].split("=", 1)
        values[key] = value
    required = {"OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_WEAK_MODEL_ID"}
    missing = sorted(required - values.keys())
    if missing:
        raise ValueError(f"Missing auth fields: {', '.join(missing)}")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--auth",
        type=Path,
        default=Path(os.environ.get("ICLR_AUTH_FILE", Path.home() / "auth")),
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "llm",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "api_luna",
    )
    parser.add_argument("--max-output-tokens", type=int, default=12000)
    parser.add_argument("--limit", type=int, help="Run only the first N prepared batches")
    parser.add_argument("--probe", action="store_true", help="Send only a tiny connectivity request")
    parser.add_argument("--resume", action="store_true", help="Skip batches with valid saved results")
    args = parser.parse_args()

    auth = load_auth(args.auth)
    client = OpenAI(
        base_url=auth["OPENAI_BASE_URL"],
        api_key=auth["OPENAI_API_KEY"],
        timeout=900,
        max_retries=3,
    )
    if args.probe:
        response = client.responses.create(
            model=auth["OPENAI_WEAK_MODEL_ID"],
            input='Return exactly this JSON and nothing else: {"ok":true}',
            max_output_tokens=20,
        )
        print(
            json.dumps(
                {
                    "model": response.model,
                    "output": response.output_text,
                    "usage": response.usage.model_dump() if response.usage else None,
                },
                ensure_ascii=False,
            )
        )
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prompts = sorted(args.input_dir.glob("batch_*_prompt.json"))
    if args.limit is not None:
        prompts = prompts[: args.limit]

    runs = []
    summary_path = args.output_dir / "summary.json"

    def write_summary() -> None:
        summary = {"model": auth["OPENAI_WEAK_MODEL_ID"], "runs": sorted(runs, key=lambda x: x["batch"])}
        temporary = summary_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(summary_path)

    for path in prompts:
        index = path.stem.split("_")[1]
        result_path = args.output_dir / f"batch_{index}_result.json"
        meta_path = args.output_dir / f"batch_{index}_meta.json"
        if args.resume and result_path.exists() and meta_path.exists():
            saved = json.loads(meta_path.read_text(encoding="utf-8"))
            if saved.get("valid_json"):
                runs.append(saved)
                print(json.dumps({**saved, "resumed": True}, ensure_ascii=False), flush=True)
                write_summary()
                continue
        try:
            response = client.responses.create(
                model=auth["OPENAI_WEAK_MODEL_ID"],
                input=path.read_text(encoding="utf-8"),
                max_output_tokens=args.max_output_tokens,
            )
        except Exception as exc:
            run = {"batch": int(index), "model": auth["OPENAI_WEAK_MODEL_ID"], "error": str(exc)}
            meta_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
            runs.append(run)
            write_summary()
            raise
        result_path.write_text(response.output_text, encoding="utf-8")
        valid_json = False
        result_papers = 0
        try:
            parsed = json.loads(response.output_text)
            valid_json = True
            result_papers = len(parsed.get("papers", []))
        except json.JSONDecodeError:
            pass
        usage = response.usage.model_dump() if response.usage else None
        run = {
            "batch": int(index),
            "model": response.model,
            "usage": usage,
            "valid_json": valid_json,
            "result_papers": result_papers,
            "status": response.status,
            "incomplete_details": (
                response.incomplete_details.model_dump() if response.incomplete_details else None
            ),
        }
        meta_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        runs.append(run)
        print(json.dumps(run, ensure_ascii=False), flush=True)
        write_summary()


if __name__ == "__main__":
    main()
