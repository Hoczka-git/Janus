# Investigation Report: Kanban Completion Contract Enforcement

**Date:** 2026-09-02
**Scope:** Why Kanban workers can exit without calling `kanban_complete`, whether the
existing nudge mechanisms reliably prevent this, and what should change.
**Sources:** Three upstream research tasks — contract enforcement tracing,
no-complete-exit reproduction, and root-cause analysis (see §7 for citations).

---

## 1. Executive Summary

A dispatcher-spawned Kanban worker is **contractually required** to terminate by
calling one of `kanban_complete`, `kanban_block`, or `kanban_request_review`. In
practice, workers can and do exit cleanly (rc=0) without calling any of these.
Two independent "nudge" layers attempt to prevent this, but **both are advisory
prompt injections — not enforced tool calls**. A model that narrates intent and
stops without tool calls bypasses both nudges. The dispatcher's post-exit crash
detection is a reactive accounting mechanism, not a prevention mechanism: it
records the violation and requeues, but cannot retroactively cause completion.

**Bottom line:** The completion contract is enforced by social pressure (the
prompt) and eventual circuit-breaking (3 consecutive violations → `blocked`),
not by any deterministic guarantee. This is a known, intentional design trade-off
with documented escape hatches, but the probabilistic failure rate is not surfaced
to operators.

---

## 2. Original Questions — Direct Answers

### Q1: Where is the completion contract enforced?

The contract is **communicated** in the worker prompt and **enforced** at two
independent layers:

| Layer | Mechanism | File | Behavior on violation |
|-------|-----------|------|------------------------|
| L1 — Agent-side stop guard | Synthetic user nudge injected into the same session after every assistant turn | `agent/kanban_stop.py` → `agent/conversation_loop.py:8663-8711` | Bounded: 2 nudges per session, then allows clean exit |
| L2 — Goal-mode supervisor nudge | Ralph-style goal loop with auxiliary judge; finalizes when judge says "done" but task is open | `hermes_cli/goals.py:2168-2298` | Bounded: 1 finalize nudge, then `block_fn()` |
| L3 — Dispatcher crash detection | Post-exit PID liveness check; classifies exit kind | `herkanban_db.py:9192-9489` | Bounded: 3 consecutive violations → `blocked` (circuit breaker) |

**Worker entry point:** `hermes_cli/kanban_db.py:11074` (`_default_spawn`) fires
`hermes -p <profile> chat -q "work kanban task <tid>"` as a subprocess, injecting
`HERMES_KANBAN_TASK`, `HERMES_KANBAN_WORKSPACE`, `HERMES_KANBAN_GOAL_MODE`, and
related env vars. The first turn begins with `kanban_show()` output built by
`build_worker_context()` (`kanban_db.py:11369`), which embeds the Kanban Task
Protocol instructions telling the worker which tools to call.

**Valid terminal handoffs (worker-initiated):**
- `kanban_complete` → `_handle_complete()` (`tools/kanban_tools.py:655`)
- `kanban_block` → `_handle_block()` (`tools/kanban_tools.py:833`)
- `kanban_request_review` → `_handle_request_review()` (`tools/kanban_tools.py:914`)

**Exit code contract** (`cli.py:22064-22088`): exit 0 = terminal handoff called;
exit 75 = rate-limited (requeued without counting failure).

---

### Q2: Why does the nudge not reliably cause `kanban_complete`?

Six root causes (see §3 for detail). The primary one:

