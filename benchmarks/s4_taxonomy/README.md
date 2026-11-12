# S4: original paper trees and DKTA comparisons

Current real GPU comparison (2026-10-23): RTX 4060 Ti 16GB, isolated
`/data_big/iclr-s4/runtime-dkta`, 200 title/abstract inputs. Qwen3.5-9B NF4 eager
attention and KP20k ONE2MANY BART each completed all 200 extractions, as did the
same-input DeepSeek baseline. `scripts/s4_dkta_compare.py` imports the audited
ACM CCS mirror projection, runs the matched baseline, blind 50-paper model judging,
and generates `comparison.md/json`. The shared-ACM LLM arm controls vocabulary effects.
Artifacts: `/data_big/iclr-s4/experiments/dkta4060_200_v1`; completion statuses live there.
Completed: 800 assignments, full parent closure verified, 50/50 blind evaluations.
Results and limitations: [200-paper GPU report](dkta4060_200_report.md).
Author-keyphrase agreement and model judging are proxy metrics, not taxonomy gold.
New calls now default to auth's OpenAI weak model (`gpt-6-luna`, concurrency 4).
Retained DeepSeek outputs are historical comparisons; no new DeepSeek calls are made.
Its 679 HTTP402 failures yielded 678 valid OpenAI recoveries and one explicit unknown
after the shared six-request budget. Cache-only materialization makes no model requests.
See [S4_DKTA.md](../../docs/technical_details/S4_DKTA.md) for the pinned models,
multi-parent closure semantics, commands, and current real experiment.

```bash
/data_big/iclr-s4/runtime-dkta/bin/python -m unittest discover -s benchmarks/s4_taxonomy -p 'test_*.py' -v
```

The October 21 environment limitations below are historical and superseded.

New methods (2026-10-21): Qwen full-attention keyphrase extraction and fine-tuned BART
One2Many, plus their DKTA RRF combination. All align against the same versioned
three-level multi-parent DAG; existing paper trees are unchanged, Kimi is excluded.
See [S4_DKTA.md](../../docs/technical_details/S4_DKTA.md) for backend requirements,
input formats, score semantics, staged commands and current missing assets.

```bash
/data_big/iclr-s4/runtime/bin/python scripts/s4_dkta.py prepare
/data_big/iclr-s4/runtime/bin/python -m unittest discover -s benchmarks/s4_taxonomy -p test_dkta.py -v
```

## Completed: original three-source paper trees

2026-10-21: exclude Kimi from current exports. Each paper title is the root, followed
by the original L1/L2/L3 paths from DeepSeek, OpenAI and Qwen. Sources are node
attributes, not another tree level. No merging, semantic repair, generation or training
is performed. Previously pruned outputs remain in per-paper JSON metadata.

```bash
/data_big/iclr-s4/runtime/bin/python scripts/s4_export_paper_trees.py
/data_big/iclr-s4/runtime/bin/python -m unittest discover -s benchmarks/s4_taxonomy -p test_paper_trees.py -v
```

Outputs: `/data_big/iclr-s4/experiments/taxonomy_llm3_paper_trees_200_v1/{trees.md,index.md,manifest.json,papers/}`.
The following four-source instructions are historical, superseded by the export entry above.

---

# Historical S4 v4 experiment

Canonical plan: [S4_plan.md](../../docs/technical_details/S4_plan.md).

Active analysis version: taxonomy_llm4_gpt_200_v1. Historical source: taxonomy_llm4_200_v1.
All 200 previously consumed papers are development data.

As clarified on 2026-10-17, completed Kimi candidates, evidence, coarse votes and alignment
votes remain in use. Only missing/future Kimi evaluation duties move to gpt-6-luna.
Replacement votes record assigned_role=kimi, actual_provider=openai and the actual model.
Exact cached GPT cross-votes are reused; replacement observations count once with GPT,
while original Kimi observations retain their independent provenance. The old three-provider
branch is stopped and superseded, with its files preserved.
The historical worker finishes its in-flight Qwen queue. The new branch waits for those files,
retains all historical candidates, and repeats only votes whose label definition changed.
Original request IDs, cached responses and retry ledgers are shared without resetting budgets.
Same-scope merges/containment require a majority of unique actual sources and no no vote.

