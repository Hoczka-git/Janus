# Gap Analysis: PR Automation Workflow Design vs. Target Semantics

**Task:** t_6b060ae7
**Date:** 2026-09-02
**Source design:** `docs/research/pr_automation_workflow_design.md` (commit `a6987ec`, branch `wt/t_2fbd2e6e`)
**Target workflow:** implementation → commit → push → synchronize with latest target branch → run verification/tests again → create GitHub PR → wait for CI → enable/use GitHub auto-merge → verify PR was actually merged into target branch → only then mark Kanban task as DONE → kanban_task_completed → replenishment

---

## 1. Current Design Summary

The existing design (`pr_automation_workflow_design.md`) describes a **post-completion observer plugin** (`plugins/kanban_pr_create/__init__.py`) that:

1. Hooks into `kanban_task_completed` (fires AFTER `complete_task()` commits task to `status='done'`)
2. Guards on `workspace_kind == 'worktree'` and `gh auth`
3. Checks idempotency via `review_pr_list(branch_name)`
4. Creates PR via `review_create_pr()` (pushes branch + `gh pr create --fill`)
5. Persists PR URL to `tasks.metadata`

It is intentionally minimal: one new file, no core changes, no CI changes.

---

## 2. Gap List

### Gap 1: Trigger Timing — DONE happens before integration

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **Trigger event** | `kanban_task_completed` (fires after `status='done'` committed) | Must fire BEFORE the task is marked DONE |
| **Task state at PR creation** | `done` | Must remain non-DONE (e.g., `running`, `review`, or a new state) |
| **Consequence** | Replenishment fires immediately on `kanban_task_completed`, before PR exists or merges | Replenishment must wait until PR is merged |

**Evidence:** `kanban_db.py:5770` — `_fire_kanban_lifecycle_hook("kanban_task_completed", ...)` is called inside `complete_task()` AFTER the `status='done'` UPDATE commits. The replenishment plugin (`plugins/replenishment/__init__.py:63`) consumes this event immediately.

**Required change:** The integration workflow must be triggered by an event/state transition that occurs BEFORE `complete_task()` commits to `done`. Options:
- A new hook (e.g., `on_kanban_pre_complete` or `on_kanban_integration_ready`) fired from within `complete_task()` BEFORE the `status='done'` UPDATE
- A new Kanban status (e.g., `integrating`) that the task enters after `kanban_complete` is called but before `done`
- Reuse of the existing `review` status as the "integration in progress" state

---

### Gap 2: No branch synchronization before PR creation

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **Branch freshness** | Relies on `_enforce_repo_sync_gate()` which only checks "committed + pushed" | Must rebase onto latest target branch immediately before PR creation |
| **Staleness detection** | None — assumes pushed = fresh | Must detect `merge-base <task> <target>` behind `origin/<target>` |
| **Rebase** | Not performed | Required: `git rebase origin/<target>` |
| **Force-push** | Not performed | Required: `git push --force-with-lease` after rebase |

**Evidence:** `_enforce_repo_sync_gate()` (`kanban_db.py:5465-5531`) only checks `_worktree_is_dirty()` and `_worktree_has_unpushed_commits()`. It does NOT compare merge-base against the remote target. A task branch pushed yesterday is "synced" by this gate even if target advanced today.

**Required change:** Add a sync step that fetches the remote target, computes merge-base, rebases if stale, and force-pushes. The existing `git_sync.py` (`src/janus/git_sync.py`) already implements this primitive but is not wired into the PR workflow.

---

### Gap 3: No verification/tests re-run before PR creation

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **Test execution** | None before PR creation | Must run full test suite on the rebased branch |
| **CI gate** | None — PR created regardless of CI status | Must verify tests pass after final rebase, before PR creation |
| **Failure handling** | N/A | Block task with `post_sync_verification_failure` if tests fail |

**Evidence:** The design explicitly states "CI already covers `wt/*` branches" (§4.1) but this is CI on the push, not a gate before PR creation. The PR is created regardless of whether tests pass.

**Required change:** After the final rebase (Gap 2), run the project's test suite locally. Only proceed to PR creation if tests pass. This mirrors Phase 3 of `sync_integration_workflow_design.md`.

---

### Gap 4: No post-PR lifecycle management

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **After PR creation** | PR URL stored in metadata; workflow ends | Must wait for CI, enable auto-merge, verify merge |
| **CI monitoring** | None | Must poll `gh pr checks` or equivalent until completion |
| **Auto-merge** | Explicitly out of scope | Must enable via `gh pr merge --auto` (if repo supports it) |
| **Merge verification** | None | Must verify PR was actually merged into target branch |
| **State feedback** | None | Must update task state based on PR outcome |

