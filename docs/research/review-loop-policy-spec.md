# Review-Loop Observability and Optional Limits — Policy Specification

**Status:** Approved for implementation
**Scope:** Hermes Agent kanban system — review cycles (review → request_changes → re-review)
**Date:** 2026-08-31
**Source analysis:** `docs/research/review-loop-risk-analysis.md`, `docs/research/review-loop-handling-findings.md`

---

## 1. Purpose and Design Posture

This spec defines the observability signals and optional limits for repeated review cycles. The governing posture is:

> **Preserve unlimited review cycling by default.** Review cycling is a healthy, expected part of the workflow. Automated limits are opt-in and evidence-driven, not preemptive.

The system currently has NO automated circuit breaker for review cycles. This spec adds visibility (metrics, warnings) and an optional hard limit that defaults to OFF.

---

## 2. Default Behavior

| Aspect | Policy |
|--------|--------|
| Cycle limit | **Unlimited** — no automated cap on the number of review cycles |
| Circuit breaker | **None** — review transitions do not trip `consecutive_failures` or `block_recurrences` |
| Task status | Task remains in `review` → `ready`/`todo` → `review` loop until `kanban_complete` or human intervention |
| Reviewer engagement | Each cycle requires active reviewer re-engage (natural brake) |
| Per-cycle runtime | Capped by existing `max_runtime_seconds` (per-run, not per-task) |

**Invariant:** Under default configuration, a task can cycle through review indefinitely without any automated block, triage, or escalation. This preserves the current design philosophy that "review is not a block."

---

## 3. Metrics Emitted

### 3.1 `review_rounds` (primary metric)

- **Definition:** Count of `changes_requested` events for a given `task_id`.
- **Computation:** Dynamic — `SELECT COUNT(*) FROM task_events WHERE task_id = ? AND kind = 'changes_requested'`. No schema migration required.
- **Exposure:** Surfaced in `kanban_show` output as a top-level integer field.
- **Lifecycle:** Increments by 1 each time `request_changes()` is called on the task.

### 3.2 Per-round timestamps

- **Signal:** Each `changes_requested` event already persists `{reason, implementer, reviewer, status, timestamp}` in the event payload.
- **Derived metric:** Time-between-rounds = `timestamp(changes_requested[n]) - timestamp(changes_requested[n-1])`. Computable from event history, not stored separately.

### 3.3 Total elapsed time

- **Definition:** `now() - timestamp(first review_requested event)` for the task.
- **Exposure:** Surfaced in `kanban_show` as `review_elapsed_seconds` (integer, computed on read).

### 3.4 Event log

All existing event types remain unchanged. One new event type is added (see §4.2).

---

## 4. Warning Policy

### 4.1 When warnings emit

A warning is emitted when a task's `review_rounds` count reaches a configurable threshold.

| Condition | Behavior |
|-----------|----------|
| `review_rounds < threshold` | No warning |
| `review_rounds >= threshold` | Emit `review_round_warning` event (once per threshold crossing) |

**Threshold crossing semantics:** The warning fires on the round that reaches the threshold, not on every subsequent round. Example: with threshold=3, the warning fires at round 3 only. If the threshold is later lowered to 2, the warning fires on the next round that crosses the new threshold.

### 4.2 Warning event schema

```json
{
  "kind": "review_round_warning",
  "task_id": "<task_id>",
  "payload": {
    "review_rounds": 3,
    "message": "This task is on review round 3. Consider escalating to a human reviewer."
  }
}
```

- **Persistence:** Written to `task_events` table (visible in task history / `kanban_show`).
- **Effect:** Informational only. Does NOT block, triage, or change task status.
- **Delivery:** Visible in `kanban_show` output and task event stream. No separate notification channel.

### 4.3 How N is determined

| Mechanism | Default | Configurable | Scope |
|-----------|---------|--------------|-------|
| `kanban.review_round_warning_threshold` | **3** | Yes | Global (all boards) |

- **Fixed default:** 3 rounds. Chosen because (a) it exceeds the typical 1-2 round review cycle for straightforward tasks, and (b) it aligns with the `sdlc-review` skill's lens variation (Round 3+ uses the "Contract" lens).
- **Configurability:** Operators can lower it (for aggressive early warning) or raise it (to reduce noise). Setting it to 0 disables warnings entirely.
- **Not evidence-driven:** The default is a fixed constant, not dynamically adjusted. Rationale: warning thresholds are a policy choice, not a statistical inference.