Two additional paper representations directly encode original text: title+abstract (TA) and
title+abstract+keywords (TAK), alongside six-section embeddings (E1) and no-embedding (E0).
The pinned BGE-M3 uses 510 content tokens, 64 overlap, normalized-mean chunk pooling and
fold-local PCA. Full LLM evidence and label-name/definition embeddings remain unchanged.
All four paper-representation conditions have before/after-repair arms; no gold metrics are fabricated.
Input hashes and chunk/spec records accompany the new vectors. GPU encoding waits for Qwen's
current cross-votes, then restores the local model. The active service is s4-llm4-gpt-fusion.service.
The real related-work ablation compares three unchanged generators with a matching three-model
full-input control, preventing the Kimi-to-GPT model change from confounding that comparison.

```bash
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 OMP_NUM_THREADS=4 \
 /data_big/iclr-s4/runtime/bin/python scripts/s4_crowd_fusion.py watch \
 --root /data_big/iclr-s4/experiments/taxonomy_llm4_gpt_200_v1 \
 --source-root /data_big/iclr-s4/experiments/taxonomy_llm4_200_v1 \
 --providers deepseek kimi openai qwen --replace-kimi-with-openai
```

The four-model and Kimi instructions below describe the historical source experiment only.
The former 23-anchor clustering experiment has been removed; its pipeline remains legacy code.
No production taxonomy is frozen. Official labels remain observed facts in core.paper_area.

The new pipeline extracts six original sections, embeds each separately, and calls DeepSeek Flash,
Kimi K2.6, gpt-6-luna and local Qwen3.5-9B Q8_0 independently. Each model proposes up to
3 roots × 3 children × 3 grandchildren, with evidence-based pruning and complete audit trails.
Local span references are resolved into original quotes. Missing sections stay missing.

After the same-corpus 10-paper pilot, generation continues to all 200. A separate resumable
postprocessor waits for all four generators, then aligns labels, collects explicit cross-votes
and hierarchy-containment votes, trains DS/static/conditional Crowd Layer baselines, runs the
E0R0/E1R0/E0R1/E1R1 arms, enforces parent closure and persists experimental outputs.
Related-work ablation reruns generation on the same 200 papers with that section removed.
Fine posteriors are latent scores, not calibrated correctness probabilities.

