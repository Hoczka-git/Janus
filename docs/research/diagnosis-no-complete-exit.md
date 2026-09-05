# Diagnosis: Why Kanban Workers Exit Without Calling kanban_complete

**Date:** 2026-09-02 | **Task:** t_6bbeba9e | **Status:** Diagnosis complete, no fix implemented (per task constraints)

---

## 1. Where the Completion Contract Is Enforced

Three independent enforcement layers, documented in `findings-completion-contract-enforcement.md` (t_c42301b2):

| Layer | Mechanism | File | Behavior on violation |
|-------|-----------|------|-----------------------|
| L1 — Agent-side stop guard | Synthetic nudge injected into worker's conversation loop after every assistant turn | `agent/kanban_stop.py:69-101` → `agent/conversation_loop.py:8663-8711` | Fires up to 2 times per session; then allows clean exit |
| L2 — Goal-mode supervisor nudge | Ralph-style goal loop with auxiliary judge; "finalize nudge" when judge says "done" but task still open | `hermes_cli/goals.py:2168-2298` | 1 finalize nudge, then blocks via `block_fn()` |
| L3 — Dispatcher crash detection | Post-exit PID liveness check in `detect_crashed_workers()` | `hermes_cli/kanban_db.py:9192-9489` | Records `protocol_violation` event; 3 consecutive → `gave_up` → `blocked` |

**Valid terminal handoffs** (worker must call exactly one):
- `kanban_complete` → `tools/kanban_tools.py:655` → `kanban_db.py:5534` → `status='done'`
- `kanban_block` → `tools/kanban_tools.py:833` → `kanban_db.py:6432` → `status='blocked'/'todo'/'triage'`
- `kanban_request_review` → `tools/kanban_tools.py:914` → `kanban_db.py:6733` → `status='review'`

The prompt that communicates the contract is built by `build_worker_context()` at `kanban_db.py:11369`.

**Key finding:** No layer *forces* a tool call. Every layer is advisory.

---

## 2. Why the Nudge Does Not Reliably Cause kanban_complete

Six root causes (RC-1 through RC-6), from `findings-nudge-completion-root-cause.md` (t_b7e69cfc):

**RC-1 (PRIMARY): The nudge is a prompt injection, not a tool call.**
Both L1 (`kanban_stop.py:89-101`, build_kanban_stop_nudge returns a string) and L2 (`goals.py:2158-2165`, KANBAN_GOAL_FINALIZE_TEMPLATE is a string) inject a synthetic user message and rely on the LLM *voluntarily* calling kanban_complete on the next turn. When the model narrates intent ("Let me write the report now") and stops with finish_reason=stop and no tool calls, the nudge has no mechanism to force compliance. The module docstring acknowledges this explicitly: "Models (especially GLM / Qwen families) sometimes narrate the next step and stop with finish_reason=stop and no tool calls."

**RC-2: Budgets are small and exhaustible.**
- L1: `_DEFAULT_MAX_ATTEMPTS = 2` (`kanban_stop.py:22`). After 2 ignored nudges, the guard returns None — worker exits cleanly.
- L2: 1 finalize nudge (`goals.py:2262-2273`). A second "done" verdict after the nudge triggers block_fn immediately.
- These budgets are intentional escape hatches (~96% of violations complete on a later run), but they mean the nudge is not a reliable in-session correction.

**RC-3: Gating misses non-dispatcher workers.**
- L1: `kanban_stop_nudge_enabled()` (`kanban_stop.py:25-35`) returns False when `HERMES_KANBAN_TASK` is not set.
- L2: `run_kanban_goal_loop()` (`goals.py:2168`) only runs when `HERMES_KANBAN_GOAL_MODE=1`.
- Workers spawned through other paths (interactive `hermes chat` with manual kanban_show) have zero nudge coverage.

**RC-4: Contract checked at wrong semantic level.**
- L1 stop guard runs only after finish_reason=stop (`conversation_loop.py:8663-8711`). It checks whether a terminal tool was *already* called, not whether the current turn produced one.
- L2 judge evaluates content (`goals.py:2256`), not tool calls. "I have completed the task" triggers a "done" verdict without any tool call.

**RC-5: No deterministic fallback.**
No code path directly calls kanban_complete on the worker's behalf. If the model never calls it, the task never auto-completes. The best the system can do is block after 3 violations.

**RC-6: Dispatcher nudge fires post-exit.**
`detect_crashed_workers()` runs on a periodic tick (default 60s). By the time it runs, the worker process has already exited rc=0. The dispatcher can only record a violation and requeue — it cannot nudge a dead process.

**Failure sequence (end-to-end):**
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
At no point does any mechanism *force* kanban_complete. Confirmed by 7-case pytest suite in `repro_no_complete_exit.py` (t_6cf58e06).

