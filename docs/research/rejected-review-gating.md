# Dependency Gating Around Rejected Reviews

Research artifact for kanban task `t_822c1089`.

**Scope:** Hermes Kanban board (`hermes_cli/kanban_db.py`, `gateway/kanban_watchers.py`, `tools/kanban_tools.py`, config).

**Question:** How does a rejected review (`kanban_request_changes`) gate downstream / dependent work items?

---

## 1. State Machine

```
running ──request_review()──► review ──claim_review_task()──► running
                                                              │
                                   request_changes() ◄────────┘
                                        │
                                        ▼
                              ┌─ ready   (all parents done)
                              └─ todo    (parents not done yet)
```

The reviewer calls `kanban_request_changes(reason=...)`. The DB function `request_changes()` (`kanban_db.py:6663`) closes the active review run and lands the task back in the implementation lane.

---

## 2. Hard Preconditions (request_changes refuses otherwise)

`request_changes()` returns `(False, diagnostic)` when any of these fail:

| Condition | Check | Error |
|---|---|---|
| Task is in an active run | `status == 'running' AND current_run_id IS NOT NULL` | `"task is not in an active review run"` |
| Run was claimed from `review` | Latest `claimed` event has `source_status == 'review'` | `"active run was not claimed from review"` |
| Prior `review_requested` event exists | Lookup latest event of that kind | `"no prior review_requested event"` |
| Implementer provenance is valid | `review_requested` payload has a non-empty `implementer` | `"review handoff has no valid implementer provenance"` |
| Run ID matches | `expected_run_id == current_run_id` | `"run_id mismatch"` |

All checks happen inside a single `write_txn` so the handoff is atomic.

---

## 3. The Gate: Parent-Completion Re-gating

After closing the review run, `request_changes()` calls `_landing_status_after_parents(conn, task_id)` at `kanban_db.py:6880`:

```python
def _landing_status_after_parents(conn, task_id):
    """Return 'todo' if any parent isn't 'done' yet, else 'ready'."""
    undone_parents = conn.execute("""
        SELECT 1 FROM task_links l
        JOIN tasks p ON p.id = l.parent_id
        WHERE l.child_id = ?
        AND p.status NOT IN ('done', 'archived') LIMIT 1
    """, (task_id,)).fetchone()
    return "todo" if undone_parents else "ready"
```

**This is the gate.** If any upstream parent task is still in progress (`ready`, `running`, `blocked`, etc.), the task lands in `todo` — NOT `ready`. The dispatcher will not spawn the implementer until `recompute_ready()` promotes it, which only happens when **every** parent reaches `done` or `archived`.

This is verified by the test `test_review_changes_reapply_parent_gate` (`test_kanban_review_lifecycle_complete.py:206`): a parent is reopened to `ready` after the task enters review; `request_changes` then lands the task in `todo`, not `ready`.

---

## 4. Reassign-to-Implementer

`request_changes()` reads the original implementer from the `review_requested` event payload and reassigns the task:

```python
implementer = requested_payload.get("implementer")
cur = conn.execute("""
    UPDATE tasks SET status = ?, assignee = COALESCE(?, assignee), ...
    WHERE id = ?
""", (new_status, implementer, task_id, ...))
```

The `changes_requested` event payload records both `implementer` and `reviewer` for audit and for notifier routing.

---

## 5. Failure Counter Preservation (Circuit Breaker Interaction)

`request_changes` **deliberately preserves** `consecutive_failures` (neither reset nor incremented). Review transitions are not evidence the pathology cleared. Only `complete_task`'s success path resets the counter (`test_review_transitions_preserve_consecutive_failures`, `test_kanban_review_lifecycle_complete.py:647`).

Because the counter survives review cycles, a task that crashes repeatedly across multiple review rounds accumulates failures and eventually trips the circuit breaker via `_record_task_failure`, landing in `blocked` with a `status` event. This prevents infinite review loops.

