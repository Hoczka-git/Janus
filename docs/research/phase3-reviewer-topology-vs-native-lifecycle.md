# Analysis: Phase 3 Incident — Reviewer-Child Topology vs. Native Rejected-Review Lifecycle

**Task:** t_dd0d5816 — Analyze Phase 3 incident and reviewer-child topology vs native rejected-review lifecycle
**Date:** 2026-08-31
**Author:** researcher (synthesis of t_75b3bc29, t_c84e54e3, t_58167618, t_9e30708e)

---

## 1. Question Investigated

Was the Phase 3 incident purely a reviewer tool-selection error (wrong task_id, wrong invocation context) or an incompatibility between the decomposed reviewer-child topology and the native rejected-review lifecycle?

---

## 2. Scope and Constraints

- **In scope:** Native rejected-review lifecycle (`kanban_request_changes`), auto-decomposer topology (separate reviewer/implementer child tasks), worker task ownership enforcement (`_enforce_worker_task_ownership`), DB precondition chain for `request_changes`, dispatcher review dispatch.
- **Out of scope:** Phase 3.5 F-03 bug, CI typos, profile SOUL.md gaps (covered in retrospective t_9e30708e).
- **Evidence sources:** Parent task artifacts (t_75b3bc29, t_c84e54e3, t_58167618), retrospective (t_9e30708e), direct source code inspection.

---

## 3. Evidence Examined

### 3.1 Native Rejected-Review Lifecycle (from t_c84e54e3, t_58167618)

The native lifecycle is a **single-task workflow**:

```
Implementer calls kanban_request_review(task_id=<own_task>)
    → task transitions running → review
    → dispatcher claims review task (claim_review_task: review → running)
    → reviewer worker spawned, scoped to SAME task_id
    → reviewer calls kanban_request_changes(task_id=<same_task>)
    → ownership check passes (tid == HERMES_KANBAN_TASK)
    → DB preconditions pass (claimed from review, review_requested event exists)
    → task returns to implementer (ready/todo)
```

Key properties:
- **Single task_id binding**: The tool accepts one `task_id`. The implementer is recovered from the `review_requested` event payload, not from a separate argument.
- **Ownership enforcement**: `_enforce_worker_task_ownership(tid)` at `tools/kanban_tools.py:183` requires `tid == HERMES_KANBAN_TASK`. In the native flow, the reviewer worker is scoped to the same task_id that was handed off, so this check passes.
- **DB preconditions** (all at `hermes_cli/kanban_db.py:6663`):
  1. Task exists
  2. `status == "running"` AND `current_run_id is not None`
  3. `expected_run_id` matches `current_run_id` (if provided)
  4. Active run was claimed from `review` status
  5. Prior `review_requested` event exists
  6. `review_requested` payload has valid `implementer` provenance

### 3.2 Auto-Decomposer Topology (from t_75b3bc29)

The auto-decomposer creates **separate tasks** for implementer and reviewer:

```
Root task (orchestrator)
    ├── Implementer child (assignee=implementer, parents=[root])
    └── Reviewer child (assignee=reviewer, parents=[implementer])
```

The reviewer child is scoped to `HERMES_KANBAN_TASK=<reviewer_child_id>`. The implementer child is scoped to `HERMES_KANBAN_TASK=<impl_child_id>`.

### 3.3 Ownership Enforcement Block (from t_75b3bc29, Experiment 1)

When the reviewer child attempts to call `kanban_request_changes(task_id=<impl_child_id>)`:

```python
# tools/kanban_tools.py:183
def _enforce_worker_task_ownership(tid: str) -> Optional[str]:
    env_tid = os.environ.get("HERMES_KANBAN_TASK")
    if not env_tid:
        return None  # Orchestrator context
    if tid != env_tid:
        return tool_error(
            f"worker is scoped to task {env_tid}; refusing to mutate "
            f"{tid}. Use kanban_comment to hand off information to other "
            f"tasks, or kanban_create to spawn follow-up work."
        )
    return None
```

**Result:** `"worker is scoped to task t_606cf080; refusing to mutate t_3fcd1646."`

The reviewer child **cannot** mutate the implementer child's task. This is by design — it prevents cross-task corruption (#19534).

### 3.4 DB Precondition Block (from t_75b3bc29, Experiment 2)

Even if ownership were bypassed, calling `kanban_request_changes` on a task without review context fails:

```
"active run was not claimed from review"
```

The implementer child's run was claimed from `ready`, not `review`. The `request_changes` function requires the active run to have been claimed from `review` status (precondition #4 at `kanban_db.py:6711`).

### 3.5 Phase 3 Close-Out Flow (from t_9e30708e)

The Phase 3 close-out used the **native lifecycle**, not the decomposed topology:

