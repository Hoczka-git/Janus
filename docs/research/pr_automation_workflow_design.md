# Revised PR Automation Workflow Design

**Task:** t_85572968
**Parent context:** t_6b060ae7 (gap analysis, 12 gaps), t_c0e3a822 (design summary), t_6fba151b (first revision)
**Revision date:** 2026-09-02
**Status:** superseded-by-this-revision

---

## 1. What Changed From t_6fba151b's Revision

The t_6fba151b revision incorporated all 12 gaps and 13 architectural decisions from the gap analysis. This revision does **not** rewrite the architectural decisions — it keeps D1–D13 intact — but it corrects three categories of issues:

1. **Codebase facts:** The design references `src/janus/git_sync.py` and `src/janus/verification_step.py` as existing modules. These do **NOT** exist in the Janus repository. The design must reference the actual Hermes-Agent capabilities (`kanban_db.py:_enforce_repo_sync_gate`, `web_git.py`, `cli.py` worktree helpers) and Janus's actual `verification.py`.

2. **Lifecycle timing diagnosis:** The design asserts `on_kanban_integration_ready` should fire "before the `status='done'` UPDATE." The existing `complete_task()` function flows: gate check → `write_txn` (status='done') → event → lifecycle hook (→ `kanban_task_completed`). There is no hook firing *before* the write. The correct trigger for worktree tasks is: **inside `complete_task()`'s write transaction, transition to `review` instead of `done`, then fire a new hook after the transaction commits.** This requires a code change to `complete_task()`.

3. **State persistence reality:** The design assumes `tasks.metadata` is a free-form JSON dict available for `integration_state` etc. The actual `tasks` schema uses a `metadata` TEXT column stores JSON. This is compatible — no schema change needed — but the design must be explicit that `set_metadata()` is the accessor.

---

## 2. Workflow Overview (Target Semantics, Unchanged From Gap Analysis)

```
implementation → commit → push → synchronize with latest target branch
              → run verification/tests again → create GitHub PR
              → wait for CI → enable/use GitHub auto-merge
              → verify PR was actually merged into target branch
              → only then mark Kanban task as DONE
              → kanban_task_completed → replenishment
```

This is a **blocking, integrated** workflow: the task is not marked `done` until the PR has been created, CI has passed, auto-merge has been engaged (where supported), and the PR has been **verified merged** into the target branch. `kanban_task_completed` (and therefore replenishment) fires only after successful integration.

---

## 3. Explicit Answers to Design Questions (A–L)

### A. What exact event/state transition starts the integration workflow?

**Answer (D1, corrected):** A new lifecycle hook `on_kanban_integration_ready` fires from within `complete_task()` **after** the write transaction commits, but only for worktree tasks — and only when `complete_task()` transitions the task to `review` (instead of `done`).

**Implementation reality:** `complete_task()` in `kanban_db.py` (line ~5534) currently:
1. Runs `_enforce_repo_sync_gate()` (guard: committed + pushed)
2. Opens `write_txn`, sets `status='done'`, creates run, appends event
3. Calls `_cleanup_workspace()` (removes worktree)
4. Fires `_fire_kanban_lifecycle_hook("kanban_task_completed", ...)`

**Required change to `complete_task()`:**
- For `workspace_kind == 'worktree'`: inside the write transaction, set `status='review'` (not `done`). After the transaction commits and before `_cleanup_workspace()`, fire `on_kanban_integration_ready`. Do NOT fire `kanban_task_completed` from this path.
- For non-worktree tasks: keep existing behavior (transition to `done`, fire `kanban_task_completed`).
- Defer `_cleanup_workspace()` for worktree tasks until the integration agent confirms merge and calls the final completion. The worktree must survive the integration workflow (sync, verify, PR creation, CI monitoring, merge verification).

**The hook is best-effort and synchronous** (wraps in `try/except` per `_fire_kanban_lifecycle_hook`). It sets `metadata.integration_state = 'ready'` and emits a `kanban_integration_queued` event. The actual integration work runs in a separate polling agent — not inside the hook.

### B. How can the task remain non-DONE while PR/CI/merge is in progress?

**Answer (D2, unchanged):** Reuse the existing `review` status. The `review` status already exists in `VALID_STATUSES` (`kanban_db.py:102`), is claimable by an integration agent, and semantically means "waiting for external approval." The finer-grained state (`syncing`, `pr_created`, `ci_running`, etc.) lives in `metadata.integration_state`.