**Evidence:** Design §6 explicitly states "No automated 'PR merged → mark task integrated' transition" and "No polling for PR state changes."

**Required change:** After PR creation, the workflow must:
1. Poll CI status (via `gh pr checks --watch` or `gh api` polling loop)
2. On CI success: enable auto-merge (via `gh pr merge --auto --squash`)
3. Poll PR state until `merged == true`
4. On merge verified: proceed to DONE
5. On CI failure: block task, notify worker

---

### Gap 5: No auto-merge enablement

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **Auto-merge** | Explicitly out of scope (§4.2, §11) | Must be enabled if repo supports it |
| **Safety** | N/A | Requires branch protection + CI passing (or explicit opt-in) |

**Evidence:** Design §4.2: "Not enabled by this design... explicitly does not enable auto-merge."

**Required change:** After PR creation and CI success, call `gh pr merge --auto --squash --delete-branch` (or equivalent via GraphQL API). The `github-pr-workflow` skill documents both `gh` and `curl` paths for this.

---

### Gap 6: No actual merge completion detection

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **Merge detection** | None | Must verify PR `state == 'MERGED'` or target branch contains task commit |
| **Proof** | PR URL in metadata | Must confirm `gh pr view <number> --json state` returns `MERGED` or `git branch -r --contains <sha>` includes target |

**Evidence:** Design §6: "No way for downstream automation to know whether the PR was merged."

**Required change:** After enabling auto-merge, poll PR state. Only when GitHub reports the PR as merged should the task proceed to DONE.

---

### Gap 7: No conflict handling during sync

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **Sync conflicts** | Not addressed (no rebase performed) | Must detect rebase conflicts and block task |
| **Resolution** | N/A | Route to merge-reconciler skill |
| **Integration conflicts** | PR still created; conflict visible on GitHub | Must NOT create PR if sync produces conflicts |

**Evidence:** Design §4.3: "Not handled by this design... PR still created; conflict visible on GitHub."

**Required change:** During the sync step (Gap 2), if rebase produces conflicts:
1. Abort the rebase
2. Block task with reason `sync_conflict`
3. Route to merge-reconciler (existing skill)
4. Do NOT proceed to PR creation

---

### Gap 8: Replenishment fires before integration completes

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **Replenishment trigger** | `kanban_task_completed` (immediately on DONE) | Must fire only after PR merged |
| **Consequence** | Next task in chain starts before current task's code is in the target branch | Next task starts only after current code is integrated |

**Evidence:** `plugins/replenishment/__init__.py:63` — `on_task_completed` fires on `kanban_task_completed`. Since `complete_task()` fires this hook after `status='done'` but before PR merge, replenishment runs too early.

**Required change:** The `kanban_task_completed` event must only fire after successful integration (PR merged). This is a direct consequence of Gap 1 — if DONE only happens after merge, replenishment naturally fires at the right time.

---

### Gap 9: No idempotency for the full workflow

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **PR idempotency** | `review_pr_list` check prevents duplicate PRs | Full workflow must be idempotent: sync, verify, PR, CI, merge |
| **Retry safety** | Re-completion skips if PR exists | Retry must resume from last successful step, not re-create PR or re-merge |
| **Step state** | None persisted | Must persist step state (e.g., `sync_done`, `pr_created`, `pr_number`, `merge_verified`) |

**Evidence:** Design §3.2 only guards PR creation. No state is persisted for "have we already synced?", "have we already created the PR?", "have we already enabled auto-merge?".

**Required change:** Persist workflow step state in `tasks.metadata` (or a dedicated tracking structure). On retry, read state and resume from the last incomplete step. Required state fields:
- `sync_state`: `pending | done | conflict`
- `pr_number`: int (set after PR creation)
- `pr_url`: str
- `auto_merge_enabled`: bool
- `merge_verified`: bool
- `target_branch`: str
- `task_commit_sha`: str

---

### Gap 10: No worker feedback on integration outcome

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **PR creation failure** | Swallowed by `try/except`; task stays `done` | Worker must be notified; task blocked |
| **CI failure** | Out of scope | Worker must be notified; task blocked |
| **Merge conflict** | Out of scope | Worker must be notified; task blocked |
| **GitHub unavailable** | Swallowed; task stays `done` | Worker must be notified; task blocked or retried |

