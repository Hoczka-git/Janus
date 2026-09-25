# ADR-003, ADR-004, ADR-005: Consolidated Decisions

**Date:** 2026-09-16
**Last verified:** 2026-09-25
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
| ADR-005 (Activity Data Ingestion Layer) | **ACCEPT** | Proposed → Accepted | Core design is correct and implemented; `data_protection.py` was deleted, all callers migrated to `atomic_io` via `data_integrity.py` (PR #204). Backup-strategy preference (rotating vs simple `.bak`) remains an open design choice. |

**No ADRs were rejected.** Model B of ADR-003 is rejected as the canonical review topology (Model A is adopted), but this is part of ADR-003 itself, not a separate ADR rejection.

> **Follow-up disposition (2026-09-25, task t_b84710e6):** ADR-003 §Implementation Caveats
> and §Remaining Uncertainty below were re-baselined for historical accuracy; the items are
> reported in §Follow-up disposition with current disposition. No stale follow-ups remain.

---

## Decision 1: ADR-003 — Canonical Review Topology for Hermes Kanban

**Review task:** t_985404ff
**Recommendation:** ACCEPT
**Status:** `docs/decisions/003-canonical-review-topology.md` — `Proposed` → `Accepted`

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

### Implementation Caveats (Follow-Up Disposition)

> **All follow-ups RESOLVED (2026-09-25, task t_b84710e6).** The items below were tracked as required follow-ups after this ADR review. All have been implemented and verified in subsequent work — see the consolidated follow-up disposition in §Follow-up disposition below.
>
> 1. **Patch `prompt_builder.py` (lines 321-324).** RESOLVED in the Hermes agent repo (commit `5c275ad8b`, PR #29). `GAP-003` closed: 0 grep matches for Model B language in `KANBAN_GUIDANCE`.
> 2. **Test gaps** (medium/low severity, not blockers): RESOLVED.
>    - `tests/test_kanban_review_topology.py` (7 tests, 256 lines) covers `_landing_status_after_parents()` parent-state matrix, `reopen_review_task()` edge cases (non-review, post-completion, parent-gating), `block_loop_detected` escalation payload structure, and `changes_requested` watcher notification (`test_changes_requested_wakes_origin_subscriber`).
>    - `_escalate_review_loop_exceeded` payload test: the real loop-escalation mechanism is `block_task`'s `block_loop_detected` event (see test above); a dedicated standalone function was never built and remains an open design question, not a stale follow-up.
> 3. **Document `delegate_task` review probes interaction and human-in-the-loop review path.** RESOLVED in `docs/decisions/003-review-probes-and-human-review.md` (supplement, 359 lines). Covers probe semantics, interaction with the native review lane, human-in-the-loop review, and the distinction from Model B.

### Rejection Rationale

**Model B (Reviewer-Child Workflow)** is rejected as the canonical review topology. Rejection rationale:

1. **Context fragmentation** — A reviewer child has its own title/body/metadata; handoff evidence must be duplicated or linked manually. Model A keeps everything on one card.
2. **No provenance chain** — If the reviewer requests changes, there is no built-in way to ensure the same reviewer gets the re-review. Model A solves this via event payloads.
3. **Conflict with the worker protocol** — The "pre-created child" and "never request same-card review" paths are confusing for workers to choose between. Model A makes the choice unambiguous.
4. **Chicken-and-egg deadlock risk** — If the review child's parent is the implementer, and the implementer cannot complete until the review child is done, the system can deadlock.
5. **Orchestrator overhead** — Model B requires the implementer to create, link, and reference the review child, adding API surface area and failure modes.

### Remaining Uncertainty (Follow-Up Disposition)

> **Items 1 and 2 RESOLVED (2026-09-25, task t_b84710e6).** The topics they raised have been addressed in subsequent work:
> - **Item 1 (parallel review fan-out):** Documented in `docs/decisions/003-review-probes-and-human-review.md` §1 — the `delegate_task` probe pattern is described, including why it differs from Model B and how it coexists with the native review lane.
> - **Item 2 (human-in-the-loop review):** Documented in `docs/decisions/003-review-probes-and-human-review.md` §2.8 — human review path is described and confirmed as Model A compliant.
>
> **Item 3 (review loop limits)** remains an open question. `_escalate_review_loop_exceeded` is not present in the current implementation; the real loop-escalation mechanism is `block_task`'s `block_loop_detected` event, emitted when a task is re-blocked for the same cause past `BLOCK_RECURRENCE_LIMIT` (see `tests/test_kanban_review_topology.py` `test_block_loop_detected_payload_structure` for the payload shape any future guard relies on). This is an open design question, not a stale follow-up.

---

## Decision 2: ADR-004 — Safe Sync-and-Integrate Workflow for Coding Tasks

**Review task:** t_9f249780
**Recommendation:** ACCEPT
**Status:** `docs/decisions/004-safe-sync-integrate-workflow.md` — `Proposed` → `Accepted`

### Rationale

ADR-004's core design is sound and fully implemented post-PR-189:

- The 5-phase gated workflow (Pre-Implementation Sync → Implementation → Pre-Completion Gate → Safe Integration → Completion) is wired into `complete_task()` via `run_completion_gates()`.
- Fail-stop gates with structured reason codes, no shared `dev` branch, atomic integration with rollback are all implemented.
- Phase 1: `_phase1_resync()` in `tasks.py` (gate-time; start-time remains an explicit deferred design choice).
- Phase 3: `_phase3_pre_completion_gate()` in `tasks.py` — clean tree, `git diff --check`, test re-run after rebase.
- Phase 4: `integrate_task()` in `src/janus/integration.py` — active merge/push/rollback.
- Phase 5: `run_completion_gates()` in `complete_task()` gates completion on Phases 1+3+4.
- Alternatives are well-reasoned: Alternative A (single post-impl sync) is correctly rejected; Alternative B (CI-only) is correctly rejected because CI runs after push, not before `kanban_complete`.

### Specification Gaps (Resolved)

> **All gaps below are RESOLVED.** Each was a prerequisite for implementation and
> has been addressed in subsequent work (PRs #176, #178, #189, #250).
>
> ~~1. **ADR references `kanban_db.py` — does not exist in this codebase.**~~ **RESOLVED.**
> The ADR-to-Codebase Mapping Table (ADR-004 §Reconciliation) explicitly maps every
> `kanban_db.py` reference to the actual code location in `src/janus/services/tasks.py`
> and `src/janus/integration.py`. The stale `kanban_db.py` references are reconciled;
> the actual completion path is `src/janus/services/tasks.py:complete_task()`.
>
> ~~2. **Phase 4 integrator identity is deferred to a non-existent task.**~~ **RESOLVED.**
> Phase 4 Integrator Model: **Option B (Pragmatic Automated Step)** adopted — integration
> is an automated step in the completion path, not a separate agent (ADR-004 §Neutral).
> Implemented in `src/janus/integration.py` (`integrate_task()`). The
> deferred task `t_36b3d88f` is superseded; integration was delivered incrementally
> through phase-specific tasks.
>
> ~~3. **Phase 3 verification is contract-based, not deterministic.**~~ **RESOLVED.**
> Default-on deterministic checks run the three deterministic
> checks — `working_tree_clean`, `git_diff_check`, `tests_pass_after_rebase` — wired into `run_completion_gates()`
> (`src/janus/services/tasks.py`, PR #176, 15 tests).

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

> **All items below are IMPLEMENTED.** Priority 1 items delivered via PRs #176/#178;
> Priority 2 (Phase 4 integrator model) resolved via Option B; Priority 3
> (reconciliation) documented in ADR-004 §Reconciliation and this doc's
> Specification Gaps section.

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
**Recommendation:** ACCEPT
**Status:** `docs/decisions/005-activity-data-ingestion-layer.md` — `Proposed` → `Accepted`

### Rationale

The architectural design is correct and well-reasoned. The ingestion layer implementation (`activity_ingest.py` + `atomic_io.py`) is solid. The rejected alternatives (full persistence rewrite, event sourcing, per-call atomic_write only) are correctly dismissed:

- **Alternative A** (full persistence-layer rewrite to JSON/SQLite) — rejected because it breaks the existing markdown-editing workflow, is far outside scope, and contradicts ADR-002.
- **Alternative B** (append-only log / event sourcing) — rejected because it adds a second source of truth and a replay/compaction step that does not exist today.
- **Alternative C** (per-call atomic_write only, no ingestion service) — rejected because it addresses crash-safety but not normalization, deduplication, or the "model cannot regenerate files" rule.
- **Alternative D** (model writes via CLI subprocess) — rejected because the model IS the Janus agent; direct import + gateway routing is the established pattern.

The core design strengths are strong: single entry point with typed `ActivityRecord` dataclass, normalize → validate → dedup → dispatch pipeline, config-driven file routing, tolerance-window dedup, observability via the existing `emit()` convention, and 1,818 lines of test coverage.

### Implementation Caveats (Resolved)

> Both caveats are **RESOLVED** by ADR-005 Amendment 01 and the associated
> migration (PR #204).
>
> ~~1. **Service migration incomplete.**~~ **RESOLVED.** All service functions
> have been migrated from `data_protection.protected_write` to `atomic_io`.
> `data_protection.py` was deleted (PR #204). The ADR-005
> "Resolved" section (§9.2) confirms: "No service write path opens a `data/`
> file with a raw `open()` or `write_text()` call outside `atomic_io` or its
> `read_modify_write` wrapper."
>
> ~~2. **Two overlapping protection layers need consolidation.**~~ **RESOLVED.**
> ADR-005 Amendment 01 (`docs/decisions/005-01-atomic_io-vs-data_protection-amendment.md`)
> adopted **Option (b): Layered composition.** `atomic_io` is the canonical
> low-level primitive; `data_protection`'s policy-layer features (rotating
> backups, flock, post-write verification, regeneration gating) live in
> `data_integrity.py` and wrap `atomic_io`. The dependency direction is
> one-way: `data_integrity` → `atomic_io`.

### Implementation Status (Post-PR-204)

The ADR-005 implementation caveats are resolved:

1. **Service migration complete.** All legacy `protected_write` callers were migrated to `atomic_io`/`data_integrity` in PR #204. `data_protection.py` was deleted. The "two overlapping layers" problem described in the original ADR is resolved by deletion + re-layering: `atomic_io` = mechanism, `data_integrity.py` = policy & recovery.

2. **Backup-strategy preference remains open.** Choice between rotating timestamped backups (former `data_protection` approach) vs simple `.bak` (current `atomic_io` approach). Current behavior uses simple `.bak`; rotating backups can be added if needed.

### Rejection Rationale

**No ADR-005 was rejected.** ADR-005 itself is accepted. The rejected alternatives (full persistence rewrite, event sourcing, per-call atomic_write only, CLI subprocess) are all correctly dismissed as outlined above.

### Remaining Uncertainty (Follow-Up Disposition)

> **Item 1 (service migration scope) RESOLVED (2026-09-25, task t_b84710e6).** The service migration is complete — all `protected_write` callers were migrated to `atomic_io` / `data_integrity` in PR #204; `data_protection.py` was deleted. The "two overlapping layers" problem is resolved by deletion + re-layering: `atomic_io` = mechanism, `data_integrity.py` = policy & recovery. See §Implementation Status above.
>
> **Item 2 (backup-strategy preference) remains open.** Choice between rotating timestamped backups (former `data_protection` approach) vs simple `.bak` (current `atomic_io` approach). This is a preference decision, not a correctness defect — the current simple `.bak` is sufficient for the operational needs documented in ADR-005 Amendment 01 §Backup strategy. Not a stale follow-up.

---

## Action Items

### Completed in this task (t_77e35ea8):

- [x] Collected accept/reject recommendations for ADR-003, ADR-004, ADR-005 from parent review tasks
- [x] Updated ADR-003 status: `Proposed` → `Accepted`
- [x] Updated ADR-004 status: `Proposed` → `Accepted` (post-PR-189; all 5 phases implemented)
- [x] Updated ADR-005 status: `Proposed` → `Accepted` (post-PR-204; migration complete, `data_protection.py` deleted)
- [x] Created this consolidated summary document

### Follow-up disposition (consolidated, 2026-09-25, task t_b84710e6)

All follow-up items tracked across ADR-003, ADR-004, and ADR-005 have been re-baselined below. Each item carries a current disposition and evidence checked against HEAD (commit `ae57574`).

| ADR | Follow-up item | Disposition | Evidence |
|-----|---------------|---------------|----------|
| ADR-003 | Patch `prompt_builder.py` to remove Model B language from `KANBAN_GUIDANCE` | RESOLVED (Hermes agent repo) | Commit `5c275ad8b` (PR #29); 0 grep matches for Model B language in `KANBAN_GUIDANCE`; see also `docs/decisions/003-review-probes-and-human-review.md` §3 ("Model B remains rejected") |
| ADR-003 | Add review-topology edge-case tests (`_landing_status_after_parents`, `_escalate_review_loop_exceeded`, `reopen_review_task`, `changes_requested` watcher) | RESOLVED | `tests/test_kanban_review_topology.py` (7 tests, 256 lines); `block_loop_detected` escalation payload covered by `test_block_loop_detected_payload_structure` |
| ADR-003 | Document `delegate_task` review probes interaction and human-in-the-loop review path | RESOLVED | `docs/decisions/003-review-probes-and-human-review.md` (supplement, 359 lines) |
| ADR-004 | Reconcile `kanban_db.py` references with `services/tasks.py` | RESOLVED | No `kanban_db.py` in Janus repo; completion path is `src/janus/services/tasks.py:complete_task()`; ADR-to-code mapping documented in ADR-004 §Reconciliation |
| ADR-004 | Auto-invoke `sync_branch()` at task start (Phase 1) | RESOLVED (gate-time) | `plugins/janus_sync/__init__.py:on_task_claimed` (line 197); PR #178; 9 tests pass. Start-time invocation remains an explicit deferred design choice |
| ADR-004 | Default-on deterministic checks (Phase 3) | RESOLVED | `src/janus/services/tasks.py:_phase3_pre_completion_gate()` (clean tree, `git diff --check`, test re-run after rebase); PR #176; 15 tests pass |
| ADR-004 | Decide and implement Phase 4 integrator model | RESOLVED | Option B adopted; `src/janus/integration.py:integrate_task()`; PR #189; 15 tests pass |
| ADR-004 | Gate enforcement to `complete_task()` (Phase 5) | RESOLVED | `complete_task()` calls `run_completion_gates()` before markdown flip; PR #176/#189; 7+2 tests pass |
| ADR-005 | Migrate `tasks.py`, `goals.py`, `milestones.py` to route writes through `atomic_io` | RESOLVED | PR #204; `data_protection.py` deleted; 0 `protected_write` imports remain in `src/janus/services/` |
| ADR-005 | Resolve `atomic_io` vs `data_protection` layer overlap | RESOLVED | ADR-005 Amendment 01 (Option b: layered composition); `data_integrity.py` wraps `atomic_io`; dependency direction one-way (`data_integrity` → `atomic_io`) |
| ADR-005 | Backup-strategy decision (rotating vs simple `.bak`) | DEFERRED — not stale | Preference decision, not a correctness defect; current simple `.bak` sufficient per ADR-005 Amendment 01 §Backup strategy |

No stale follow-ups remain. The items above that are marked RESOLVED carry verifiable evidence against HEAD. The one item marked DEFERRED (backup-strategy preference) is a deliberate open design choice and is not a stale follow-up.

### Additional deferred work

- **ADR-003 Item 3 (review loop limits):** `_escalate_review_loop_exceeded` is not implemented as a standalone function; the actual loop-escalation mechanism is `block_task`'s `block_loop_detected` event (emitted when a task is re-blocked for the same cause past `BLOCK_RECURRENCE_LIMIT`). This is an open design question, not a stale follow-up.
- **ADR-005 deferred features (`t_1f9c2a7`):** SHA-256 conflict detection, `fcntl.flock` advisory locking, and post-write verification in `atomic_io` are explicitly deferred to `t_1f9c2a7` and remain as planned future work, not stale claims.