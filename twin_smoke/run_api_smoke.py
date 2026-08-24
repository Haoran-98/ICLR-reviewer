#!/usr/bin/env python3
"""Run prepared smoke batches through the low-cost Responses API model."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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


def response_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/responses"


def output_text(payload: dict) -> str:
    parts = []
    for output in payload.get("output") or []:
        for content in output.get("content") or []:
            if content.get("type") == "output_text" and content.get("text") is not None:
                parts.append(str(content["text"]))
    return "".join(parts)


def create_response(auth: dict[str, str], input_text: str, max_output_tokens: int) -> dict:
    body = json.dumps(
        {
            "model": auth["OPENAI_WEAK_MODEL_ID"],
            "input": input_text,
            "max_output_tokens": max_output_tokens,
        }
    ).encode("utf-8")
    request = Request(
        response_url(auth["OPENAI_BASE_URL"]),
        data=body,
        headers={
            "Authorization": f"Bearer {auth['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_error = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=900) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"Responses API HTTP {exc.code}: {detail[:1000]}")
            if exc.code < 500 and exc.code != 429:
                break
        except (URLError, TimeoutError) as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(2**attempt)
    raise RuntimeError(f"Responses API request failed: {last_error}")


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
    if args.probe:
        response = create_response(
            auth,
            'Return exactly this JSON and nothing else: {"ok":true}',
            20,
        )
        print(
            json.dumps(
                {
                    "model": response.get("model"),
                    "output": output_text(response),
                    "usage": response.get("usage"),
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
            response = create_response(auth, path.read_text(encoding="utf-8"), args.max_output_tokens)
        except Exception as exc:
            run = {"batch": int(index), "model": auth["OPENAI_WEAK_MODEL_ID"], "error": str(exc)}
            meta_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
            runs.append(run)
            write_summary()
            raise
        text = output_text(response)
        result_path.write_text(text, encoding="utf-8")
        valid_json = False
        result_papers = 0
        try:
            parsed = json.loads(text)
            valid_json = True
            result_papers = len(parsed.get("papers", []))
        except json.JSONDecodeError:
            pass
        usage = response.get("usage")
        run = {
            "batch": int(index),
            "model": response.get("model"),
            "usage": usage,
            "valid_json": valid_json,
            "result_papers": result_papers,
            "status": response.get("status"),
            "incomplete_details": response.get("incomplete_details"),
        }
        meta_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        runs.append(run)
        print(json.dumps(run, ensure_ascii=False), flush=True)
        write_summary()


if __name__ == "__main__":
    main()