**Reality check:** The `review` status is already dispatched to reviewers via `_dispatch_once_locked` (line ~10310). The integration agent must be distinguishable from human reviewers — the agent's profile should be configured to claim `review`-status worktree tasks and process them through the integration pipeline. This is a profile configuration concern, not a code change.

### C. What exact event/state transition marks the task DONE?

**Answer (D11, unchanged):** Only after the integration agent verifies the PR is merged (Step 7). The integration agent calls `complete_task()` — which this time commits the task to `status='done'` and fires `kanban_task_completed` → replenishment. This is the **second** call to `complete_task()` for the same task: the first (by the worker) transitions to `review`; the second (by the integration agent) transitions to `done`.

**Reality check:** `complete_task()` currently requires `status IN ('running', 'ready', 'blocked', 'review')` to transition to `done`. Since the task is in `review` after the first call, the second call is valid. The `_enforce_repo_sync_gate()` guard runs again on the second call — this is acceptable because the worktree should still be clean (the integration agent hasn't modified it; all git ops happen on the branch, not the worktree).

### D. How is branch freshness checked and enforced?

**Answer (D3, corrected for actual codebase):**

**Step 2 (Synchronize) uses Hermes-Agent's existing primitives, not Janus's non-existent `git_sync.py`:**

1. **Fetch remote target branch.** `git fetch origin <target_branch>` — via `web_git.py:_git()` or direct subprocess.
2. **Compute merge-base.** `git merge-base <task_branch> origin/<target_branch>` — this is the core primitive the design needs. `web_git.py:_branch_base()` computes merge-base with the remote default branch for the **current** branch in `cwd`. For the integration agent working on a specific task branch, the merge-base must be computed explicitly against `origin/<target_branch>`.
3. **Detect staleness.** If merge-base is behind `origin/<target_branch>`, the branch is stale.
4. **Rebase onto target.** `git rebase origin/<target_branch>` on the task branch. The integration agent's `cwd` is the worktree path (`tasks.workspace_path`), so this operates directly on the task branch.
5. **Force-push.** `git push --force-with-lease origin <task_branch>`.

**Gap from the design:** `web_git.py` does NOT have a `is_branch_stale()` function. The merge-base computation (`_branch_base`) is for the current branch vs remote default. The integration agent must compute the merge-base against a specific target branch reference, which requires a small addition to `web_git.py` or a direct git call in the plugin.

**Janus side:** `src/janus/verification.py` exists and provides verification primitives. The integration agent's Step 3 (verification) uses this, not a non-existent `verification_step.py`.

### E. How is PR creation made idempotent?

**Answer (D4, unchanged):** Persist `pr_number` + `pr_url` in `tasks.metadata`. Before creating a PR, check if `metadata.pr_number` is set. If set, verify the PR still exists via `review_pr_list(workspace_path, branches=[branch_name])`. If it exists and is open, skip to CI monitoring. If the persisted record is stale, proceed to re-create.

**Reality check:** `review_pr_list()` accepts `branches` and `numbers` params. It uses GraphQL to query PRs by branch name. This is sufficient for the idempotency check.

### F. How is CI monitored?

**Answer (D5, unchanged):** Poll `gh pr checks <number>` or the GitHub Checks API. Poll interval ~30s. On CI success, proceed to auto-merge. On CI failure, block the task with `ci_failure`, attach CI logs, notify worker.

**Reality check:** `gh pr checks --watch` blocks until CI completes (with a timeout). Alternatively, `gh api repos/{owner}/{repo}/commits/{sha}/status` polls the commit status. Both paths are documented in the `github-pr-workflow` skill.

### G. How is auto-merge enabled?

**Answer (D6, unchanged):** `gh pr merge <number> --auto --squash --delete-branch`, with a direct-merge fallback. After CI success, check if the repo supports auto-merge. If yes, enable it. If no, merge directly.

**Reality check:** `gh pr merge --auto` requires the repository to have auto-merge enabled in its settings (a one-time repository configuration, not a code change). If the API rejects `--auto`, fall back to `gh pr merge <number> --squash --delete-branch`.

### H. How is actual merge completion detected?

**Answer (D7, unchanged):** Poll `gh pr view <number> --json state` until it returns `MERGED`. Cross-check with `git fetch origin` then `git branch -r --contains <task_commit_sha>` to confirm `origin/<target_branch>` contains the task commit.

**Reality check:** `review_ship_info()` already calls `gh pr view --json url,state,number`. The integration agent can use the same `gh` invocation pattern.

### I. What happens on CI failure?

**Answer (D8, unchanged):** Block the task with `ci_failure`, attach CI logs as artifacts, post a comment via `kanban_comment`, notify the worker. Do NOT enable auto-merge. The worker fixes the issue, re-commits, force-pushes, and the agent resumes from `ci_running`.

### J. What happens on merge conflict?

**Answer (D9, unchanged):** During sync (Step 2), rebase conflicts → abort, block with `sync_conflict`, attach conflict output, route to `merge-reconciler`. Do NOT create PR. During integration (post-PR), if GitHub reports a conflict → block with `integration_conflict`, route to `merge-reconciler`.

**Reality check:** The `merge-reconciler` skill exists and provides neutral third-party conflict resolution. The integration agent blocks the task and the reconciler workflow handles resolution.

### K. What happens if GitHub is unavailable?

**Answer (D10, unchanged):** Retry transient failures (API 5xx, network errors, rate-limit 429) with exponential backoff (5s, 10s, 30s, 60s, 120s — up to 5 attempts). After exhausting retries, block with `github_unavailable` and notify the worker. The agent does NOT mark DONE under any failure condition.

**Reality check:** `review_ship_info()` returns `ghReady: False` when `gh` is missing or unauthenticated. The integration agent checks this before PR creation and retries.

### L. How does this interact with `kanban_task_completed` and replenishment?

**Answer (D11, unchanged):** For worktree tasks, `complete_task()` (first call, by worker) does NOT fire `kanban_task_completed` — it transitions to `review` and fires `on_kanban_integration_ready`. The integration agent fires `kanban_task_completed` (only after merge verification) by calling `complete_task()` a second time, which transitions to `done` and fires the hook. Replenishment fires at the correct time (after merge). For non-worktree tasks, `complete_task()` fires `kanban_task_completed` as before (no integration step).

**Reality check:** The `replenishment` plugin (`plugins/replenishment/__init__.py`) hooks into `kanban_task_completed` and is unchanged. The timing change is purely in when the hook fires — the plugin sees the same event, just later. No changes to the replenishment plugin are required.

---

## 4. Reading Task Metadata

The integration agent reads the task row via `kanban_db.get_task(task_id)` → `Task` dataclass.

Fields used:

| Column            | Purpose                                      |
|-------------------|----------------------------------------------|
| `workspace_kind`  | Guard: only `'worktree'` eligible            |
| `branch_name`     | Branch to create PR from                     |
| `workspace_path`  | Absolute path to the worktree; `cwd` for `web_git` functions |
| `status`          | Must be `review` (the integration-ready state) |
| `metadata`        | JSON dict carrying `integration_state`, `pr_number`, `pr_url`, `target_branch`, `task_commit_sha`, `auto_merge_enabled`, `merge_verified` |

**Reality check:** The `metadata` column is a TEXT column storing JSON. `get_task()` returns it as a parsed dict (if the `Task` dataclass handles deserialization). If not, the integration agent must call `json.loads()` on the raw value. `set_metadata()` is the accessor — if it doesn't exist, the agent uses `kanban_db` UPDATE directly or a new helper.

Branch naming: deterministic via `projects_db.branch_name_for()` for project-linked tasks → `<project-slug>/<task-id>[-<title-slug>]`; fallback `wt/<task-id>` for non-project worktree tasks (set by dispatcher).

**Scope boundary:** Only tasks with `workspace_kind == 'worktree'` have an associated git branch and are eligible for PR automation. Scratch and dir tasks are silently skipped and follow the normal `complete_task() → done → kanban_task_completed` path.

---

## 5. The Integration Workflow (8 Steps, Idempotent)

### Step 1 — Commit & Push (implementation discipline)

**Assumption:** The worker has already committed and pushed their work to the task branch before calling `kanban_complete`. The repo-sync gate in `complete_task()` (`_enforce_repo_sync_gate()`) enforces this: `_worktree_is_dirty()` and `_worktree_has_unpushed_commits()` (from `cli.py`) check the worktree state. A worktree task **cannot leave `running`** (and cannot enter `review`) unless its repo state is committed and pushed.

This means the integration agent only ever sees branches whose commits are already on the remote — no stale-branch problem at workflow start.

### Step 2 — Synchronize with latest target branch

**Required (Gap 2 + Gap 7).** The repo-sync gate only checks "committed + pushed" — it does NOT compare merge-base against the remote target.

1. **Fetch remote target branch.** `git fetch origin <target_branch>`.
2. **Compute merge-base.** `git merge-base <task_branch> origin/<target_branch>`.
3. **Detect staleness.** If the merge-base is behind `origin/<target_branch>`, the branch is stale.
4. **Rebase onto target.** `git rebase origin/<target_branch>` on the task branch (in the worktree `cwd`).
5. **Force-push.** `git push --force-with-lease origin <task_branch>`.
6. **Conflict handling.** If the rebase produces conflicts:
   - Abort the rebase (`git rebase --abort`).
   - Block the task with reason `sync_conflict` (set `status='blocked'`).
   - Attach the rebase conflict output as artifacts.
   - Route to the `merge-reconciler` skill.
   - **Do NOT proceed to PR creation or verification.**

State persisted: `metadata.integration_state = 'syncing'` before, `'synced'` or `'conflict'` after.

### Step 3 — Run verification/tests

**Required (Gap 3).** After the final rebase (Step 2), run the project's test suite **locally** on the rebased branch.

- Use Janus's `src/janus/verification.py` (which exists) to run the deterministic verification gate.
- Only proceed to PR creation if **all checks pass**.
- On failure: block the task with reason `post_sync_verification_failure`, attach test output as artifacts, and notify the worker.

State persisted: `metadata.integration_state = 'verifying'` (running) → `'verified'` (pass) or task blocked (fail). The `task_commit_sha` is recorded after rebase so it can be verified post-merge.

### Step 4 — Create GitHub PR

Reuses existing `web_git.py` functions:

1. **Guard — gh auth.** `review_ship_info(workspace_path)` → returns `{"ghReady": bool, ...}`. If `ghReady` is False, retry with backoff.
2. **Guard — idempotency.** Check `metadata.pr_number`. If set, verify the PR still exists via `review_pr_list(workspace_path, branches=[branch_name])`. If the PR exists and is open, skip to CI monitoring (Step 5). If the persist record is stale, log and proceed to re-create.
3. **Create PR.** `review_create_pr(workspace_path)` — internally calls `_review_push(cwd)` (handles both tracked and untracked branches), then runs `gh pr create --fill` (title/body auto-populated from commits).
4. **Persist.** Store `pr_number`, `pr_url`, and `target_branch` in `tasks.metadata`.

State persisted: `metadata.integration_state = 'pr_created'`.

### Step 5 — Wait for CI

**Required (Gap 4).** After PR creation, the integration agent must wait for CI to complete:

1. Poll `gh pr checks <number>` (or the GitHub Checks API via `gh api`) until all **required** checks are in a terminal state (`SUCCESS` or `FAILURE`).
   - Poll interval: ~30s. Use `gh pr checks --watch` where available.
2. **On CI success:** proceed to auto-merge (Step 6).
3. **On CI failure:** block the task with reason `ci_failure`, attach CI logs as artifacts, and notify the worker. Do NOT enable auto-merge.

State persisted: `metadata.integration_state = 'ci_running'` (polling) → `'ci_passed'` or task blocked.

### Step 6 — Enable auto-merge

**Required (Gap 5).** After CI success:

1. Check if the repo has auto-merge enabled in its settings. If not, fall back to manual merge via `gh pr merge <number> --squash --delete-branch`.
2. If auto-merge is enabled: call `gh pr merge <number> --auto --squash --delete-branch`.
3. If auto-merge is not enabled: merge directly with `gh pr merge <number> --squash --delete-branch`.

State persisted: `metadata.integration_state = 'auto_merge_enabled'` or `'merged'`, `metadata.auto_merge_enabled = true` (boolean), `metadata.merge_method = 'auto'|'direct'`.

### Step 7 — Verify merge into target

**Required (Gap 6).** After enabling auto-merge (or direct merge), poll until the PR is confirmed merged:

1. Poll `gh pr view <number> --json state` until it returns `MERGED` (poll interval ~30s).
2. **Alternative / cross-check:** `git fetch origin` then `git branch -r --contains <task_commit_sha>` to confirm `origin/<target_branch>` contains the task commit.
3. Only when merge is **confirmed** does the integration agent proceed to mark the task `done`.

State persisted: `metadata.integration_state = 'merge_verified'`, `metadata.merge_verified = true`.

### Step 8 — Mark task DONE

Only after Step 7 confirms the merge:

1. The integration agent calls `complete_task()` — which this time commits the task to `status='done'` and fires `kanban_task_completed`.
2. `kanban_task_completed` → replenishment plugin fires at the correct time (after merge).
3. The worktree is cleaned up by `_cleanup_workspace()` during this final `complete_task()` call.

---

## 6. Integration Safety

### 6.1 Branch freshness

`_enforce_repo_sync_gate()` in `complete_task()` enforces that a worktree task's repo state is committed and pushed before it can transition out of `running`. This prevents the integration agent from seeing a dirty or unpushed branch.

However, this gate does **not** guarantee the branch is up to date with the latest target. Step 2 (Synchronize) fills that gap: it fetches the remote target, computes merge-base, rebases if stale, and force-pushes — all before PR creation.

### 6.2 Auto-merge

**Enabled by this revised design** (was out of scope in the original). After CI passes (Step 6), the integration agent enables auto-merge via `gh pr merge <number> --auto --squash --delete-branch`. If the repository does not support auto-merge, the agent falls back to a direct merge.

### 6.3 Merge conflicts

**Handled by this revised design** (was deferred in the original).

| Context              | Behavior                                                      |
|----------------------|---------------------------------------------------------------|
| **During sync** (Step 2) | Rebase conflicts → abort, block task with `sync_conflict`, route to merge-reconciler. **Do NOT create PR.** |
| **During integration**  | If GitHub reports a merge conflict after PR creation → block with `integration_conflict`, route to merge-reconciler. |

### 6.4 Worktree cleanup timing

`_cleanup_workspace()` is called inside `complete_task()` at line ~5767. Since `complete_task()` now transitions worktree tasks to `review` (not `done`) on the first call, and the actual `done` transition happens later in the integration agent, the worktree must **not** be cleaned up at first-completion time — it must remain available for sync, verification, and PR operations.

**Required change:** Defer `_cleanup_workspace()` for worktree tasks until the integration agent's final `complete_task()` call (Step 8). The integration agent can delete the worktree after merge verification; the source branch is also deleted by `gh pr merge --delete-branch`.

---

## 7. Failure Modes and Worker Feedback

| Failure                              | Handling                                                      |
|--------------------------------------|---------------------------------------------------------------|
| Sync conflict (rebase fails)         | Block task with `sync_conflict`, attach conflict output, route to merge-reconciler. (Step 2) |
| Pre-PR verification fails            | Block task with `post_sync_verification_failure`, attach test output. (Step 3) |
| PR creation fails (gh error)         | Retry with exponential backoff. After N retries, block with `github_unavailable`. (Step 4) |
| CI fails on the PR                   | Block task with `ci_failure`, attach CI logs, notify worker. No auto-merge. (Step 5) |
| Auto-merge cannot be enabled         | Fall back to direct merge. If direct merge also fails, block with `merge_failed`. (Step 6) |
| Merge not confirmed (timeout)        | Block task with `merge_timeout`, notify worker. (Step 7) |
| Branch is stale at PR creation       | Prevented by Step 2 (Synchronize).                            |
| GitHub temporarily unavailable       | Retry with backoff. After N retries, block with `github_unavailable`. |
| `gh` not installed / not authenticated | Retry with backoff. If persistent, block with `github_unavailable`. |
| Non-worktree task                    | Silently skipped — follows normal `complete_task() → done` path. |
| Duplicate workflow start             | `metadata.integration_state` + `pr_number` idempotency check → resume from last step. (Step 4, D4) |

**Worker feedback:** On any failure that blocks the task:
1. The integration agent sets `status='blocked'` with the specific reason.
2. Attaches error/conflict/CI-log output as artifacts (via `kanban_attach`).
3. Posts a comment to the task (via `kanban_comment`) explaining what failed and what the worker must do next.
4. The worker fixes the issue, then re-runs the integration (the agent resumes from the last successful step — idempotency via D4/D9).

**Retry semantics (D13):** Transient failures (GitHub API 5xx, network errors, rate limits) are retried with exponential backoff (5s, 10s, 30s, 60s, 120s — up to 5 attempts). Permanent failures (4xx auth errors, 404 not found, validation errors) block immediately without retry.

---

## 8. Task ↔ PR State Tracking (D4, D12)

The PR URL, PR number, and full workflow step state are persisted in `tasks.metadata` (a TEXT column storing JSON). No new `pr_created` status column or separate tracking table is introduced.

`integration_state` values:

| Value                  | Meaning                                    |
|------------------------|--------------------------------------------|
| *(not set)*            | Integration not yet started                 |
| `ready`                | Hook fired, queued for the integration agent |
| `syncing`              | Rebase + force-push in progress             |
| `synced` / `conflict`  | Sync done / sync conflict                   |
| `verifying`            | Tests running                               |
| `verified`             | Tests passed, ready for PR creation         |
| `pr_created`           | PR exists on GitHub                         |
| `ci_running`           | Waiting for CI                              |
| `ci_passed`            | CI passed                                   |
| `auto_merge_enabled` / `merged` | Auto-merge enabled / direct merge done  |
| `merge_verified`       | PR confirmed merged into target             |

Additional metadata fields:

| Field                  | Type    | Purpose                                      |
|------------------------|---------|----------------------------------------------|
| `pr_number`            | int     | GitHub PR number (set after PR creation)     |
| `pr_url`               | str     | GitHub PR URL                                |
| `target_branch`        | str     | The branch the PR targets (e.g. `master`)    |
| `task_commit_sha`      | str     | SHA of the task branch tip after rebase (Step 3) |
| `auto_merge_enabled`   | bool    | Whether auto-merge was enabled               |
| `merge_verified`       | bool    | Whether merge into target was confirmed      |

**Idempotency (D4):** On retry, the integration agent reads `integration_state` and resumes from the last successful step. It does NOT re-run sync if already past `synced`; it does NOT re-create a PR if `pr_number` is set; it does NOT re-enable auto-merge if already enabled.

---

## 9. Kanban Completion vs. Integration (C, D11)

### 9.1 When does Kanban become DONE?

**Kanban becomes DONE only after the PR is verified merged into the target branch.**

For worktree tasks:
1. Worker calls `kanban_complete` → `complete_task()` transitions the task to `review` (not `done`), fires `on_kanban_integration_ready` (sets `integration_state = 'ready'`), and returns control to the worker.
2. The integration agent picks up the task and runs Steps 1–7.
3. Only after Step 7 confirms the merge does the integration agent call `complete_task()` to commit the task to `status='done'` and fire `kanban_task_completed` → replenishment.

### 9.2 Interaction with replenishment

Replenishment is **unchanged in mechanism** — it still consumes `kanban_task_completed` via `plugins/replenishment/__init__.py`. What changes is **timing**: that event now fires later (after merge instead of after `kanban_complete`). No changes to the replenishment plugin are required.

---

## 10. Non-Repository / Non-Coding Tasks

**Preserved by the `workspace_kind` guard.** Tasks with `workspace_kind != 'worktree'` (scratch, dir) have no associated git branch and are silently skipped by the integration workflow. They follow the normal `complete_task() → done → kanban_task_completed` path — `kanban_complete` transitions them directly to `done`.

---

## 11. Architectural Decisions (D1–D13, Confirmed)

D1: New `on_kanban_integration_ready` hook fired from within `complete_task()` after the write transaction commits, but only for worktree tasks transitioning to `review`.
D2: Reuse the existing `review` status.
D3: Use Hermes-Agent's `web_git.py` + direct git calls for sync; Janus's `verification.py` for verification.
D4: Persist `pr_number` + `pr_url` in `tasks.metadata`; check before creating.
D5: Poll `gh pr checks` or the GitHub Checks API.
D6: `gh pr merge --auto --squash --delete-branch`, with a direct-merge fallback.
D7: Poll `gh pr view <number> --json state` until `MERGED`.
D8: Block with `ci_failure`, attach logs, notify worker.
D9: Block + route to merge-reconciler. Do NOT create PR if sync conflicts.
D10: Retry with exponential backoff; block if persistent.
D11: `kanban_task_completed` fires only after merge verification.
D12: `tasks.metadata` JSON column + `integration_state` field.
D13: Exponential backoff (5 attempts) + step-level timeouts.

---

## 12. Risks and Mitigations

1. **Race condition (two tasks integrating to the same target branch):** The second push will be rejected by git. Mitigation: retry with re-sync.
2. **Long-running integration agent:** CI + auto-merge + merge confirmation can take minutes to hours. The integration agent is a long-running process or a cron-polled workflow, not a single synchronous hook call.
3. **Hook timeout:** The `on_kanban_integration_ready` hook is synchronous and best-effort. It only sets `integration_state = 'ready'`. The actual work is done by the polling agent.
4. **Replenishment double-fire:** `kanban_task_completed` is fired from the integration agent's second `complete_task()` call, not from the worker's first call. No double-fire.
5. **Worktree cleanup timing:** `_cleanup_workspace()` must be deferred for worktree tasks until the final `complete_task()` call. **Required code change.**
6. **Agent crash mid-workflow:** The integration state is persisted in `tasks.metadata` after every step. On restart, the agent resumes from the last `integration_state`.
7. **CI flakiness:** Transient CI failures may block merge. The CI monitoring step polls until a terminal state. If CI fails, the task is blocked (D8).
8. **Non-worktree tasks in `review` status:** If a non-worktree task ends up in `review` (e.g., manually transitioned), the integration agent's `workspace_kind` guard ensures it is skipped.

---

## 13. Codebase Reality Check (Gaps Between Design Claims and Actual Code)

The t_6fba151b revision referenced several modules as existing that do not exist in the Janus repository. This section documents the actual state.

### 13.1 Modules the design claims exist but do NOT in Janus

| Claimed module | Design reference | Actual status |
|----------------|------------------|---------------|
| `src/janus/git_sync.py` | D3, §14 Change 2 imports | **Does not exist.** Sync primitives must come from Hermes-Agent's `web_git.py` + direct `git` subprocess calls. |
| `src/janus/verification_step.py` | D3, §14 Change 2 imports, Step 3 | **Does not exist.** Verification must use Janus's actual `src/janus/verification.py`. |

### 13.2 Modules the design claims exist and DO exist (in Hermes-Agent)

| Capability                | Location                                | Status |
|---------------------------|-----------------------------------------|--------|
| worktree-per-task         | `kanban_db.py:_ensure_git_worktree`    | ✅ Exists |
| repo-sync gate            | `kanban_db.py:_enforce_repo_sync_gate` | ✅ Exists (pre-commit/push gate only) |
| PR creation               | `web_git.py:review_create_pr`          | ✅ Exists (in Hermes-Agent, not Janus) |
| PR idempotency check      | `web_git.py:review_pr_list`            | ✅ Exists |
| gh auth check             | `web_git.py:review_ship_info`          | ✅ Exists |
| target branch detection   | `web_git.py:_default_branch_name`      | ✅ Exists |
| merge-base computation    | `web_git.py:_branch_base`              | ✅ Exists (for current branch vs remote default; needs extension for specific target branch) |
| pre-PR verification gate  | `src/janus/verification.py`            | ✅ Exists (Janus, not `verification_step.py`) |
| lifecycle hooks           | `kanban_db.py:_fire_kanban_lifecycle_hook` | ✅ Exists |
| Kanban state transitions  | `complete_task`, `request_review`, etc. | ✅ Exists |
| replenishment plugin      | `plugins/replenishment/__init__.py`    | ✅ Exists (fires correctly after this) |
| merge-reconciler skill    | `skills/autonomous-ai-agents/merge-reconciler/` | ✅ Exists |
| github-pr-workflow skill  | `skills/github/github-pr-workflow/`    | ✅ Exists |

### 13.3 Modules the design requires but do NOT exist anywhere

| Required capability | Gap | Mitigation |
|---------------------|-----|------------|
| `on_kanban_integration_ready` hook | No such hook exists in `kanban_db.py` or `lifecycle.py` | **Required code change:** add hook name to dispatch registry + firing point in `complete_task()` |
| `set_metadata()` accessor for `tasks.metadata` | No such function found in `kanban_db.py` | **Required code change:** add `set_metadata()` or use direct UPDATE |
| `is_branch_stale()` / `merge_base_with()` in `web_git.py` | `_branch_base()` computes merge-base for current branch vs remote default only | **Required code change:** extend `web_git.py` or compute in plugin via direct git call |
| Integration agent plugin (`plugins/kanban_pr_create/__init__.py`) | Does not exist | **Required code change:** new file |

---

## 14. Smallest Set of Hermes Changes Required

### Change 1: `hermes_cli/kanban_db.py` — new hook + trigger point adjustment (~50–80 lines)

1. Add `on_kanban_integration_ready` to the hook dispatch registry (if a registry exists; otherwise just fire it via `_fire_kanban_lifecycle_hook`).
2. In `complete_task()`: for `workspace_kind == 'worktree'`, transition to `review` (not `done`) inside the write transaction. After the transaction commits and before `_cleanup_workspace()`, fire `on_kanban_integration_ready`. Do NOT fire `kanban_task_completed` from this path.
3. For non-worktree tasks: keep existing behavior.
4. Defer `_cleanup_workspace()` for worktree tasks until the final `done` transition (Step 8). Either skip it in the first `complete_task()` call for worktree tasks, or guard it with a check that the task is actually `done` (not `review`).

### Change 2: `plugins/kanban_pr_create/__init__.py` — new integration agent plugin (~300–400 lines)

New file following the `plugins/replenishment/` pattern but as a polling integration agent:

```python
# 1. register() — registers on_kanban_integration_ready callback
# 2. on_kanban_integration_ready(task_id, ...) — thin hook callback
#    Sets metadata.integration_state = 'ready'; emits kanban_integration_queued event.
# 3. _run_integration(task_id) — main agent loop:
#    a. load task → check workspace_kind == 'worktree' (else skip)
#    b. read integration_state → resume from last step
#    c. Step 2: sync (fetch target, merge-base, rebase, force-push, conflict→block)
#    d. Step 3: verify (verification.py: run tests)
#    e. Step 4: create PR (review_create_pr, idempotent via pr_number)
#    f. Step 5: wait for CI (gh pr checks --watch or polling)
#    g. Step 6: enable auto-merge (gh pr merge --auto --squash --delete-branch, direct-merge fallback)
#    h. Step 7: verify merge (gh pr view --json state → MERGED)
#    i. Step 8: complete_task() → done → kanban_task_completed → replenishment
#    j. on failure at any step: block task, attach artifacts, kanban_comment to notify
```

### Change 3: `hermes_cli/web_git.py` — merge-base against specific target branch (~10–20 lines)

Add a function to compute merge-base between a specific branch and a specific target ref, since `_branch_base()` only handles current branch vs remote default. Alternatively, the plugin can call `git merge-base` directly via subprocess.

### Change 4: `hermes_cli/kanban_db.py` — `set_metadata()` helper (~10–20 lines)

Add a `set_metadata(conn, task_id, key, value)` helper that reads the existing JSON, updates the key, and writes it back. If `get_task()` already deserializes `metadata` into the `Task` dataclass, use that path.

### Change 5: Plugin registration in profile config (~1 line)

Add `kanban_pr_create` to the profile's plugin config (e.g. `config.yaml` under `plugins:`), matching how `replenishment` is registered.

### Imports (plugin):

- `review_ship_info`, `review_pr_list`, `review_create_pr` from `hermes_cli.web_git`
- `get_task`, `complete_task`, `_default_branch_name` from `hermes_cli.kanban_db`
- `set_metadata` from `hermes_cli.kanban_db` (new)
- `merge_base_with` from `hermes_cli.web_git` (new) or direct `git merge-base` call
- `VerificationStep` / verification from `src/janus.verification` (Janus, not `verification_step`)

### Summary: 5 changes, ~400–550 lines total

1. `kanban_db.py` — new hook + trigger point + cleanup deferral (~50–80 lines)
2. `plugins/kanban_pr_create/__init__.py` — new integration agent (~300–400 lines)
3. `web_git.py` — merge-base against specific target (~10–20 lines)
4. `kanban_db.py` — `set_metadata()` helper (~10–20 lines)
5. `config.yaml` — plugin registration (~1 line)

No new status column, no new table, no dev branch, no Git orchestration framework.

---

## 15. Verification Criteria

1. **Trigger fires before DONE:** Complete a worktree task; confirm the task enters `review` (not `done`) and `integration_state = 'ready'` is set. `kanban_task_completed` does NOT fire yet.
2. **Sync runs before PR:** Confirm rebase onto target branch is performed before PR creation.
3. **Verification gate:** Confirm tests are run after rebase. Confirm a test failure blocks the task.
4. **PR created:** Confirm PR appears on GitHub on the task branch.
5. **CI monitoring:** Confirm the agent polls CI and waits for completion.
6. **Auto-merge enabled:** Confirm `gh pr merge --auto` is called after CI passes.
7. **Merge verified:** Confirm the agent polls PR state until `MERGED`, and only then transitions the task to `done`.
8. **Replenishment timing:** Confirm `kanban_task_completed` fires only after merge verification.
9. **Idempotency:** Kill the agent mid-workflow, restart; confirm it resumes from the last `integration_state`. Re-complete the task; confirm no duplicate PR.
10. **Conflict handling:** Inject a merge conflict during sync; confirm the task is blocked, the conflict output is attached, and no PR is created.
11. **Non-worktree skipped:** Complete a scratch task; confirm no integration workflow and the task goes directly to `done`.
12. **Failure feedback:** Force a PR creation failure; confirm the task is blocked, logs are attached, and a comment is posted.
13. **Worktree preserved during integration:** Confirm the worktree is NOT cleaned up after the first `complete_task()` call; it is only cleaned up after the integration agent's final `complete_task()` call.

---

## 16. Explicitly Out of Scope

- No `pr_created` task status column (state tracked in `metadata` instead).
- No separate PR state machine table.
- No PR labeling bridge.
- No outbound webhook or event bridge.
- No CI configuration changes.
- No changes to `hermes_cli/` core beyond the trigger-point adjustment in `complete_task()` and the new hook name.
- No human-in-the-loop for the happy path.
- No `src/janus/git_sync.py` (does not exist; use Hermes-Agent primitives).
- No `src/janus/verification_step.py` (does not exist; use `verification.py`).