---

## 5. Hard Limit Policy

### 5.1 Existence and default

A hard limit **exists as an optional mechanism** but is **disabled by default**.

| Config key | Default | Meaning |
|------------|---------|---------|
| `kanban.review_round_limit` | `NULL` | Unlimited — no hard cap |

### 5.2 Activation conditions

The hard limit activates ONLY when:

1. `kanban.review_round_limit` is set to a positive integer (e.g., `5`), AND
2. A task's `review_rounds` count reaches that integer.

When both conditions are met, the task is **auto-blocked** with:
- `block_kind`: `"review_loop_detected"`
- `block_reason`: `"Task reached review round limit (N). Manual intervention required."`
- Task status: `blocked` (not `triage` — this is a known pattern, not an anomaly)

### 5.3 Behavior after block

- The task enters the `blocked` column.
- A human operator must unblock (after investigating the loop cause).
- Unblocking resets `review_rounds` to 0 (the count is event-based; clearing events is NOT required — the operator can reset via a dedicated `reset_review_rounds` action or the count can continue from where it was; this is an implementation detail).
- The `block_recurrences` counter does NOT increment for `review_loop_detected` blocks (review is not a block-loop pattern).

### 5.4 Why the hard limit is opt-in

- **False positive risk:** Some tasks legitimately need 4+ review rounds (complex features, security-sensitive work, ambiguous requirements).
- **Design philosophy:** The current system deliberately treats review cycling as healthy. Adding a hard limit without evidence of harm would violate the principle of minimal intervention.
- **Evidence trigger:** Operators should enable this limit only after metrics show a pattern of tasks cycling beyond N rounds without progress.

---

## 6. Configuration Interface

### 6.1 Config keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `kanban.review_round_warning_threshold` | `int` | `3` | Emit warning when `review_rounds >= this value`. Set to 0 to disable warnings. |
| `kanban.review_round_limit` | `int \| NULL` | `NULL` | Hard limit on review rounds. When reached, task is auto-blocked with `review_loop_detected`. NULL = unlimited. |

### 6.2 Exposure mechanism

- **Primary:** Config file (`config_defaults.py` / `config.yaml`) — same mechanism as `kanban.failure_limit`, `kanban.review_dispatch`, etc.
- **Override:** Environment variable `HERMES_KANBAN_REVIEW_ROUND_WARNING_THRESHOLD` and `HERMES_KANBAN_REVIEW_ROUND_LIMIT` (matching the existing env var pattern for kanban config).
- **Per-board:** Not supported in v1. Global only. (Per-board scoping can be added if needed without breaking the global default.)

### 6.3 Validation

| Value | Behavior |
|-------|----------|
| `review_round_warning_threshold = 0` | Warnings disabled |
| `review_round_warning_threshold >= 1` | Warning fires at that round |
| `review_round_limit = NULL` | Unlimited (default) |
| `review_round_limit = 1` | Task blocked after first `request_changes` (aggressive; not recommended) |
| `review_round_limit >= 2` | Task blocked at that round |

Invalid values (negative integers) are rejected at config load time with a clear error message.

---

## 7. Acceptance Criteria

### 7.1 Default behavior preservation

| # | Criterion | Verification |
|---|-----------|--------------|
| AC-1 | A task cycling through review 1-2 times produces NO warning and NO block | Integration test: run 2 review cycles, assert no `review_round_warning` event, task status is `ready`/`todo` after each reopen |
| AC-2 | A task cycling indefinitely with default config (`review_round_limit=NULL`) never auto-blocks | Integration test: run 10 review cycles, assert task never enters `blocked` status |
| AC-3 | `kanban_show` output includes `review_rounds` count | Unit test: call `kanban_show` on a task with 2 `changes_requested` events, assert `review_rounds == 2` |
| AC-4 | `kanban_show` output includes `review_elapsed_seconds` | Unit test: assert field is present and is a positive integer |

### 7.2 Warning behavior

