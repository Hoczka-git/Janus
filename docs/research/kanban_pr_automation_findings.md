# Survey: Hermes Kanban → GitHub PR Automation Hooks

**Date:** 2026-09-02
**Scope:** Hermes Agent kanban subsystem (`~/.hermes/hermes-agent/`), Janus project repo, PR creation trigger points.
**Method:** Code search + read-only inspection. No implementation.

---

## 1. Current PR Creation Trigger Points

**Finding: There is NO existing automation that creates PRs from Kanban task state changes.**

What exists today:

| Surface | What it does | Connected to Kanban? |
|---|---|---|
| `hermes_cli.web_git.review_create_pr()` | Runs `gh pr create --fill` for the current branch. Used by the desktop "ship" flow and `/api/git/review/create-pr` REST endpoint. | **No.** Manual/desktop only. |
| `/api/git/review/create-pr` | REST endpoint wrapping `review_create_pr`. | **No.** Client-driven. |
| `gh pr create` (skill guidance) | GitHub PR workflow skill teaches the LLM to run `gh pr create` in terminal. | **No.** LLM-initiated, not event-driven. |
| Webhook `github-pr-review` | Receives PR events from GitHub, routes to agent for review, delivers comments back via `gh pr comment`. | **No.** Inbound (GitHub → Hermes), not outbound. |

The only automation-adjacent mechanism is the **Kanban lifecycle plugin hook** system (`kanban_task_completed`, `kanban_task_claimed`, `kanban_task_blocked`). These hooks fire on task state transitions and can be consumed by plugins. The `replenishment` plugin already uses `kanban_task_completed` to pull new tasks onto the board. **This is the integration point for task → PR automation** — but no plugin currently creates PRs.

---

## 2. Branch Naming & Labeling Conventions Tied to Kanban Tasks

Two conventions exist, both deterministic:

### a) Project-linked tasks (canonical)
Defined in `hermes_cli.projects_db.branch_name_for()`:
```
<project-slug>/<task-id>[-<title-slug>]
```
Example: `janus/t_c3259458-survey-pr-hooks`

- `project-slug` comes from the project record in `projects.db`.
- `title-slug` is derived from the task title (lowercase, separators collapsed, capped at 40 chars).
- Set via `set_branch_name()` at dispatch time (`kanban_db.py:10613`).

### b) Non-project tasks (fallback)
```
wt/<task-id>
```
- Applied when no project is linked and no explicit branch name was given.
- This is the random-looking fallback the Janus workspace currently uses (`wt/t_c3259458`).

### c) Labeling
**No labeling convention tied to Kanban tasks exists.** No code searches for GitHub label creation or label-from-task mappings. The only label-like construct is the `kanban_request_review` / `kanban_request_changes` event provenance, which persists reviewer/implementer identity but does not map to GitHub labels.

---

## 3. Gaps Between Current Behavior and Desired "Task → PR" Automation

| Gap | Detail |
|---|---|
| **No PR creation hook** | `kanban_task_completed` fires in the worker process after a task is marked done. No plugin consumes it for PR creation. This is the most natural integration point. |
| **No task-→PR state machine** | Current task lifecycle: `todo → ready → running → done` (or `review → done`). No `pr_created` status, no PR URL persistence on the task, no guard against double-creation. |
| **No branch-→PR linking** | The dispatcher persists `branch_name` on the task (`tasks.branch_name`) and creates the worktree. But nothing reads that branch back to create a PR. |
| **No labeling bridge** | Task metadata (assignee, project, title/body) could map to PR labels, but no such mapping exists. |
| **Review lane ≠ PR lane** | The existing review flow (`kanban_request_review` → reviewer worker → `kanban_complete`) is a human/LLM code-review cycle inside Hermes. It does not produce a GitHub PR. The two flows are orthogonal. |
| **Inbound webhooks only** | GitHub webhooks (`github-pr-review`, `github-issues`) are inbound — Hermes reacts to PRs, doesn't create them from task events. |

---

## 4. Integration Points for Future Automation

1. **`kanban_task_completed` plugin hook** — fires in the worker process with `{task_id, board, assignee, run_id, summary}`. A plugin could: read the task's `branch_name`, check if a PR already exists (`gh pr list --head <branch>`), and create one if not. The replenishment plugin (`plugins/replenishment/`) is the reference implementation for a `kanban_task_completed` consumer.

2. **`_fire_kanban_lifecycle_hook()` in `kanban_db.py:188`** — the central dispatch for all lifecycle hooks. Already handles `kanban_task_completed`, `kanban_task_claimed`, `kanban_task_blocked`. Best-effort and observer-only — a broken PR plugin cannot break task completion.

3. **`review_create_pr()` in `web_git.py:556`** — existing function that runs `gh pr create --fill` and returns the PR URL. A plugin could call this with the task's workspace path.

4. **`/api/git/review/create-pr` REST endpoint** (`web_routers/git.py:167`) — already exposes PR creation over HTTP. Could be called from a plugin or external automation.

5. **`tasks.branch_name` column** — already persisted per-task. A PR automation plugin would read this to know which branch to create the PR from.

6. **Worktree lifecycle** — the dispatcher already creates a worktree per task under `<repo>/.worktrees/<task-id>`. The worker pushes commits there. PR creation would happen after the worker finishes (on `kanban_task_completed`).

---

## 5. Summary

- **What exists:** Lifecycle hooks (`kanban_task_completed`), deterministic branch naming, worktree-per-task, `gh pr create` helper, REST API for PR creation.
- **What is missing:** A plugin or automation that connects `kanban_task_completed` (or a new event) to `gh pr create`. No PR-on-completion, no task↔PR linking, no label sync.
- **The path of least resistance:** A `kanban_task_completed` plugin (like replenishment) that reads the task's `branch_name`, checks for an existing PR on that branch, and creates one if absent. The `review_create_pr()` function does the actual `gh pr create --fill` call.

---

## References

- `hermes_cli/kanban_db.py:188` — `_fire_kanban_lifecycle_hook()`
- `hermes_cli/kanban_db.py:6733` — `request_review()` (review lifecycle)
- `hermes_cli/projects_db.py:1013` — `branch_name_for()` (deterministic branch naming)
- `hermes_cli/web_git.py:556` — `review_create_pr()` (gh pr create wrapper)
- `hermes_cli/web_routers/git.py:167` — `/api/git/review/create-pr` endpoint
- `hermes_cli/plugins.py:263-287` — `VALID_HOOKS` documentation for kanban lifecycle hooks
- `plugins/replenishment/__init__.py:866-867` — reference plugin registering `kanban_task_completed`
- `gateway/kanban_watchers.py:228-266` — terminal event kinds (`completed`, `review_requested`, `changes_requested`)
- `.github/workflows/ci.yml` — Janus CI triggers on `push` to `master`/`main`/`wt/*` and on `pull_request` to `master`/`main`