> **The nudge is a prompt injection, not a tool call.** Both mechanisms inject a
> synthetic user message and rely on the LLM *voluntarily* calling
> `kanban_complete` on the next turn. When the model narrates intent ("Let me
> write the report now") and stops with `finish_reason=stop` and no tool calls,
> the nudge has no teeth.

The bounded budgets are exhaustible (2 attempts per session in Layer 1, 1
finalize nudge in Layer 2), and once exhausted the worker exits cleanly. The
dispatcher's post-exit detection (Layer 3) runs on a periodic tick (default 60s)
— the worker process has already exited by then, so the dispatcher can only
record a `protocol_violation` event and requeue for retry.

---

### Q3: Is this expected behavior?

**Yes and no.** The escape hatches are intentional:
- Layer 1 budget of 2 is documented in code comments as an intentional relaxation
  ("~96% of violations complete on a later run").
- Layer 3's 3-violation circuit breaker is a safety valve, not a primary
  enforcement mechanism.
- The dispatcher is explicitly a reactive system, not a real-time supervisor.

**However**, the *probabilistic failure rate* is not surfaced to operators. A task
can silently fail to complete multiple times before an operator sees a `blocked`
state. The architecture documentation does not communicate that the nudge is
advisory, not enforced.

---

## 3. Root-Cause Analysis

### RC-1: Nudge is prompt injection, not tool call (PRIMARY)

- `agent/kanban_stop.py:89-101` — nudge is a string returned by
  `build_kanban_stop_nudge()`, injected as synthetic user message
- `hermes_cli/goals.py:2158-2165` — `KANBAN_GOAL_FINALIZE_TEMPLATE` is a string
  fed back via `run_turn()` into `run_conversation()`
- **Impact:** Probabilistic compliance. The module docstring itself acknowledges
  this: "Models (especially GLM / Qwen families) sometimes narrate the next step
  and stop with finish_reason=stop and no tool calls."

### RC-2: Budgets are small and exhaustible

- `agent/kanban_stop.py:22` — `_DEFAULT_MAX_ATTEMPTS = 2`
- `hermes_cli/goals.py:2262-2273` — after one finalize nudge, a second "done"
  verdict triggers `block_fn()` immediately
- **Impact:** A worker that ignores the nudge twice exits rc=0; the dispatcher
  must reclaim.

### RC-3: Gating misses non-dispatcher workers

- `agent/kanban_stop.py:25-35` — `kanban_stop_nudge_enabled()` returns `False`
  when `HERMES_KANBAN_TASK` is not set
- `hermes_cli/goals.py:2168` — goal loop only runs when
  `HERMES_KANBAN_GOAL_MODE=1`
- **Impact:** Workers spawned through other paths (interactive `hermes chat` with
  manual `kanban_show`) have zero nudge coverage.

### RC-4: Contract checked at wrong semantic level

- `conversation_loop.py:8663-8711` — stop guard runs only after `finish_reason=stop`
- `hermes_cli/goals.py:2256` — judge evaluates content, not tool calls
- **Impact:** A response like "I have completed the task successfully" triggers a
  "done" verdict without any tool call.

### RC-5: No deterministic fallback

- No code path directly calls `kanban_complete` on the worker's behalf.
- **Impact:** If the model never calls `kanban_complete`, the task never
  auto-completes. After 3 violations it blocks for manual intervention.

### RC-6: Dispatcher nudge fires post-exit

- `kanban_db.py:9192-9489` — `detect_crashed_workers()` runs inside
  `dispatch_once()` on a periodic tick (default 60s)
- **Impact:** The dispatcher cannot nudge a dead process. It can only record and
  requeue.

### Failure Sequence (End-to-End)

```
1. Worker announces "completing" in text, no kanban_complete call
2. Agent stop guard fires nudge #1 → loop continues in same session
3. Worker narrates again, still no terminal call
4. Agent stop guard fires nudge #2 → loop continues
5. Worker narrates again, still no terminal call
6. Guard gives up (budget exhausted) → worker exits rc=0
7. Dispatcher reaps zombie, classifies as clean_exit
8. Dispatcher records protocol_violation event, requeues to ready
9. (repeat from 1 on next dispatch)
10. After 3 consecutive violations → gave_up → blocked (terminal)
```

At no point does any mechanism *force* `kanban_complete`.

---

## 4. Reproduction Evidence

A 7-case pytest suite (`repro_no_complete_exit.py`) confirms both defense layers:

| Test | Layer | Assertion |
|------|-------|-----------|
| `test_stop_guard_nudges_when_worker_exits_without_terminal_tool` | L1 | Nudge fires, contains task id and tool names |
| `test_stop_guard_bounded_by_max_attempts` | L1 | Returns `None` after attempts >= 2 |
| `test_stop_guard_does_not_fire_after_kanban_complete` | L1 | No nudge when terminal tool already called |
| `test_dispatcher_records_protocol_violation_on_clean_exit` | L3 | `protocol_violation` event + status=ready |
| `test_dispatcher_bounded_retry_blocks_after_3_violations` | L3 | status=blocked after 3rd violation |
| `test_dispatcher_violation_streak_independent_of_other_failures` | L3 | Real crash doesn't consume violation budget |
| `test_full_sequence_demo` | both | End-to-end narrative with printed sequence |

**Caveat:** The reproduction asserts the nudge is *issued*, not that the model
*obeys*. Observing actual model compliance requires running a live worker with a
real LLM.

---

## 5. Recommended Next Steps

### 5.1 Enforce completion at exit (deterministic fallback)

Add a code path that calls `kanban_complete` on the worker's behalf when the
worker's last action produced deliverable artifacts (files written, git commits
made) but no terminal handoff. This converts the advisory nudge into a
deterministic safety net. Risk: false positives when work is genuinely
incomplete but files were touched.

