# ADR-003, ADR-004, ADR-005: Consolidated Decisions

**Date:** 2026-09-16
**Last verified:** 2026-09-24
**Consolidator:** t_77e35ea8 (implementer)
**Source reviews:**
- ADR-003: t_985404ff — `docs/research/adr-003-review.md`
- ADR-004: t_9f249780 — `docs/research-findings/adr004_review_recommendation.md`
- ADR-005: t_b41ffe1f — `docs/research/adr005-review.md`

---

## Executive Summary

All three ADRs were reviewed and **accepted**. None were rejected.

| ADR | Recommendation | Status Change | Key Rationale |
|-----|----------------|---------------|---------------|
| ADR-003 (Canonical Review Topology) | **ACCEPT** | Proposed → Accepted | Model A (Native Review Lane) is fully implemented, tested (5,359 lines), and enforced across all subsystems. Model B never existed in code. |
| ADR-004 (Safe Sync-and-Integrate Workflow) | **ACCEPT** | Proposed → Accepted | Core 5-phase design is sound and fully implemented post-PR-189. All phases wired into completion path. Only Phase 1 start-time invocation remains an explicit deferred design choice. |
| ADR-005 (Activity Data Ingestion Layer) | **ACCEPT (with caveats)** | Proposed → Accepted (on consolidation) | Core design is correct and partially implemented; service migration incomplete and two overlapping protection layers (`atomic_io` vs `data_protection`) need consolidation. |

**No ADRs were rejected.** Model B of ADR-003 is rejected as the canonical review topology (Model A is adopted), but this is part of ADR-003 itself, not a separate ADR rejection.

---

## Decision 1: ADR-003 — Canonical Review Topology for Hermes Kanban

**Review task:** t_985404ff
**Recommendation:** ACCEPT
**Status:** `docs/decisions/003-canonical-review-topology.md` — Updated from `Proposed` to `Accepted`

### Rationale

ADR-003 does not propose a new architecture — it formalizes the existing one. The codebase has already committed to Model A (Native Review Lane) through implementation, testing, and enforcement across all subsystems:

| Subsystem | Evidence | Status |
|-----------|----------|--------|
| DB Schema | `VALID_STATUSES` includes `review`; `request_review()`, `request_changes()`, `claim_review_task()`, `reopen_review_task()` | Complete |
| Tool surface | `kanban_request_review` and `kanban_request_changes` registered with handlers | Complete |
| Dispatcher | Review lane dispatched with `sdlc-review` skill force-loaded | Complete |
| Watchers | `review_requested` and `changes_requested` events wake subscribers | Complete |
| CLI | `hermes kanban request-review` and `hermes kanban reopen-review` subcommands | Complete |
| Skill system | `sdlc-review/SKILL.md` explicitly designed for Model A; rejects Model B | Complete |
| Event provenance | `{implementer, reviewer, summary, round}` persisted in event payloads | Complete |
| Parent re-gating | `_landing_status_after_parents()` ensures tasks returning from review wait | Complete |

Model B (Reviewer-Child Workflow) is **referenced in prose but never implemented** — it exists only in the worker prompt's "pre-created review, QA, or release child" guidance, which creates ambiguity. It is correctly rejected.

The test suite provides ~5,359 lines of dedicated review-topology tests across 5 test files.

### Implementation Caveats (Required Follow-Up)

1. **Patch `prompt_builder.py` (lines 321-324)** — Remove the Model B "pre-created child" language from `KANBAN_GUIDANCE`, replacing with Model A-only guidance.
2. **Test gaps** (medium/low severity, not blockers):
   - Add direct tests for `_landing_status_after_parents()` with various parent states
   - Add `_escalate_review_loop_exceeded()` payload structure test
   - Add `reopen_review_task()` edge case tests
   - Add `changes_requested` watcher notification test

### Rejection Rationale

**Model B (Reviewer-Child Workflow)** is rejected as the canonical review topology. Rejection rationale:
1. **Context fragmentation** — A reviewer child has its own title/body/metadata; handoff evidence must be duplicated or linked manually. Model A keeps everything on one card.
2. **No provenance chain** — If the reviewer requests changes, there is no built-in way to ensure the same reviewer gets the re-review. Model A solves this via event payloads.
3. **Conflict with the worker protocol** — The "pre-created child" and "never request same-card review" paths are confusing for workers to choose between. Model A makes the choice unambiguous.
4. **Chicken-and-egg deadlock risk** — If the review child's parent is the implementer, and the implementer cannot complete until the review child is done, the system can deadlock.
5. **Orchestrator overhead** — Model B requires the implementer to create, link, and reference the review child, adding API surface area and failure modes.

### Remaining Uncertainty

