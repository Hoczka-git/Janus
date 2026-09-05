# GitHub PR Workflow — Findings & Recommendations

**Task**: t_d4829259 — Review existing github-pr-workflow for PR creation and CI gating
**Date**: 2026-09-02
**Scope**: `github-pr-workflow` skill, Hermes Kanban plugin hooks, Janus CI configuration, existing PR automation surfaces.
**Method**: Skill inspection, code search, read-only repository analysis. No implementation.

---

## 1. Current State: The `github-pr-workflow` Skill

The skill at `github/github-pr-workflow/SKILL.md` (v1.1.0) documents the complete PR lifecycle. It is **LLM guidance** — it teaches the agent which `gh` / `git`+`curl` commands to run. It is NOT automated event-driven logic.

### 1.1 PR Creation

| Method | Command | Notes |
|--------|---------|-------|
| `gh` (primary) | `gh pr create --title "..." --body "..."` | Supports `--draft`, `--reviewer`, `--label`, `--base` |
| `gh` (fill) | `gh pr create --fill` | Auto-fills title/body from commits |
| `git`+`curl` (fallback) | `POST /repos/{owner}/{repo}/pulls` | Used when `gh` is unavailable |

The skill also documents `review_create_pr()` in `hermes_cli/web_git.py:556` which wraps `gh pr create --fill` and is exposed via the `/api/git/review/create-pr` REST endpoint.

### 1.2 CI Monitoring

| Method | Command | Notes |
|--------|---------|-------|
| `gh` one-shot | `gh pr checks` | Lists check status |
| `gh` watch | `gh pr checks --watch` | Polls every 10s until done |
| `curl` polling | `GET /repos/{owner}/{repo}/commits/{sha}/status` | Manual loop, 30s interval, 10min cap |
| `curl` check-runs | `GET /repos/{owner}/{repo/commits/{sha}/check-runs` | GitHub Actions specific |

The skill documents a full auto-fix loop: check status → read logs → fix code → push → re-check (up to 3 attempts).

### 1.3 Merge Strategies

| Strategy | `gh` command | `curl` equivalent |
|----------|--------------|-------------------|
| Merge commit | `gh pr merge --merge --delete-branch` | `PUT /pulls/{n}/merge` with `"merge_method": "merge"` |
| Squash (default) | `gh pr merge --squash --delete-branch` | `"merge_method": "squash"` |
| Rebase | `gh pr merge --rebase --delete-branch` | `"merge_method": "rebase"` |

### 1.4 Auto-Merge

