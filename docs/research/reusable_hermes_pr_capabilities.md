# Reusable Hermes Capabilities for Kanban → PR Automation

**Source:** `docs/research/kanban_pr_automation_findings.md` (commit `0661322`)
**Date:** 2026-09-02
**Scope:** Hermes Agent kanban subsystem (`~/.hermes/hermes-agent/`), Janus project repo, PR creation trigger points.

---

## 1. Existing Hermes Features Reusable for PR Creation & Integration

### 1.1 Plugin Hook System (Task Lifecycle Events)

| Capability | Location | Notes |
|---|---|---|
| `kanban_task_completed` hook — fires AFTER task state is committed to SQLite; observer-only (cannot break board transitions) | `hermes_cli/kanban_db.py:188` — `_fire_kanban_lifecycle_hook()` | Primary integration point for PR automation. Already consumed by `replenishment` plugin. |
| `kanban_task_claimed` hook — fires in dispatcher process before worker spawns | `hermes_cli/plugins.py:285-287` — `VALID_HOOKS` | Could be used to pre-create branches or validate repo state. |
| `kanban_task_blocked` hook — fires in worker process | `hermes_cli/plugins.py:287` | Observer-only. |
| Hook invocation (first-party + plugin) | `hermes_cli/lifecycle.py:11` — `invoke_hook()` | Central dispatch; calls `plugins.invoke_hook()`. |
| Reference plugin implementation | `plugins/replenishment/__init__.py:866-867` — `register()` | Registers `kanban_task_completed` — template for new PR plugin. |

### 1.2 Branch Naming & Persistence

| Capability | Location | Notes |
|---|---|---|
| Deterministic branch naming for project-linked tasks | `hermes_cli/projects_db.py:1013` — `branch_name_for()` | Format: `<project-slug>/<task-id>[-<title-slug>]` (e.g., `janus/t_c3259458-survey-pr-hooks`). |
| Fallback branch naming (non-project tasks) | `hermes_cli/kanban_db.py:10613` | Format: `wt/<task-id>`. |
| Branch name persisted per-task | `hermes_cli/kanban_db.py:1356` — `tasks.branch_name` column | Read by PR plugin to know which branch to create PR from. |
| Branch name set at dispatch time | `hermes_cli/kanban_db.py:10611-10613` — `set_branch_name()` | Called during claim/dispatch. |

### 1.3 PR Creation & GitHub Interaction

| Capability | Location | Notes |
|---|---|---|
| `gh pr create --fill` wrapper — pushes branch, creates PR, returns URL | `hermes_cli/web_git.py:556` — `review_create_pr(cwd)` | Core function for PR creation. Takes a `cwd` (workspace path). |
| Push branch to upstream | `hermes_cli/web_git.py:385` — `_review_push(cwd)` | Handles both tracked (`git push`) and untracked (`git push -u origin <branch>`) cases. |
| Check PR existence on a branch | `hermes_cli/web_git.py:505` — `review_pr_list(cwd, branches, numbers)` | Uses GraphQL to query PRs by branch name — prevents double-creation. |
| Check gh auth status + current branch PR | `hermes_cli/web_git.py:447` — `review_ship_info(cwd)` | Returns `{ghReady, pr}` — useful guard before PR creation. |
| `gh` CLI wrapper (non-interactive) | `hermes_cli/web_git.py:429` — `_gh(cwd, args)` | All `gh` calls go through this; sets `GH_PROMPT_DISABLED=1`. |
| REST endpoint for PR creation | `hermes_cli/web_routers/git.py:167` — `/api/git/review/create-pr` | HTTP interface wrapping `review_create_pr`. |
| REST endpoint for push | `hermes_cli/web_routers/git.py:162` — `/api/git/review/push` | HTTP interface wrapping `review_push`. |
| REST endpoint for ship info | `hermes_cli/web_routers/git.py:132` — `/api/git/review/ship-info` | HTTP interface wrapping `review_ship_info`. |
| GitHub PR comment (inbound webhook flow) | `gateway/platforms/webhook.py:1384-1427` | `gh pr comment <pr_int> --repo <repo> --body <content>` — used by `github-pr-review` webhook handler. |

### 1.4 Worktree Lifecycle

| Capability | Location | Notes |
|---|---|---|
| Worktree creation | `hermes_cli/web_git.py:697` — `worktree_add(cwd, options)` | Creates worktree with branch; supports existing branches, new branches, base refs. |
| Worktree removal | `hermes_cli/web_git.py:756` — `worktree_remove(cwd, worktree_path, force)` | Force-capable removal. |
| Worktree listing | `hermes_cli/web_routers/git.py:90-92` — `/api/git/worktrees` | REST endpoint. |
| Per-task worktree creation | `hermes_cli/kanban_db.py:10611-10613` | Dispatcher creates worktree under `<repo>/.worktrees/<task-id>`. |

