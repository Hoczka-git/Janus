# Consolidated ADR Decisions: ADR-003, ADR-004, ADR-005

Synthesizes the review recommendations for the three architecture decisions under the
Janus/Mermes roadmap and records the disposition of each. This document is the
single source of truth that implementation tasks downstream are linked against.

## ADR-003 — Canonical Review Topology

- **File:** `docs/decisions/003-canonical-review-topology.md`
- **Status:** Accepted
- **Recommendation source:** `docs/research/adr-003-review.md`

**Decision:** Model A (Native Review Lane) is adopted as the canonical review
topology. Review is a phase of the same task — the implementer hands off via
`kanban_request_review()`, the task enters the `review` status, a reviewer worker
is spawned, and the reviewer either approves (`kanban_complete`) or returns for
rework (`kanban_request_changes`). Model B (Reviewer-Child Workflow) is rejected.

**Implementation work:** `t_3f19d507` (patch `prompt_builder.py` Model B language),
`t_7688471b` (document `delegate_task` review probes + human-in-the-loop path),
`t_a7678ba8` (add tests for review topology edge cases).

## ADR-004 — Safe Sync-and-Integrate Workflow

- **File:** `docs/decisions/004-safe-sync-integrate-workflow.md`
- **Status:** Accepted (with implementation caveats)
- **Recommendation source:** `docs/research-findings/adr004_review_recommendation.md`

**Decision:** The core design (5-phase workflow: sync → implement → verify →
integrate → complete, fail-stop gates, no shared dev branch, atomic integration)
is accepted. The full workflow is implemented and enforced in the completion
path: Phase 1 re-sync at gate time, Phase 3 default-on deterministic pre-completion
gate, Phase 4 active safe integration, and Phase 5 gating on Phases 1/3/4 via
`run_completion_gates()` in `complete_task()`. Evidence artifacts
(`pre_completion_report.json`, `integration_report.json`) are produced.

Caveats (residual): Phase 1 is enforced at gate time (pre-completion) but not
at task-start time — this is an explicit design choice documented in
`docs/design/sync_integration_workflow_design.md`. Phase 1 start-time invocation
remains a separate decision if/when desired.

**Implementation work (linked to implementation task IDs):**
- `t_021f3833` — Phase 1 sync primitive (`git_sync.py:sync_branch()`).
- `t_e2f37f8c` — Phase 3 default-on deterministic checks (`_phase3_pre_completion_gate()`).
- Phase 4 (active safe integration) + Phase 5 (gated completion) — PR #189
  (`2a947b8`), branch `wt/t_2f105d50`; implemented in `src/janus/integration.py`
  (`integrate_task()`) and `src/janus/services/tasks.py` (`run_completion_gates()`).
- `t_4cd8c17f` — Gate `complete_task()` on Phase 3 + Phase 4 passing (Phase 5).
  **Delivered by PR #189; depends on Phase 4 integration.**
- `t_9d03b5ad` — Reconcile `kanban_db.py` references with `services/tasks.py`;
  add ADR→actual-file mapping table.

## ADR-005 — Activity Data Ingestion Layer

- **File:** `docs/decisions/005-activity-data-ingestion-layer.md`
- **Status:** Accepted (on consolidation)
- **Recommendation source:** `docs/research/adr-005-review.md`

**Decision:** The controlled-write-gateway design (normalize → validate → dedup
→ dispatch pipeline, `ActivityRecord` dataclass, `atomic_io` primitives) is sound
and already implemented. Caveats: the service migration is incomplete —
`tasks.py`, `goals.py`, and `milestones.py` still use `data_protection.py`, not
`atomic_io`. Two overlapping protection layers (`atomic_io.py` vs
`data_protection.py`) must be consolidated.

**Implementation work:**
- `t_20dfee19` — Decide and document the consolidation strategy for the
  `atomic_io` vs `data_protection` overlap (this is a docs decision record).
- `t_d14e6113` — Migrate services/goals/milestones and integration modules to
  route writes through `atomic_io.read_modify_write()`; add a CI grep gate in
  `verification.py` to enforce the single write gateway.

## ADR Disposition Summary

| ADR  | Status                  | Rationale                                   |
| ---- | ----------------------- | ------------------------------------------- |
| 003  | Accepted                | Model A fully implemented and tested        |
|| 004  | Accepted                | Full workflow implemented; enforced in completion path; Phase 1 start-time invocation is an explicit design choice |
| 005  | Accepted (on consensus) | Design implemented; migration incomplete    |
