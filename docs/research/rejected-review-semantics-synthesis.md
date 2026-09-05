# Rejected-Review Semantics and Dependency Behavior — Synthesis

**Task:** t_58167618 — Synthesize rejected-review semantics and dependency behavior
**Date:** 2026-08-31
**Author:** researcher (synthesis of t_49ce1f1a, t_822c1089)

---

## 1. What the Rejected-Review Workflow Does

The rejected-review workflow is the mechanism by which a reviewer returns an implemented task to the implementer for rework. It is **not** a standalone workflow definition — there is no YAML pipeline, no named workflow file, and no explicit "rejected-review" process document in the repository. Instead, it is an emergent behavior composed of:

- The `kanban_request_changes(reason=...)` tool call (the rejection action)
- The `_landing_status_after_parents` gate (determines where the task lands)
- The `changes_requested` event (audit trail + notifier wake)
- The reviewer provenance system (auto-routes re-reviews to the same reviewer)

The workflow closes the active review run and returns the task to the implementation lane, reassigning it to the original implementer (captured from the `review_requested` event payload).

---

## 2. When and How It Is Triggered

### Trigger conditions

A reviewer calls `kanban_request_changes(reason=...)` when inspection finds the implementation insufficient. The function enforces five hard preconditions — all must pass inside a single `write_txn`:

| Condition | Check | Error on failure |
|---|---|---|
| Task is in an active run | `status == 'running' AND current_run_id IS NOT NULL` | `"task is not in an active review run"` |
| Run was claimed from `review` | Latest `claimed` event has `source_status == 'review'` | `"active run was not claimed from review"` |
| Prior `review_requested` event exists | Lookup latest event of that kind | `"no prior review_requested event"` |
| Implementer provenance is valid | `review_requested` payload has non-empty `implementer` | `"review handoff has no valid implementer provenance"` |
| Run ID matches | `expected_run_id == current_run_id` | `"run_id mismatch"` |

### How review reaches the reviewer

When `kanban.review_dispatch` is enabled (default `True`):
1. The dispatcher's `dispatch_once()` finds tasks in `review` status with an assignee matching a real profile
2. `claim_review_task()` transitions `review → running`, re-checking `_parents_satisfied` first
3. The reviewer worker loads the `sdlc-review` skill, which instructs: approve (`kanban_complete`), request changes (`kanban_request_changes`), or escalate (`kanban_block`)

If `review_dispatch` is disabled, tasks in `review` are never auto-claimed; a human must pull them from the dashboard.

---

## 3. What States or Actions It Produces

### State transition

```
running ──request_review()──► review ──claim_review_task()──► running
                                                              │
                                   request_changes() ◄────────┘
                                        │
                                        ▼
                              ┌─ ready   (all parents done)
                              └─ todo    (parents not done yet)
```

### Actions produced

1. **Review run closed** — the active `task_runs` row is finalized
2. **Task reassigned** — `assignee` set to the original implementer (from `review_requested` payload)
3. **Task re-gated** — `_landing_status_after_parents` determines `ready` vs `todo`
4. **`changes_requested` event emitted** — records both `implementer` and `reviewer` for audit
5. **Notifier wake** — `changes_requested` is a `_WAKE_KINDS` event:
   - Push-capable adapters (Telegram): sends `🛑 Kanban {id} review requested changes/BLOCK: {reason} — reviewer @{reviewer} → implementer @{implementer}`
   - All adapters: delivers a wake turn to the creator session with reviewer's reason + guidance
6. **`consecutive_failures` preserved** — neither reset nor incremented (review transitions are not evidence the pathology cleared)

---

## 4. How It Gates or Influences Dependent Work

### Primary gate: parent-completion re-gating

`_landing_status_after_parents(conn, task_id)` is the critical gate:

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

If any upstream parent is still in progress (`ready`, `running`, `blocked`, etc.), the task lands in `todo` — NOT `ready`. The dispatcher will not spawn the implementer until `recompute_ready()` promotes it, which only happens when **every** parent reaches `done` or `archived`.

**Verified by:** `test_review_changes_reapply_parent_gate` (`test_kanban_review_lifecycle_complete.py:206`) — a parent is reopened to `ready` after the task enters review; `request_changes` then lands the task in `todo`, not `ready`.

### Circuit breaker interaction

`consecutive_failures` survives review cycles. A task that crashes repeatedly across multiple review rounds accumulates failures and eventually trips the circuit breaker via `_record_task_failure`, landing in `blocked`. `recompute_ready()` respects this: it will not promote a `todo` task whose `consecutive_failures >= effective_limit`.

**Verified by:** `test_review_transitions_preserve_consecutive_failures` (`test_kanban_review_lifecycle_complete.py:647`).

### Block-loop accounting

`request_changes` is **not a block** — it never touches `block_recurrences` / `block_kind`. Repeated review-rejection cycles do NOT count toward block-loop detection and will never route the task to `triage`. Contrast with `kanban_block`, which increments `block_recurrences` and trips at `BLOCK_RECURRENCE_LIMIT`.

### Reviewer provenance

The `changes_requested` event payload records `reviewer`. When the implementer re-requests review, the dispatcher auto-routes the re-review to the same reviewer profile (via provenance on the `changes_requested` event).

