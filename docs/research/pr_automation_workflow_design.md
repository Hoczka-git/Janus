# PR Automation Design for Repository-Backed Kanban Tasks

**Task:** t_2fbd2e6e
**Parents:** t_a471fe81 (analysis), t_351b36de (design)
**Date:** 2026-09-02

---

## 0. Source

This design is based on `docs/research/reusable_hermes_pr_capabilities.md` (from t_a471fe81)
and `docs/research/pr_automation_design.md` (from t_351b36de). The original reference file
`docs/research/kanban_pr_automation_findings.md` does not exist in this repository; the
analysis and design from the child tasks serve as the design input.

---

## 1. Trigger: What event starts PR creation? (A)

**`kanban_task_completed` hook.**

- Fired by `complete_task()` in `hermes_cli/kanban_db.py:5534` after the task row is
  committed to `status='done'` and the write transaction closes.
- Dispatched through `_fire_kanban_lifecycle_hook()` (`kanban_db.py:188`), which wraps
  every plugin call in `try/except` — a broken PR plugin cannot break task completion.
- Fires in the **worker process** (the `hermes -p <profile> chat -q` subprocess), per
  `hermes_cli/plugins.py:273`. The plugin gets direct SQLite access with no write lock.
- Hook kwargs (`plugins.py:283`): `task_id`, `board`, `assignee`, `run_id`, `summary`,
  `profile_name`. Notably: **no branch name, no workspace path** — the plugin must read
  those from the `tasks` table itself.

Reference implementation pattern: `plugins/replenishment/__init__.py` — thin
`on_task_completed(task_id, ...)` callback delegating to a `_run_*` function wrapped in
`try/except Observer-only`.

---

## 2. Reading Task Metadata (B, D)

The plugin reads the task row via `kanban_db.get_task(task_id)` → `Task` dataclass
(`kanban_db.py:1066-1071`).

Fields used:

| Column            | Purpose                                      |
|-------------------|----------------------------------------------|
| `workspace_kind`  | Guard: only `'worktree'` proceeds           |
| `branch_name`     | Branch to create PR from (e.g. `janus/t_xyz` or `wt/<id>`) |
| `workspace_path`  | Absolute path to the worktree; `cwd` for `web_git` functions |

Branch naming is deterministic: `projects_db.branch_name_for()` (`projects_db.py:1013`)
for project-linked tasks → `<project-slug>/<task-id>[-<title-slug>]`; fallback
`wt/<task-id>` for non-project worktree tasks (set by dispatcher at `kanban_db.py:10611`).

**Scope boundary:** only tasks with `workspace_kind == 'worktree'` have an associated git
branch and are eligible for PR automation. Scratch and dir tasks are silently skipped.

---

## 3. PR Creation: Reusing Existing Functions

All git/PR operations already exist in `hermes_cli/web_git.py`. The plugin calls three
functions, in order:

### 3.1 Guard — gh auth
`review_ship_info(workspace_path)` (`web_git.py:447`) → returns `{"ghReady": bool, ...}`.
If `ghReady` is False (gh not installed or not authenticated), skip silently.

### 3.2 Guard — idempotency
`review_pr_list(workspace_path, branches=[branch_name])` (`web_git.py:505`) — GraphQL-based
query that asks about branches we have sessions on. If any returned PR has
`"branch" == branch_name`, skip — PR already exists. This makes hook retries and
re-completions safe.

### 3.3 Create PR
`review_create_pr(workspace_path)` (`web_git.py:556`) — internally calls
`_review_push(cwd)` (`web_git.py:385`) which handles both tracked (`git push`) and
untracked (`git push -u origin <branch>`) branches, then runs `gh pr create --fill`
(title/body auto-populated from commits).

### 3.4 Persist PR URL
The PR URL from `review_create_pr` result (`result.get("url")`) is persisted back to the
task via `kanban_db.set_metadata()` or the `metadata` column.

---