---

## 3. Expected Behavior or Bug?

**Partially expected, partially a known gap.**

The escape hatches are intentional:
- L1 budget of 2 is documented in code comments as an intentional relaxation.
- L2's single finalize nudge is part of the goal-mode design.
- L3's 3-violation circuit breaker is a safety valve, not a primary enforcement mechanism.
- The dispatcher is explicitly a reactive system, not a real-time supervisor.

However:
- The *probabilistic failure rate* is not surfaced to operators. A task can silently fail to complete multiple times before an operator sees a `blocked` state.
- The architecture documentation does not communicate that the nudge is advisory, not enforced.
- The interaction between L1 (agent-side stop guard) and L2 (goal-mode loop) is not fully documented: if a goal-mode worker ignores L1 twice, does L2 still get a chance to nudge? (Likely yes, but not verified.)

**Classification:** Expected behavior with undocumented probabilistic failure. Not a bug in the implementation sense — the nudges work as designed. The design itself is advisory, and the failure rate is a consequence of that design choice.

---

## 4. Did the git add exit 128 Contribute?

**No, it did not contribute to the protocol violation.**

Exit 128 from `git add` (typically "unknown option" or fatal git error) is a nonzero exit. The dispatcher's `_classify_worker_exit()` (`kanban_db.py:8463-8503`) classifies nonzero exits as `nonzero_exit` → `crashed` event → `_record_task_failure()` (increments unified failure counter). This is a *different* failure path from `clean_exit` (rc=0) → `protocol_violation`.

The two failure counters are independent: `test_dispatcher_violation_streak_independent_of_other_failures` confirms that real crashes do not consume the protocol violation budget.

However, exit 128 *can indirectly contribute* if it caused the worker to exit before reaching the point where it would narrate "completing" and trigger L1/L2 nudges. In that scenario, the worker would get 0 nudges before exiting — but the exit would still be classified as `nonzero_exit` (crashed), not `clean_exit` (protocol violation). The task would be requeued with a `crashed` event and a ticked failure counter, not a `protocol_violation`.

**Bottom line:** If the worker exited with rc=128, the protocol violation path was NOT taken. The exit 128 is a separate failure. If the worker somehow exited rc=0 *despite* a git add failure (e.g., the git failure was caught and the worker continued), then the exit 128 was irrelevant to the protocol violation. Either way, the git add exit 128 is not a root cause of the no-complete-exit problem.

---

## 5. Smallest Fix

**Recommended: deterministic fallback in the worker exit path (RC-5 fix).**

The smallest fix that addresses the root cause is a code path in the worker's conversation loop exit handler that checks: "Did this worker produce deliverable artifacts (files written, git commits made) but never call a terminal kanban tool?" If yes, auto-call `kanban_complete` with a summary derived from the work.

**Where to place it:** The worker's exit path in `cli.py:22064-22088` (exit code contract) or the conversation loop exit handler around `conversation_loop.py:8663-8711`. The check runs before exit 0 is returned — if artifacts exist and no terminal tool was called, call kanban_complete on the worker's behalf instead of exiting cleanly.

**Why this is the smallest fix:**
- Addresses RC-5 directly (no deterministic fallback).
- Does not change the nudge budgets or semantics.
- Does not change the dispatcher reclaim paths.
- Operates at the agent side, where the worker's actual work is visible.
- Preserves the existing advisory nudges for cases where work is genuinely incomplete.

**Risk:** False positives when work is genuinely incomplete but files were touched. Mitigation: scope the check to files in the task's workspace or git-tracked changes in the task branch.

**Alternative (larger, semantic change):** Raise the L1 budget from 2 to infinity and only allow exit after kanban_complete is called. This eliminates the silent retry loop but increases tasks ending in blocked state. Not recommended as the smallest fix.

**Visibility fix (complementary, smaller):** Emit a visible signal (e.g., `nudge_exhausted` event, or a console warning) when the L1 guard gives up and the worker exits cleanly. This addresses the "probabilistic failure rate not surfaced" gap without changing semantics. Could be done as a one-line addition to `kanban_stop.py` near line 83.

---

## 6. Sources

| Document | Task | Location |
|----------|------|----------|
| Completion contract enforcement map | t_c42301b2 | `docs/research/findings-completion-contract-enforcement.md` |
| Investigation report (Q1-Q3 answers) | t_821a3555 | `docs/research/findings-completion-contract-investigation-report.md` |
| Root-cause analysis (RC-1 through RC-6) | t_b7e69cfc | `docs/research/findings-nudge-completion-root-cause.md` |
| Reproduction (7-case pytest suite) | t_6cf58e06 | `repro_no_complete_exit.py` + `docs/research/findings-no-complete-exit-reproduction.md` |
