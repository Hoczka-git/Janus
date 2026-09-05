# Review-Loop Handling and Metrics — Findings Summary

**Task:** Discover existing review-loop handling and metrics in the codebase
**Scope:** Hermes Agent kanban system — review cycles (review → request_changes → re-review)
**Date:** 2026-08-31

---

## Executive Summary

**There is NO automated pathological-loop handling for review cycles in the codebase. This is by design.** The system explicitly treats review cycling as a healthy, expected part of the workflow and deliberately excludes review transitions from all existing loop-detection and circuit-breaker mechanisms.

Two loop-detection systems exist, but neither applies to review:
1. **Block→unblock loop** (`block_recurrences` / `BLOCK_RECURRENCE_LIMIT`) — only counts re-blocks after unblock.
2. **Spawn/crash/timeout circuit breaker** (`consecutive_failures` / `failure_limit`) — only counts non-success worker outcomes.

A task can bounce between implementer and reviewer indefinitely without tripping any guard.

---

## 1. Existing Loop/Cycle Detection — What Exists and Why It Doesn't Cover Review

### 1.1 Block→Unblock Loop (`block_recurrences`)

- **File:** `hermes_cli/kanban_db.py:6257` (`block_task`)
- **Mechanism:** When a task is re-blocked for the SAME kind after a prior unblock, `block_recurrences` increments. At `BLOCK_RECURRENCE_LIMIT` (default: 2, line 134), the task routes to `triage` instead of `blocked` and emits a `block_loop_detected` event.
- **Why review is excluded:** Review transitions (`request_review`, `request_changes`, `reopen_review_task`) deliberately do NOT touch `block_recurrences` or `block_kind`. The docstrings explicitly state: "Deliberately does NOT touch `block_recurrences`/`block_kind`: review is not a block, so there is no loop counter to reset." (`reopen_review_task`, line 6971).

### 1.2 Consecutive Failures Circuit Breaker (`consecutive_failures`)

- **File:** `hermes_cli/kanban_db.py:9163` (`_record_task_failure`)
- **Mechanism:** Counts consecutive non-success outcomes (spawn_failed, crashed, timed_out). At the effective `failure_limit` (resolved from per-task `max_retries` → caller-supplied `failure_limit` → `DEFAULT_FAILURE_LIMIT` = 2), the task auto-blocks with `gave_up`.
- **Why review is excluded:** `request_changes()` (line 6742-6745) explicitly preserves `consecutive_failures` — "Review transitions are not evidence the pathology cleared — only complete_task's success path resets the breaker counter." Review success/failure is a quality signal, not a worker-health signal.

### 1.3 Dependency Graph Cycle Detection (`_would_cycle`)

- **File:** `hermes_cli/kanban_db.py:3871`
- **Mechanism:** Prevents adding a parent→child link that would create a cycle in the task graph.
- **Why review is unrelated:** This is about graph topology, not review lifecycle.

### 1.4 Decompose Review-Child Retry Limit

- **File:** `hermes_cli/kanban_decompose.py:442` (`_REVIEW_PROMPT_RETRY_LIMIT = 2`)
- **Mechanism:** Limits how many times the decomposer re-prompts the LLM to avoid creating review-style child tasks.
- **Why review is unrelated:** This limits decomposition behavior, not review cycles on an existing task.

---

## 2. Review-Related Metrics, Counters, Logs, Telemetry

### 2.1 What Exists

| Signal | Location | What it tracks |
|--------|----------|----------------|
| `changes_requested` events | `kanban_db.py:6767-6778` | Each review rejection persists `{reason, implementer, reviewer, status}` in the event payload. |
| `review_requested` events | `kanban_db.py:6649-6660` | Each review handoff persists `{summary, implementer, reviewer}`. |
| `review_reopened` events | `kanban_db.py:7021-7026` | Each review reopen persists `{status, implementer}`. |
| `changes_requested` event count | `sdlc-review` skill (manual) | The skill counts `changes_requested` entries in the task's run history to determine the current review round (round = count + 1). |
| `review_iteration` metadata field | `kanban-tutorial.md:189` (example) | A convention for workers to stamp the iteration number in `metadata={}` when calling `kanban_request_review`. NOT enforced or tracked by the platform. |

### 2.2 What Does NOT Exist

- **No dedicated `review_rounds` or `review_iterations` column** on the `tasks` table.
- **No automated counter** that increments per review cycle.
- **No telemetry/metrics pipeline** for review iteration counts.
- **No circuit breaker** that trips after N review cycles.
- **No diagnostic rule** that flags tasks cycling through review (the `_rule_review_dependency_deadlock` in `kanban_diagnostics.py:753` detects a legacy "review-required:" block pattern, not review cycling).

---

## 3. Configuration Options That Indirectly Affect Review Retries

