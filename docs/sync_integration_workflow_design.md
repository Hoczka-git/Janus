# Design Spec: Safe Sync-and-Integrate Workflow for Coding Tasks

**Task:** t_f5586eb3 — Design safe sync-and-integrate workflow and define completion criteria
**Date:** 2026-09-02
**Status:** Draft for review
**Author:** Hermes Agent (implementer)
**Related:** t_891f872c (survey findings), t_ad23793c (parent implementation task), t_71f70a87 (sync primitive), t_bc8fcd6b (verification step), t_36b3d88f (integration step)

---

## 1. Executive Summary

This document defines the step-by-step workflow a coding task branch must pass through before
being considered successfully completed, and the concrete completion criteria that gate each stage.
The workflow is split into **three phases** — **Pre-Implementation Sync**, **Pre-Completion
Gate**, and **Safe Integration** — each with deterministic verification checks that must pass
before the Kanban task may transition to `done`.

Key design decisions:

- **No shared mutable state.** Each task is isolated in its own worktree and task branch
  (`wt/<task-id>` or `<project>/<task-id>`). There is no shared `dev` branch.
- **Target branch is configurable per repository.** Detected via `origin/HEAD` with
  `main`/`master` fallback (see existing `web_git.py:_default_branch_name`).
- **Fail-stop gates.** Any gate failure transitions the task to an auditable blocked or
  reconciliation state — never to `done`.
- **Separation of concerns.** The implementor runs the gates; a separate reviewer (Model A
  native review lane) performs semantic review; integration is a distinct step/agent.
- **Idempotent and resumable.** Each step records its output; a retry resumes from the last
  successful gate rather than re-running everything.

---

## 2. Scope and Goals

### In scope

- The pre-implementation sync step (bring task branch up to date against target before coding).
- The pre-completion verification gate (working tree clean, all changes committed, tests pass
  after the final rebase).
- The integration step (fast-forward merge where possible, controlled merge otherwise, push
  target branch, verify inclusion).
- Conflict handling and failure semantics.
- Completion gating: `kanban_complete` must not succeed unless sync + verification + integration
  all pass.
- Replenishment interaction: `kanban_task_completed` fires only after successful integration.

### Out of scope (explicitly deferred)

- Pre-commit hooks (gap identified in t_891f872c findings §7.3 — no `.pre-commit-config.yaml`).
  Local verification is handled by the pre-completion gate, not git hooks.
- GitHub-specific PR automation. The workflow integrates via git pushes and merges, not the
  GitHub PR API, unless the existing Hermes architecture already requires it
  (t_ad23793c constraint).
- Redesigning the Kanban state model. The existing state machine
  (`todo` → `ready` → `running` → `review` → `done`) is preserved.
- Non-coding task workflows (research, design specs, planning). The sync-integrate workflow
  only applies to tasks that produce git-branch changes.
- Adversarial/review-stage checks (semantic correctness, test quality). These are handled by
  the Model A native review lane (`kanban_request_review` → reviewer verdict).

---

## 3. Target Branch Detection

Per `web_git.py:146-160` (`_default_branch_name`), the target branch is resolved in priority order:

1. `origin/HEAD` (symbolic ref pointing at the remote default branch)
2. `refs/heads/main`
3. `refs/heads/master`
4. `refs/remotes/origin/main`
5. `refs/remotes/origin/master`

**Design addition:** The target branch must be **configurable per repository** via project
configuration. The default resolution above is the fallback; a project-level setting overrides it.
This avoids hard-coding `master` (per t_ad23793c constraint).

The merge base (divergence point) is computed via `git merge-base <task-branch> <target-branch>`
(per existing `web_git.py:_branch_base`).

---

## 4. Step-by-Step Workflow

### Phase 0 — Task Assignment

```
task assigned → worktree created (wt/<task-id>) → task branch based on current target
```