**Evidence:** Design §5: "PR creation fails → Swallowed by hook's try/except — task stays done."

**Required change:** The integration workflow must NOT be observer-only. It must be a blocking workflow that:
- Updates task status to `blocked` on failure
- Attaches error output as artifacts
- Notifies the worker via the Kanban comment system or gateway

---

### Gap 11: No handling of GitHub unavailability

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **GitHub down** | `review_create_pr` fails; swallowed | Must retry with backoff; block if persistent |
| **Network errors** | Swallowed | Must distinguish transient from permanent failures |

**Evidence:** Design §5: "GitHub temporarily unavailable → review_create_pr fails; swallowed by hook; task stays done."

**Required change:** Implement retry with exponential backoff for transient GitHub API failures. After N retries, block the task with a `github_unavailable` reason.

---

### Gap 12: No distinction between repository and non-repository tasks

| Aspect | Current Design | Target |
|--------|---------------|--------|
| **Scope guard** | `workspace_kind == 'worktree'` | Same guard, but workflow must not break non-worktree tasks |
| **Non-coding tasks** | Silently skipped | Must remain silently skipped |

**Evidence:** Design §8: "Preserved by the `workspace_kind` guard." This is adequate for the current design but the expanded workflow must also respect it.

**Required change:** Keep the `workspace_kind` guard. The expanded workflow only applies to `worktree` tasks. Non-worktree tasks proceed through the normal `complete_task()` → `done` → `kanban_task_completed` path.

---

## 3. Existing Capabilities to Reuse

The following already exist and must be reused (per requirement 9):

| Capability | Location | Status |
|------------|----------|--------|
| **worktree-per-task** | `kanban_db.py:_ensure_git_worktree` (line 8053) | ✅ Exists |
| **repo-sync gate** | `kanban_db.py:_enforce_repo_sync_gate` (line 5465) | ✅ Exists, but insufficient (Gap 2) |
| **sync primitive** | `src/janus/git_sync.py` | ✅ Exists (rebase + force-push + conflict detection) |
| **PR creation** | `web_git.py:review_create_pr` (line 556) | ✅ Exists |
| **PR idempotency check** | `web_git.py:review_pr_list` (line 505) | ✅ Exists |
| **gh auth check** | `web_git.py:review_ship_info` (line 447) | ✅ Exists |
| **target branch detection** | `web_git.py:_default_branch_name` (line 146) | ✅ Exists |
| **merge-base computation** | `web_git.py:_branch_base` (line 132) | ✅ Exists |
| **github-pr-workflow** | `skills/github/github-pr-workflow/SKILL.md` | ✅ Exists (gh + curl paths for PR lifecycle) |
| **merge-reconciler** | `skills/autonomous-ai-agents/merge-reconciler/SKILL.md` | ✅ Exists (neutral conflict resolution) |
| **lifecycle hooks** | `kanban_db.py:_fire_kanban_lifecycle_hook` (line 188) | ✅ Exists |
| **Kanban state transitions** | `complete_task`, `request_review`, `request_changes`, `unblock_task` | ✅ Exists |
| **replenishment plugin** | `plugins/replenishment/__init__.py` | ✅ Exists, but fires too early (Gap 8) |

---

## 4. Key Architectural Decisions Needed

### D1: What event/state transition starts the integration workflow?

The current `kanban_task_completed` fires too late (after DONE). Options:
- **Option A:** Fire a new `on_kanban_integration_ready` hook from within `complete_task()` BEFORE the `status='done'` UPDATE, after `_enforce_repo_sync_gate` passes.
- **Option B:** Introduce a new Kanban status `integrating` that `complete_task()` transitions to instead of `done`. A separate integration agent watches for `integrating` tasks and processes them.
- **Option C:** Reuse the existing `review` status. After `kanban_request_review` approval, the reviewer triggers integration instead of `kanban_complete`.

**Recommendation:** Option A is the smallest change. It reuses the existing hook infrastructure and requires only a new hook name + firing point inside `complete_task()`.

### D2: How does the task remain non-DONE while PR/CI/merge is in progress?

Options:
- **Option A:** Task stays in `review` status (already exists, already means "waiting for external approval").
- **Option B:** New `integrating` status.
- **Option C:** Task stays in `running` status with a `metadata.integration_in_progress` flag.