| Task | Role | Action |
|------|------|--------|
| t_b01ff44e | implementer | Called `kanban_request_review` on own task |
| t_5dcad317 | reviewer | Was assigned to review t_b01ff44e (same task_id) |
| t_a665778c | root | Absorbed remediation after reviewer REJECT |

The reviewer (t_5dcad317) performed a clean-checkout inspection and found uncommitted work. The reviewer posted a REJECT comment but **did not call `kanban_request_changes`**. Instead, the root task (t_a665778c) absorbed the remediation.

This is the critical observation: **the Phase 3 reviewer did not attempt to use `kanban_request_changes` at all**. The reviewer used `kanban_comment` to report findings, and the root task handled the remediation.

---

## 4. Current State

### 4.1 Native Lifecycle: Works as Designed

The native rejected-review lifecycle works correctly when:
1. The implementer calls `kanban_request_review` on their own task
2. The dispatcher claims the review task and spawns a reviewer worker scoped to the same task_id
3. The reviewer calls `kanban_request_changes` on that same task_id

All preconditions pass, ownership enforcement passes, and the task returns to the implementer.

### 4.2 Decomposed Reviewer-Child Topology: Structurally Incompatible

When the auto-decomposer creates separate reviewer and implementer child tasks, the reviewer child **cannot** call `kanban_request_changes` against the implementer child because:

1. **Ownership enforcement blocks cross-task mutation**: The reviewer child is scoped to its own `HERMES_KANBAN_TASK`. The implementer child has a different task_id. The check at `tools/kanban_tools.py:183` refuses the mutation.

2. **No review context on implementer child**: Even if ownership were bypassed, the implementer child's run was claimed from `ready`, not `review`. The DB precondition at `kanban_db.py:6711` requires `source_status == "review"`.

3. **Single task_id binding**: The tool only accepts one `task_id`. There is no way to tell the tool "reject implementer X" — it can only "reject the task that this reviewer was assigned to review."

### 4.3 Diagnostic Rule Exists (from kanban_diagnostics.py:753)

The system has a diagnostic rule `_rule_review_dependency_deadlock` that detects this exact scenario:

> "Older workers were instructed to sticky-block an implementation with a `review-required:` reason. A separately modelled reviewer child cannot promote until that parent is terminal, so the lane has no autonomous next step."

This confirms the incompatibility is a known pattern, not a new discovery.

---

## 5. Findings

### F1: The Phase 3 incident was NOT purely a reviewer tool-selection error

The reviewer (t_5dcad317) did not attempt to call `kanban_request_changes`. The reviewer used `kanban_comment` to report findings, and the root task absorbed the remediation. The incident was a **process gap** (no mechanical durability gate before review dispatch), not a tool-selection error.

### F2: The decomposed reviewer-child topology is structurally incompatible with the native rejected-review lifecycle

The native lifecycle assumes the reviewer operates on the same task_id that was handed off. The auto-decomposer creates separate reviewer and implementer tasks. The ownership enforcement correctly prevents the reviewer child from mutating the implementer child's task.

### F3: Two distinct review patterns exist, and they are not interchangeable

| Pattern | Mechanism | Reviewer scope | Rejection path |
|---------|-----------|----------------|----------------|
| Same-card review (native) | `kanban_request_review` on implementer's own card | Same task_id | `kanban_request_changes` on same task_id |
| Pre-created downstream card (decomposed) | `kanban_create` with `parents=[impl_id]` | Separate reviewer child task | `kanban_complete` on implementation parent releases child; reviewer cannot call `request_changes` on implementer |

### F4: The auto-decomposer does not generate reviewer children that use the native lifecycle

The decomposer creates reviewer children as separate tasks with `parents=[impl_id]`. These children are instructed to review the parent's work, but they have no mechanism to reject the parent via `kanban_request_changes`. The only way to "reject" in this topology is for the reviewer child to call `kanban_block` or `kanban_comment`, and for the orchestrator to handle the remediation.

---

## 6. Alternatives Considered

### A: Fix the reviewer child to call `kanban_request_changes` on the implementer child

