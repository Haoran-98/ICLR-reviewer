# S5 fused-method diagnostic

This diagnostic runs 20 real paper–reviewer threads through the configured
OpenAI weak model, with `reasoning.effort=medium` and exactly one request in
flight. It combines RbtAct-style author-action annotation, DRPG-style
evidence-constrained response planning, and structural score context plus
the 44 exchange-feature labels from the score-trajectory study.

It uses prompting to annotate actions, plan evidence-constrained responses,
and inspect observed discussion transitions.

## Run

```bash
python scripts/s5_fused20.py self-check
python scripts/s5_fused20.py prepare
python scripts/s5_fused20.py run
```

The runner reads `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and
`OPENAI_WEAK_MODEL_ID` from `ICLR_AUTH_FILE` (default: `$HOME/auth`).
Credentials never enter request logs. `--root` selects an external artifact
directory. Requests, raw responses, source text, and per-sample results stay
there; they are not copied into this repository. Completed requests are
reused only when their request hash matches. Attempts are reserved before
sending and bounded across restarts.
When a response includes both commentary and `final_answer` messages, only
the explicitly marked final messages are parsed as the result JSON.

## Frozen sampling

- Only papers already marked `dev` in the existing taxonomy development
  manifest are eligible; no held-out test papers are opened.
- Twenty distinct papers: 2024 and 2025 each contribute five threads with
  later focal-reviewer feedback and five without it.
- Eligible candidates are ordered by a deterministic SHA-256 key.
- The review snapshot must demonstrably predate the cutoff. The cutoff is
  the end of the first author-response burst, at most 30 minutes after its
  first available message and before the next focal-reviewer response.
- Message availability uses the later of creation and modification time;
  unavailable historical message versions are not reconstructed.
- The selected cohort favors reviews that were not edited later. It is
  unsuitable for estimating the prevalence or causal effect of score changes.

## Two dependent calls per sample

1. **Prefix:** provide the review, available author messages, and only peer
   rating snapshots demonstrably available at cutoff. Extract atomic
   concerns, map RbtAct action categories, code observable exchange features,
   propose feasible response strategies, and draft replies. An optional
   score-direction judgment is explicitly uncalibrated. No future discussion
   or undated manuscript text enters this request.
2. **Replay:** provide the frozen prefix result and actual later messages.
   Retrieve manuscript paragraphs using concern terms and review text.
   Reconstruct concern-state transitions and plan grounded next steps.
   Manuscript version time is unverified, so these excerpts support only
   retrospective checks and planning. Generated replies are never treated
   as real historical events.

Each concern separates author action, evidence support, and the focal
reviewer's expressed judgment. Silence remains `unknown`. Verify the snapshot date separately when attributing a revision
to the rebuttal period. Missing independent before/after score pairs remain
`unknown`, even when a single final rating snapshot exists.

## Validation and artifacts

The model selects pre-numbered original passages; the program restores the
source ID, verbatim quote, and character offsets. The already validated first
prefix result retains its original quote-based citation record. Failed setup
attempts are preserved and included in returned usage totals. Each stage has
at most eight attempts across restarts. The current transport streams Responses
events and limits idle reads to 180 seconds. Timeouts without returned usage
are reported as unknown usage rather than zero cost.

Concern origins directly select passages from the initial review. If the
model selects a strategy it also marks infeasible, the execution guard
abstains, suppresses the draft, and preserves the rejected choice and draft
in the request ledger. This constraint can recover an otherwise valid saved
response without another inference call; recovered stages are counted
separately from requests that passed immediately.

Initial-review extraction explicitly names the original review source, since
the prefix can also contain later reviewer discussion notes. New issues from
those notes belong in replay `new_concerns`. A saved S07 origin-constraint
clarification records the retry-boundary prompt change; prior validated results
remain available with their original request hashes.

JSON schemas, original-source quote matching, character offsets, reference
integrity, plan feasibility, and the requirement for post-cutoff focal-reviewer
evidence for observed resolution are checked before saving a successful result.
These checks establish traceability and structural consistency; the labels
still require human adjudication for scientific accuracy.

The run directory contains `manifest.json`, `config.json`, `progress.json`,
`summary.json`, `REPORT.md`, and per-sample `inputs/`, `requests/`, and
`results/`. The report links to each sample's concern ledger, candidate
strategies, response drafts, and limitations. Actual API token usage includes
returned usage from failed attempts where available.

The run-local `verify_run.py` rechecks saved artifacts without model calls and
writes `verification.json` plus each sample's `replay_timeline.json`. Timelines
retain parent links, missing parent IDs, message creation times, snapshot
availability times, and the original model transition order. A separately
sorted view follows snapshot availability; no state labels are re-inferred.

`feature_codebook.json` retains the 44 source labels and their source polarity,
and adds prefix-aware `present / not_observed / unknown` coding. Source
polarity retains the original feature-label meaning. Response quality and
causal effects require separate evaluation.

## Sources

- [RbtAct, Findings of ACL 2026](https://aclanthology.org/2026.findings-acl.1696/)
- [DRPG](https://arxiv.org/abs/2601.18081)
- [Rebuttals Move Peer-Review Scores, but Initial-Review Structure Bounds the Movement](https://arxiv.org/abs/2606.22166)
- [OpenAI reasoning parameter](https://developers.openai.com/api/docs/guides/reasoning)
