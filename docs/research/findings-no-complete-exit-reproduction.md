# Reproduction Report: Kanban No-Complete Exit Scenario

## Question Investigated

When a Kanban worker completes implementation, commits and pushes, announces
"completing", then exits cleanly (rc=0) without calling `kanban_complete` /
`kanban_block`:

1. Does the worker supervisor nudge it?
2. Does the nudge cause `kanban_complete` to be called?
3. What is the final task state if the nudge is ignored?

## Answer: Two Layers of Defense

The system has **two independent layers** that compose to handle this scenario.
Layer 1 operates *within* the worker session; Layer 2 operates *after* the
worker exits.

### Layer 1 — Agent-side stop guard (same session)

**File:** `agent/kanban_stop.py` (consumed in `agent/conversation_loop.py:8663-8711`)

When a worker process has `HERMES_KANBAN_TASK` set, the conversation loop checks
after every assistant turn whether the worker already called a terminal kanban
tool (`kanban_complete` or `kanban_block`). If not, it injects a synthetic user
nudge and continues the loop **in the same session**.

```
[System: You are a Hermes kanban worker. A plain-text reply is NOT a terminal
state for the board.

Task `t_xxx` is still `running`. Ending now without a board tool causes a
protocol violation...

Do this immediately in your next response — do not narrate intent:
1. Finish any remaining deliverable (write the required file(s) now).
2. Call `kanban_complete(summary=..., artifacts=[...])` if the work is done,
   OR `kanban_block(reason=...)` if you are blocked.]
```

**Bounded:** `_DEFAULT_MAX_ATTEMPTS = 2`. After 2 nudges the guard returns
`None` — the worker is allowed to exit cleanly. This is the intentional
escape hatch: ~96% of violations complete on a later run, so the guard does
not try to force completion indefinitely.

**Observed behavior:** The nudge fires immediately after the narrated stop,
before the worker process exits. It gives the model a chance to self-correct
within the same session.

### Layer 2 — Dispatcher-side crash detection (post-exit)

**File:** `hermes_cli/kanban_db.py` — `detect_crashed_workers()` (lines 9192+)

If the worker STILL exits rc=0, the dispatcher's next tick reaps the zombie,
classifies the exit via `_classify_worker_exit()` as `"clean_exit"`, and
records a `protocol_violation` event. The task is requeued to `ready`.

**Bounded retry:** `_PROTOCOL_VIOLATION_FAILURE_LIMIT = 3`. The violation
streak is tracked independently from the unified `consecutive_failures` counter
(via `_protocol_violation_streak`). After 3 *consecutive* clean-exit
violations, `_record_task_failure` trips the circuit breaker, emitting a
`gave_up` event and flipping the task to `blocked`.

**Observed sequence (from reproduction):**
```
Violation 1: pid=993001 → status=ready,   events=[created, claimed, spawned, protocol_violation]
Violation 2: pid=993002 → status=ready,   events=[..., protocol_violation]
Violation 3: pid=993003 → status=blocked, events=[..., protocol_violation, gave_up]
```

## Sequence of Events (Full Lifecycle)

```
1. Worker announces "completing" in text, no kanban_complete call
2. Agent stop guard fires nudge #1 → loop continues in same session
3. Worker narrates again, still no terminal call
4. Agent stop guard fires nudge #2 → loop continues
5. Worker narrates again, still no terminal call
6. Guard gives up (budget exhausted) → worker exits rc=0
7. Dispatcher reaps zombie, classifies as clean_exit
8. Dispatcher records protocol_violation event, requeues to ready
9. (repeat from 1 on next dispatch, if worker keeps exiting cleanly)
10. After 3 consecutive violations → gave_up → blocked (terminal)
```

## Key Design Decisions (verified in source)

- **The nudge does NOT directly call `kanban_complete`.** It injects a synthetic
  user message and relies on the model to call the tool on the next turn.
  Success depends on the model complying.
- **Layer 1 and Layer 2 are independent budgets.** Layer 1 is per-session
  (2 attempts); Layer 2 is per-task-lifetime (3 consecutive violations).
  A session that self-corrects on nudge #1 never touches Layer 2.
- **The violation streak is isolated.** Real crashes (nonzero exit, timeout,
  reclaim) neither consume nor extend the violation budget. Verified by
  `test_dispatcher_violation_streak_independent_of_other_failures`.
- **`max_retries` per-task override** wins over the default limit of 3.

## Reproduction Artifact

`repro_no_complete_exit.py` — 7 pytest cases, all passing:

| Test | Layer | Assertion |
|------|-------|-----------|
| `test_stop_guard_nudges_when_worker_exits_without_terminal_tool` | 1 | Nudge fires, contains task id and tool names |
| `test_stop_guard_bounded_by_max_attempts` | 1 | Returns `None` after attempts >= 2 |
| `test_stop_guard_does_not_fire_after_kanban_complete` | 1 | No nudge when terminal tool already called |
| `test_dispatcher_records_protocol_violation_on_clean_exit` | 2 | `protocol_violation` event + status=ready |
| `test_dispatcher_bounded_retry_blocks_after_3_violations` | 2 | status=blocked after 3rd violation |
| `test_dispatcher_violation_streak_independent_of_other_failures` | 2 | Real crash doesn't consume violation budget |
| `test_full_sequence_demo` | both | End-to-end narrative with printed sequence |

## Remaining Uncertainty

- The nudge is a prompt injection; model compliance is probabilistic, not
  guaranteed. The reproduction asserts the nudge is *issued*, not that the
  model *obeys*. Observing actual model behavior requires running a live
  worker with a real LLM.
- The `kanban_stop_nudge_enabled()` check depends on `HERMES_KANBAN_TASK` being
  set in the worker's environment. If a worker is spawned without this env var
  (non-dispatcher path), Layer 1 is silent.
