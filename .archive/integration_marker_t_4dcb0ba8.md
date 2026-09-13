# Integration Marker — t_4dcb0ba8

**Task:** t_4dcb0ba8 — Implement research-to-finding connection

**Status:** Integration verified. PR #114 merged to master. CI green (SUCCESS).

**Merge commit:** 04f293ca60d98c3ac9d523a2138f620fdc2cc5a5 (on origin/master)

**Tests:** 1547 passed.

## Summary

When a Hermes Kanban task with `janus_domain: object: research|finding` completes,
`_ingest_research` in `src/janus/services/execution_feedback.py` now closes the
research-to-finding connection:

1. **Knowledge pipeline** — runs `validate_artifact` (Step 1 intake validation)
   and `generate_summary` (Step 2 summary generation) to produce a
   `KnowledgeSummary` IR from the persisted `ResearchArtifact`.
2. **Goal linking** — links the artifact to its declared goals bidirectionally
   via `services.artifact_linking.link_artifact_to_goal`.
3. **Attention emission** — converts knowledge gaps from the `KnowledgeSummary`
   into attention-item dicts via
   `services.knowledge_pipeline.emit_knowledge_gaps_as_attention`.

The connection is resilient: pipeline failures, link errors, and validation
warnings are captured in the result dict without aborting ingestion.

## Changed files

- `src/janus/services/execution_feedback.py` — `_ingest_research` extended with
  pipeline + goal linking + attention emission.
- `tests/test_execution_feedback.py` — 7 new tests in
  `TestResearchToFindingConnection` class.
