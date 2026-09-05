# Git-Worktree Usage Analysis — Evidence Report

**Task**: t_49b0c43b — Analyze git-worktree usage for branch isolation
**Date**: 2026-09-02
**Scope**: How worktrees are created per task, branch management inside worktrees, and branch synchronization with master/main in the Hermes/JANUS workflow.

---

## 1. Current State

### 1.1 Worktree Creation (Per-Task)

Every JANUS coding task with `workspace_kind=worktree` gets its own linked git worktree.

**Location**: `hermes_cli/kanban_db.py`

| Function | Lines | Purpose |
|----------|-------|---------|
| `_resolve_worktree_workspace()` | 8083-8169 | Resolves anchor + materializes worktree |
| `_ensure_git_worktree()` | 8053-8080 | Runs `git worktree add` |
| `resolve_workspace()` | 8172-8234 | Top-level dispatcher (handles scratch/dir/worktree) |

**Materialization logic** (`_ensure_git_worktree`):
```python
if _git_branch_exists(repo_root, branch_name):
    cmd = ["git", "-C", str(repo_root), "worktree", "add", str(target), branch_name]
else:
    cmd = ["git", "-C", str(repo_root), "worktree", "add", "-b", branch_name, str(target), "HEAD"]
```

**Anchor resolution**: Worktrees anchor on the board's `default_workdir` (a persistent project checkout), not `Path.cwd()`. Target path: `<repo_root>/.worktrees/<task_id>`.

**Evidence**: `kanban_db.py:8096-8124`

### 1.2 Branch Naming

Two patterns exist:

| Pattern | When | Example |
|---------|------|---------|
| `wt/<task-id>` | Fallback when no project link | `wt/t_891f872c` |
| `<project-slug>/<task-id>[-<title-slug>]` | Project-linked tasks (deterministic) | `janus/t_891f872c-survey-sync` |

**Source**:
- `kanban_db.py:8096`: `branch_name = (task.branch_name or "").strip() or f"wt/{task.id}"`
- `projects_db.py:1013-1026`: `branch_name_for()` — deterministic naming from project slug

The resolved branch name is persisted to the DB via `set_branch_name()` (`kanban_db.py:8244-8251`).

### 1.3 Branch Origin

Worktree branches are created from `HEAD` of the main checkout at worktree creation time. This means:
- The branch starts from whatever commit `master` (or `main`) points to when the task is claimed.
- If `master` advances while the task is in progress, the worktree branch diverges without warning.

**Evidence**: `kanban_db.py:8066-8068` — `git worktree add -b <branch_name> <target> HEAD`

### 1.4 Branch Synchronization with Master/Main

**Status: NO automatic sync exists.**

Once a worktree branch is created, there is no mechanism to sync it with the target branch (no rebase, no merge from main).

**Evidence**:
- The only sync commit found in git history: `d049037 Merge branch 'master' into wt/t_6149be8f` — a one-time manual merge, not an automated process.
- `web_git.py` has `_branch_base()` (line 132-143) and `_default_branch_name()` (line 146-160) helpers, but they are used for status display (`repo_status()`), not for sync.
- `review_push()` exists in `web_git.py:385-392` but is not wired into the task completion flow.
- `update_cmd.py` has fork sync logic (`_sync_fork_with_upstream`, `_sync_with_upstream_if_needed`) but that is for Hermes's own update process, not for worktree branches.

**Documented gap** (from `docs/research/sync_integration_patterns_findings.md`, commit 8836c90):
> **7.6 No Sync Between Worktree Branches**
> Once a worktree branch is created, there is no mechanism to sync it with the target branch (rebase, merge from main). If the target branch advances while a task is in progress, the worktree branch diverges without warning.

### 1.5 Worktree Cleanup (Post-Completion)

`_cleanup_worktree_workspace()` in `kanban_db.py:6142-6203`:

**Safety invariants** (never violated):
- Tracked modifications NEVER deleted (any age, any mode)
- Unique unpushed commits NEVER deleted (uses `git cherry` patch-equivalence)
- Live-locked trees (owning PID alive) never touched
- Branch deleted only after worktree removal succeeds
- Untracked-only dirt ARCHIVED to `~/.hermes/archive/worktree-prune/` before reaping

`worktree_gc.py` (432 lines): Attended counterpart for reclaiming preserved trees and orphaned branches (invoked via `hermes worktree prune`).

---

## 2. Key Files Reference