- The dispatcher creates a worktree and branch anchored on the board's `default_workdir`.
- The initial branch is based on the current target branch (already happens per
  `kanban_db.py:_ensure_git_worktree`).

### Phase 1 — Pre-Implementation Sync

**When:** Immediately before implementation begins (or at task start if the worktree already
exists and may be stale).

**Steps:**

1. **Fetch** the remote target branch: `git fetch origin <target-branch>`.
2. **Detect staleness:** Compare the task branch's merge-base against the freshly fetched
   target. If `merge-base` is behind `origin/<target-branch>`, the branch is stale.
3. **Rebase** the task branch onto the target: `git rebase origin/<target-branch>`.
   - For isolated task branches, rebase (not merge) keeps history linear and makes
     fast-forward integration possible later.
4. **Conflict handling:** If the rebase produces conflicts:
   - Do NOT resolve them in the task worktree.
   - Transition the task to `blocked` with reason `"sync_conflict"` and attach a
     `sync_conflict` artifact (rebase status, conflicted file list).
   - The conflict is handled by a neutral reconciliation workflow (see §7).
5. **Push** the rebased task branch: `git push origin <task-branch> --force-with-lease`.
   - `--force-with-lease` is used because the rebase rewrites history. The lease
     protects against overwriting others' work.
   - This is the first push of the task branch (per t_891f872c gap §7.1: no auto-push
     currently exists).

**Failure modes:**

| Condition | Action |
|---|---|
| Remote target branch not found | Block task: `"target_branch_missing"` |
| Rebase diverges unexpectedly | Block task: `"rebase_diverged_unexpectedly"` |
| Push fails (e.g., lock, permissions) | Block task: `"sync_push_failed"` with error output |
| Already up to date (no rebase needed) | Proceed (no-op, log `"already_up_to_date"`) |

### Phase 2 — Implementation

**When:** After Phase 1 succeeds (or is a no-op).

- The implementor works in the isolated worktree on the task branch.
- No changes to existing implementation behavior. The implementor may commit as it goes.
- This phase is bounded: the task has a lifecycle timeout enforced by the dispatcher
  (`max_runtime_seconds`).

### Phase 3 — Pre-Completion Gate

**When:** When the implementor believes implementation is complete and before
`kanban_complete` may succeed. This gate replaces the current "agent claims done → human
reviews" handoff with a deterministic mechanical check.

**Steps (in order):**

1. **Working tree clean-check (staged):**
   - `git status --porcelain` must show only the intended changes.
   - All untracked files that are part of the task must be staged (`git add`).
   - No stray temporary files, debug artifacts, or credentials.
   - If unstaged changes exist that are NOT task-related, block: `"uncommitted_unstaged_changes"`.

2. **Commit completeness:**
   - All intended changes must be committed on the task branch.
   - The working tree must be clean (`git status --porcelain` is empty or only contains
     expected untracked files that are explicitly excluded by scope constraints).
   - If the working tree is dirty with uncommitted changes that belong to the task,
     the agent must commit them before the gate can pass.

3. **Final fetch + sync:**
   - `git fetch origin <target-branch>` again — the target may have advanced since Phase 1.
   - Re-check staleness. If stale, re-run Phase 1 (rebase + force-push) and go to step 4.

4. **Re-run verification suite on the rebased branch:**
   - This is the critical step: tests must pass **after** the final rebase, not before.
   - For Janus: `uv run pytest tests/ -v` (per `docs/verification.md`).
   - For the repository's contract verification (if a contract exists):
     `hermes verify-contract <contract>` or `janus verify-contract <contract>`.
   - If any test fails after rebase, block: `"post_sync_verification_failure"`.
   - The implementor fixes the test failure (e.g., rebase-induced breakage) and re-runs
     the gate. It is never acceptable to skip re-verification after a rebase.

5. **Git hygiene check:**
   - `git diff --check` must pass (no whitespace errors, no conflict markers).
   - `git log --oneline -1` should have a sensible commit message (policy check, not
     strict — but flagged if it contains "WIP" or "temp").