1. **Parallel review fan-out** — The interaction between `delegate_task`-based review probes and the native review lane is acknowledged as undocumented.
2. **Human-in-the-loop review** — When a human pulls a review task manually, the path works correctly but should be documented in the operator guide.
3. **Review loop limits** — `consecutive_failures` is preserved across review cycles; no separate "review loop" counter exists. `_escalate_review_loop_exceeded` provides a safety net but whether a dedicated guard is needed is an open question.

---

## Decision 2: ADR-004 — Safe Sync-and-Integrate Workflow for Coding Tasks

**Review task:** t_9f249780
**Recommendation:** ACCEPT
**Status:** `docs/decisions/004-safe-sync-integrate-workflow.md` — Updated from `Proposed` to `Accepted`

### Rationale (Post-PR-189)

ADR-004's core design is sound and fully implemented post-PR-189:
- The 5-phase gated workflow (Pre-Implementation Sync → Implementation → Pre-Completion Gate → Safe Integration → Completion) is wired into `complete_task()` via `run_completion_gates()`.
- Fail-stop gates with structured reason codes, no shared `dev` branch, atomic integration with rollback are all implemented.
- Phase 1: `_phase1_resync()` in `tasks.py` (gate-time; start-time remains an explicit deferred design choice).
- Phase 3: `_phase3_pre_completion_gate()` in `tasks.py` — clean tree, `git diff --check`, test re-run after rebase.
- Phase 4: `integrate_task()` in `src/janus/integration.py` — active merge/push/rollback.
- Phase 5: `run_completion_gates()` in `complete_task()` gates completion on Phases 1+3+4.

### Current Implementation Status vs. ADR-004 (Post-PR-189)

| ADR Phase | Current State | Gap |
|-----------|---------------|-----|
| Phase 1 — Pre-Implementation Sync | Implemented (`git_sync.py:sync_branch()`, wired into gate via `tasks.py:_phase1_resync()`); start-time invocation is an explicit deferred design choice | None at gate time; start-time sync deferred |
| Phase 2 — Implementation | Worktree isolation exists | None |
| Phase 3 — Pre-Completion Gate | Default-on deterministic gate implemented (`tasks.py:_phase3_pre_completion_gate()`) | None |
| Phase 4 — Safe Integration | Active `integrate_task()` in `src/janus/integration.py`, merge/push/rollback implemented | None |
| Phase 5 — Gated Completion | `run_completion_gates()` in `complete_task()` enforces Phases 1+3+4 | None |

### Rejection Rationale

**No ADR-004 was rejected.** ADR-004 itself is accepted. However, three alternatives within ADR-004 are correctly rejected:
- **Alternative A** (single post-implementation sync + merge) — rejected because tests run before final sync; rebase-induced breakage is not caught.
- **Alternative B** (CI-only verification) — rejected because CI runs after push, not before `kanban_complete`; CI does not verify "tests pass after the final rebase onto target."
- **Alternative C** (pre-commit hooks) — rejected because hooks slow down every commit, can be bypassed, and do not cover the "final sync before completion" or "post-merge verification" steps.
- **Alternative D** (shared `dev` branch) — rejected because shared branches are a source of contention, require locking, and complicate cleanup.

### Recommended Implementation Path

All priorities are now implemented post-PR-189:

**Priority 1** (DONE):
- Auto-invoke `sync_branch()` at task start — wired into gate via `_phase1_resync()` (gate time). Start-time sync remains an explicit deferred design choice.
- Extend `verification.py` with default-on deterministic checks — done in `_phase3_pre_completion_gate()` (clean tree, `git diff --check`, test re-run after rebase).
- Generate `pre_completion_report.json` from `VerificationReport` — done.

**Priority 2** (DONE):
- Phase 4 model decided: **Option B (automated step in completion flow)**. `src/janus/integration.py:integrate_task()` is called from `complete_task()` via `run_completion_gates()`.

**Priority 3** (DONE):
- ADR-004 text already references `services/tasks.py` as the completion path.
- Phase 4 description updated to reflect Option B implementation model.

---

## Decision 3: ADR-005 — Activity Data Ingestion Layer

**Review task:** t_b41ffe1f
**Recommendation:** ACCEPT (with implementation caveats)
**Status:** `docs/decisions/005-activity-data-ingestion-layer.md` — Updated from `Proposed` to `Accepted (on consolidation)`

### Rationale

The architectural design is correct and well-reasoned. The ingestion layer implementation (`activity_ingest.py` + `atomic_io.py`) is solid. The rejected alternatives (full persistence rewrite, event sourcing, per-call atomic_write only) are correctly dismissed:
- **Alternative A** (full persistence-layer rewrite to JSON/SQLite) — rejected because it breaks the existing markdown-editing workflow, is far outside scope, and contradicts ADR-002.
- **Alternative B** (append-only log / event sourcing) — rejected because it adds a second source of truth and a replay/compaction step that does not exist today.
- **Alternative C** (per-call atomic_write only, no ingestion service) — rejected because it addresses crash-safety but not normalization, deduplication, or the "model cannot regenerate files" rule.
- **Alternative D** (model writes via CLI subprocess) — rejected because the model IS the Janus agent; direct import + gateway routing is the established pattern.