| Config | Default | Effect on review |
|--------|---------|------------------|
| `kanban.failure_limit` | 2 (`config_defaults.py:2831`) | Dispatcher circuit breaker for spawn/crash/timeout. Does NOT apply to review cycles. |
| `kanban.review_dispatch` | true | When false, the dispatcher does NOT spawn reviewer workers; tasks stay in `review` until a human acts. |
| Per-task `max_retries` | NULL (falls through to `failure_limit`) | Same as `failure_limit` — only for worker failures, not review. |
| `BLOCK_RECURRENCE_LIMIT` | 2 (`kanban_db.py:134`) | Only for block→unblock loops. Review excluded. |

---

## 4. Review Cycle Flow — How It Works Today

```
Implementer                    Reviewer
    |                              |
    |-- request_review() --------->|  (status: review)
    |                              |-- request_changes(reason)
    |<-- reopen_review_task() -----|  (status: ready/todo)
    |-- claim -> work -> request_review()
    |                              |-- request_changes(reason)
    |<-- reopen_review_task() -----|
    |-- claim -> work -> request_review()
    |                              |-- kanban_complete()
    |                              |  (status: done)
```

Key implementation details:

- **`request_review()`** (`kanban_db.py:6501`): On re-review, if no `reviewer` is specified, it reads the latest `changes_requested` event to recover the prior reviewer provenance and routes back to the same profile (line 6561-6598).
- **`request_changes()`** (`kanban_db.py:6663`): Validates the run was claimed from `review` (via `source_status` on the `claimed` event), restores the implementer from the latest `review_requested` event, and emits an auditable `changes_requested` event.
- **`reopen_review_task()`** (`kanban_db.py:6962`): Mirrors `unblock_task` (parent re-gating, defensive stale-run close, `consecutive_failures` preserved) and emits a `review_reopened` event.
- **`claim_review_task()`** (`kanban_db.py:4750`): Atomically transitions `review → running` and creates a new run entry for the reviewer.

---

## 5. Skill-Level Review Round Tracking

The `sdlc-review` skill (`skills/devops/sdlc-review/SKILL.md`) is the only mechanism that tracks review rounds:

- **How:** Counts `changes_requested` entries in the "Prior attempts on this task" section of the worker context (also visible as prior runs in `kanban_show`).
- **Purpose:** Varies the review lens per round (Round 1: Artifact, Round 2: Execution, Round 3+: Contract) to avoid repeating the same inspection.
- **Limitation:** This is a skill-level convention, not a platform enforcement. A reviewer that doesn't load the skill (or ignores it) has no round awareness.

---

## 6. Prompt Guidance — Explicit Design Decision

The `KANBAN_GUIDANCE` in `prompt_builder.py:317-333` explicitly instructs workers:

> "Review is not a block, so repeated review cycles do not trip unblock-loop detection."

The `kanban_request_review` tool description (`kanban_tools.py:1904-1914`) reinforces:

> "Unlike `kanban_block` this is NOT a blocker — it never counts toward unblock-loop detection, so a task can cycle through review across follow-ups without ever being falsely escalated to triage."

---

## 7. Test Coverage

- **`test_review_cycle_end_to_end`** (`test_kanban_review_lifecycle.py:635`): Explicitly tests a full loop (run → review → reopen → re-run → review → approve → done) and asserts "Never blocks, never triages."
- **`test_goal_loop_stops_after_reviewer_requests_changes`** (`test_kanban_review_surfaces.py:369`): Verifies the goal loop stops with outcome `changes_requested_by_reviewer` when a reviewer requests changes.
- **`test_reviewer_reassigns_for_autonomous_dispatch`** (`test_kanban_review_lifecycle.py:696`): Verifies reviewer provenance is preserved across re-reviews.

---

## 8. Remaining Uncertainty / Open Questions

1. **Is the lack of review-loop handling a deliberate final design or a known gap?** The `docs/decisions/003-canonical-review-topology.md:155` notes: "Whether a dedicated review-loop guard is needed is an open question."
2. **What's the worst-case cost of unbounded review cycling?** A task stuck in a review loop burns worker tokens on both the implementer and reviewer sides, with no automated escalation. The only natural brake is the reviewer eventually approving or the human operator intervening.
3. **Could `consecutive_failures` be repurposed?** No — it tracks worker health (spawn/crash/timeout), not quality. Conflating the two would break the circuit breaker's semantic clarity.

---

## 9. Recommendation

If the project needs pathological-loop protection for review, the minimal approach is:
- Add a `review_rounds` column to `tasks` (or count `changes_requested` events dynamically).
- Add a config like `kanban.review_round_limit` (default: NULL = unlimited).
- Trip a diagnostic or auto-block when the limit is reached.

Until then, the only guard is the human operator noticing a task stuck in review and intervening manually (or the reviewer eventually approving).