**Gating semantics:**

- Every check is deterministic. The gate either PASSES or FAILS (no "close enough").
- On PASS: the task is eligible for integration (Phase 4).
- On FAIL: the task is blocked with a specific reason code. The implementor must address
  the failure and re-earn the gate. `kanban_block(reason=<code>)` is used.

**Evidence artifact:** On pass, the gate writes a `pre_completion_report.json` to the
workspace (or a reports directory) recording: commit hash, test pass/fail summary, diff stat,
target branch commit the branch was synced to. This becomes part of the evidence package.

### Phase 4 — Safe Integration

**When:** After the Pre-Completion Gate passes. Integration is performed by a dedicated
integration step/agent (not the implementor) to ensure the implementor is not the sole arbiter
of "is this done" — see `docs/verification_pipeline_design.md:486` principle: "Implementor ≠
Sole Arbiter."

**Steps (in order):**

1. **Verify the task branch is up to date with target:**
   - Confirm that `merge-base <task-branch> origin/<target-branch>` equals
     `origin/<target-branch>` (the task branch contains the latest target).
   - If not, re-sync (rebase onto target, force-push, re-run verification) and return to
     step 1 of this phase.

2. **Attempt fast-forward merge:**
   - `git checkout <target-branch>` (in the main repo checkout, NOT the task worktree).
   - `git merge --ff-only <task-branch>`.
   - If fast-forward succeeds: proceed to step 5.
   - If `--ff-only` fails (target has diverged): fall through to controlled merge.

3. **Controlled merge (when fast-forward is not possible):**
   - `git merge --no-ff <task-branch>` with a descriptive merge message
     (e.g., "Merge task branch wt/t_<id> into <target-branch>").
   - `--no-ff` preserves branch topology for traceability.
   - If the merge produces conflicts:
     - Do NOT resolve them in the integration workspace.
     - Transition the task to `blocked` with reason `"integration_conflict"`.
     - Route to the neutral merge-reconciler (§7).
   - If the merge succeeds, proceed to step 5.

4. **Run verification on the integrated branch:**
   - After merge, run the full test suite on `<target-branch>` to ensure the integrated
     state is green: `uv run pytest tests/ -v`.
   - If tests fail after integration, the integration is **rolled back**:
     - `git reset --hard <pre-merge-target-sha>` (the target branch is restored to its
       pre-integration state).
     - Task is blocked with reason `"post_integration_test_failure"`.
   - The repository must NOT be left in a partially-integrated state.

5. **Push the target branch:**
   - `git push origin <target-branch>`.
   - If push fails (e.g., remote reject, network): block with `"target_push_failed"`.
     The local integration stands but is not published; the task is not marked done.

6. **Verify remote target contains the task commit:**
   - `git fetch origin` then confirm that
     `git branch -r --contains <task-commit-sha>` includes `<target-branch>`.
   - This is the final proof that integration reached the shared repository successfully.
   - If verification fails: block with `"target_contains_check_failed"`.

**Evidence artifact:** On success, write `integration_report.json` recording: target branch
commit before/after, merge strategy used (ff/fast-forward-only), task commit SHA, test
results on the integrated branch, push timestamp, remote verification timestamp.

### Phase 5 — Completion

**When:** After Phase 4 succeeds (integration complete and verified on the remote).

- The integration agent/step calls `kanban_complete()` with:
  - `summary`: human-readable summary of what was integrated.
  - `metadata`: `{commit_sha, target_branch, merge_strategy, integration_report, pre_completion_report, tests_passed: true}`.
  - `artifacts`: paths to the evidence JSON files.
- `kanban_complete` triggers the existing post-completion side effects (§2.1 of t_891f872c
  findings):
  - Worktree cleanup (if clean and merged).
  - Failure-counter clear.
  - `recompute_ready()` to promote dependent tasks.
  - Lifecycle hook fires `kanban_task_completed` event.