The core design strengths are strong: single entry point with typed `ActivityRecord` dataclass, normalize → validate → dedup → dispatch pipeline, config-driven file routing, tolerance-window dedup, observability via the existing `emit()` convention, and 1,818 lines of test coverage.

### Implementation Caveats (Two Prerequisites)

1. **Service migration incomplete.** The ADR's central constraint — "All Janus service functions that the sync listener dispatches to will be refactored to delegate file I/O to `atomic_io`" and "No service method retains a direct `write_text` call to any `data/` file" — is violated. `tasks.py`, `goals.py`, and `milestones.py` still use `data_protection.protected_write`, not `atomic_io`. Only the new `activity_ingest.py` routes through `atomic_io`.

2. **Two overlapping protection layers need consolidation.** `data_protection.py` (pre-existing, 847 lines, more features) and `atomic_io.py` (new, 224 lines, simpler) coexist with overlapping but non-identical semantics:

| Feature | `data_protection.py` | `atomic_io.py` |
|---------|----------------------|----------------|
| Atomic write | Yes (write-to-temp + os.replace) | Yes (write-to-temp + os.replace) |
| Backup | Timestamped .bak with rotation | Simple path.bak (overwrite) |
| Conflict detection | SHA-256 hash comparison | inode/mtime/size snapshot |
| File locking | fcntl.flock (POSIX advisory) | None (detection + retry) |
| Regeneration gating | Yes (change-fraction threshold) | None |
| Post-write verification | Yes (re-read + compare) | None |
| Concurrency retry | No | Yes (configurable exponential backoff) |

Resolution options:
- (a) Deprecate `data_protection.py`, migrate all callers to `atomic_io` + add missing features (regeneration gating, file locking, post-write verification, rotating backups).
- (b) Layer `atomic_io` as the low-level primitive, keep `data_protection` as the policy layer wrapping `atomic_io`.
- (c) Keep two layers — but this contradicts the ADR's "single choke point" principle.

### Rejection Rationale

**No ADR-005 was rejected.** ADR-005 itself is accepted. The rejected alternatives (full persistence rewrite, event sourcing, per-call atomic_write only, CLI subprocess) are all correctly dismissed as outlined above.

### Remaining Uncertainty

1. Is the service migration already planned in a separate task? The ADR mentions children `t_0c3b8b86` and `t_2b7957a3` for implementation, but their scope is unknown without inspecting them.
2. Will the team prefer rotating backups (`data_protection`'s approach) or simple `.bak` (`atomic_io`'s approach)? This affects whether `data_protection`'s backup logic needs porting into `atomic_io`.

---

## Action Items

### Completed in this task (t_77e35ea8):
- [x] Collected accept/reject recommendations for ADR-003, ADR-004, ADR-005 from parent review tasks
- [x] Updated ADR-003 status: `Proposed` → `Accepted`
- [x] Updated ADR-004 status: `Proposed` → `Accepted (with implementation caveats)` → later updated to `Accepted` post-PR-189
- [x] Updated ADR-005 status: `Proposed` → `Accepted (on consolidation)`
- [x] Created this consolidated summary document

### Outstanding follow-up work (tracked separately):
- **ADR-003 follow-ups:**
  - Patch `prompt_builder.py` to remove Model B language from `KANBAN_GUIDANCE`
  - Add tests for `_landing_status_after_parents()`, `_escalate_review_loop_exceeded()`, `reopen_review_task()` edge cases, `changes_requested` watcher notification
  - Document `delegate_task` review probes interaction and human-in-the-loop review path
- **ADR-004 follow-ups (DONE post-PR-189):**
  - [x] Reconcile `kanban_db.py` references with `services/tasks.py`
  - [x] Auto-invoke `sync_branch()` at task start (Phase 1) — wired into gate via `_phase1_resync()`
  - [x] Extend `verification.py` with default-on deterministic checks (Phase 3) — done in `_phase3_pre_completion_gate()`
  - [x] Decide and implement Phase 4 integrator model — Option B implemented in `src/janus/integration.py`
  - [x] Add gate enforcement to `complete_task()` (Phase 5) — `run_completion_gates()` implemented
- **ADR-005 follow-ups:**
  - Migrate `tasks.py`, `goals.py`, `milestones.py` to route writes through `atomic_io`
  - Resolve `atomic_io` vs `data_protection` layer overlap (deprecate, compose, or document coexistence)
  - Address backup-strategy regression (port rotating backups into `atomic_io` or accept the tradeoff)
