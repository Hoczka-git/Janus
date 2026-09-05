# Root-Cause Analysis: Why the Nudge Does Not Reliably Cause Completion

## Question Investigated

Why do the existing nudge mechanisms (agent-side stop guard + goal-mode supervisor
nudge) fail to reliably trigger `kanban_complete` when a worker finishes
implementation but exits without calling a terminal board tool?

## Executive Summary

**The nudges are advisory prompt injections, not enforced tool calls.** Both
mechanisms inject a synthetic user message and rely on the LLM voluntarily
calling `kanban_complete` on the next turn. When the model narrates intent
("Let me write the report now") and stops with `finish_reason=stop` and no tool
calls, the nudge has no teeth. The bounded budgets (2 attempts per session, 1
finalize nudge per goal loop) are exhaustible, and once exhausted the worker
exits cleanly — the nudge has failed. The dispatcher's post-exit crash
detection is an accounting mechanism, not a prevention mechanism: it records
the violation and requeues, but cannot retroactively cause completion.

---

## The Two Nudge Mechanisms

### Layer 1 — Agent-side stop guard (`agent/kanban_stop.py`)

**File:** `agent/kanban_stop.py` (consumed in `agent/conversation_loop.py:8663-8711`)

Fires after every assistant turn in the worker's conversation loop. Checks
whether the session has already called `kanban_complete` or `kanban_block`. If
not, injects a synthetic user nudge and continues the loop in the same session.

**Budget:** `_DEFAULT_MAX_ATTEMPTS = 2`. After 2 nudges the guard returns `None`
— the worker is allowed to exit cleanly.

### Layer 2 — Goal-mode supervisor nudge (`hermes_cli/goals.py:2168`)

**File:** `hermes_cli/goals.py:2168-2298` (`run_kanban_goal_loop`)

Ralph-style goal loop with an auxiliary judge. Each iteration checks task
status, judges the latest response against the card's acceptance criteria, and:
- `verdict == "continue"` → continuation prompt (loop)
- `verdict == "done"` + task still open → **FINALIZE NUDGE** (1st time only)
- `verdict == "done"` + already nudged → `block_fn()` → `blocked_budget`
- Turn budget exhausted → `block_fn()` → `blocked_budget`

**Budget:** 1 explicit finalize nudge before blocking.

---

## Root Causes

### RC-1: The nudge is a prompt injection, not a tool call (PRIMARY)

**Evidence:**
- `agent/kanban_stop.py:89-101` — the nudge is a string returned by
  `build_kanban_stop_nudge()`, injected as a synthetic user message
  (`conversation_loop.py:8687-8691`)
- `hermes_cli/goals.py:2158-2165` — `KANBAN_GOAL_FINALIZE_TEMPLATE` is a
  string fed back via `run_turn()` into the worker's `run_conversation()`

**Mechanism:** Both nudges rely on the LLM voluntarily calling
`kanban_complete` in response to the synthetic message. The module docstring
itself acknowledges the problem: "Models (especially GLM / Qwen families)
sometimes narrate the next step ('Let me write the report now') and stop with
`finish_reason=stop` and no tool calls."

**Impact:** This is a probabilistic compliance problem. The nudge is *issued*
but the model does not *obey*. The reproduction suite asserts the nudge is
issued, not that the model obeys (see
`findings-no-complete-exit-reproduction.md`).

**Classification:** Implemented but bypassed. The nudge mechanism works as
designed; the design itself is advisory.

### RC-2: The nudge budgets are small and exhaustible

**Evidence:**
- `agent/kanban_stop.py:22` — `_DEFAULT_MAX_ATTEMPTS = 2`
- `hermes_cli/goals.py:2262-2273` — after one finalize nudge, a second
  "done" verdict triggers `block_fn()` immediately

**Mechanism:** A worker that ignores the nudge twice in a session is allowed
to exit cleanly. The goal-mode loop gives exactly one chance to finalize
before blocking. These budgets are intentional escape hatches (~96% of
violations complete on a later run), but they mean the nudge is not a
reliable in-session correction.

**Impact:** A worker that consistently narrates past the nudge will exhaust
the budget and exit rc=0. The nudge has failed; the dispatcher must reclaim.

**Classification:** Expected behavior that is undocumented. The bounded retry
is intentional but the probabilistic failure rate is not surfaced to operators.

### RC-3: The nudge targets the wrong process/state for non-dispatcher workers

**Evidence:**
- `agent/kanban_stop.py:25-35` — `kanban_stop_nudge_enabled()` returns `False`
  when `HERMES_KANBAN_TASK` is not set in the environment
- `hermes_cli/goals.py:2168` — `run_kanban_goal_loop()` only runs when
  `HERMES_KANBAN_GOAL_MODE=1` (set by `_default_spawn` for goal-mode tasks)