**Recommendation:** Option A (reuse `review`). The `review` status already exists and is claimable by an integration agent. The task enters `review` after implementation + sync + verification, and the integration agent (a separate profile) processes the PR lifecycle.

### D3: How is branch freshness checked and enforced?

Use the existing `git_sync.py:detect_target_branch()` + `is_branch_stale()` + `fetch_target()` + rebase + force-push. The sync step must run immediately before PR creation, not just at task start.

### D4: How is PR creation made idempotent?

Persist `pr_number` and `pr_url` in `tasks.metadata` after creation. Before creating, check `review_pr_list(branch_number)` or the persisted `pr_number`. If PR exists, skip to CI monitoring.

### D5: How is CI monitored?

Use `gh pr checks --watch` (polls every 10s) or a manual polling loop via `gh api repos/{owner}/{repo}/commits/{sha}/status` (per `github-pr-workflow` skill §4). Run in a background process or cron-like loop.

### D6: How is auto-merge enabled?

After CI success, call `gh pr merge <number> --auto --squash --delete-branch` (per `github-pr-workflow` skill §6). Requires the repo to have auto-merge enabled in settings (a one-time ~30s UI configuration).

### D7: How is actual merge completion detected?

Poll `gh pr view <number> --json state` until it returns `MERGED`. Alternatively, `git fetch origin` then `git branch -r --contains <task-sha>` to confirm target contains the task commit.

### D8: What happens on CI failure?

Block the task with reason `ci_failure`. Attach CI logs as artifacts. Notify worker. Do NOT enable auto-merge. Worker fixes and re-triggers.

### D9: What happens on merge conflict?

During sync: block with `sync_conflict`, route to merge-reconciler. During integration: block with `integration_conflict`, route to merge-reconciler. Do NOT create PR.

### D10: What happens if GitHub is unavailable?

Retry with exponential backoff (up to N attempts). If persistent, block with `github_unavailable`. Do NOT mark DONE.

### D11: How does this interact with `kanban_task_completed` and replenishment?

`kanban_task_completed` must only fire after merge verification (Gap 8). This means `complete_task()` must NOT fire it directly for worktree tasks. Instead, the integration agent fires it after merge verification. Replenishment naturally fires at the right time.

---

## 5. Summary of Required Changes

| # | Change | Scope | Complexity |
|---|--------|-------|------------|
| 1 | New hook `on_kanban_integration_ready` fired before `status='done'` | `kanban_db.py` | Low |
| 2 | Wire `git_sync.py` into the workflow (rebase + force-push before PR) | Plugin | Medium |
| 3 | Add pre-PR verification step (run tests after rebase) | Plugin | Low |
| 4 | Add post-PR CI monitoring (poll `gh pr checks`) | Plugin | Medium |
| 5 | Add auto-merge enablement (`gh pr merge --auto`) | Plugin | Low |
| 6 | Add merge verification (poll PR state until MERGED) | Plugin | Medium |
| 7 | Persist workflow step state in `tasks.metadata` | Plugin | Low |
| 8 | Add conflict handling (block + route to merge-reconciler) | Plugin | Medium |
| 9 | Add retry with backoff for GitHub unavailability | Plugin | Low |
| 10 | Delay `kanban_task_completed` until after merge | `kanban_db.py` + plugin | Medium |
| 11 | Worker feedback on integration failure (block + artifacts) | Plugin | Low |

---

## 6. Risks and Open Questions

1. **Race condition:** Two tasks integrating to the same target branch simultaneously. The second push will be rejected by git. Mitigation: retry with re-sync (git's ref-update atomicity is the guard).

2. **Long-running integration agent:** CI + auto-merge can take minutes to hours. The integration agent must be a long-running process or a cron-polled workflow, not a single synchronous hook call.

3. **Hook timeout:** The existing `_fire_kanban_lifecycle_hook` is synchronous and best-effort. A long-running integration workflow cannot run inside it. Mitigation: the hook only *enqueues* the integration work (e.g., sets a flag or creates an integration card), and a separate agent processes it.

4. **Replenishment double-fire:** The `kanban_task_completed` hook fires both from `complete_task()` and from `kanban_swarm.create_swarm()` (per `replenishment/__init__.py:50-54`). The integration workflow must be idempotent to handle this.

5. **Worktree cleanup timing:** `_cleanup_workspace` is called inside `complete_task()` (line 5767). If integration happens after `done`, the worktree may already be cleaned up. Mitigation: defer worktree cleanup until after integration, or run integration in the main checkout (not the worktree).