- Replenishment consumes `kanban_task_completed` and fires only here
  (t_ad23793c §5: "Replenishment must happen only after successful repository integration
  and task completion").

---

## 5. Failure Semantics

### 5.1 Hard failures (block the task)

| Failure mode | Phase | Reason code | Kanban action |
|---|---|---|---|
| Target branch missing | 1, 2 | `target_branch_missing` | `kanban_block` |
| Rebase conflict | 1, 2 | `sync_conflict` | `kanban_block` |
| Force-push rejected (lease) | 1, 2 | `sync_push_failed` | `kanban_block` |
| Uncommitted/unstaged changes | 3 | `uncommitted_changes` | `kanban_block` |
| Tests fail after final sync | 3 | `post_sync_verification_failure` | `kanban_block` |
| Integration merge conflict | 4 | `integration_conflict` | `kanban_block` |
| Push target branch failed | 4 | `target_push_failed` | `kanban_block` |
| Post-integration tests fail | 4 | `post_integration_test_failure` | rollback + `kanban_block` |
| Remote contains check failed | 4 | `target_contains_check_failed` | `kanban_block` |

**Principle:** A failure at any phase must NOT leave the repository in a partially-integrated
state. Integration (Phase 4) is atomic: either the merge + push + verification all succeed, or
the integration is rolled back and the task is blocked.

### 5.2 Recovery

- The implementor may fix the issue and re-trigger the relevant phase.
- For conflicts (Phase 1/2 sync or Phase 4 integration), the task is routed to a neutral
  merge-reconciler profile (§7). The original implementor does NOT resolve conflicts between
  independently developed branches (t_ad23793c §4).
- For test failures after sync, the implementor fixes the code and re-runs the Pre-Completion
  Gate. No re-approval needed (the task is still in the same run).
- For integration failures that required a rollback, the implementor re-syncs to target
  (catching any new target changes) and the integration is retried.

### 5.3 Auditable state

Every block transitions the task to `blocked` (or `todo` if parents need re-gating) with a
structured reason code in the event payload. No evidence of the failure is lost:

- The reason code is stored in the `kanban_block` reason.
- The error output (git/diff/test) is attached as an artifact or recorded in the report JSON.
- The task remains claimable by the same or a different implementer profile.

---

## 6. Per-Task Isolation (No Shared Mutable State)

The workflow explicitly avoids shared mutable state:

- **No shared `dev` branch.** Each task has its own branch (`wt/<task-id>` or
  `<project>/<task-id>`). Integration is into the single target branch only.
- **Worktree isolation.** Each task runs in its own worktree (`<repo>/.worktrees/<task-id>`),
  per existing `_resolve_worktree_workspace` (t_891f872c §3.3). Worktrees do not share `cwd`.
- **Integration happens in the main checkout**, not in the task worktree, to avoid cross-
  contamination. The integration step operates on the repository's default workdir.
- **Evidence is per-task.** Report files (`pre_completion_report.json`,
  `integration_report.json`) live in the task's own workspace/reports directory, not shared.
- **Rebase over merge for task branches.** Because task branches rebase onto target, they
  never accumulate merge commits from other tasks. The target branch is the only place
  where integration merges land.

---

## 7. Conflict Handling and the Merge-Reconciler

### 7.1 Sync conflicts (Phase 1 / Phase 3)

A rebase conflict between the task branch and the target branch means the implementor's
work conflicts with target progress. Resolution:

1. The task is blocked (`kanban_block` with `sync_conflict`).
2. The implementor is notified but does NOT resolve the conflict alone — they may lack
   context on what changed in target.
3. The conflict is routed to a **neutral reconciler** using the existing
   `merge-reconciler` skill (see `skills/autonomous-ai-agents/merge-reconciler/SKILL.md`).
4. The reconciler is spawned as a separate agent (via `delegate_task` or a dedicated
   reconciliation card assigned to a third profile) with both diffs and both intents.
5. After reconciliation, the reconciler rebases the task branch, force-pushes, and the
   workflow resumes at the relevant gate.

### 7.2 Integration conflicts (Phase 4)

If `git merge --no-ff <task-branch>` into target produces conflicts:

1. The integration is **not** committed. The merge is aborted: `git merge --abort`.
2. The task is blocked (`kanban_block` with `integration_conflict`).
3. The conflict is routed to the merge-reconciler (same as §7.1).
4. The reconciler resolves, re-runs integration, and either completes the merge + push or
   re-blocks.
5. The repository is never left with a half-resolved merge.

### 7.3 Merge-reconciler reuse

Per t_ad23793c constraint: "Do not duplicate existing merge-reconciler functionality." The
`merge-reconciler` skill already provides:

- Hunk classification (disjoint-intent, same-question-different-answer, superseded).
- Impartiality contract (never favor the spawning side).
- Verification (build/tests pass, both intents observable).
- Structured hand-back (per-hunk decision summary).

This design delegates all conflict resolution to it. No new conflict-resolution logic is
introduced.

---

## 8. Completion Criteria

### 8.1 Acceptance criteria (what this spec must define)

| # | Criterion | Status |
|---|---|---|
| AC-1 | Pre-implementation sync is defined: fetch, detect staleness, rebase, conflict → block | ✅ Spec §4.1–4.5 |
| AC-2 | Pre-completion gate is defined: clean tree, committed changes, final sync, re-run tests, git hygiene | ✅ Spec §4.3 |
| AC-3 | Integration is defined: verify up-to-date, fast-forward attempt, controlled merge fallback, post-merge verification, push, remote contains check | ✅ Spec §4.4 |
| AC-4 | Completion requires all three phases to pass; `kanban_complete` is gated | ✅ Spec §4.5 |
| AC-5 | Failure modes are enumerated with reason codes and Kanban actions | ✅ Spec §5.1 |
| AC-6 | Failures leave an auditable Kanban state and never a partially-integrated repo | ✅ Spec §5.3, §5.1 (atomicity) |
| AC-7 | No shared mutable state (no `dev` branch, per-task worktrees, per-task evidence) | ✅ Spec §6 |
| AC-8 | Conflicts routed to the existing merge-reconciler; implementor does not self-resolve | ✅ Spec §7 |
| AC-9 | Target branch is configurable per repository; not hard-coded to `master` | ✅ Spec §3 |
| AC-10 | Replenishment fires only after successful integration + completion | ✅ Spec §4.5, §5 |

### 8.2 Completion is NOT achieved when

- Any gate fails (the task is blocked, not done).
- Tests fail after the final rebase.
- The merge/push/contains-check fails (integration rolled back).
- The working tree has uncommitted or stray changes.
- A conflict is left unresolved in any workspace.
- The task branch is not verified to contain the latest target before integration.

### 8.3 Evidence package (what the implementor hands off)

When all gates pass, the following artifacts constitute proof of successful completion:

1. `pre_completion_report.json` — commit SHA, test results, diff stat, target commit SHA.
2. `integration_report.json` — merge strategy, commit SHA, post-merge test results,
   push/verify timestamps.
3. `git diff --stat` output.
4. `git log --oneline` of the task branch.
5. Full test output (or summary + report path).

These are attached to the `kanban_complete` call as `artifacts` and `metadata`,
per the structured handoff pattern in `docs/verification_pipeline_design.md:514`.

---

## 9. Workflow Diagram (State Machine)

```
task assigned
    ↓
[Phase 1: Pre-Implementation Sync]
task branch based on target
    ↓
fetch origin target → detect staleness → rebase onto target → force-push
    │
    ├── ✓ up to date / rebased  ──→ [Phase 2: Implementation]
    └── ✗ conflict              ──→ kanban_block(sync_conflict)
                                      ↓
                                      merge-reconciler resolves → resume Phase 1
    ↓
[Phase 2: Implementation in isolated worktree]
    ↓
implementor completes work
    ↓
[Phase 3: Pre-Completion Gate]
    ├── working tree clean check
    ├── all changes committed
    ├── final fetch + re-sync (if needed, loop to Phase 1)
    ├── re-run tests  ← tests must pass AFTER final rebase
    └── git diff --check
    │
    ├── ✓ all pass  ──→ [Phase 4: Safe Integration]
    └── ✗ any fail   ──→ kanban_block(<reason_code>)
                                      ↓
                                      implementor fixes → resume Phase 3
    ↓
[Phase 4: Safe Integration]  (dedicated step/agent, not implementor)
    ├── verify task branch contains latest target
    ├── fast-forward merge attempt (--ff-only)
    │   ├── ✓ ff success  ──→ skip to post-merge verify
    │   └── ✗ ff fails      ──→ controlled merge (--no-ff)
    │       ├── ✓ merge clean  ──→ post-merge verify
    │       └── ✗ merge conflict ──→ git merge --abort → kanban_block(integration_conflict)
    │                                                    ↓
    │                                                    merge-reconciler → retry Phase 4
    ├── post-merge test suite on target  ← must pass AFTER merge
    │   └── ✗ fail → git reset --hard <pre-merge> → kanban_block(post_integration_test_failure)
    ├── push origin target
    │   └── ✗ push fails → kanban_block(target_push_failed)
    └── verify remote target contains task commit
        └── ✗ check fails → kanban_block(target_contains_check_failed)
    │
    ├── ✓ all pass  ──→ [Phase 5: Completion]
    └── ✗ any fail   ──→ (rolled back / blocked above)
    ↓
[Phase 5: Completion]
kanban_complete(summary, metadata={...}, artifacts=[...])
    ↓
kanban_task_completed event → worktree cleanup → recompute_ready → replenishment
```

---

## 10. Integration with Existing Systems

### 10.1 Kanban task lifecycle (unchanged)

| Kanban state | Workflow phase | Action that transitions |
|---|---|---|
| `todo` / `ready` | — | (task assigned, worktree created) |
| `running` | Phase 1, 2, 3 | implementor working; calls `kanban_block` on failure |
| `review` | (Model A review lane) | implementor calls `kanban_request_review` after Phase 3 pass |
| `done` | Phase 5 | integration agent calls `kanban_complete` after Phase 4 pass |
| `blocked` | any failure | `kanban_block(reason=<code>)` |

**Key insight:** The implementor completes Phase 3 (Pre-Completion Gate) and then enters the
**Model A review lane** (`kanban_request_review`). The reviewer verifies semantic correctness.
Only after review approval does the **integration agent** proceed with Phase 4. This preserves
the "Implementor ≠ Sole Arbiter" principle: the implementor cannot mark done; the reviewer
and integration agent must both agree.

### 10.2 Worktree lifecycle (reused)

- Worktree creation: existing `_ensure_git_worktree` (t_891f872c §3.2).
- Worktree cleanup on completion: existing `_cleanup_worktree_workspace` (t_891f872c §6).
  Safety invariants are preserved: tracked modifications never deleted, unique unpushed
  commits never deleted, live-locked trees never touched, branch deleted only after
  worktree removal succeeds.

### 10.3 Verification pipeline (wired in)

- Phase 3 uses the existing Janus verification pipeline (`src/janus/verification.py`,
  9 check types) and the Hermes recipe runner (`agent/verify/runner.py`).
- The `verify-on-stop nudge` (`agent/verification_stop.py`) is policy-only — it does NOT
  run checks. This spec replaces that nudge with an actual gate: the implementor's
  completion claim triggers Phase 3 deterministically.
- Contract-based verification (`janus verify-contract`) is invoked if a contract exists.

### 10.4 CI (preserved, not replaced)

- `.github/workflows/ci.yml` runs `pytest` on push/PR to the target branch. This fires
  after Phase 4 (push target branch) and provides remote verification.
- The local pre-completion gate (Phase 3) runs tests **before** CI. CI is the second line
  of defense; the local gate is the first.

### 10.5 Replenishment (preserved)

- `kanban_task_completed` event fires only after `kanban_complete` succeeds (Phase 5).
- Replenishment consumes this event and promotes dependent tasks.
- If any phase fails, the task is blocked, `kanban_complete` is never called, and
  replenishment does NOT fire.

---

## 11. Non-Goals (Explicitly Out of Scope)

- **Pre-commit hooks.** No `.pre-commit-config.yaml`. Local verification is handled by
  Phase 3's deterministic gate, not git hooks. Adding hooks is a separate task.
- **PR automation.** No GitHub PR creation or auto-merge via the GitHub API. Integration
  is via git push + merge into the target branch. CI provides the PR-equivalent gate.
- **Shared `dev` branch.** Explicitly rejected (t_ad23793c: "Do not introduce a shared dev
  branch").
- **Kanban state model changes.** The existing state machine is preserved. No new statuses.
- **Semantic/adversarial review.** Handled by the Model A native review lane, not this
  workflow. This spec defines the mechanical gates only.
- **Non-coding tasks.** Research, design, planning tasks do not go through this workflow.
  A task opts in only if it has a worktree/ git-branch payload.

---

## 12. Remaining Open Questions

1. **Two-reviewer for high-risk tasks.** The current Model A is single-reviewer. Should
   Phase 3's gate require review approval, or only mechanical pass? Decision: mechanical
   pass is required; review approval is handled by the existing `review` status
   transition before `kanban_complete` is called.

2. **Force-push safety on shared branches.** `--force-with-lease` is safe for task branches
   (only the task owner pushes). But if a task branch is ever used by multiple profiles,
   force-push becomes dangerous. Mitigation: task branches are single-writer by design
   (one worktree, one claim).

3. **Integration agent identity.** Who performs Phase 4? Options: (a) the implementor
   itself after review approval, (b) a dedicated `integrator` profile, (c) the reviewer
   as part of their verdict. Decision deferred to the implementation task (t_36b3d88f).
   This spec requires that whoever performs Phase 4 is NOT the sole arbiter — at minimum,
   Phase 3's gate must have passed independently.

4. **Rollback scope on post-integration failure.** If post-merge tests fail and the
   integration is rolled back, the task branch is still valid — only the target branch
   integration is reverted. The task returns to Phase 3 for the implementor to fix.
   This is safe because target was only advanced by the (now-rolled-back) merge.

5. **Concurrent task branches targeting the same repo.** If two tasks both try to
   integrate to `master` simultaneously, the second integration's `git push` will be
   rejected. This is handled by git's push rejection (non-fast-forward) and surfaces as
   `target_push_failed`. The implementor re-syncs and retries. No lock is needed —
   git's own ref-update atomicity is the guard.

---

## 13. Acceptance Checklist

- [ ] Phase 1 (Pre-Implementation Sync) steps are defined with failure modes.
- [ ] Phase 3 (Pre-Completion Gate) is defined as a fail-stop deterministic check.
- [ ] Phase 4 (Safe Integration) uses fast-forward first, controlled merge fallback,
      atomic rollback on failure.
- [ ] `kanban_complete` is gated on Phases 1, 3, and 4 all passing.
- [ ] All failure modes have reason codes + Kanban block actions.
- [ ] No shared mutable state (no `dev` branch, per-task worktrees, per-task evidence).
- [ ] Conflicts routed to the existing merge-reconciler skill.
- [ ] Target branch is configurable per repository.
- [ ] Replenishment fires only after successful integration + completion.
- [ ] This spec is decomposed into implementation tasks (sync, verification, integration)
      that match the existing child task decomposition.

---

*This spec is a design document only. Implementation is tracked in the child tasks:
t_71f70a87 (sync primitive), t_bc8fcd6b (verification step),
t_36b3d88f (integration step), coordinated via t_ad23793c.*