### 5.2 Make the nudge block until complete (raise the budget ceiling)

Instead of allowing clean exit after 2 ignored nudges, transition the task to
`blocked` with `reason="Worker exited without terminal handoff after N nudges"`
on the first violation. This eliminates the silent retry loop. Risk: more tasks
end up in `blocked` state requiring manual triage.

### 5.3 Add a guard that checks tool calls, not just narrative

Replace the content-based judge with a structural check: after the worker's last
turn, scan the response for any tool calls to `kanban_complete`/`kanban_block`/
`kanban_request_review`. If none exist and `finish_reason=stop`, force a
continuation turn with a tool-call-specific prompt. This addresses RC-4.

### 5.4 Surface the failure rate to operators

Emit a visible signal (e.g., a `nudge_exhausted` event or a dashboard metric)
when a worker exits without terminal handoff, rather than silently requeueing.
Operators should see that a task is looping before it hits the 3-violation
circuit breaker.

### 5.5 Extend nudge coverage to non-dispatcher paths

Decouple `kanban_stop_nudge_enabled()` from `HERMES_KANBAN_TASK` being set.
Use a broader heuristic (e.g., "worker was spawned with a kanban task id in
context") so that interactive or manually-spawned workers also get the stop
guard. This addresses RC-3.

### 5.6 Prioritization

If only one change is made: **5.1 (deterministic fallback)** provides the
strongest guarantee against silent non-completion. Combined with **5.4
(visibility)**, it converts an invisible reliability problem into a manageable
operational signal.

---

## 6. Remaining Uncertainty

- **Actual nudge compliance rate** across different models is unknown. The
  reproduction asserts the nudge is issued, not that the model obeys.
- The "~96% complete on a later run" statistic from code comments has not been
  independently verified against production data.
- The interaction between the agent-side stop guard (L1) and the goal-mode loop
  (L2) is not fully traced: if a goal-mode worker ignores the stop guard twice,
  does the goal-mode loop still get a chance to nudge? (Likely yes — the goal
  loop runs via `run_conversation` in `cli.py:21432`, and the stop guard budget is
  per-session, not per-loop.)
- Whether a worker that commits/pushes code but doesn't call `kanban_complete`
  should be auto-completed is a semantic question, not a technical one.

---

## 7. Source Citations

| Source | Location | Key Findings |
|--------|----------|--------------|
| Contract enforcement trace | `.worktrees/t_c42301b2/docs/research/findings-completion-contract-enforcement.md` | Full control flow map; entry points, terminal handoffs, dispatcher reclaim paths |
| No-complete-exit reproduction | `.worktrees/t_6cf58e06/docs/research/findings-no-complete-exit-reproduction.md` | 7-case pytest suite; Layer 1 and Layer 2 confirmed; observed violation sequence |
| Root-cause analysis | `.worktrees/t_b7e69cfc/docs/research/findings-nudge-completion-root-cause.md` | Six root causes (RC-1 through RC-6); classification table; failure sequence |