### Two orthogonal patterns

| Pattern | Mechanism | Gate for downstream |
|---|---|---|
| Same-card review | `kanban_request_review` on implementer's own card | `request_changes` returns the same card to implementer; re-review routed to same reviewer via provenance |
| Pre-created downstream card | `kanban_create` with `parents=[impl_id]` | Child stays in `todo` until parent reaches `done`/`archived` (`_parents_satisfied` in `claim_task`, `recompute_ready`, `complete_task`) |

For the downstream card pattern, `kanban_complete` on the implementation parent is what releases the child — NOT `kanban_request_review`. The parent must be `done`/`archived`.

---

## 5. Ambiguities, Inconsistencies, and Gaps

### A1: No explicit rejected-review workflow definition

The repository contains **zero** workflow, pipeline, or process definitions for "rejected-review", "review rejection", "review-rejection", or "request_changes". The only "review" references are:
- CI workflow (`.github/workflows/ci.yml`)
- Input validation tests (`test_task_state_progress.py`, `test_fitness.py`)
- A "Code review" calendar test fixture
- Task metadata comments
- Goal/task domain models (`GoalReview`, `WeeklyReview`)

None of these implement a rejected-review workflow. The behavior is entirely emergent from the `kanban_request_changes` function and its interaction with the dispatcher.

### A2: Reviewer SOUL.md is incomplete

The reviewer profile SOUL.md ends at line 103 with no verdict section. Verdict guidance (approve / request changes / block, what the summary must cite) lives in the `sdlc-review` skill, not in the profile doc. A reviewer reading only the SOUL.md would not find the verdict standard.

### A3: Implementer handoff evidence is under-specified

The implementer SOUL.md names "Hand off for review" as the final step but does not define the handoff evidence shape. There is no requirement to attest to commit state, changed file status (committed vs uncommitted), or verification command exit code. This contributed to the Phase 3 close-out failure (F1, F3 in the retrospective) where uncommitted work was submitted for review.

### A4: No mechanical durability gate before review dispatch

The workflow trusts the implementer's self-report. `kanban_request_review` carries summary + metadata but no git-state attestation. The board accepts the transition based on the call, not on an independent verification of commit state. The retrospective explicitly notes this as the highest-leverage architectural change if the constraint were lifted.

### A5: `request_changes` vs `kanban_block` — overlapping escalation paths

Both `request_changes` and `kanban_block` can be called from the review lane, but they have different accounting:
- `request_changes`: not a block, no block-loop counting, preserves `consecutive_failures`
- `kanban_block`: increments `block_recurrences`, trips at `BLOCK_RECURRENCE_LIMIT`, routes to `triage`

The `sdlc-review` skill instructs reviewers to use `kanban_block` only for genuine external escalation. However, the distinction is not mechanically enforced — a reviewer could repeatedly call `request_changes` without tripping any circuit breaker (since `block_recurrences` is unaffected), while the task accumulates `consecutive_failures` only if it crashes (not if it is rejected). This means a task could theoretically cycle through review indefinitely without tripping any limit if the implementer keeps producing non-crashing but insufficient work.

### A6: Retrospective decomposed with no body

The Phase 3 retrospective root task (t_1a5efa07) was created with no body and no triaged step. Decomposition happened within 33 seconds of creation. Scope and acceptance criteria are defined only implicitly by child task titles. This is a process quality gap — the rejected-review synthesis (this task) shares the same decomposition pattern.

### A7: Configuration not surfaced in profile docs

No profile SOUL.md mentions that `review_dispatch` is automated, how `failure_limit` behaves, or what `max_in_progress_per_profile` means. This operational knowledge lives only in `config.yaml` and `config_defaults.py`.

---

## 6. Configuration Reference

| Key | Location | Default | Effect |
|---|---|---|---|
| `kanban.review_dispatch` | `config.yaml` / `config_defaults.py` | `True` | Auto-claim review tasks and spawn reviewer workers |
| `kanban.failure_limit` | `config.yaml` | `2` | Circuit breaker trips after N consecutive failures |
| `kanban.max_in_progress` | `config.yaml` | `1` | Limits concurrent workers |

---

## References

- `hermes_cli/kanban_db.py` — `request_changes` (L6663), `_landing_status_after_parents` (L6880), `request_review` (L6501), `claim_review_task` (L4750), `recompute_ready` (L4521), `_resume_status_from_events` (L4492), `_parents_satisfied` (L4617), `unblock_task` (L6901), `complete_task` (L5363)
- `tools/kanban_tools.py` — `_handle_request_changes` (L976), `_handle_request_review` (L900+)
- `gateway/kanban_watchers.py` — notifier wake on `changes_requested` (L655, L842)
- `config_defaults.py` — `review_dispatch` default (L2824)
- `tests/hermes_cli/test_kanban_review_lifecycle_complete.py` — `test_review_changes_reapply_parent_gate` (L206), `test_review_transitions_preserve_consecutive_failures` (L647)
- `tests/gateway/test_kanban_changes_requested_notifier.py` — notification content tests
- `skills/devops/sdlc-review/SKILL.md` — reviewer workflow
- Parent task artifact: `docs/research/rejected-review-gating.md` (t_822c1089)
