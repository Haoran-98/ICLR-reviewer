---
name: modular-review-grounder-full
description: Distill all eligible completed S4 paper and initial-review pairs into conditional review mechanisms, curate traceable local updates, and export composable review modules.
---

# Modular Review Grounder — full S4 corpus

Use [the runner](../../scripts/full_s4_review_skills.py). Preserve the sealed S4
corpus and previous pilot libraries. Model: gpt-6-luna; reasoning: medium; at most
three simultaneous requests. No training, rebuttal processing, or comparison arm.

## Induce mechanisms from sources

Process every completed S4 paper for eligibility, across all years and areas.
Use earliest observed reviewer-authored reviews available before the first known
author response. Exclude chairs, meta-reviews, and temporally unverified records.
Keep original review fields and exact source offsets. Version alignment with the
current manuscript remains unknown unless independently established.

Abstract a reusable concern as **review object → applicability/assumptions →
possible failure mechanism → consequence → verification and clearing evidence**.
Distinguish the reported observation from the induced conditional check. Do not
infer the reviewer's hidden reasoning, certify a historical allegation, or turn
one paper's technical vocabulary into a universal checklist.

Useful lenses, only when supported by source observations, include claim scope,
transfer of guarantees between stages, correctness of definitions/inference,
evidence design, robustness boundaries, comparative attribution, and feasibility.
Preserve concrete scientific scope within each lens. Match evidence requirements
to the contribution: inspect proofs for theoretical claims and experiments for
empirical claims. Record an unavailable appendix as an access gap. Clear a concern
using evidence that addresses its failure mechanism. Verify definitions and
quantified conditions before alleging contradictions. Separate access gaps, clarification requests,
testable hypotheses, and supported defects.

Split independent technical objects or failure mechanisms into atoms. Preserve
the context linking a follow-up question to its parent concern. Account for every
input review unit: extracted atoms, no concern, or an explicit unresolved reason.
When evidence packs are partial, missing evidence stays unknown. Retain all
original text and split requests to account for every review unit.

## Curate and compose

Use general, domain, method, task, and specialty levels. Equivalent rules share
the technical object, failure mechanism, and compatible clearing conditions;
matching broad topics alone is insufficient. Keep useful single-source rules as
candidates. Source-supported rules require two independent paired manuscripts;
general rules additionally require two areas. Record provenance and scientific adjudication as separate statuses.

Apply localized AutoManual/ACE-style additions, refinements, merges, splits, or
deprecations. Keep stable IDs, before/after versions, evidence, and a durable
candidate disposition ledger. Preserve minority scopes and conflicting evidence;
do not inflate support by combining different clauses. Unresolved candidates
remain inspectable after the bounded two-visit curation pass.

Export supported modules and separate candidate modules with explicit status.
For later reviewing, retrieve a small combination by S4 area, scientific scope,
and review mechanism; inspect applicability before emitting concerns. Keep full
main text at review time, verifying each new paper's boundary independently.
Freeze the library before evaluation; evaluation reviews must never enter the
review input or directly modify the library. Papers used here become development
sources, including any papers that were held out in earlier pilots.

This combines AutoManual-style case induction, ACE-style local updates, and
ReviewGrounder-style evidence grounding in the project runner.