| # | Criterion | Verification |
|---|-----------|--------------|
| AC-5 | Warning fires at exactly round 3 with default threshold | Integration test: run 3 review cycles, assert `review_round_warning` event exists with `review_rounds == 3` |
| AC-6 | Warning does NOT fire at round 2 | Integration test: run 2 review cycles, assert no `review_round_warning` event |
| AC-7 | Warning threshold is configurable | Unit test: set `review_round_round_warning_threshold=2`, run 2 cycles, assert warning fires at round 2 |
| AC-8 | Warning fires once per threshold crossing | Integration test: run 5 cycles with threshold=3, assert exactly 1 `review_round_warning` event |

### 7.3 Hard limit behavior

| # | Criterion | Verification |
|---|-----------|--------------|
| AC-9 | With `review_round_limit=5`, task auto-blocks at round 5 | Integration test: set limit=5, run 5 cycles, assert task status is `blocked` with `block_kind == "review_loop_detected"` |
| AC-10 | With `review_round_limit=5`, task does NOT block at round 4 | Integration test: set limit=5, run 4 cycles, assert task is NOT blocked |
| AC-11 | `review_round_limit=NULL` means unlimited | Integration test: run 10 cycles with NULL limit, assert no block |

### 7.4 Non-interference

| # | Criterion | Verification |
|---|-----------|--------------|
| AC-12 | `consecutive_failures` is NOT incremented by review cycles | Unit test: run 3 review cycles, assert `consecutive_failures` remains 0 |
| AC-13 | `block_recurrences` is NOT incremented by `review_loop_detected` blocks | Unit test: trigger a `review_loop_detected` block, unblock, re-block, assert `block_recurrences` does not increment |
| AC-14 | Existing tests pass without modification | Run `pytest tests/test_kanban_review_lifecycle.py tests/test_kanban_review_surfaces.py` — all green |
| AC-15 | `sdlc-review` skill's lens variation is unaffected | The skill counts `changes_requested` events independently; platform-level `review_rounds` does not conflict |

### 7.5 Configuration

| # | Criterion | Verification |
|---|-----------|--------------|
| AC-16 | Config keys exist in `config_defaults.py` | Unit test: assert `kanban.review_round_warning_threshold` defaults to 3, `kanban.review_round_limit` defaults to NULL |
| AC-17 | Env vars override config | Unit test: set `HERMES_KANBAN_REVIEW_ROUND_LIMIT=4`, assert resolved value is 4 |
| AC-18 | Invalid values rejected | Unit test: set `review_round_limit=-1`, assert config load raises clear error |

---

## 8. Non-Goals (Out of Scope)

1. **Per-board configuration** — v1 is global only.
2. **Automatic threshold tuning** — N is operator-chosen, not ML-driven.
3. **Warning delivery via external channels** (Telegram, email) — warnings are in-task-events only.
4. **Soft throttling / cooldown** — rejected for now; revisit if metrics show need.
5. **Review-loop detection for non-review block cycles** — this spec is scoped to review transitions only.
6. **Schema migration for `review_rounds` column** — the count is derived from events, not stored.

---

## 9. Implementation Notes

### 9.1 Where to compute `review_rounds`

- In `kanban_show()` — add a dynamic count query.
- In `reopen_review_task()` — after emitting `review_reopened`, count events and emit `review_round_warning` if threshold reached.
- In `request_review()` — after accepting the review request, check if `review_rounds >= review_round_limit` and auto-block if so.

### 9.2 Event type registration

Add `"review_round_warning"` to the event type enum/validation in `kanban_db.py`.

### 9.3 Diagnostic rule

Add a diagnostic rule in `kanban_diagnostics.py` that flags tasks with `review_rounds > 3` as `review_stuck_candidate` (severity: warning). This is separate from the runtime warning event — it's a board-level diagnostic for operators.

---

## 10. When to Revisit

Revisit this policy if:

- Operators report tasks stuck in review for >5 cycles with default config.
- Metrics show a pattern of high-round-count tasks consuming disproportionate resources.
- The `sdlc-review` skill's lens variation proves insufficient for decorrelation.
- A hard limit becomes necessary — at which point `kanban.review_round_limit` can be set globally without code changes.
