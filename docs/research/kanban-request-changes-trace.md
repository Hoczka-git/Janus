# Trace: `kanban_request_changes` Tool Wrapper & `kanban_db.request_changes()`

## Call Chain Overview

```
Model calls kanban_request_changes(task_id=?, reason, board=?)
        |
        v
KANBAN_REQUEST_CHANGES_SCHEMA          tools/kanban_tools.py:1951
        |
        v
_handle_request_changes(args, **kw)     tools/kanban_tools.py:976
        |
        v
kb.request_changes(conn, tid, reason, expected_run_id)
                                       hermes_cli/kanban_db.py:6663
        |
        v
_end_run(...)        hermes_cli/kanban_db.py:4335
_append_event(...)   hermes_cli/kanban_db.py:4311
```

---

## 1. Tool Wrapper: `_handle_request_changes`

**File:** `/home/dan11hermes/.hermes/hermes-agent/tools/kanban_tools.py`
**Lines:** 976–1021

### Schema (`KANBAN_REQUEST_CHANGES_SCHEMA`, line 1951)

```python
{
    "name": "kanban_request_changes",
    "parameters": {
        "properties": {
            "task_id": {"type": "string", "description": _DESC_TASK_ID_DEFAULT},
            "reason":  {"type": "string", "description": "Specific, actionable changes..."},
            "board":  _board_schema_prop(),
        },
        "required": ["reason"],  # task_id is OPTIONAL
    },
}
```

**`task_id` is optional** — defaults to `HERMES_KANBAN_TASK` from the environment
when the worker was spawned by the dispatcher.

### Handler logic (lines 976–1021)

| Step | Code | Purpose |
|------|------|---------|
| 1 | `_reject_delegated_child_mutation("kanban_request_changes")` | Deny Kanban mutations from `delegate_task` children (line 85) — they may not complete/block/comment directly |
| 2 | `_default_task_id(args.get("task_id"))` | Resolve task_id from arg or fall back to `HERMES_KANBAN_TASK` env var (line 142). In delegated child context, returns `None` to prevent inheritance. |
| 3 | `_enforce_worker_task_ownership(tid)` | If `HERMES_KANBAN_TASK` is set and `tid != HERMES_KANBAN_TASK`, refuse mutation with error (line 183). Orchestrators (no task-scope) bypass this. |
| 4 | `redact_sensitive_text(str(reason), force=True)` | Strip secrets/tokens from the reason string before persistence |
| 5 | `_connect(board=board)` | Obtain DB connection (line 215) |
| 6 | `kb.request_changes(conn, tid, reason=reason, expected_run_id=_worker_run_id(tid))` | Core mutation (see section 2) |
| 7 | On success: `_ok(task_id, run_id, status, implementer)` | Returns landing status + new run id + the implementer it was routed to |

### `_worker_run_id(tid)` (line 156)

Returns `HERMES_KANBAN_RUN_ID` only when `HERMES_KANBAN_TASK == tid`; otherwise `None`.
This is passed as `expected_run_id` to detect stale runs.

---

## 2. DB Method: `kanban_db.request_changes()`

**File:** `/home/dan11hermes/.hermes/hermes-agent/hermes_cli/kanban_db.py`
**Lines:** 6663–6779

**Signature:**
```python
def request_changes(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    reason: str,
    expected_run_id: Optional[int] = None,
) -> tuple[bool, Optional[str]]:
```

### Preconditions (all inside `write_txn(conn)`)

| # | Check | SQL / Condition | Error message |
|---|-------|-----------------|---------------|
| 1 | Task exists | `SELECT status, assignee, current_run_id FROM tasks WHERE id = ?` | `"task not found"` |
| 2 | Active review run | `status == "running"` AND `current_run_id is not None` | `"task is not in an active review run"` |
| 3 | Run id match | `expected_run_id` is `None` OR `current_run_id == expected_run_id` | `"run_id mismatch"` |
| 4 | Claimed from review | Look up latest `claimed` event for `current_run_id`; check `payload.source_status == "review"` | `"active run was not claimed from review"` |
| 5 | Prior handoff | Latest `review_requested` event exists for task_id | `"no prior review_requested event"` |
| 6 | Valid implementer provenance | `review_requested` payload has non-empty string `implementer` | `"review handoff has no valid implementer provenance"` |

