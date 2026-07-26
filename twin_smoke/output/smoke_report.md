# ICLR Digital-Twin Smoke Test Report

Date: 2026-07-20

## Scope

- Corpus: 44,758 processed ICLR 2024-2026 paper JSON files.
- Sample: 45 papers (0.1%, rounded), selected deterministically with seed `20260720`.
- Strata: year and main/workshop track.
- Sampling within each stratum: token-length quantiles, covering short, typical,
  and long review/rebuttal records.
- Model run: two balanced Codex batches with low reasoning effort.
- Encoding used for local counts: `o200k_base`.

## Sample Allocation

| Year | Main | Workshop | Total |
| --- | ---: | ---: | ---: |
| 2024 | 7 | 1 | 8 |
| 2025 | 12 | 2 | 14 |
| 2026 | 20 | 3 | 23 |
| Total | 39 | 6 | 45 |

## Existing JSON Input Tokens

The full corpus was scanned locally, so these values are counts rather than a
0.1% extrapolation.

| Content | Tokens |
| --- | ---: |
| Paper metadata, title, abstract, TLDR, keywords | 14,564,901 |
| Reviews | 100,915,175 |
| Rebuttal and reviewer discussion | 252,032,365 |
| Total without stable IDs | 367,512,441 |
| Estimated total with stable paper IDs | 368,495,128 |

Payload distribution without stable IDs:

| Statistic | Tokens per paper |
| --- | ---: |
| Mean | 8,211 |
| Median | 7,615 |
| P90 | 16,493 |
| P95 | 19,808 |
| P99 | 27,320 |
| Maximum | 60,671 |

The discussion layer accounts for about 68.6% of the current payload. Token
optimization should therefore focus on thread reconstruction, deduplication,
and deterministic extraction before reducing abstract length.

## Successful LLM Run

| Metric | Batch 1 | Batch 2 | Total |
| --- | ---: | ---: | ---: |
| Papers | 22 | 23 | 45 |
| Application prompt tokens | 181,716 | 181,922 | 363,638 |
| Reported input tokens | 197,448 | 197,654 | 395,102 |
| Output tokens | 7,911 | 8,227 | 16,138 |
| Reasoning tokens, included in output | 121 | 138 | 259 |
| Valid JSON | Yes | Yes | Yes |

- Average structured output: 358.6 tokens per paper.
- Fixed Codex context overhead: 15,732 input tokens per batch.
- Total successful smoke usage: 411,240 tokens.

## Full Current-Corpus Estimate

Assumes approximately 181,500 payload tokens per request and the same compact
output schema used in the smoke test.

| Execution method | Estimated total tokens |
| --- | ---: |
| Direct model API with compact system prompt | 385,203,370 |
| Measured `gpt-5.6-luna` Responses API behavior | 393,787,335 |
| Codex CLI, approximately 2,031 large batches | 417,155,062 |
| Codex CLI called once per paper | 1,103,158,410 |

Large batching saves roughly 686 million tokens compared with one Codex call
per paper. The production route is the direct Responses API configured in
`$HOME/auth`, using `gpt-5.6-luna` for bulk work; this avoids the coding-agent
system context. Stronger models are reserved for ambiguous samples.

## `gpt-5.6-luna` 0.1% Rerun

The same 45 papers and prompts were rerun through the direct API configured in
`$HOME/auth`. No Codex CLI model was used.

| Metric | Batch 1 | Batch 2 | Total |
| --- | ---: | ---: | ---: |
| Papers | 22 | 23 | 45 |
| Input tokens | 186,489 | 186,695 | 373,184 |
| Cached input tokens | 3,840 | 3,840 | 7,680 |
| Output tokens | 8,315 | 6,707 | 15,022 |
| Reasoning tokens, included in output | 197 | 214 | 411 |
| Total tokens | 194,804 | 193,402 | 388,206 |

The Luna rerun used 5.6% fewer total tokens than the prior Codex strong-model
run. Extrapolating the measured provider overhead and output length gives about
393.8 million tokens for an all-LLM pass over the current JSON corpus. Larger
batches can reduce the fixed overhead further.

Quality checks for the Luna run:

- 45 expected IDs, 45 returned unique IDs, no missing or extra papers.
- Zero list-limit violations after the model response.
- Six workshop papers produced no response outcomes or counterfactuals.
- 102 main-track response outcomes were extracted.
- 67 counterfactual hypotheses were produced, fewer than the strong model's
  113; Luna is more conservative and requires recall auditing on a labeled set.

## Complete Build Budget

The smoke test covers only the existing structured JSON. A production causal
digital twin also needs PDF text, public Note revisions, and profile/trend
synthesis. Under explicit planning assumptions:

| Additional layer | Assumption | Additional tokens |
| --- | --- | ---: |
| PDFs | 8,000-15,000 tokens per paper | 358-671 million |
| Note revision deltas | 15%-40% of current review/discussion text | 53-141 million |
| Agent/profile/trend synthesis | Aggregated second pass | 20-80 million |

Estimated one-time direct-API build total: **0.82-1.28 billion tokens**.
Processing complete revision snapshots instead of deltas may push the total
above 1.5 billion tokens. This range must be recalibrated after a revision/PDF
sample is fetched.

Repeated reviewer-author simulation is a separate online budget. A two-round
panel with several reviewer and author agents is provisionally expected to use
about 0.3-0.8 million tokens per new manuscript, depending on manuscript length,
retrieval depth, and panel size.

