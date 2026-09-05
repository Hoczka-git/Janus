# Mechanical Verification: Decomposed Reviewer -> kanban_request_changes

## Question
Can a separate reviewer child task, created by the auto-decomposer, successfully invoke `kanban_request_changes` to return its corresponding implementer child to rework?

## Answer: NO — structurally impossible

A decomposed reviewer child **cannot** invoke `kanban_request_changes` on its implementer. The call fails at multiple independent gates before reaching the DB, and even if all gates were bypassed, it would mutate the wrong task.

## Call Chain Trace (tools/kanban_tools.py → hermes_cli/kanban_db.py)

### Gate 1: `_reject_delegated_child_mutation` (line 978)
- If the reviewer runs as a `delegate_task` child → rejected immediately for **all** kanban mutations
- Dispatcher-spawned worker → passes through

### Gate 2: `_default_task_id` (line 981, helper at line 142)
Resolves the target `task_id`:
- Explicit arg → uses it (e.g., implementer's task_id)
- No arg → falls back to `HERMES_KANBAN_TASK` env var (reviewer's own task_id)

### Gate 3: `_enforce_worker_task_ownership` (line 986, definition at line 183)
- Checks `HERMES_KANBAN_TASK` env == `tid`
- If `tid != HERMES_KANBAN_TASK`: **BLOCKED** with tool error
- Runtime-verified: `_enforce_worker_task_ownership("t_implementer_child")` returns error string when `HERMES_KANBAN_TASK = "t_reviewer_child"`

### Gate 4: `_worker_run_id` (line 1001, definition at line 156)
- Checks `HERMES_KANBAN_TASK == tid`
- Returns `None` for cross-task calls → `expected_run_id=None` → `request_changes` precondition 6c may fail

### Gate 5: `kb.request_changes()` DB preconditions (hermes_cli/kanban_db.py:6663)
Six preconditions, all scoped to a single `task_id`:
1. Task exists
2. `status='running'` with active `current_run_id`
3. `expected_run_id` matches `current_run_id` (if provided)
4. Latest claimed event: `source_status='review'`
5. A prior `review_requested` event exists on **this** task_id
6. `review_requested` payload contains valid `implementer`

## Two Topologies — Not Interchangeable

### Same-task topology (native lifecycle)
```
request_review(task) → claim_review_task(task) [source_status='review']
  → request_changes(task) → reassigns task to implementer
```
All events, claims, and preconditions scoped to ONE task_id. Works correctly.

### Decomposed topology (auto-decomposer)
```
Reviewer task R (HERMES_KANBAN_TASK=R)
Implementer task I (separate task_id)
```
- Reviewer scoped to R via `HERMES_KANBAN_TASK=R`
- Ownership enforcement blocks mutation of I
- DB preconditions (review_requested event, claimed-from-review) cannot cross task boundaries
- Even if bypassed: `request_changes` updates WHERE `id=task_id` — the wrong task

## Phase 3 Root Cause

The Phase 3 incident was **NOT** purely a reviewer tool-selection error. The reviewer (t_5dcad317) called `kanban_complete` instead of `kanban_request_changes`, but the deeper cause is structural: the decomposed reviewer-child topology is fundamentally incompatible with the native rejected-review lifecycle.

The reviewer never successfully attempted `kanban_request_changes` because:
1. The ownership gate would have blocked it
2. The DB preconditions cannot be satisfied across task boundaries
3. The native lifecycle assumes the reviewer operates on the same task_id it was handed off

## Verification Method

Runtime Python verification confirmed `_enforce_worker_task_ownership` blocks cross-task mutation:
```
HERMES_KANBAN_TASK = "t_reviewer_child"
_enforce_worker_task_ownership("t_implementer_child")
→ '{"error": "worker is scoped to task t_reviewer_child; refusing to mutate t_implementer_child..."}'
```

DB inspection confirmed no `review_requested` events exist in the kanban.db — the working tasks are all in `done` status with no review topology active.