## 4. Integration Safety (E, F, G)

### 4.1 Branch freshness (E)

The repo-sync gate in `complete_task()` (`kanban_db.py:~5589`) enforces
`_enforce_repo_sync_gate()`: a worktree task **cannot be marked `done`** unless its repo
state is committed and pushed. This means the PR plugin only ever sees branches whose
commits are already on the remote — no stale-branch problem at PR creation time.

CI already covers `wt/*` branches and `pull_request` events (`.github/workflows/ci.yml:3-7`).
No CI changes are needed.

### 4.2 Auto-merge (F)

**Not enabled by this design.** The repo has no branch protection and
`auto_merge_config` is null (per analysis doc). The design explicitly does **not** enable
auto-merge; PRs land in the GitHub PR queue for human or existing-Hermes review
(`kanban_request_review`, a separate internal flow per `kanban_db.py:6733`).

If auto-merge is desired in future, it would be a separate opt-in step triggered after PR
creation, via `gh pr merge --auto` — but that is explicitly out of scope for the minimal
implementation.

### 4.3 Merge conflicts (G)

**Not handled by this design.** The minimal implementation stops at PR creation. If a merge
conflict exists, the PR is still created (GitHub will show the conflict status); resolution
is left to the human reviewer or the existing merge-reconciler mechanism. The plugin does
not attempt to rebase or resolve conflicts — that would introduce new Git orchestration,
which the design explicitly avoids.

---

## 5. Failure Modes

| Failure                              | Handling                                         |
|--------------------------------------|--------------------------------------------------|
| PR creation fails (gh error)         | Swallowed by hook's `try/except` — task stays `done`. Plugin logs error. |
| CI fails on the PR                   | Out of scope — PR is already created; CI is a separate concern. |
| Branch is stale                      | Prevented by repo-sync gate in `complete_task()`. |
| Merge conflict                        | PR still created; conflict visible on GitHub. Resolution deferred. |
| Auto-merge cannot be enabled          | Not attempted — out of scope.                   |
| GitHub temporarily unavailable        | `review_create_pr` fails; swallowed by hook; task stays `done`. Retry via re-completion (idempotent) or manual trigger. |
| `gh` not installed / not authenticated | `review_ship_info` → `ghReady: False` → skip silently. |
| Non-worktree task                     | Guard on `workspace_kind` → skip silently.       |
| Duplicate hook fire                   | `review_pr_list` idempotency check → skip.       |

---

## 6. Task ↔ PR State Tracking (D)

**Minimal implementation: metadata column only.**

The PR URL is persisted in `tasks.metadata` (a free-form dict, `kanban_db.py:5534-5576`).
No new `pr_created` status column, no PR state machine, no separate tracking table — these
are deferred.

What this gives us:
- Task row carries the PR URL for audit/handoff purposes.
- `review_pr_list` idempotency check prevents duplicate PRs regardless of metadata.

What this does NOT give us:
- No automated "PR merged → mark task integrated" transition.
- No polling for PR state changes.
- No way for downstream automation to know whether the PR was merged.

This is intentional — the minimal design stops at PR creation.

---

## 7. Kanban Completion vs. Integration (C, H)

### 7.1 When does Kanban become DONE? (C)

**Kanban becomes DONE when `complete_task()` commits the task to `status='done`.** This
happens **before** PR creation. The PR plugin is an observer-only hook that fires after the
fact. The task is considered complete from the Kanban perspective the moment the worker calls
`kanban_complete` — PR creation is a post-completion side effect, not a precondition.

This matches the existing replenishment pattern: `plugins/replenishment/__init__.py`'s
`on_task_completed` fires after the task is already `done` and does not affect the task's
status.

### 7.2 Interaction with replenishment (H)

**No interaction.** The PR creation plugin and the replenishment plugin both consume the same
`kanban_task_completed` hook, but they operate independently:
- Replenishment: reads task metadata, generates new tasks in TRIAGE.
- PR creation: reads task branch/workspace, creates GitHub PR.