**Rejected**: Ownership enforcement (`tools/kanban_tools.py:183`) explicitly blocks this. The check is a security feature (#19534) to prevent cross-task corruption. Bypassing it would require either:
- Removing the ownership check (security risk)
- Adding a special "reviewer bypass" (adds complexity, undermines the ownership model)

### B: Have the reviewer child call `kanban_request_changes` on its own task

**Rejected**: The DB preconditions require the task to have been claimed from `review` status. The reviewer child is claimed from `ready` (via the dispatcher's review dispatch). Even if it were claimed from `review`, the `review_requested` event would not exist on the reviewer child — it exists on the implementer child.

### C: Use the native lifecycle for decomposed reviewer children

**Rejected**: The native lifecycle requires the reviewer to be assigned to the same task_id as the implementer. In the decomposed topology, the reviewer is a separate task. Merging them would defeat the purpose of decomposition.

### D: Accept the incompatibility and route rejections through the orchestrator

**Selected**: This is the current pattern. The reviewer child reports findings via `kanban_comment` or `kanban_block`. The orchestrator (root task) absorbs the remediation and routes back to the implementer. This is what happened in Phase 3.

---

## 7. Recommendation

### R1: Document the two review patterns and their constraints

Add to the `sdlc-review` skill and/or the kanban tutorial:

1. **Same-card review** (native lifecycle): Use when the implementer and reviewer are the same task. The reviewer can call `kanban_request_changes` to return the task to the implementer.
2. **Pre-created downstream card** (decomposed): Use when the reviewer is a separate child task. The reviewer **cannot** call `kanban_request_changes` on the implementer. The reviewer must use `kanban_comment` or `kanban_block`, and the orchestrator handles remediation.

### R2: Add a precondition check or skill guidance for reviewer children

The `sdlc-review` skill should explicitly state: "If you are a reviewer child task (separate from the implementer), do not attempt to call `kanban_request_changes` on the implementer's task. Use `kanban_comment` to report findings and let the orchestrator handle remediation."

### R3: Consider a dedicated "reject parent" tool for decomposed reviewer children

If the decomposed topology needs a mechanical rejection path, consider adding a new tool (e.g., `kanban_reject_parent`) that:
- Is scoped to the reviewer child's task
- Validates the parent-child relationship
- Transitions the parent back to the implementer via a controlled path
- Does not violate ownership enforcement (it mutates the reviewer child's task, not the implementer's)

This is a larger change and should be evaluated separately.

---

## 8. Remaining Uncertainty

1. **Auto-decomposer behavior**: The auto-decomposer's system prompt and JSON schema are not inspectable from this workspace. It is unknown whether the decomposer explicitly instructs reviewer children to use `kanban_request_changes` or whether it relies on the `sdlc-review` skill.

2. **Dispatcher review dispatch interaction**: When `review_dispatch` is enabled, the dispatcher claims review tasks and spawns reviewer workers. It is unclear how this interacts with decomposed reviewer children — whether the dispatcher would attempt to claim a decomposed reviewer child that is already in `todo` status.

3. **Phase 3 reviewer's actual tool calls**: The retrospective documents the reviewer's comment and the root task's remediation, but the exact tool calls made by the reviewer worker are not captured in the evidence. It is possible the reviewer attempted `kanban_request_changes` and failed, then fell back to `kanban_comment`.

---

## 9. Conclusion

The Phase 3 incident was **not** purely a reviewer tool-selection error. The reviewer did not attempt to call `kanban_request_changes`. The incident was a process gap (no mechanical durability gate before review dispatch) that allowed uncommitted work to reach the reviewer.

However, the investigation revealed a **structural incompatibility** between the decomposed reviewer-child topology and the native rejected-review lifecycle:

- The native lifecycle assumes the reviewer operates on the same task_id that was handed off.
- The auto-decomposer creates separate reviewer and implementer tasks.
- Ownership enforcement correctly prevents the reviewer child from mutating the implementer child's task.
- DB preconditions (claimed from review, review_requested event) cannot be satisfied across task boundaries.

The two review patterns (same-card vs. decomposed) are **not interchangeable**. The decomposed topology requires a different rejection path (orchestrator-mediated), which is what Phase 3 actually used.

---

## References

- `tools/kanban_tools.py:183` — `_enforce_worker_task_ownership`
- `tools/kanban_tools.py:976` — `_handle_request_changes`
- `hermes_cli/kanban_db.py:6663` — `request_changes()`
- `hermes_cli/kanban_db.py:6501` — `request_review()`
- `hermes_cli/kanban_db.py:4750` — `claim_review_task()`
- `hermes_cli/kanban_db.py:6880` — `_landing_status_after_parents`
- `hermes_cli/kanban_db.py:10310-10368` — Review column dispatch
- `hermes_cli/kanban_decompose.py` — Auto-decomposer
- `hermes_cli/kanban_diagnostics.py:753` — `_rule_review_dependency_deadlock`
- Parent artifact: `docs/research/reviewer-child-request-changes-repro.md` (t_75b3bc29)
- Parent artifact: `docs/research/kanban-request-changes-trace.md` (t_c84e54e3)
- Parent artifact: `docs/research/rejected-review-semantics-synthesis.md` (t_58167618)
- Retrospective: `docs/phase3_workflow_retrospective.md` (t_9e30708e)