### 1.5 Kanban Task State & Metadata

| Capability | Location | Notes |
|---|---|---|
| Task completion (state transition + lifecycle hook firing) | `hermes_cli/kanban_db.py:5534` — `complete_task()` | Fires `kanban_task_completed` hook after write txn commits. |
| Review lifecycle (`request_review`, `request_changes`) | `hermes_cli/kanban_db.py:6733` — `request_review()` | Existing human/LLM review flow inside Hermes (orthogonal to GitHub PR). |
| Task metadata persistence (`summary`, `metadata`, `result`) | `hermes_cli/kanban_db.py:5534-5576` | `metadata` is a free-form dict for structured handoff facts (e.g., `changed_files`, `tests_run`). |
| Artifact upload on completion | `gateway/kanban_watchers.py:1190` | Uploads files referenced in `kanban_complete(artifacts=[...])`. |
| Terminal event delivery (completed, blocked, review_requested, etc.) | `gateway/kanban_watchers.py:224-247` — `_kanban_notifier_watcher()` | Delivers events to subscribed users/platforms. |

### 1.6 CI / GitHub Actions

| Capability | Location | Notes |
|---|---|---|
| Janus CI triggers on push to `wt/*` and on `pull_request` to `master`/`main` | `.github/workflows/ci.yml:3-7` | CI already runs on worktree branches — no CI changes needed for PR automation. |

---

## 2. Gaps That Must Be Filled

| Gap | Detail | Impact |
|---|---|---|
| **No PR creation plugin** | No plugin currently consumes `kanban_task_completed` for PR creation. The hook exists but has no PR-oriented subscriber. | Must build a new plugin (pattern: `plugins/replenishment/`). |
| **No task ↔ PR state machine** | No `pr_created` status, no PR URL persistence on the task, no guard against double-creation. | Risk of duplicate PRs; no way to track which tasks have PRs. |
| **No branch → PR linking** | `tasks.branch_name` is persisted but nothing reads it back to create a PR. | The branch exists but no PR is opened from it. |
| **No labeling bridge** | Task metadata (assignee, project, title/body) could map to PR labels, but no such mapping exists. | PRs would lack labels; no automation routing. |
| **Review lane ≠ PR lane** | `kanban_request_review` is an internal Hermes review cycle; it does not produce a GitHub PR. | Two separate flows must coexist without confusion. |
| **Inbound webhooks only for GitHub events** | `github-pr-review` webhook reacts to PRs (inbound); no outbound PR creation from task events. | No existing outbound automation to model after. |
| **No auto-merge configuration** | Repo setting is null; no branch protection (private repo). | Auto-merge must be enabled in GitHub repo settings or via `gh pr merge --auto`. |

---

## 3. Constraints on Scope

1. **Plugin must be observer-only** — `kanban_task_completed` hooks are best-effort; a broken PR plugin cannot break task completion. Failures must be swallowed/logged, not propagated.

2. **Worker-process context** — `kanban_task_completed` fires in the worker subprocess (separate `hermes -p <profile> chat -q` process). The plugin must run in that context or communicate outward.

3. **No SQLite write lock held** — Hook fires AFTER the write txn commits, so plugin code observes durable state but must not block the board.

4. **Idempotency required** — Hook may fire multiple times (retries, re-completions). PR creation must be idempotent: check `gh pr list --head <branch>` before creating.

5. **`gh` CLI dependency** — All PR operations require `gh` installed and authenticated. Must guard with `gh auth status` first.

6. **Workspace path needed** — `review_create_pr(cwd)` needs the task's workspace path. Must resolve from `tasks.workspace_path` or worktree registry.

7. **CI already covers `wt/*` branches** — No CI changes needed; existing `.github/workflows/ci.yml` triggers on push to `wt/*` and on `pull_request`.

8. **Private repo, no branch protection** — Simpler path (no required reviews, no status checks) but also no guardrails. Auto-merge is safe to enable but must be explicit.

---

## 4. Recommended Integration Path (Summary)

The path of least resistance is a `kanban_task_completed` plugin (modeled on `plugins/replenishment/`) that:
1. Reads the task's `branch_name` and `workspace_path` from `tasks` table.
2. Checks `gh auth status` in the workspace.
3. Queries `review_pr_list(cwd, branches=[branch_name])` to detect existing PR.
4. If no PR exists, calls `review_create_pr(cwd)` to push and create.
5. Persists the PR URL back to the task (new column or `metadata`).

All building blocks exist; the gap is the plugin wiring them together.