Neither plugin modifies the other's behavior. The hook system's best-effort dispatch
(`_fire_kanban_lifecycle_hook`, `kanban_db.py:188`) ensures that if either plugin fails, the
other still runs (each call is wrapped independently).

The existing `kanban_task_completed → replenishment` workflow is preserved unchanged.

---

## 8. Non-Repository / Non-Coding Tasks (J)

**Preserved by the `workspace_kind` guard.**

Tasks with `workspace_kind != 'worktree'` (scratch, dir) have no associated git branch and
are silently skipped by the PR plugin. The existing `kanban_task_completed` hook continues
to fire for all task types; only the PR plugin's callback bothers to check the workspace kind.
All other hook consumers (replenishment, any future plugins) are unaffected.

---

## 9. Minimal Implementation Plan

**Exactly one new file:**

### `plugins/kanban_pr_create/__init__.py`

Follows the `plugins/replenishment/` pattern:

```python
# 1. register() — registers on_task_completed callback
# 2. on_task_completed(task_id, ...) — thin hook callback
# 3. _run_pr_creation(task_id) — reads task, guards, creates PR, persists URL
```

Imports:
- `review_ship_info`, `review_pr_list`, `review_create_pr` from `hermes_cli.web_git`
- `get_task` from `hermes_cli.kanban_db`

Registration: add to the profile's plugin config (e.g. `config.yaml` under `plugins:`),
matching how `replenishment` is registered.

**No changes to `hermes_cli/` core.** All needed functions already exist.

**No CI changes.** CI already covers `wt/*` and `pull_request`.

**No new Git orchestration.** Reuses `_review_push` + `gh pr create --fill`.

---

## 10. Design Decisions Summary

| Question | Answer |
|----------|--------|
| **A. What event starts PR creation?** | `kanban_task_completed` hook, fired after task is committed to `done`. |
| **B. What means "task successfully integrated"?** | PR created and pushed (not merged). Integration = PR exists on GitHub. Merge is a separate step. |
| **C. When does Kanban become DONE?** | When `complete_task()` commits to `status='done'`. PR creation is post-completion, not a precondition. |
| **D. How is task↔PR mapping persisted?** | PR URL in `tasks.metadata` column. No state machine, no new columns. |
| **E. How is branch freshness enforced?** | Repo-sync gate in `complete_task()` prevents stale branches from reaching `done`. CI covers `wt/*`. |
| **F. How is auto-merge enabled?** | Not enabled. Out of scope for minimal implementation. PRs land in GitHub queue for human/existing review. |
| **G. What happens on conflict?** | PR is still created; conflict visible on GitHub. Resolution deferred to human or merge-reconciler. No automated conflict handling. |
| **H. How does this interact with replenishment?** | No interaction. Both plugins consume the same hook independently. Replenishment workflow preserved unchanged. |

---

## 11. What This Design Does NOT Include

- No `pr_created` task status column.
- No PR state machine or polling.
- No auto-merge (`gh pr merge --auto`).
- No branch rebase / conflict resolution.
- No PR labeling bridge.
- No outbound webhook or event bridge.
- No CI configuration changes.
- No changes to `hermes_cli/` core.

---

## 12. Verification

After implementation, verify:

1. **Hook fires:** Complete a worktree task; confirm `kanban_task_completed` callback runs (log line).
2. **PR created:** Confirm PR appears on GitHub on the `janus/<task-id>` branch.
3. **Idempotency:** Re-complete the task; confirm no second PR.
4. **Non-worktree skipped:** Complete a scratch task; confirm no PR attempt.
5. **No gh auth:** Run with `gh auth status` failing; confirm graceful skip.
6. **Replenishment unchanged:** Confirm replenishment still creates exactly one task in TRIAGE.

These match the verification pattern from `t_bc8fcd6b` and the existing
`tests/plugins/test_replenishment_plugin.py` test harness.