Supported via:
- `gh pr merge --auto --squash --delete-branch` (merges when all checks pass)
- GraphQL mutation `enablePullRequestAutoMerge` (REST doesn't support auto-merge)

**Caveat**: Auto-merge requires the repo to have it enabled in settings.

### 1.5 Skill References & Templates

- `references/conventional-commits.md` — commit message format
- `references/ci-troubleshooting.md` — failure pattern diagnosis
- `templates/pr-body-feature.md` — feature PR template
- `templates/pr-body-bugfix.md` — bugfix PR template

---

## 2. Existing PR Automation Surfaces in Hermes

### 2.1 What Exists

| Surface | Location | Connected to Kanban? |
|---------|----------|---------------------|
| `review_create_pr()` | `hermes_cli/web_git.py:556` | **No.** Manual/desktop only |
| `/api/git/review/create-pr` | `hermes_cli/web_routers/git.py:167` | **No.** Client-driven |
| `gh pr create` (skill) | `github-pr-workflow` skill | **No.** LLM-initiated |
| `github-pr-review` webhook | Inbound event handler | **No.** Inbound (GitHub → Hermes) |

### 2.2 What Does NOT Exist

- **No PR creation hook** — `kanban_task_completed` fires but no plugin creates PRs
- **No task→PR state machine** — no `pr_created` status, no PR URL persistence
- **No branch→PR linking** — `tasks.branch_name` is persisted but not read back for PR creation
- **No labeling bridge** — task metadata could map to PR labels but doesn't
- **No CI wait logic** — no automated "wait for CI then merge" flow

---

## 3. Integration Points for Task → PR Automation

### 3.1 `kanban_task_completed` Plugin Hook

**Location**: `hermes_cli/kanban_db.py:5770-5771`

Fires in the worker process AFTER the task completion is committed to the board DB. Payload:
```python
{
    "task_id": str,
    "board": str | None,
    "assignee": str | None,
    "run_id": int | None,
    "summary": str | None,
    "profile_name": str,
}
```

**Reference implementation**: `plugins/replenishment/__init__.py:866-867` — registers `kanban_task_completed` and consumes it for roadmap replenishment. A PR automation plugin would follow the same pattern.

### 3.2 Branch Naming (Deterministic)

| Pattern | When | Example |
|---------|------|---------|
| `<project-slug>/<task-id>[-<title-slug>]` | Project-linked tasks | `janus/t_c3259458-survey-pr-hooks` |
| `wt/<task-id>` | Fallback (no project) | `wt/t_c3259458` |

**Source**: `hermes_cli/projects_db.py:1013-1026` (`branch_name_for()`)

The branch name is persisted to `tasks.branch_name` at dispatch time.

### 3.3 REST API for PR Creation

`POST /api/git/review/create-pr` — already exposes PR creation over HTTP. Could be called from a plugin or external automation.

### 3.4 Worktree Lifecycle

The dispatcher creates a worktree per task under `<repo>/.worktrees/<task-id>`. The worker pushes commits there. PR creation would happen after the worker finishes (on `kanban_task_completed`).

---

## 4. Janus CI Configuration

**File**: `.github/workflows/ci.yml`

```yaml
on:
  push:
    branches: ["master", "main", "wt/*"]
  pull_request:
    branches: ["master", "main"]

jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --dev
      - run: uv sync && uv run python -c "import yaml; ..."
      - run: uv run pytest tests/ -v
```

**Key observations**:
- CI triggers on push to `master`/`main`/`wt/*` AND on `pull_request` to `master`/`main`
- Single job `verify` with 10-minute timeout
- Runs full test suite: `uv run pytest tests/ -v`
- Also verifies production dependencies (no dev)

---

## 5. Gap Analysis: Current vs. Desired

| Desired Capability | Current State | Gap |
|-------------------|---------------|-----|
| Auto-create PR on task completion | No automation exists | Need `kanban_task_completed` plugin |
| Wait for CI checks to pass | Skill documents `gh pr checks --watch` | Need automated polling logic |
| Safe auto-merge when green | Skill documents `gh pr merge --auto` | Need guard conditions |
| PR URL persistence on task | No PR URL field in tasks DB | Need schema change or comment-based linking |
| Prevent double PR creation | No guard | Need idempotency check (`gh pr list --head <branch>`) |
| Label sync (task → PR) | No mapping exists | Need label convention |

---

## 6. Recommended Minimal Configuration Changes

### 6.1 For JANUS Tasks: Automatic PR Creation

**Path of least resistance**: A `kanban_task_completed` plugin (like replenishment) that:
1. Reads the task's `branch_name` from `tasks.branch_name`
2. Checks if a PR already exists: `gh pr list --head <branch> --state open`
3. If no PR exists, creates one: `gh pr create --fill` (or via REST API)
4. Persists the PR URL as a task comment (no schema change needed)

**Reference**: `plugins/replenishment/__init__.py` for the hook registration pattern.

### 6.2 CI Wait Logic

The skill already documents `gh pr checks --watch` (polls every 10s). For automation:
- Use `gh pr checks --watch` in a subprocess with timeout
- Or implement polling loop: `GET /commits/{sha}/status` every 30s, break on `success`/`failure`/`error`

### 6.3 Safe Auto-Merge Conditions

Recommended safeguards before auto-merge:
1. All CI checks pass (`gh pr checks` returns success)
2. PR is not a draft (`gh pr view --json isDraft` → false)
3. Branch is up-to-date with base (`gh pr view --json mergeState` or `mergeable` field)
4. No merge conflicts (`gh pr view --json mergeable` == `MERGEABLE`)

Then: `gh pr merge --auto --squash --delete-branch`

### 6.4 Merge Strategy Recommendation

For JANUS tasks (small, focused changes): **squash merge** is cleanest — one commit per task, clean history.

For larger features with meaningful commit history: **merge commit** preserves context.

**Recommendation**: Default to squash, with a task metadata flag (`pr_merge_strategy`) for exceptions.

---

## 7. Remaining Uncertainty

1. **Auto-merge repo setting**: Unknown whether the Janus repo has auto-merge enabled in GitHub settings. The GraphQL `enablePullRequestAutoMerge` mutation requires this.
2. **PR URL persistence**: Whether to add a `pr_url` column to tasks or use comments. Comments are zero-schema-change but less queryable.
3. **Idempotency**: The `kanban_task_completed` hook can fire more than once for the same task (e.g., `complete_task` + direct `on_task_completed` call). The replenishment plugin uses a `[replenish]` comment marker as an idempotency guard — a PR plugin should do the same.
4. **CI wait timeout**: How long to wait for CI before giving up. The skill suggests 10 minutes (20 iterations × 30s), but this is configurable.
5. **Fork handling**: If tasks run from forks, `gh pr create` needs `--head <fork>:<branch>` syntax. Current worktree setup uses the same repo, so this may not apply.

---

## 8. Summary

| Aspect | Finding |
|--------|---------|
| PR creation capability | ✅ Exists (`gh pr create`, `review_create_pr()`, REST API) |
| CI monitoring | ✅ Exists (`gh pr checks --watch`, polling loop) |
| Merge strategies | ✅ All three (merge, squash, rebase) |
| Auto-merge | ✅ Supported (`gh pr merge --auto`, GraphQL) |
| Task → PR automation | ❌ Does not exist |
| CI wait logic | ❌ Not automated (skill only) |
| PR URL persistence | ❌ Not implemented |
| Label sync | ❌ Not implemented |

**Bottom line**: The building blocks exist. What's missing is a `kanban_task_completed` plugin that wires them together — reading the task's branch, creating a PR, waiting for CI, and optionally auto-merging. The replenishment plugin is the template.

---

## References

- `github/github-pr-workflow/SKILL.md` — full PR lifecycle skill
- `hermes_cli/web_git.py:556` — `review_create_pr()` function
- `hermes_cli/web_routers/git.py:167` — `/api/git/review/create-pr` endpoint
- `hermes_cli/kanban_db.py:188` — `_fire_kanban_lifecycle_hook()`
- `hermes_cli/kanban_db.py:5770` — `kanban_task_completed` firing site
- `hermes_cli/plugins.py:263-287` — `VALID_HOOKS` documentation
- `plugins/replenishment/__init__.py:866-867` — reference plugin pattern
- `hermes_cli/projects_db.py:1013` — `branch_name_for()` deterministic naming
- `.github/workflows/ci.yml` — Janus CI configuration
- `docs/research/kanban_pr_automation_findings.md` — prior survey (commit 0661322)
- `docs/research/git_worktree_branch_sync_findings.md` — worktree analysis (commit e48d929)