### Actions on success

1. **Compute landing status** — `_landing_status_after_parents(conn, task_id)` (line 6880):
   - Returns `"ready"` if every parent is `done` or `archived`
   - Returns `"todo"` if any parent is still in progress

2. **Update task row**:
   ```sql
   UPDATE tasks
      SET status = ?,                          -- "ready" or "todo"
          assignee = COALESCE(?, assigner),     -- restore original implementer
          claim_lock = NULL,
          claim_expires = NULL,
          worker_pid = NULL
    WHERE id = ? AND status = 'running' AND current_run_id = ?
   ```
   Rowcount check: `!= 1` → `"task changed during review handoff"`

3. **End the review run** — `_end_run(conn, task_id, outcome="changes_requested", status=new_status, summary=reason)` (line 4335):
   - Sets run `ended_at`, `status`, `outcome`, clears `claim_lock`/`claim_expires`/`worker_pid`
   - Clears `tasks.current_run_id = NULL`

4. **Append audit event** — `_append_event(conn, task_id, "changes_requested", {reason, implementer, reviewer, status})` (line 4311)

### Return value

- `(True, implementer)` on success
- `(False, <diagnostic>)` on any precondition failure

### Side effects preserved

- **`consecutive_failures` counter is deliberately PRESERVED** (neither reset nor incremented). Review transitions are not evidence the pathology cleared — only `complete_task`'s success path resets the breaker counter (mirrors `unblock_task`, #35072).

---

## 3. CLI Handler: `_cmd_request_changes`

**File:** `/home/dan11hermes/.hermes/hermes-agent/hermes_cli/kanban.py`
**Lines:** 2572–2592

```python
def _cmd_request_changes(args: argparse.Namespace) -> int:
    tid = args.task_id
    reason = " ".join(args.reason).strip()
    with kb.connect_closing() as conn:
        ok, detail = kb.request_changes(
            conn, tid, reason=reason,
            expected_run_id=_worker_run_id_for(tid),
        )
```

- CLI `request-changes` subparser (line 721) requires `task_id` (positional) and `reason` (nargs="+")
- Delegates directly to `kb.request_changes`; no ownership check (CLI is trusted surface)

---

## 4. Answers to Specific Questions

### Where does `task_id` originate?

- **Model tool call**: optional kwarg `task_id` in `kanban_request_changes(...)`
- **Fallback**: `_default_task_id()` reads `HERMES_KANBAN_TASK` env var (set by dispatcher for worker processes)
- **CLI**: positional `args.task_id` (required)

### How is it passed to `request_changes()`?

As the first positional arg: `kb.request_changes(conn, tid, reason=..., expected_run_id=...)`

### Is it a single task_id or a pair (reviewer, implementer)?

**Single `task_id`.** The implementer is *recovered* from the most recent `review_requested` event's payload (`requested_payload["implementer"]`). The reviewer is derived from the task's current `assignee` (the profile that was assigned when the task entered `review`).

### Preconditions enforced

1. Task exists
2. Task is in `running` status with active `current_run_id`
3. Run id matches `expected_run_id` (if provided)
4. The active run was claimed from `review` status
5. A `review_requested` event exists
6. That event has a valid `implementer` provenance
7. Parent-completion re-gating via `_landing_status_after_parents`

### Additional guards

- **Delegate child rejection**: delegated `delegate_task` children cannot call this tool
- **Worker task ownership**: a worker scoped to `HERMES_KANBAN_TASK` cannot mutate a foreign task id
- **Secret redaction**: `redact_sensitive_text` (wrapper) + `redact_review_value` (DB method)
