---
name: domain-review-grounder
description: Distill reusable domain review criteria from paired historical papers and initial reviews, then generate an evidence-grounded initial review for a new paper using its S4 labels. Use for the project's untrained domain reviewer prototype and domain skill distillation.
---

# Domain Review Grounder

Use S4 labels to route a manuscript to a compact domain skill. Historical reviews
teach inspection criteria; the new manuscript supplies all evidence for its review.
This adapts ReviewGrounder's rubric and grounding mechanisms to a single review
call.

## Historical skill

- Pair historical review comments with the corresponding paper passages. Preserve
  source IDs and distinguish reviewer preferences from verified manuscript facts.
- Distill conditional checks: applicability, what to inspect, evidence needed,
  when a problem is consequential, and when to abstain.
- A reusable check needs review examples from at least two different papers and
  paired manuscript passages. Record source support as provenance; assess
  scientific correctness through independent adjudication.
- Keep the target paper and its versions out of the historical sources. Anonymous
  reviewer aliases do not identify the same person across papers.

## New manuscript

1. Match existing S4 node IDs and the skill's narrower scope. Shared broad labels
   alone do not establish expertise; abstain when scope is unsupported.
2. Load only the selected domain skill and a balanced manuscript evidence pack.
3. In one model call, inspect claim support, methods, experiments, and positioning,
   then write the initial review. Recheck each historical concern against this paper.
4. Cite supplied manuscript passage IDs for material judgments. A concern records
   the observation, consequence, requested clarification, and uncertainty.
5. Distinguish a demonstrated issue from something not found in the supplied pack.
   Do not assert a missing baseline, proof, or experiment from retrieval failure.
   External novelty comparisons remain unverified without the cited source.
6. Base the overall rating on stated evidence and unresolved issues. Do not average
   imaginary reviewer scores. Limit confidence when the evidence pack is partial.

The target's human reviews, acceptance result, reviewer identities, and author
responses are excluded from generation. Do not enter rebuttal or score-change mode.

## Project runner

Use [domain_review_skill.py](../../scripts/domain_review_skill.py) to prepare the
read-only development snapshot, distill once, and review once. The runner saves
input hashes, S4 route evidence, source passages, raw responses, usage, and checks.
It reuses matching completed calls; failed calls remain recorded for explicit recovery.
Data-derived domain skills stay in the selected external run directory.

Source: [ReviewGrounder, ACL 2026](https://aclanthology.org/2026.acl-long.1477/).
