# Reproduction Report: Reviewer Child Invoking `kanban_request_changes` Against Implementer Child

**Task:** t_75b3bc29 — Reproduce reviewer child invoking kanban_request_changes against implementer child
**Date:** 2026-08-31
**Workspace:** /home/dan11hermes/workspaces/janus/.worktrees/t_75b3bc29

---

## 1. Reproduction Setup

Two child tasks were created to mirror the auto-decomposer topology:

| Role | Task ID | Assignee | Status |
|------|---------|----------|--------|
| Implementer child (target) | `t_3fcd1646` | implementer | ready |
| Reviewer child | `t_606cf080` | reviewer | ready (blocked on parent) |

The reviewer child (`t_606cf080`) was linked with the implementer child (`t_3fcd1646`) as its parent, mirroring the auto-decomposer's dependency topology where the reviewer depends on the implementer.

The reviewer child's body was annotated with the implementer child's task_id via comment.

---

## 2. Experiment 1: Cross-Task Mutation Attempt

**Caller:** Worker scoped to `HERMES_KANBAN_TASK=t_75b3bc29` (this task)
**Target:** `t_3fcd1646` (implementer child)
**Tool call:** `kanban_request_changes(task_id="t_3fcd1646", reason="repro: testing ownership enforcement")`

**Result:** BLOCKED at the tool wrapper layer.

**Exact error:**
```
worker is scoped to task t_75b3bc29; refusing to mutate t_3fcd1646. Use kanban_comment to hand off information to other tasks, or kanban_create to spawn follow-up work.
```

**Layer:** `_enforce_worker_task_ownership()` at `tools/kanban_tools.py:183`

This is the critical finding: **a worker process spawned by the dispatcher has `HERMES_KANBAN_TASK` set to its own task_id. The ownership enforcement check refuses any mutation where `tid != env_tid`.** This means a reviewer child (scoped to its own task_id) cannot directly invoke `kanban_request_changes` against a different implementer child task_id.

---

## 3. Experiment 2: Same-Task Mutation Without Review Context

**Caller:** Worker scoped to `HERMES_KANBAN_TASK=t_75b3bc29`
**Target:** `t_75b3bc29` (own task)
**Tool call:** `kanban_request_changes(task_id="t_75b3bc29", reason="repro: calling on own task to observe precondition failures")`

**Result:** BLOCKED at the DB precondition layer.

**Exact error:**
```
could not request changes for t_75b3bc29: active run was not claimed from review
```

**Layer:** `kanban_db.request_changes()` precondition #4 at `hermes_cli/kanban_db.py:6711`

Even when the ownership check passes (same task), the DB method requires the active run to have been claimed from `review` status. This task's run was claimed from `ready`, not `review`.

---

## 4. Experiment 3: Default task_id (no explicit arg)

**Caller:** Worker scoped to `HERMES_KANBAN_TASK=t_75b3bc29`
**Target:** (defaulted to `t_75b3bc29` via `HERMES_KANBAN_TASK` env)
**Tool call:** `kanban_request_changes(reason="repro: own task, no review context")`

**Result:** Same as Experiment 2 — blocked at DB precondition layer.

**Exact error:**
```
could not request changes for t_75b3bc29: active run was not claimed from review
```

This confirms that `_default_task_id()` correctly falls back to `HERMES_KANBAN_TASK` when no explicit `task_id` is provided.

---

## 5. Full Precondition Chain (from trace document)

For `kanban_request_changes` to succeed, ALL of the following must hold:

| # | Layer | Check | Error message |
|---|-------|-------|---------------|
| 1 | Wrapper | Not a delegated child context | (delegate rejection) |
| 2 | Wrapper | `task_id` resolves (arg or env) | `"task_id is required"` |
| 3 | Wrapper | `_enforce_worker_task_ownership(tid)` — `tid` must equal `HERMES_KANBAN_TASK` | `"worker is scoped to task {env_tid}; refusing to mutate {tid}"` |
| 4 | DB | Task exists | `"task not found"` |
| 5 | DB | `status == "running"` AND `current_run_id is not None` | `"task is not in an active review run"` |
| 6 | DB | `expected_run_id` matches `current_run_id` (if provided) | `"run_id mismatch"` |
| 7 | DB | Active run was claimed from `review` status | `"active run was not claimed from review"` |
| 8 | DB | Prior `review_requested` event exists | `"no prior review_requested event"` |
| 9 | DB | `review_requested` payload has valid `implementer` provenance | `"review handoff has no valid implementer provenance"` |

---

## 6. Key Finding: The Structural Incompatibility

The reproduction confirms a **structural incompatibility** between the auto-decomposer's reviewer-child topology and the native rejected-review lifecycle:

1. **Worker task ownership enforcement** (`_enforce_worker_task_ownership`) prevents any dispatcher-spawned worker from mutating a task other than its own. A reviewer child scoped to `HERMES_KANBAN_TASK=<reviewer_child_id>` cannot target the implementer child's task_id.

2. **Single task_id binding**: The tool only accepts one `task_id`. The implementer is recovered from the `review_requested` event payload, not from a separate argument. There is no way to tell the tool "reject implementer X" — it can only "reject the task that this reviewer was assigned to review."

3. **The native lifecycle expects the reviewer to be the SAME task as the one in review**: In the native flow, an implementer calls `kanban_request_review` on their OWN task, which transitions it to `review` status and assigns it to a reviewer. The reviewer then calls `kanban_request_changes` on that SAME task_id. The ownership check passes because the reviewer worker is scoped to that task.

4. **The auto-decomposer creates SEPARATE tasks**: The reviewer child is a distinct task from the implementer child. The reviewer child is never assigned to the implementer child's task_id, so the ownership check will always fail when it tries to reject the implementer.

**Conclusion:** The Phase 3 incident was NOT purely a reviewer tool-selection error. There is a fundamental incompatibility: the native `kanban_request_changes` lifecycle assumes the reviewer operates on the task that was handed off to them (same task_id), while the auto-decomposer's topology creates separate reviewer and implementer tasks. The ownership enforcement correctly prevents the reviewer child from mutating the implementer child's task.

---

## 7. Artifacts

- Implementer child task: `t_3fcd1646`
- Reviewer child task: `t_606cf080`
- Trace document (from sibling task t_c84e54e3): `/home/dan11hermes/workspaces/janus/.worktrees/t_c84e54e3/docs/research/kanban-request-changes-trace.md`
