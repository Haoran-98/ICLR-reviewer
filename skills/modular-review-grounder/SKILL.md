---
name: modular-review-grounder
description: Distill historical paper and initial-review pairs into reusable modular review checks, curate localized AutoManual/ACE-style updates, and compose checks for new manuscripts using existing S4 evidence.
---

# Modular Review Grounder

Use [the runner](../../scripts/modular_review_skill.py) for the 100-source/five-target pilot.
Keep the sealed S4 data read-only. Use S4 core entities as retrieval facets.
Models remain frozen.

Pair atomic historical observations with manuscript passages. Distill applicability,
inspection steps, issue conditions, clearing conditions, consequences and exceptions.
Reviewer preferences and unverified concerns remain weak observations. Missing
retrieved evidence remains unknown. Do not reconstruct imaginary reasoning traces.

Keep general, domain, method, task and specialty modules composable. A rule needs
paired evidence from two independent manuscripts to be source-supported; a general
rule also needs two source areas. Scientific validity requires independent adjudication.
Single-paper observations remain cases or candidate checks.

Curate local deltas with stable rule IDs. Record the previous and next contents,
reason and candidate sources for additions, refinements, merges, splits and
deprecations. Distinguish rule errors from retrieval and execution failures. Retain
unresolved conflicts instead of inferring correctness from reviewer frequency.

Freeze the library before composing up to ten relevant checks for each target.
Recheck applicability using the target manuscript; do not assume every check fails.
Generate an initial review with target-only citations and conservative confidence.
Exclude target reviews, scores, decisions and author responses. Trial reviews can
propose later investigation but cannot directly change shared rules.

Adapted mechanisms:
- [AutoManual, NeurIPS 2024](https://openreview.net/forum?id=Pwl9n4zlf5): structured rules, cases and logs.
- [ACE, ICLR 2026](https://openreview.net/forum?id=eC4ygDs02R): localized itemized deltas and deduplication.
- [ReviewGrounder, ACL 2026](https://aclanthology.org/2026.acl-long.1477/): rubric-guided evidence grounding.

The implementation combines these mechanisms in a bounded extraction, curation and review workflow.
Stop after 100 extractions, ten curation batches and five trial reviews for inspection.
