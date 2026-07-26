# ICLR Twin Smoke Test

Build a deterministic 0.1% sample and count the current JSON corpus with the
`o200k_base` tokenizer:

```bash
python smoke_test.py
```

Workshop papers are excluded by default. Apply deterministic filters before
paid inference:

```bash
python python_filter.py
python run_api_smoke.py --input-dir output/main_filtered/batches \
  --output-dir output/main_filtered/api_luna
python validate_results.py --input-dir output/main_filtered/api_luna \
  --manifest output/main_filtered/main_sample_manifest.jsonl \
  --local-records output/main_filtered/local_records.json \
  --prefix main_filtered_luna_
```

Outputs are written to `output/`:

- `sample_manifest.jsonl`: selected paper IDs and token sizes.
- `smoke_prompt.json`: compact end-to-end extraction payload for the sample.
- `token_report.json`: exact current-corpus input token totals and distributions.

Refresh only the 45-paper prompt after changing extraction fields:

```bash
python refresh_sample_prompt.py
```

This test covers the existing structured JSON. PDF text, OpenReview Note
revisions, live trend monitoring, and repeated author/reviewer simulations are
separate token budgets.

Prepare two balanced LLM batches, or run them through the logged-in Codex CLI:

```bash
python run_llm_smoke.py
python run_llm_smoke.py --run
python validate_results.py
```

The Codex CLI runner is retained only for strong-model debugging and defaults
to `gpt-5.6-sol`:

```bash
python run_llm_smoke.py --run
```

For production bulk labeling, use the cheaper direct Responses API configured
by `ICLR_AUTH_FILE` (default: `$HOME/auth`). The script reads the file at
runtime and does not copy the key into the project:

```bash
python run_api_smoke.py --probe
python run_api_smoke.py
python run_api_smoke.py --resume
python validate_results.py --input-dir output/api_luna --prefix luna_
```

The production direct API defaults to `OPENAI_WEAK_MODEL_ID`
(`gpt-5.6-luna`).

Extract and semantically screen the priority Agent/Education subset:

```bash
python extract_priority_topics.py
python prepare_priority_luna.py --batch-tokens 90000
python run_api_smoke.py \
  --input-dir output/priority_agent_education/luna_batches \
  --output-dir output/priority_agent_education/api_luna \
  --max-output-tokens 24000 --resume
python finalize_priority_luna.py
```

Build historical domain reviewer archetypes locally:

```bash
python build_reviewer_twins.py
python run_api_smoke.py \
  --input-dir output/reviewer_twins/luna_batches \
  --output-dir output/reviewer_twins/api_luna \
  --max-output-tokens 16000 --resume
python build_reviewer_twins.py --results output/reviewer_twins/api_luna
```

Export the public main-track title/abstract catalog:

```bash
python export_public_raw.py --input /path/to/iclr_reviews --output ../raw
```

Run the prepared 1% main-track sample with resumable Luna batches:

```bash
python run_api_smoke.py \
  --input-dir output/one_percent/main_filtered/batches \
  --output-dir output/one_percent/main_filtered/api_luna \
  --resume
python validate_results.py \
  --input-dir output/one_percent/main_filtered/api_luna \
  --manifest output/one_percent/main_filtered/main_sample_manifest.jsonl \
  --local-records output/one_percent/main_filtered/local_records.json \
  --prefix one_percent_main_luna_
```
