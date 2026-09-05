# Summary: PR Automation Workflow Design

**Source:** `docs/research/pr_automation_workflow_design.md` (commit `a6987ec`, on branch `wt/t_2fbd2e6e`)
**Task:** t_c0e3a822

---

## 1. Current Workflow Steps

The design describes a **post-completion observer plugin** that creates a GitHub PR after a Kanban task is marked `done`:

1. **Trigger:** `kanban_task_completed` hook fires after `complete_task()` commits a task to `status='done'` (in `hermes_cli/kanban_db.py:5534`).
2. **Guard — workspace kind:** Plugin reads the task row; only `workspace_kind == 'worktree'` proceeds. Scratch/dir tasks are silently skipped.
3. **Guard — gh auth:** `review_ship_info(workspace_path)` → if `ghReady` is False, skip silently.
4. **Guard — idempotency:** `review_pr_list(workspace_path, branches=[branch_name])` → if a PR already exists for this branch, skip.
5. **Create PR:** `review_create_pr(workspace_path)` → internally pushes the branch (`_review_push`) and runs `gh pr create --fill`.
6. **Persist PR URL:** The resulting PR URL is stored in `tasks.metadata` (free-form dict column).

**One new file:** `plugins/kanban_pr_create/__init__.py` (follows `plugins/replenishment/` pattern). No changes to `hermes_cli/` core, no CI changes.

---

## 2. Stated Automation Goals and Constraints

**Goals:**
- Minimal implementation: reuse existing `web_git.py` functions (`review_ship_info`, `review_pr_list`, `review_create_pr`).
- Idempotent and safe: hook failures cannot break task completion (wrapped in `try/effort` by `_fire_kanban_lifecycle_hook`).
- Observer-only: PR creation is a post-completion side effect, not a precondition for `done`.
- No new Git orchestration: reuses `_review_push` + `gh pr create --fill`.

**Constraints (explicitly out of scope):**
- No auto-merge (`gh pr merge --auto`).
- No branch rebase or merge-conflict resolution.
- No PR state machine or polling.
- No `pr_created` status column.
- No PR labeling bridge, webhooks, or event bridge.
- No CI configuration changes.
- No changes to `hermes_cli/` core.

---

## 3. Gaps Between Current Design and a Complete impl→commit→push→sync→verify→PR Workflow

| Phase | Current Design | Gap |
|-------|---------------|-----|
| **Implementation** | Assumes code is already written in a worktree. | No gap — this is the worker's responsibility. |
| **Commit** | Assumes worker committed changes before `kanban_complete`. | Relies on human/worker discipline; no enforced pre-commit check in the plugin. |
| **Push** | Handled by `_review_push` inside `review_create_pr`. | No gap — push happens automatically. |
| **Sync** | Enforced by `_enforce_repo_sync_gate()` in `complete_task()` — task cannot reach `done` unless repo is committed and pushed. | No gap — sync is a precondition for `done`. |
| **Verify** | CI already covers `wt/*` branches and `pull_request` events. | **Gap:** The design does not gate PR creation on CI passing. PR is created regardless of CI status. No verification step between push and PR creation. |
| **PR** | PR created via `gh pr create --fill`. | **Gap:** No auto-merge. PR lands in GitHub queue for human/existing review. No automated "PR merged → mark task integrated" transition. |
| **Post-PR** | PR URL stored in `tasks.metadata` only. | **Gap:** No polling for PR state changes. No way for downstream automation to know if the PR was merged, closed, or is in review. No feedback loop to the Kanban task. |
| **Conflict handling** | PR still created; conflict visible on GitHub. | **Gap:** No automated conflict resolution or rebase. Deferred to human or merge-reconciler. |
| **Labeling / routing** | Not addressed. | **Gap:** No PR labeling bridge to route PRs to reviewers or teams. |

### Key Architectural Gaps

1. **No verification gate before PR creation.** The design creates the PR immediately after `done`, without checking CI status. A complete workflow would verify CI passed on the branch before creating the PR.

2. **No post-PR lifecycle management.** Once the PR is created, the Kanban task has no awareness of PR state. There is no automated path from "PR merged" back to the task (e.g., marking it `integrated` or triggering downstream tasks).

3. **No auto-merge.** The design explicitly avoids this, but a complete end-to-end workflow would include auto-merge (with appropriate safety conditions) to fully close the loop.

4. **No conflict resolution.** The design defers this entirely, but a more complete workflow would attempt an automated rebase before giving up.

5. **No feedback to the worker.** The worker that completed the task gets no signal about whether PR creation succeeded or failed (it is observer-only and swallowed by `try/except`).

---

## Recommendation

The design is intentionally minimal and achieves a safe, idempotent "create PR on completion" workflow with a single new plugin file. The primary gaps — verification gating, post-PR lifecycle, and auto-merge — are all explicitly deferred. A revision should decide whether to close any of these gaps or keep the minimal scope.