Runtime and pinned model cache: /data_big/iclr-s4/runtime and /data_big/iclr-s4/models.
Artifacts: /data_big/iclr-s4/experiments/taxonomy_llm4_200_v1.
Credentials: /home/yhr/auth; provider concurrency is read case-insensitively, local Qwen = 1.
Each job reserves an attempt before sending; initial + at most five retries across restarts.
HTTP 429 honors Retry-After with a provider-wide cooldown. Permanent HTTP errors stop retries.
The Kimi channel initially used K2.6, then switched at the user's request to the Coding endpoint,
kimi-for-coding with reasoning_effort=low. Auth's Kimi_model overrides legacy Kimi_weak_model;
Kimi_think_strength maps to reasoning_effort. The completed 134 old-model papers remain intact;
the next papers used the new configuration. An incomplete paper restarted under the new model with
its earlier levels retained in generated_history. kimi_model_transition.json records this mixture.
Initial pilot calls retain their original responses and diagnostics.
After Coding hit its five-hour quota, Kimi switched back to K2.6; 139/200 papers were complete
when paused. The remaining 61 now resume through Moonshot Batch API (40% lower inference fees
per the official guide, 24h completion window per batch). Hierarchy levels run in dependent rounds;
independent official votes can share a batch. The transport shares realtime job IDs, cached results,
original evidence validation and the initial-plus-five-retries budget. Creation is reconciled by
input_file_id after an ambiguous response to avoid duplicate paid submissions.
K2.6 prefix caching is automatic and also has a Batch cached-input rate (CNY0.66/M,
versus CNY3.90/M uncached; output CNY16.20/M, official pricing checked 2026-10-16).
New Kimi requests put unchanged paper evidence before variable instructions and parent state.
All original payload fields and logical job IDs stay intact; request_layout/request_hash audit
the wire ordering change without resetting attempt budgets. Already submitted batches are not resent.
K2.6 does not support the newer Cache Write/TTL controls; no prompt_cache_options/cache_control
is added. Batch cache_usage summaries preserve missing-vs-zero usage coverage and report actual
cache reads/hit ratios from responses, not assumed savings. Scheduling may limit prefix reuse.
Parser v2 handles the observed Batch status_code=0 sentinel only with an error-free completion
body that passes finish-reason, JSON, schema-field and original-evidence validation. It preserves
the raw status rather than fabricating HTTP200. Previously imported batches are revalidated from
downloaded local files, retaining original attempt decisions in a before_batch_response_v2 audit.
This does not send inference requests or reset attempt budgets. Malformed JSON remains retryable;
new K2.6 requests use response_format=json_object, while semantic/evidence checks remain mandatory.
All four channels reached 200/200 on 2026-10-17 12:17:46 Asia/Shanghai. Three Qwen official
votes were recovered without inference by collapsing repeated adjacent tokens only when the
result exactly matches an allowed class; originals remain attached. OpenAI paper3374 uses an
explicit user-approved repair round linked to its exhausted original job; the six original
attempts are retained and the new round retains the same initial-plus-five-retries cap.
Fusion Kimi calls (alignment, cross-label and containment votes) also use Batch, as does Kimi
generation in the real no-related-work ablation. analysis_batch_progress.json and
batch/analysis_active.json record the active analysis batch; other providers follow auth concurrency.
Pruning failures are semantic outcomes, not a reason to repeat unchanged inference six times.

Embedding uses the pinned BGE-M3 revision, six masks and 512-token chunks with 64 overlap.
The Qwen server starts after embedding releases physical GPU 1 (V100). S3 remains untouched.

Run or resume generation:

```bash
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 OMP_NUM_THREADS=8 /data_big/iclr-s4/runtime/bin/python scripts/s4_llm_taxonomy.py run
```

Run or resume postprocessing (waits if generation is still in progress):

```bash
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 OMP_NUM_THREADS=4 /data_big/iclr-s4/runtime/bin/python scripts/s4_crowd_fusion.py watch
```

Resume the Kimi batch worker (uses the same run.lock as realtime):

```bash
/data_big/iclr-s4/runtime/bin/python scripts/s4_kimi_batch.py
```

Kimi's background service is s4-llm4-200.service; other channels are not restarted.
Batch artifacts are batch/active.json, batch/<batch_id>.json and downloaded output/error JSON.
Remote scheduling determines batch concurrency; auth's realtime Kimi_concurrency does not.
Stopping the local worker does not cancel a remote batch: explicitly cancel the owned remote batch
before pausing, retain its completed results, then stop further dependent submissions.
Logs are batch.log and fusion.log in the artifact directory. execution.json tracks generation;
postprocess_execution.json tracks postprocessing. pilot_summary.json is written only after
all four models finish the pilot. generation_complete.json does not mean quality acceptance.

Checks (database checks create and remove only a uniquely named temporary test database):

```bash
S4_DATABASE_TEST=1 OMP_NUM_THREADS=4 /data_big/iclr-s4/runtime/bin/python -m unittest discover -s benchmarks/s4_taxonomy -p 'test_*.py' -v
```

Development induction is transductive; outer folds isolate supervised fitting, PCA and thresholds.
Current extractor coverage is recorded in section_stats.json; a missing mask means the extractor
did not locate that section, and can include unrecognized heading variants. Do not equate it
with proof that the paper has no such section. Formal unseen-paper evaluation needs new data.