`recompute_ready()` respects the circuit breaker: it will not promote a `todo` task whose `consecutive_failures >= effective_limit` (`kanban_db.py:4589`).

---

## 6. Block-Loop Accounting

`request_changes` is **not a block** — it never touches `block_recurrences` / `block_kind`. Repeated review-rejection cycles do NOT count toward block-loop detection and will never route the task to `triage`. Contrast with `kanban_block`, which increments `block_recurrences` and trips at `BLOCK_RECURRENCE_LIMIT`.

---

## 7. Dispatch of Review

When `review_dispatch` is enabled (default `True`, config key `kanban.review_dispatch`):

1. The dispatcher's `dispatch_once()` loop finds tasks in `review` status with an assignee matching a real profile.
2. It calls `claim_review_task()` (`kanban_db.py:4750`), which transitions `review → running` and creates a fresh `task_runs` row, re-checking `_parents_satisfied` first.
3. The reviewer worker loads the bundled `sdlc-review` skill, which instructs it to approve (`kanban_complete`), request changes (`kanban_request_changes`), or escalate (`kanban_block`).

If `review_dispatch` is disabled, tasks in `review` are never auto-claimed; a human must pull them from the dashboard.

---

## 8. Notification / Wake

`changes_requested` is one of the `_WAKE_KINDS` in `gateway/kanban_watchers.py:842`. When the notifier sees a `changes_requested` event:

- **Push-capable adapters (Telegram, etc.):** sends `"🛑 Kanban {id} review requested changes/BLOCK: {reason} — reviewer @{reviewer} → implementer @{implementer}"` to subscribers.
- **All adapters:** delivers a wake turn to the creator session, including the reviewer's reason and guidance text.

---

## 9. Same-Card vs. Downstream Card Workflow

Two orthogonal patterns exist (documented in `kanban-worker-lanes.md`):

| Pattern | Mechanism | Gate for downstream |
|---|---|---|
| Same-card review | `kanban_request_review` on the implementer's own card | `request_changes` returns the same card to the implementer; re-review is routed to the same reviewer via provenance on `changes_requested` event |
| Pre-created downstream card | `kanban_create` with `parents=[impl_id]` | Child stays in `todo` until parent reaches `done`/`archived` (`_parents_satisfied` in `claim_task`, `recompute_ready`, `complete_task`) |

For the downstream card pattern, `kanban_complete` on the implementation parent is what releases the child — NOT `kanban_request_review`. The parent must be `done`/`archived`.

---

## 10. Configuration Summary

| Key | Location | Default | Effect |
|---|---|---|---|
| `kanban.review_dispatch` | `config.yaml` / `config_defaults.py` | `True` | Auto-claim review tasks and spawn reviewer workers |
| `kanban.failure_limit` | `config.yaml` | `2` | Circuit breaker trips after N consecutive failures |
| `kanban.max_in_progress` | `config.yaml` | 1 | Limits concurrent workers |

---

## References

- `hermes_cli/kanban_db.py` — `request_changes` (L6663), `_landing_status_after_parents` (L6880), `request_review` (L6501), `claim_review_task` (L4750), `recompute_ready` (L4521), `_resume_status_from_events` (L4492), `_parents_satisfied` (L4617), `unblock_task` (L6901), `complete_task` (L5363)
- `tools/kanban_tools.py` — `_handle_request_changes` (L976), `_handle_request_review` (L900+)
- `gateway/kanban_watchers.py` — notifier wake on `changes_requested` (L655, L842)
- `config_defaults.py` — `review_dispatch` default (L2824)
- `tests/hermes_cli/test_kanban_review_lifecycle_complete.py` — `test_review_changes_reapply_parent_gate` (L206), `test_review_transitions_preserve_consecutive_failures` (L647)
- `tests/gateway/test_kanban_changes_requested_notifier.py` — notification content tests
- `skills/devops/sdlc-review/SKILL.md` — reviewer workflow