## Quality Checks

- 45 expected papers, 45 returned papers, 45 unique and matching IDs.
- All six workshop papers produced zero response outcomes and zero
  counterfactuals, as their sampled records contained no discussion evidence.
- 102 reviewer-response outcomes and 113 counterfactual hypotheses were
  extracted from the 39 main-track papers.
- The model exceeded requested positive/negative-factor list limits on ten
  papers. Local validation now truncates these lists.
- Free-text effectiveness and score-action values were not database-safe.
  The validation layer preserves raw text and maps it to canonical enums.
- Reviewer silence is normalized to `unknown`, not success or failure.

An initial failed run omitted stable paper IDs. It returned 45 records but only
17 unique non-null identifiers. The payload was fixed and the failed events are
retained under `llm_failed_missing_ids/` for regression testing.

## Recommendation

Proceed with the current compact schema, direct API batching, and deterministic
post-validation. Before committing the 0.82-1.28B token budget, run the next
smoke test on public Note revisions and PDF text because those are the largest
remaining uncertainties.

## Main-Track-Only Python Filter Rerun

Workshop papers are now excluded from the active pipeline. The retained 0.1%
sample contains 39 main-track papers: 7 from 2024, 12 from 2025, and 20 from
2026.

Deterministic Python preprocessing performed before Luna inference:

- Removed 352 quoted lines and 409 duplicate paragraphs.
- Removed 125 courtesy-only paragraphs and two author score-update nudges.
- Compressed 918 Markdown table lines and 13 reference-list blocks.
- Classified 14 explicit reviewer score/resolution events locally.
- Preserved raw source files and evidence/message IDs for audit.

| Metric | Value |
| --- | ---: |
| Main-track papers | 39 |
| Payload before filtering | 364,975 tokens |
| Payload after filtering | 315,137 tokens |
| Payload reduction | 49,838 tokens / 13.66% |
| Luna input tokens | 325,268 |
| Luna output tokens | 15,148 |
| Actual Luna total | 340,416 |

All 39 IDs were returned uniquely. Eleven locally classified events matched
model outcomes and were deduplicated; three additional deterministic events
were merged into the final results. The canonical result therefore preserves
local facts without asking the model to rediscover them.

## 1% Main-Track Luna Test

The next smoke test sampled 389 of 38,890 main-track papers (1.0003%) and did
not include Workshop papers. The deterministic annual allocation was 74 papers
from 2024, 117 from 2025, and 198 from 2026. Five papers had no review or
discussion evidence requiring semantic inference and were retained as
Python-only records; 384 papers were sent to Luna in 18 resumable batches.

Python preprocessing reduced the sampled semantic payload from 3,709,133 to
3,204,224 tokens, saving 504,909 tokens (13.61%) before inference. It removed
3,020 quoted lines, 3,442 duplicate paragraphs, 1,098 courtesy paragraphs,
eight generic reminders, and three pure score-update nudges. It also compressed
8,548 Markdown table lines and 160 reference blocks. The prepared prompts
contained 3,209,456 locally counted tokens.

| Metric | 1% result |
| --- | ---: |
| API batches completed | 18 / 18 |
| Model-returned papers | 384 |
| Python-only papers | 5 |
| Final unique papers | 389 / 389 |
| Luna input tokens | 3,295,370 |
| Cached input tokens | 61,440 |
| Luna output tokens | 132,812 |
| Reasoning tokens, included in output | 5,375 |
| Actual Luna total | 3,428,182 |

All API responses had status `completed`, valid JSON, the required top-level
schema, and unique expected IDs. The normalization layer truncated one
overlong research-tag list, 77 positive-factor lists, and five negative-factor
lists to their schema limits. No response-outcome or counterfactual list from
the model exceeded its requested limit.

The canonical result contains 3,872 research tags, 1,846 positive factors,
2,862 negative factors, 595 reviewer-response outcomes across 221 papers, and
614 counterfactuals across 293 papers. Reviewer-response effectiveness is
normalized to 119 strong successes, 180 partial successes, 36 no-effect cases,
and 260 unknown cases. Score actions are 135 increases, four promised
increases, 135 maintained scores, one decrease, and 320 unknown actions.
Reviewer silence or ambiguous wording remains `unknown`.

The larger sample exposed an important causal-label issue in the initial
Python rules. The broad phrase match for "concerns addressed" incorrectly
treated negated or qualified statements such as "haven't been fully addressed"
and "addressed some concerns, but ..." as success. Re-evaluating the 249 local
events with conservative rules changed 102 resolution labels; only explicit
full-resolution language is now classified as strong success. During final
normalization, 194 model outcomes were reconciled with these evidence excerpts
and 47 additional local outcomes were merged. Ambiguous local statements were
set to `unknown`. The API calls were not repeated, avoiding another 3.43 million
tokens; final local causal labels use the corrected conservative rules.

Scaling the measured 1% usage by the exact main-track payload ratio gives an
estimated 342.8 million tokens for the same filtered extraction pass over all
38,890 main-track papers: about 329.5 million input and 13.3 million output
tokens. The deterministic filters are projected to remove about 50.5 million
payload tokens before the full run. This estimate covers the existing JSON
only and still excludes PDFs, OpenReview Note revision deltas, profile
synthesis, trend modeling, and multi-agent debate.