| File | Purpose |
|------|---------|
| `hermes_cli/kanban_db.py` | Core Kanban DB: task lifecycle, worktree resolution, cleanup |
| `hermes_cli/web_git.py` | Git operations: worktree, branch, status, commit, push, PR |
| `hermes_cli/worktree_gc.py` | Attended worktree + branch reclaim (dry-run-first) |
| `hermes_cli/projects_db.py` | Project registry: deterministic branch naming |
| `hermes_cli/kanban_swarm.py` | Swarm topology: planning root + workers + verifier + synthesizer |

---

## 3. Analysis: The Divergence Problem

### Scenario
1. Task A is claimed at time T0. Worktree branch `wt/t_A` created from `master@T0`.
2. Task B completes at time T1, merging into `master`. `master` advances.
3. Task A continues working on `wt/t_A`, which is now based on `master@T0`, not `master@T1`.
4. When Task A completes and attempts to merge, it may have conflicts or unexpected behavior due to the divergence.

### Current Mitigation
- The review workflow (Model A native review lane) catches some issues before merge.
- The Janus verification pipeline (`src/janus/verification.py`) can detect file-level conflicts.
- But neither automatically syncs the branch with master.

---

## 4. Recommended Minimal Change

### Option A: Worker Prompt Guidance (Smallest Change — Zero Code)

Add guidance to the worker's system prompt (via KANBAN_GUIDANCE or a skill) to run periodic sync:

```
# In worker system prompt or janus-task-add-nl skill
If your task runs longer than 30 minutes, periodically sync with master:
  git fetch origin && git rebase origin/master
Only do this if your working tree is clean (no uncommitted changes).
```

**Pros**: Zero code changes, uses existing git capabilities.
**Cons**: Relies on agent compliance, not mechanical, may be forgotten.

### Option B: Pre-Claim Sync (Minimal Code — Single Function)

Add a sync step in the claim path, right after `resolve_workspace()`:

```python
# In dispatch loop, after resolve_workspace() for worktree tasks
def _sync_worktree_with_default_branch(workspace_path: str, repo_root: Path) -> None:
    """Fetch + rebase worktree branch onto origin/default_branch if clean."""
    default_branch = _default_branch_name(workspace_path)
    if not default_branch:
        return
    # Only sync if working tree is clean
    status_code, status_out, _ = _git(workspace_path, ["status", "--porcelain"])
    if status_code != 0 or status_out.strip():
        return  # dirty — don't touch
    _git(workspace_path, ["fetch", "origin", default_branch])
    _git(workspace_path, ["rebase", f"origin/{default_branch}"])
```

Call this in the dispatch loop at `kanban_db.py:10611` and `kanban_db.py:10740` (after `set_workspace_path`).

**Pros**: Mechanical, automatic, safe (only rebases clean trees), minimal code.
**Cons**: Only syncs at claim time; long-running tasks may still diverge.

### Option C: Periodic Sync Hook (Most Robust)

Add a `sync_worktree_branches()` function called on each dispatcher tick that:
1. Queries all running worktree tasks
2. For each, runs `git fetch origin` + `git rebase origin/<default_branch>` in the worktree
3. Only if the worktree is clean (no uncommitted changes)

Hook into the dispatch loop alongside `_fire_worker_spawned_hook`.

**Pros**: Handles long-running tasks, mechanical, automatic.
**Cons**: More code, needs conflict handling (if rebase fails, leave tree alone).

---

## 5. Recommendation

**For the smallest change that actually works**: **Option B (Pre-Claim Sync)**.

It is:
- Mechanically verifiable (not relying on agent compliance)
- Minimal code (one function, two call sites)
- Safe (only rebases clean trees)
- Backward-compatible (no behavior change for existing tasks)

**For long-running tasks**: Combine with Option A (worker prompt guidance) as a belt-and-suspenders approach.

**Not recommended**: Option C adds complexity (conflict handling, tick-frequency tuning) that may not be needed given typical task durations.

---

## 6. Remaining Uncertainty

1. **Conflict frequency**: We don't have data on how often `master` advances during a typical task. If conflicts are rare, Option A may suffice.
2. **Rebase vs merge**: Rebase keeps linear history but rewrites commits. Merge preserves commits but adds merge commits. The project's CI runs on `wt/*` branches, so either works.
3. **Default branch detection**: `_default_branch_name()` in `web_git.py:146-160` handles `main`/`master` detection. This logic should be reused by any sync implementation.
4. **Remote availability**: Sync requires network access to `origin`. Offline tasks would skip sync silently (acceptable degradation).

---

## 7. Next Step

If Option B is approved, the implementation task should:
1. Add `_sync_worktree_with_default_branch()` to `web_git.py` (near `_branch_base` and `_default_branch_name`)
2. Call it in the dispatch loop at `kanban_db.py:10611` and `kanban_db.py:10740`
3. Add a test verifying: clean worktree → rebases onto origin/default_branch; dirty worktree → no-op
