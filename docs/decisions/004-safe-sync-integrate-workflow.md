# ADR-004: Safe Sync-and-Integrate Workflow for Coding Tasks

## Status

Proposed

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
transition to `done`) is gated on all three phases passing.

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

Performed by a dedicated integration step/agent (not the sole arbiter of the implementor):

1. Verify the task branch contains the latest target (`merge-base` check).
2. Attempt fast-forward merge (`--ff-only`) on the target branch in the main checkout.
3. If fast-forward fails: controlled merge (`--no-ff`). If merge conflicts →
   `git merge --abort` → `kanban_block(integration_conflict)` → route to merge-reconciler.
4. **Post-merge test suite** must pass on the target branch. If it fails →
   `git reset --hard <pre-merge-sha>` (rollback) → `kanban_block(post_integration_test_failure)`.
5. Push the target branch. If push fails → `kanban_block(target_push_failed)`.
6. Verify the remote target branch contains the task commit (via `git branch -r --contains`).

### Phase 5 — Completion

Only after Phases 1, 3, and 4 all pass may `kanban_complete` be called. The completion
carries structured metadata (commit SHA, target branch, merge strategy, test results) and
evidence artifacts (pre-completion and integration reports). The existing
`kanban_task_completed` event fires, triggering worktree cleanup and replenishment.

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
  the implementation task (t_36b3d88f).

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
- t_36b3d88f — Integration step (child)
- `merge-reconciler` skill: `skills/autonomous-ai-agents/merge-reconciler/SKILL.md`
- `docs/verification_pipeline_design.md` — multi-stage verification pipeline (Stages 0–6)
- `src/janus/verification.py` — Janus contract verification (9 check types)
- `agent/verify/runner.py` — Hermes recipe-based verification runner
- `docs/verification.md` — Repository verification contract (`uv run pytest tests/`)
- ADR-001 — Hermes and Janus System Model (two-layer architecture)
- ADR-003 — Canonical Review Topology (Model A: Native Review Lane)