**Mechanism:** The agent-side stop guard is gated on `HERMES_KANBAN_TASK`,
which is only set for dispatcher-spawned workers. The goal-mode nudge is
gated on `HERMES_KANBAN_GOAL_MODE`, which is only set for goal-mode tasks.
Workers spawned through other paths (e.g., interactive `hermes chat` with
manual `kanban_show`) have no nudge protection at all.

**Impact:** A worker that is not dispatcher-spawned or not goal-mode has
zero nudge coverage. It exits cleanly on the first attempt.

**Classification:** Implemented but bypassed. The gating is intentional but
creates coverage gaps.

### RC-4: The completion contract is checked only at turn boundaries that can be skipped

**Evidence:**
- `conversation_loop.py:8663-8711` — the stop guard runs after each
  assistant turn, but only if the turn produces a `finish_reason=stop`
  (i.e., the model chose to stop rather than continue tool-calling)
- `hermes_cli/goals.py:2256` — the judge evaluates the latest response,
  but if the response is text-only with no tool calls, the judge may say
  "done" while the worker never calls `kanban_complete`

**Mechanism:** The stop guard can only nudge between turns. If the model
produces a text-only response with `finish_reason=stop`, the guard fires,
but the model can keep doing this indefinitely until the budget is exhausted.
The goal-mode judge evaluates the *content* of the response, not whether a
tool was called. A response like "I have completed the task successfully"
triggers a "done" verdict, but the worker still needs to voluntarily call
`kanban_complete`.

**Impact:** The contract is checked at the wrong semantic level — it checks
whether the model *says* it's done, not whether the model *calls the tool*
that makes it done.

**Classification:** Implemented but bypassed. The check exists but operates
on the wrong signal.

### RC-5: The nudge is advisory rather than enforced — no deterministic fallback

**Evidence:** There is no code path that directly calls `kanban_complete`
on the worker's behalf. Both nudges are synthetic user messages. The only
deterministic enforcement is the dispatcher's post-exit crash detection
(`kanban_db.py:9192`), which records a `protocol_violation` event and
requeues — but does not complete the task.

**Impact:** If the model never calls `kanban_complete`, the task is never
completed by the nudge. The best the system can do is block the task after
3 consecutive violations (`_PROTOCOL_VIOLATION_FAILURE_LIMIT = 3`), which
requires manual intervention.

**Classification:** Not yet implemented. A deterministic fallback (e.g.,
auto-complete when the work is objectively done, or a forced tool call)
does not exist.

### RC-6: Timing — the dispatcher nudge fires after the worker has already exited

**Evidence:**
- `kanban_db.py:9192-9489` — `detect_crashed_workers()` runs inside
  `dispatch_once()` → `_dispatch_once_locked()`, which is a periodic tick
  (default 60s interval)
- The worker process has already exited rc=0 by the time the dispatcher
  detects the protocol violation

**Mechanism:** The dispatcher-side crash detection is a post-hoc accounting
mechanism. It cannot nudge the worker because the worker is already dead.
It can only record the violation and requeue for retry.

**Impact:** The dispatcher nudge (protocol violation recording) is not a
nudge at all — it is a scoreboard entry. It does not cause completion;
it causes retry.

**Classification:** Expected behavior that is undocumented. The dispatcher
is explicitly a reactive system, but this is not communicated in the
architecture.

---

## Classification Summary

| Root cause | Classification | Impact |
|------------|---------------|--------|
| RC-1: Nudge is prompt injection, not tool call | Implemented but bypassed | Model can narrate past it |
| RC-2: Budgets are exhaustible | Expected behavior (undocumented) | Worker exits after 2 ignored nudges |
| RC-3: Gating misses non-dispatcher workers | Implemented but bypassed | Coverage gaps |
| RC-4: Contract checked at wrong semantic level | Implemented but bypassed | Judge says "done" but no tool call |
| RC-5: No deterministic fallback | Not yet implemented | Task never auto-completes |
| RC-6: Dispatcher nudge fires post-exit | Expected behavior (undocumented) | Cannot nudge a dead process |

---

## The Failure Sequence (End-to-End)

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

At no point in this sequence does any mechanism *force* `kanban_complete`.
The nudge is advisory; the worker ignores it; the dispatcher records the
failure; the task eventually blocks for manual intervention.

---

## Remaining Uncertainty

- The actual compliance rate of the nudge across different models is unknown.
  The reproduction suite asserts the nudge is *issued*, not that the model
  *obeys*. Observing actual model behavior requires running a live worker
  with a real LLM.
- The "~96% complete on a later run" statistic cited in the code comments
  has not been independently verified against production data.
- The interaction between the agent-side stop guard and the goal-mode loop
  is not fully traced: if a goal-mode worker ignores the stop guard twice,
  does the goal-mode loop still get a chance to nudge? (Likely yes, because
  the goal loop runs in `cli.py:21432` via `_run_turn`, which calls
  `run_conversation` — but the stop guard budget is per-session, not
  per-loop.)
