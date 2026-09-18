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
is accepted. Caveats: the spec referenced non-existent `hermes_cli/kanban_db.py`;
the actual completion path is `src/janus/services/tasks.py:complete_task()`.
Phase 4 (integrator) was absent and must be designed. Phase 3 (verifier) is
opt-in/contract-based, not default-on.

**Implementation work (linked to implementation task IDs):**
- `t_021f3833` — Auto-invoke `sync_branch()` at task start (Phase 1); rebase with
  `--force-with-lease`; route conflicts to `merge-reconciler`.
- `t_e2f37f8c` — Extend `verification.py` with default-on deterministic checks
  (Phase 3): working tree clean, `git diff --check`, test re-run after rebase.
- `t_467d7d4f` — Decide and implement Phase 4 integrator model (merge/push/rollback,
  `integration_report.json`, structured reason codes).
- `t_4cd8c17f` — Gate `complete_task()` on Phase 3 + Phase 4 passing (Phase 5).
  **Depends on `t_467d7d4f`.**
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
| 004  | Accepted (w/ caveats)   | Design sound; paths/Phase 3/4 need work     |
| 005  | Accepted (on consensus) | Design implemented; migration incomplete    |
