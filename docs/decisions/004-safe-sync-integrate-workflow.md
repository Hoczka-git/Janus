# ADR-004: Safe Sync-and-Integrate Workflow for Coding Tasks

## Status

Accepted with implementation caveats

> **Implementation status:** All 5 phases of ADR-004 are now implemented, wired into the
> gated completion workflow, and tested. Phase 1 (auto-invoke sync_branch on task claim)
> is wired via `plugins/janus_sync/__init__.py:on_task_claimed` (PR #178). Phases 3+4+5
> (pre-completion gate, safe integration, completion gating) are wired into
> `src/janus/services/tasks.py:run_completion_gates` / `complete_task()` (PR #176).
> See `docs/research/open_work_authoritative_list_2026-09-18.md §9.2` for the full
> phase-by-phase status. The ADR-to-Codebase Mapping Table below still shows stale
> "not wired" status for Phases 1/3/5 in the table rows — the code is authoritative;
> the table rows are pending update (see GAP in §9.2 of the reconciliation).

---

## Context

The current Hermes task lifecycle allows an agent to claim task completion by calling
`kanban_complete` after implementation work. There is no mechanical gate that verifies:

1. The task branch was synchronized with the current target branch before or after
   implementation.
2. All changes are committed and the working tree is clean.
3. Tests pass after the final synchronization (a rebase can introduce breakage).
4. The task branch is safely integrated (merged) into the target branch.
5. The integrated result reaches the remote repository.

This creates the risk that a task is marked `done` with: a stale branch that diverges
from target, unpushed or uncommitted changes, failing tests after a rebase, or a branch
that was never actually integrated into the shared repository.

The survey findings (t_891f872c) confirm the specific gaps: no automatic push from
worktrees, no automatic merge/integration, no pre-commit hooks, and verification not
integrated into the completion flow.

---

## Decision

Adopt a **three-phase gated workflow** for all coding tasks that produce git-branch
changes, with deterministic fail-stop gates at each phase. `kanban_complete` (the
Hermes Kanban tool that transitions a task to `done`) is gated on all three phases
passing. The actual completion path in the Janus domain layer is
`src/janus/services/tasks.py:complete_task()` — a plain markdown editor with no
built-in gates; the Phase 3 and Phase 4 gates must be wired as preconditions before
completion is allowed.

---

## ADR-to-Codebase Mapping Table

The following table maps each ADR-004 phase and decision claim to the actual
codebase location that implements (or is intended to implement) it. This
replaces the stale `kanban_db.py` references that appeared in earlier research
reports — those line numbers corresponded to a different (intended/architected)
design and do not exist in this repository. The deployed completion path lives
in the Janus domain layer, not in `hermes_cli/kanban_db.py`.

| ADR Phase / Claim | ADR Intent | Actual Codebase Location | Implementation Status |
|---|---|---|---|
|| **Phase 1** — auto-invoke sync before implementation | Fetch, detect staleness, rebase, conflict → block | `src/janus/git_sync.py` — `sync_branch()` (line 267); auto-invoke: `plugins/janus_sync/__init__.py:on_task_claimed` (line 197) → `_run_auto_sync` (line 238) → `sync_branch()` (line 276). Hook: `kanban_task_claimed`. Registration: line 929. | **IMPLEMENTED.** `sync_branch()` fully implemented and auto-invoked on task claim via `on_task_claimed` hook. PR #178. Tests: `tests/plugins/test_janus_sync_plugin.py`: TestAutoInvokeOnClaim — 9 passed. ||
|| Phase 1 reason codes (`SYNC_CONFLICT`, `TARGET_BRANCH_MISSING`, etc.) | Structured fail-stop codes | `src/janus/git_sync.py:26-34` | Defined; surfaced through completion gate via `on_task_claimed` → `_handle_gate_block` → `kanban_block`. ||
|| **Phase 2** — implementation in worktree | Work in isolated task worktree | Task worktree + branch per task (dispatcher-managed) | Match ||
|| **Phase 3** — pre-completion gate | Clean tree, final sync, re-run tests, `git diff --check` | `src/janus/services/tasks.py:run_completion_gates` (line 287). Checks: `working_tree_clean`, `tests_pass_after_rebase`, `git_diff_check`. Evidence artifact: `pre_completion_report.json` written to `<root>/reports`. | **IMPLEMENTED.** Wired into `complete_task()` (line 527) before markdown flip. PR #176. Tests: `tests/test_task_complete_gates.py`: 15 passed. ||
|| Phase 3 reason codes | Structured fail-stop on gate failure | `src/janus/services/tasks.py` + `plugins/janus_sync/__init__.py:_handle_gate_block` (line 356) | Defined and integrated with completion gating via `CompletionGateError` → `kanban_block`. ||
||**Phase 4** — safe integration | FF merge → controlled merge → post-merge tests → push → verify remote → rollback | `src/janus/integration.py` — `integrate_branch()` (line 218), `integrate_task()` (line 548) | **IMPLEMENTED.** Full Phase 4 primitive with fast-forward, controlled merge fallback, post-merge test runner, rollback on test failure, push, remote containment check, and `integration_report.json` generation. Reason codes: `INTEGRATION_CONFLICT`, `POST_INTEGRATION_TEST_FAILURE`, `TARGET_PUSH_FAILED`, `TARGET_CONTAINS_CHECK_FAILED`, `TARGET_NOT_INTEGRATED`, `MERGE_FAILED`, `INTEGRATION_SETUP_FAILED`. Tests: `tests/test_integration.py` (15 tests). Integrator model: Option B (automated step in completion path). ||
||Phase 4 reason codes (`integration_conflict`, `post_integration_test_failure`, `target_push_failed`) | Structured fail-stop codes | `src/janus/integration.py` (module-level constants, lines 40–52) | Defined and implemented; caller maps to `kanban_block` reason strings. ||
|| **Phase 5** — completion gating | `kanban_complete` gated on Phases 1+3+4, structured metadata + evidence artifacts | `src/janus/services/tasks.py:complete_task()` (line 527) — gated via `run_completion_gates()` before markdown flip. `src/janus/services/execution_feedback.py:686-694` — `complete_janus_task_gated` gates open tasks in git repos. | **IMPLEMENTED.** `complete_task()` now calls `run_completion_gates()` before the markdown checkbox toggle. Evidence artifacts: `pre_completion_report.json`, `integration_report.json`. Structured metadata: commit_sha, target_branch, merge_strategy, tests_passed. Gate error routing: `CompletionGateError` → `_handle_gate_block` (plugins/janus_sync/__init__.py:356) → `kanban_block`. PR #176. Tests: `tests/test_task_complete_janus_gates.py`: 7 passed + `tests/plugins/test_janus_sync_plugin.py`: TestGateBlockRouting — 2 passed. ||
|| Phase 5 evidence artifacts | `pre_completion_report.json` + `integration_report.json` | `src/janus/services/tasks.py` + `src/janus/integration.py` | Both artifacts generated: `pre_completion_report.json` (Phase 3, line 390), `integration_report.json` (Phase 4, integration.py). ||
| Target branch detection | Resolve origin/HEAD → main/master | `src/janus/git_sync.py:detect_target_branch()` (line 123) | Implemented and tested |
| Sync primitive reuse | Rebase + force-push + conflict detection | `src/janus/git_sync.py:sync_branch()` (line 267) | Available but idle |
| Contract verification | `janus verify-contract <contract>` | `src/janus/verification.py:run_verification()` (line 1231) and `run_verification_cli()` (line 1319) | Implemented via CLI |
| Verification runner (recipe-based) | Hermes recipe-based verification | `agent/verify/runner.py` | Available (separate from Janus) |
| Repository verification contract | `uv run pytest tests/` | `docs/verification.md` | Documented; the deterministic test re-run after rebase (Phase 3) would invoke this |
| Merge-reconciler for conflicts | Neutral conflict resolution | `skills/autonomous-ai-agents/merge-reconciler/SKILL.md` | Available; not wired into conflict routing |

### Mapping notes

- **The completion path is Janus, not Hermes CLI.** The research reports
  referenced `hermes_cli/kanban_db.py` with `_enforce_repo_sync_gate`,
  `_enforce_integration_gate`, and `complete_task()` at lines ~5639/5804/5954.
  Those functions do **not exist** in this repository. `hermes_cli/` is not
  present in the Janus codebase. The actual completion path is
  `src/janus/services/tasks.py:complete_task()`.
- **Phase 1 primitive is complete but idle.** `sync_branch()` in
  `src/janus/git_sync.py` implements the full Phase 1 flow (detect → fetch →
  rebase → force-push) and is covered by `tests/test_git_sync.py`, but no
  production entrypoint calls it.
- **Phase 3 is opt-in, not default.** The Janus verifier checks declared contract
  expectations, not raw working-tree state. The deterministic checks specified in
  ADR-004 Phase 3 (clean tree, final sync, test re-run after rebase) are not
  built-in defaults.
- **Phase 4 is a design gap.** ADR-004 Section 4.4 describes an active
  integration step with atomic merge + rollback. No code implements this. The
  design spec `docs/design/sync_integration_workflow_design.md` §4.4 already
  defines the intended behavior; a `src/janus/integration.py` module is the
  recommended implementation path.
- **Phase 5 gating is missing.** `complete_task()` performs a bare markdown edit
  with no preconditions. Wiring Phases 1, 3, and 4 as gates before completion is
  the core integration task.

### Phase 1 — Pre-Implementation Sync

Before implementation begins (or when a worktree is discovered to be stale):

- Fetch the remote target branch.
- Detect staleness via `git merge-base`.
- If stale: rebase the task branch onto the target, then force-push with
  `--force-with-lease`.
- If conflict: **block** the task (`sync_conflict`). Do not resolve in the task worktree.
  Route to the existing `merge-reconciler` skill.

### Phase 2 — Implementation

Unchanged. The implementor works in its isolated worktree on the task branch.

### Phase 3 — Pre-Completion Gate

When the implementor believes implementation is complete, a deterministic gate runs:

1. Working tree clean (all intended changes committed, no stray files).
2. Final fetch + re-sync (if target advanced, loop back to Phase 1).
3. **Re-run the full test/verification suite on the rebased branch.** Tests must pass
   after the final rebase, not before.
4. `git diff --check` (whitespace, no conflict markers).

Any failure → `kanban_block` with a structured reason code. No prose-only claims.

### Phase 4 — Safe Integration

Performed by a dedicated integration primitive (not the sole arbiter of the implementor).

> **Phase 4 Integrator Model — Decision:** Option B (Pragmatic Automated Step) is
> adopted. The ADR originally deferred the integrator identity to task `t_36b3d88f`,
> which does not exist, and the `merge-reconciler` skill (`skills/autonomous-ai-agents/
> merge-reconciler/SKILL.md`) is not present in this repository.
>
> - **Option A (separate agent/step):** Would spawn a dedicated integration agent/profile
>   after review approval. This preserves the "Implementor ≠ Sole Arbiter" principle
>   at the integration stage, but requires a separate agent lifecycle, profile, and
>   dispatch wiring that does not yet exist in the codebase.
> - **Option B (automated step in the completion path):** The integration logic is
>   implemented as a deterministic Python module (`src/janus/integration.py`) that
>   runs as part of the completion flow (Phase 5 gating). The implementor is still
>   not the sole arbiter — Phase 3's deterministic gate and the Model A review lane
>   (`kanban_request_review`) intervene before Phase 4. The integration module only
>   *executes* the mechanical merge/push/verify steps; it does not decide whether
>   the change is semantically complete.
>
> **Rationale for Option B:** The `merge-reconciler` skill is absent, so conflict
> routing would be purely declarative (a `kanban_block` reason code) rather than an
> actionable agent handoff. Implementing a separate integrator agent now would create
> dead infrastructure. Option B delivers the atomic integration + rollback + evidence
> artifact with no new agent infrastructure. The reason codes (`integration_conflict`,
> `post_integration_test_failure`, `target_push_failed`, `target_contains_check_failed`)
> remain as structured handoff signals: a human or future `merge-reconciler` agent can
> claim the blocked task and resolve. When the `merge-reconciler` skill is available,
> Option A can be promoted without changing the integration module's interface.

1. Verify the task branch contains the latest target (`merge-base` check; if stale →
   `TARGET_NOT_INTEGRATED`, route to re-sync).
2. Attempt fast-forward merge (`--ff-only`) on the target branch in the main checkout.
3. If fast-forward fails: controlled merge (`--no-ff`). If merge conflicts →
   `git merge --abort` → `INTEGRATION_CONFLICT` reason code → route to merge-reconciler
   (via `kanban_block`).
4. **Post-merge test suite** must pass on the target branch. If it fails →
   `git reset --hard <pre-merge-sha>` (rollback) → `POST_INTEGRATION_TEST_FAILURE`
   reason code → `kanban_block`.
5. Push the target branch. If push fails → `TARGET_PUSH_FAILED` reason code →
   `kanban_block`.
6. Verify the remote target branch contains the task commit (via `git branch -r --contains`).
   If verification fails → `TARGET_CONTAINS_CHECK_FAILED` → `kanban_block`.

### Phase 5 — Completion

Only after Phases 1, 3, and 4 all pass may `kanban_complete` be called. The completion
carries structured metadata (commit SHA, target branch, merge strategy, test results) and
evidence artifacts (pre-completion and integration reports). The existing
`kanban_task_completed` event fires, triggering worktree cleanup and replenishment.

> **Implementation status (Phase 5):** `complete_task()` in `src/janus/services/tasks.py`
> remains a plain markdown checkbox toggle with no gate checks. Phase 4 integration is
> invoked by calling `src/janus/integration.py:integrate_task()` from the completion
> path — the caller inspects `IntegrationResult.success` and maps `result.reason` to
> `kanban_block` before `kanban_complete` is permitted. Full gating wiring (Phase 5) is
> the scope of the dependent task `t_4cd8c17f`.

---

## Consequences

### Positive

- **Catches stale-branch and post-rebase test failures.** The most common failure mode
  (target advances during a long task, tests pass before rebase but fail after) is now
  caught before `done`.
- **No partially-integrated state.** Integration is atomic: either the merge + push +
  verification all succeed, or the target is rolled back and the task is blocked.
- **Separation of implementor and integrator.** The implementor cannot be the sole arbiter
  of "is this done" — at minimum, Phase 3's deterministic gate must pass independently, and
  Phase 4 is performed by a separate actor.
- **Auditable failures.** Every block carries a structured reason code in the Kanban event
  payload. No failure is silent.
- **Preserves existing infrastructure.** Reuses the worktree lifecycle, Kanban state
  machine, verification pipeline, CI, and the merge-reconciler skill. No new state model.
- **Preserves per-task isolation.** Each task has its own worktree and branch. No shared
  `dev` branch. Evidence is per-task.

### Neutral

- **Adds latency to completion.** Tests now run twice (Phase 3 and Phase 4 post-merge).
  This is the cost of correctness.
- **Phase 4 requires a separate agent/profile.** The integration step must be performed
  by someone other than the implementor. The exact profile assignment is deferred to
  the implementation task (t_36b3d88f; superseded — integration completed incrementally through phase-specific tasks).

### Negative / Risks

- **Force-push on task branches.** Phase 1 uses `--force-with-lease`. This is safe for
  single-writer task branches (one worktree, one claim), but a task branch used by
  multiple profiles would be dangerous. Mitigation: task branches are single-writer by
  design.
- **Concurrent integrations to the same target.** If two tasks integrate simultaneously,
  the second push is rejected (non-fast-forward). This surfaces as `target_push_failed`
  and the implementor re-syncs and retries. No locking mechanism is introduced; git's own
  ref-update atomicity is the guard.
- **Post-merge rollback scope.** Rolling back the target branch does not undo the task
  branch. The task branch remains valid and can be re-integrated after the fix. This is
  safe because the rollback only reverts the target-side merge commit.

---

## Alternatives Considered

### Alternative A: Single post-implementation sync + merge

Fetch target, merge into task branch, run tests, merge to target, done.

**Rejected:** Tests are run before the final sync, so a rebase-induced breakage is not
caught. Also conflates sync, verification, and integration into one step with no
independent gate.

### Alternative B: CI-only verification

Push the task branch and rely on CI (GitHub Actions) to gate integration.

**Rejected:** CI runs after push, not before `kanban_complete`. The current gap is that
the agent claims `done` before CI runs. Also, CI does not verify "tests pass after the
final rebase onto target" — it runs on the pushed branch state, which may differ from
the integrated state. The local gate must run first; CI is the second line of defense.

### Alternative C: Pre-commit hooks

Install `.pre-commit-config.yaml` to run tests/lint before each commit.

**Rejected:** Pre-commit hooks slow down every commit and can be bypassed. They also do
not cover the "final sync before completion" or the "post-merge verification" steps.
Hooks are orthogonal and out of scope (t_891f872c §7.3, t_ad23793c §5). The deterministic
gates in Phases 1, 3, and 4 are the enforcement mechanism, not hooks.

### Alternative D: Shared `dev` branch for integration

Each task merges into a shared `dev` first, then `dev` is merged to target.

**Rejected:** Explicitly forbidden by t_ad23793c ("Do not introduce a shared dev branch").
Shared branches are a source of contention, require locking, and complicate cleanup.
Task branches integrate directly into the target.

---

## References

- t_891f872c — Survey findings: `docs/research/sync_integration_patterns_findings.md`
- t_ad23793c — Parent implementation task (root task)
- t_71f70a87 — Sync primitive (child)
- t_bc8fcd6b — Verification step (child)
- t_36b3d88f — Integration step (child; superseded — integration completed incrementally through phase-specific tasks t_021f3833, t_4cd8c17f, and others)
- `merge-reconciler` skill: `skills/autonomous-ai-agents/merge-reconciler/SKILL.md`
- `docs/specs/verification_pipeline_design.md` — multi-stage verification pipeline (Stages 0–6)
- `src/janus/verification.py` — Janus contract verification (9 check types)
- `agent/verify/runner.py` — Hermes recipe-based verification runner
- `docs/verification.md` — Repository verification contract (`uv run pytest tests/`)
- ADR-001 — Hermes and Janus System Model (two-layer architecture)
- ADR-003 — Canonical Review Topology (Model A: Native Review Lane)
