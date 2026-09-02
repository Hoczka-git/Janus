# Minimal Configuration/Skill Change Recommendation — JANUS Coding Tasks

**Task**: t_1f3f8844 — Synthesize findings from four investigation threads
**Date**: 2026-09-02
**Scope**: Smallest changes to achieve (1) auto-create PRs, (2) keep branches in sync with master, (3) wait for CI, (4) auto-merge safely.
**Method**: Synthesis of four evidence reports. No implementation.

---

## Executive Summary

All building blocks already exist. The minimal change set is **three items**:

| # | Change | Type | Effort |
|---|--------|------|--------|
| 1 | Enable auto-merge in GitHub repo settings | Repo config (UI) | ~30 seconds |
| 2 | Add `_sync_worktree_with_default_branch()` at claim time | Code (1 function, 2 call sites) | ~30 lines |
| 3 | Create `kanban_task_completed` plugin for PR lifecycle | Code (new plugin, pattern: replenishment) | ~100-150 lines |

No schema changes. No new dependencies. No branch protection required (private repo, no GitHub Pro).

---

## Goal 1: Automatically Create PRs

### What Exists Today
- `review_create_pr()` in `hermes_cli/web_git.py:556` — runs `gh pr create --fill`, returns PR URL
- `/api/git/review/create-pr` REST endpoint (`web_routers/git.py:167`)
- Deterministic branch naming: `<project-slug>/<task-id>[-<title-slug>]` or `wt/<task-id>` fallback
- `tasks.branch_name` column persisted per-task at dispatch time
- `kanban_task_completed` plugin hook fires after task completion with `{task_id, board, assignee, run_id, summary, profile_name}`
- Reference plugin pattern: `plugins/replenishment/__init__.py:866-867`

### What Is Missing
No automation connects task completion to PR creation. The hook fires but no plugin consumes it for PRs.

