# Sync and Integration Patterns — Evidence Report

**Task**: t_891f872c — Survey existing sync and integration patterns in Hermes
**Date**: 2026-09-02
**Scope**: How coding tasks are completed, branches created/pushed, target branch, sync/merge/integration steps.

---

## 1. System Architecture (Two Layers)

| Layer | Responsibility | Location |
|-------|---------------|----------|
| **Hermes** | Agent orchestration, Kanban, scheduling, workspaces, review workflow | `~/.hermes/hermes-agent/` |
| **Janus** | Domain logic, models, persistence, integrations, CLI | `~/workspaces/janus/` |

**ADR-001** (`docs/decisions/001-hermes-janus-system-model.md`): Accepted. Hermes owns agent interaction; Janus owns domain models, business logic, persistence.

---

## 2. How Coding Tasks Are Completed

### 2.1 Task Lifecycle (Hermes Kanban)

Tasks live in SQLite DB (`~/.hermes/kanban.db`). Key states: `todo` → `ready` → `running` → `review` → `done` (or `blocked`, `archived`, `cancelled`).

**Completion flow**:
1. Worker (researcher/implementer profile) claims task via dispatcher
2. Worker executes work in workspace (worktree or scratch dir)
3. Worker calls `kanban_complete()` → triggers post-commit side effects:
   - Workspace cleanup (worktree removal if clean/merged)
   - Failure-counter clear
   - `recompute_ready()` to promote dependent tasks
   - Lifecycle hook fires `kanban_task_completed` event

**Source**: `hermes_cli/kanban_db.py:6142-6203` (`_cleanup_worktree_workspace`), `kanban_swarm.py:77-126`

### 2.2 Review Workflow (Model A — Native Review Lane)

**ADR-003** (`docs/decisions/003-canonical-review-topology.md`): Accepted. Review is a phase of the *same* task, not a separate child.

- Implementer calls `kanban_request_review()` → task enters `review` status
- Reviewer worker spawned (with `sdlc-review` skill force-loaded)
- Reviewer verdicts: `kanban_complete` (approve) or `kanban_request_changes` (rework)
- Event provenance: `{implementer, reviewer}` stored in `changes_requested` event payload
- Re-review routes back to same reviewer automatically

**Source**: `kanban_db.py:6501` (`request_review`), `kanban_db.py:6663` (`request_changes`)

---

## 3. Branch Creation and Naming

### 3.1 Worktree Branch Naming

Two patterns exist:

| Pattern | When | Example |
|---------|------|---------|
| `wt/<task-id>` | Fallback when no project link | `wt/t_891f872c` |
| `<project-slug>/<task-id>[-<title-slug>]` | Project-linked tasks (deterministic) | `janus/t_891f872c-survey-sync` |

**Source**: `kanban_db.py:8096` (`branch_name = (task.branch_name or "").strip() or f"wt/{task.id}"`), `projects_db.py:1013-1026` (`branch_name_for()`)

### 3.2 Worktree Materialization

`_ensure_git_worktree()` in `kanban_db.py:8053-8080`:
- If branch exists: `git worktree add <target> <branch_name>`
- If branch new: `git worktree add -b <branch_name> <target> HEAD`

Worktree target path: `<repo_root>/.worktrees/<task_id>`

### 3.3 Anchor Resolution

Worktrees anchor on the board's `default_workdir` (a persistent project checkout), not `Path.cwd()`. This prevents scattering worktrees under the gateway's launch directory.

**Source**: `kanban_db.py:8083-8124` (`_resolve_worktree_workspace`)

---

## 4. Target Branch

### 4.1 Default Branch Detection

`_default_branch_name()` in `web_git.py:146-160`:
1. `origin/HEAD` (symbolic alias for remote default)
2. `refs/heads/main`
3. `refs/heads/master`
4. `refs/remotes/origin/main`
5. `refs/remotes/origin/master`

### 4.2 Merge Base

`_branch_base()` in `web_git.py:132-143`: Uses `merge-base HEAD <remote_default>` to find divergence point.

---

## 5. Sync/Merge/Integration Steps

### 5.1 What Exists

| Capability | Status | Evidence |
|-----------|--------|----------|
| **Git worktree creation** | ✅ Implemented | `kanban_db.py:8053-8080` |
| **Worktree cleanup on completion** | ✅ Implemented | `kanban_db.py:6142-6203` |
| **Worktree GC (attended)** | ✅ Implemented | `hermes_cli/worktree_gc.py` (432 lines) |
| **CI (GitHub Actions)** | ✅ Implemented | `.github/workflows/ci.yml` (pytest on push/PR) |
| **Verification pipeline (Janus)** | ✅ Implemented | `src/janus/verification.py` (1334 lines, 9 check types) |
| **Verification runner (Hermes)** | ✅ Implemented | `agent/verify/runner.py`, `agent/verify/recipes.py` |
| **Verify-on-stop nudge** | ✅ Implemented | `agent/verification_stop.py` (policy-only, no execution) |
| **Pre-commit hooks** | ❌ Not configured | No `.pre-commit-config.yaml` found |
| **Automatic push from worktrees** | ❌ Not implemented | No `git push` in worktree lifecycle |
| **Automatic merge/PR creation** | ❌ Not implemented | `web_git.py` has review/PR helpers but no auto-merge |
| **Structured completion handoff** | ❌ Not implemented | Agent completion claim is prose in chat message |