### Minimal Change
**Create a `kanban_task_completed` plugin** (pattern: replenishment) that:
1. Reads `tasks.branch_name` for the completed task
2. Checks for existing open PR on that branch: `gh pr list --head <branch> --state open`
3. If no PR exists, creates one via `review_create_pr()` or `gh pr create --fill`
4. Persists PR URL as a task comment (zero schema change)
5. Idempotency guard: skip if PR URL comment already exists (pattern: replenishment's `[replenish]` marker)

**Files to touch**: New file `plugins/pr_automation/__init__.py` + registration.

---

## Goal 2: Keep Branches Up to Date with Master

### What Exists Today
- Per-task worktree creation via `_resolve_worktree_workspace()` (`kanban_db.py:8083-8169`)
- `_default_branch_name()` helper in `web_git.py:146-160`
- `_branch_base()` helper in `web_git.py:132-143`
- Safety invariants in cleanup (never deletes tracked mods, never deletes unique unpushed commits)

### What Is Missing
Branches are created from `HEAD` at claim time. If `master` advances during a task, the worktree diverges silently. No automatic sync exists. Only one manual merge-from-master found in history (`d049037`).

### Minimal Change
**Option B (recommended): Pre-claim sync function.**

Add `_sync_worktree_with_default_branch(workspace_path, repo_root)` to `web_git.py` (near `_default_branch_name`). Call it in the dispatch loop at `kanban_db.py:10611` and `kanban_db.py:10740` (after `set_workspace_path`).

Logic:
- Fetch `origin/<default_branch>`
- Rebase worktree branch onto `origin/<default_branch>`
- Only if working tree is clean (no uncommitted changes) — dirty trees are left alone
- If rebase fails (conflicts), leave tree alone (safe degradation)

**Alternative (zero code):** Add worker prompt guidance to periodically run `git fetch origin && git rebase origin/master`. Relies on agent compliance, not mechanical.

**Why not Option C (periodic sync hook)?** Adds complexity (conflict handling, tick-frequency tuning) that is unnecessary given typical task durations. Option B handles the common case (sync at claim time) with minimal code.

---

## Goal 3: Wait for CI

### What Exists Today
- CI configured in `.github/workflows/ci.yml` — triggers on `pull_request` to `master`/`main`
- Single `verify` job: `uv run pytest tests/ -v` with 10-minute timeout
- `gh pr checks --watch` (polls every 10s) documented in `github-pr-workflow` skill
- REST API polling: `GET /repos/{owner}/{repo}/commits/{sha}/status`

### What Is Missing
No automated "wait for CI then proceed" flow. The skill documents the commands but nothing executes them automatically.

### Minimal Change
**The same `kanban_task_completed` plugin** (from Goal 1) handles this:
- After PR creation, wait for CI via `gh pr checks --watch` (subprocess with timeout)
- Or implement polling loop: `GET /commits/{sha}/status` every 30s, break on `success`/`failure`/`error`
- On success: proceed to auto-merge
- On failure: optionally auto-fix (read logs → fix code → push → re-check, up to 3 attempts per skill)

**No separate change needed** — this is folded into the plugin.

---

## Goal 4: Auto-Merge Safely

### What Exists Today
- `gh pr merge --auto --squash --delete-branch` supported by `gh` CLI
- GraphQL `enablePullRequestAutoMerge` available
- CI runs on PR (pytest suite)
- All recent merges use merge commit strategy

### What Is Missing
- Auto-merge repo setting is `null` (likely disabled) — must be explicitly enabled
- No branch protection rules (private repo, no GitHub Pro) — cannot enforce CI-as-gate at GitHub level
- No automated merge flow

### Minimal Change
**Two parts:**

1. **Repository setting (zero code):** Enable "Allow auto-merge" in GitHub repository settings (Settings → General → Pull Requests → Allow auto-merge). This is a one-time UI action.

2. **Plugin command:** Use `gh pr merge --auto --squash --delete-branch` in the plugin after CI passes.
   - `--squash` for clean per-task commits (recommended for JANUS tasks — small, focused changes)
   - `--delete-branch` to clean up `wt/*` branches
   - `--auto` to wait for all status checks to pass before merging

**Safety conditions the plugin should verify before auto-merge:**
- All CI checks pass (`gh pr checks` returns success)
- PR is not a draft (`gh pr view --json isDraft` → false)
- No merge conflicts (`gh pr view --json mergeable` == `MERGEABLE`)
- Branch up-to-date with base (handled by pre-claim sync from Goal 2)

**Why squash over merge commit for task PRs:**
| Merge Commit | Squash |
|--------------|--------|
| Preserves full commit history | One clean commit per task |
| Adds merge commits to history | Linear history |
| Good for large features | Better for small, focused changes |
| Current convention | Recommended for task PRs |

---

## Ordering Dependencies

```
[1] Enable auto-merge in GitHub repo settings (prerequisite for --auto flag)
         │
         ▼
[2] Add _sync_worktree_with_default_branch() at claim time
         │
         ▼
[3] Create kanban_task_completed plugin (PR create → CI wait → auto-merge)
```

- Step 1 must precede Step 3 because `gh pr merge --auto` requires the repo setting.
- Step 2 should precede Step 3 so branches are synced before PR creation (reduces merge conflicts).
- Steps 1 and 2 are independent of each other.
- Step 3 depends on both 1 and 2.

---

## Consolidated Change List (Smallest Path)

| Priority | Change | Files | Lines | Type |
|----------|--------|-------|-------|------|
| 1 | Enable auto-merge in repo settings | GitHub UI | 0 | Config |
| 2 | Add `_sync_worktree_with_default_branch()` | `web_git.py`, `kanban_db.py` (2 call sites) | ~30 | Code |
| 3 | Create PR automation plugin | `plugins/pr_automation/__init__.py` (new) | ~100-150 | Code |

**Total new code: ~130-180 lines across 3 files (1 new, 2 existing).**

---

## Remaining Uncertainty

1. **Auto-merge repo setting**: API returned `null` — requires owner verification in GitHub UI.
2. **Conflict frequency**: No data on how often `master` advances during a task. If rare, the pre-claim sync may be sufficient and periodic sync unnecessary.
3. **PR URL persistence**: Comments are zero-schema-change but less queryable than a dedicated `pr_url` column. Recommend starting with comments; migrate if queryability becomes important.
4. **CI wait timeout**: Skill suggests 10 minutes (20 iterations × 30s). Should be configurable per task or board.
5. **Auto-fix loop**: The skill documents an auto-fix loop (read logs → fix → push → re-check). Whether to enable this in automation or just fail-and-notify is a policy decision.
6. **Fork handling**: Current worktree setup uses the same repo, so fork syntax (`--head <fork>:<branch>`) may not apply. Verify if tasks ever run from forks.

---

## References

- `docs/research/git_worktree_branch_sync_findings.md` — t_49b0c43b
- `docs/research/merge_rebase_automerge_findings.md` — t_9c04786a
- `docs/research/github_pr_workflow_findings.md` — t_d4829259
- `docs/research/kanban_pr_automation_findings.md` — t_c3259458
- `.github/workflows/ci.yml` — Janus CI configuration
- `github/github-pr-workflow/SKILL.md` — PR lifecycle skill