### 5.2 CI Configuration

`.github/workflows/ci.yml`:
- Triggers: push to `master`, `main`, `wt/*`; PR to `master`, `main`
- Steps: `uv sync --dev` → `uv run pytest tests/ -v`
- No deployment, no merge gate beyond test pass

### 5.3 Verification Pipeline (Janus)

`src/janus/verification.py` — contract-based verification with 9 check types:

| Check | Purpose |
|-------|---------|
| `check_files_create` | Required files exist |
| `check_files_immutable` | Protected files unchanged |
| `check_commands` | Verification commands exit 0 |
| `check_files_modify` | Modified files have diffs |
| `check_files_unexpected_modified` | No tracked files outside contract modified |
| `check_files_untracked` | No untracked files outside contract |
| `check_symbols_required` | Required AST symbols present |
| `check_symbols_forbidden` | Forbidden AST symbols absent |
| `check_git_diff_check` | `git diff --check` passes (whitespace) |

Entry point: `run_verification(contract_path)` → `VerificationReport` (PASS/FAIL)

**Source**: `verification.py:1231-1300`

### 5.4 Verification Runner (Hermes)

`agent/verify/runner.py` — executes Recipe phases (bootstrap → build → test → start → readiness poll). Used by `hermes verify` CLI.

`agent/verify/recipes.py` — detects project recipes from manifests (package.json, pyproject.toml, Makefile, etc.).

---

## 6. Workspace Cleanup (Post-Completion)

`_cleanup_worktree_workspace()` in `kanban_db.py:6142-6203`:

**Safety invariants** (never violated):
- Tracked modifications NEVER deleted (any age, any mode)
- Unique unpushed commits NEVER deleted (uses `git cherry` patch-equivalence)
- Live-locked trees (owning PID alive) never touched
- Branch deleted only after worktree removal succeeds
- Untracked-only dirt ARCHIVED to `~/.hermes/archive/worktree-prune/` before reaping

**Source**: `worktree_gc.py:1-33` (module docstring)

---

## 7. Gaps and Missing Capabilities

### 7.1 No Automatic Push or Sync
Worktrees are created locally but never automatically pushed to remote. The `web_git.py` module has `review_push()` and `_review_push()` helpers, but these are not wired into the task completion flow.

### 7.2 No Automatic Merge/PR Creation
After review approval, there is no mechanism to automatically create a PR or merge the worktree branch into the target branch. This is entirely manual.

### 7.3 No Pre-Commit Hooks
No `.pre-commit-config.yaml` exists. The CI only runs on push/PR, not locally before commit.

### 7.4 Verification Not Integrated into Completion Flow
The Janus verification pipeline (`janus verify-contract`) is a standalone CLI tool. It is not automatically invoked when an agent claims task completion. The Hermes verify-on-stop nudge is policy-only (injects a message, doesn't execute checks).

### 7.5 No Structured Completion Handoff
Agent completion claims are prose in a chat message. There is no structured attachment of what was verified (which tests passed, which files were created, which commands were run). The human must independently re-derive what was supposed to be done.

**Source**: `docs/verification_pipeline_design.md:88-93` (Section 1.3 "What's Missing")

### 7.6 No Sync Between Worktree Branches
Once a worktree branch is created, there is no mechanism to sync it with the target branch (rebase, merge from main). If the target branch advances while a task is in progress, the worktree branch diverges without warning.

---

## 8. Key Files Reference

| File | Purpose |
|------|---------|
| `hermes_cli/kanban_db.py` | Core Kanban DB: task lifecycle, worktree resolution, cleanup |
| `hermes_cli/kanban_swarm.py` | Swarm topology: planning root + workers + verifier + synthesizer |
| `hermes_cli/web_git.py` | Git operations: worktree, branch, status, commit, push, PR |
| `hermes_cli/worktree_gc.py` | Attended worktree + branch reclaim (dry-run-first) |
| `hermes_cli/projects_db.py` | Project registry: deterministic branch naming |
| `agent/verify/runner.py` | Recipe-based verification runner (bootstrap→build→test→start) |
| `agent/verify/recipes.py` | Project recipe detection (Node/Python/Go/Rust/Java/Makefile) |
| `agent/verify_hooks.py` | Pre-verify round-end gate (policy-only) |
| `src/janus/verification.py` | Implementation contract verification (9 check types) |
| `.github/workflows/ci.yml` | CI: pytest on push/PR |
| `docs/decisions/001-hermes-janus-system-model.md` | ADR: two-layer architecture |
| `docs/decisions/003-canonical-review-topology.md` | ADR: Model A review lane |
| `docs/verification_pipeline_design.md` | Design proposal: multi-stage verification pipeline |

---

## 9. Summary

The current system has **strong worktree lifecycle management** (creation, cleanup, GC) and **a solid review workflow** (Model A native review lane). However, it lacks:

1. **Automatic push/sync** from worktrees to remote
2. **Automatic merge/PR creation** after review approval
3. **Pre-commit hooks** for local verification
4. **Integration of verification pipeline** into task completion flow
5. **Structured completion handoff** (evidence package vs. prose claim)
6. **Branch sync** (rebase/merge from target branch during long-running tasks)

The verification infrastructure exists at two levels (Janus contract verification + Hermes recipe runner) but is not wired into the Kanban completion lifecycle. This is the primary gap preventing mechanical verification of agent completion claims.
