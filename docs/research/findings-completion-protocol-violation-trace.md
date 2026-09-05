# Findings: Kanban Completion Protocol Violation Trace

## 1. The Completion Protocol

The Kanban completion contract is defined in `agent/prompt_builder.py:286-395` (`KANBAN_GUIDANCE`). Every worker is injected with this system-prompt block at spawn. It instructs the worker to terminate via exactly one of:

- `kanban_complete(summary=..., artifacts=[...])` — work is done
- `kanban_block(reason=...)` — blocked, needs human input
- `kanban_request_review(summary=..., reviewer=...)` — implementation done, awaiting review

The dispatcher spawns workers via `_default_spawn()` (`hermes_cli/kanban_db.py:11074-11123`) as fire-and-forget `hermes -p <profile> chat -q "work kanban task <id>"` subprocesses. The child's completion is observed through the board transitions it writes itself; the PID check is a safety net.

## 2. The Two Advisory Nudge Layers

### L1 — Agent-side stop guard (`agent/kanban_stop.py`)

- **Trigger**: conversation loop detects a clean exit (model returned `finish_reason=stop` with no tool calls) without a terminal kanban tool in the transcript.
- **Mechanism**: `build_kanban_stop_nudge()` (lines 69-101) returns a synthetic user message that is appended to the conversation, forcing another turn. The nudge text explicitly warns of "protocol violation" and instructs the model to call `kanban_complete` or `kanban_block`.
- **Budget**: `_DEFAULT_MAX_ATTEMPTS = 2` (line 22). After 2 nudge attempts, `build_kanban_stop_nudge()` returns `None` and the worker is allowed to exit.
- **Injection site**: `agent/conversation_loop.py:8663-8695` — the nudge is injected as a synthetic user message with `_kanban_stop_synthetic=True`.

### L2 — Dispatcher-side crash detection (`hermes_cli/kanban_db.py`)

- **Trigger**: `detect_crashed_workers()` (lines 9192-9489) runs on every dispatch tick. It finds `running` tasks whose worker PID is no longer alive.
- **Classification**: If the reap registry shows the worker exited cleanly (rc=0) but the task is still `running`, it's classified as `protocol_violation` (lines 9259-9276).
- **Accounting**: Violations are tracked via `_protocol_violation_streak()` (lines 9142-9189) — a bounded streak counter. The breaker trips after `_PROTOCOL_VIOLATION_FAILURE_LIMIT = 3` consecutive violations (line 9133).
- **Corrective action**: On violation, the task is released back to `ready` for retry. The prior-attempt error (including corrective guidance) is surfaced to the next retry worker via `build_worker_context()` (line 9265-9266, called at `kanban_db.py:11369+`).

## 3. How Workers Exit Cleanly While Ignoring the Nudge

The violation path is:

1. **Worker receives task** via `hermes chat -q "work kanban task <id>"` (spawned by `_default_spawn`, `kanban_db.py:11100`).
2. **Worker does some work** (reads files, runs commands, writes output) but ends its turn with a plain-text assistant message (e.g., "I have written the report to `docs/report.md`. The task is complete.") and `finish_reason=stop` — no tool calls.
3. **L1 nudge fires** (conversation_loop.py:8670-8695): the synthetic nudge is appended as a user message, the loop continues.
4. **Model ignores the nudge**: on the next turn, the model again returns a text response without calling `kanban_complete` / `kanban_block`. This can happen because:
   - The model "thinks" narrating completion is sufficient (common in GLM/Qwen families, per `kanban_stop.py:6-7`).
   - The model's `max_iterations` budget is exhausted before it emits the tool call.
   - The model hits an output-length limit mid-tool-call.
5. **L1 budget exhausted**: after `max_attempts=2` nudge rounds, `build_kanban_stop_nudge()` returns `None` (line 83-84), and the conversation loop exits normally.
6. **Worker process returns 0**: the `hermes chat -q` subprocess exits cleanly (rc=0) with the task still `running` in the DB.
7. **L2 detects the violation**: on the next dispatch tick, `detect_crashed_workers()` finds the dead PID + running task, classifies it as `protocol_violation` (line 9267), and either:
   - Releases the task to `ready` for retry (if streak < 3), OR
   - Trips the circuit breaker and auto-blocks the task (if streak >= 3).

### Additional clean-exit paths that bypass the nudge entirely

- **Budget exhaustion**: `agent/conversation_loop.py:2140-2144` — iteration budget exhausted → `_turn_exit_reason = "budget_exhausted"` → loop breaks → clean exit.
- **Max iterations**: `agent/conversation_loop.py:2094` — `api_call_count >= agent.max_iterations` → loop exits.
- **Run-budget wrap-up**: `agent/conversation_loop.py:2237-2238` — wall-clock budget injection is advisory; model can still exit with text.
- **Interrupt**: `agent/conversation_loop.py:2109-2114` — user interrupt → clean exit with `_turn_exit_reason = "interrupted_by_user"`.

## 4. The Core Violation

**Both L1 and L2 are advisory/heuristic mechanisms, not deterministic enforcement.** The worker process is a free-running LLM agent; nothing in the runtime *forces* it to emit a terminal tool call before exiting. The system relies on:

1. **Prompt engineering** (KANBAN_GUIDANCE) — advisory, model can ignore.
2. **Synthetic nudge injection** (L1) — advisory, model can ignore after budget exhaustion.
3. **Post-hoc detection + retry** (L2) — reactive, not preventive.

The violation is structurally unavoidable in the current architecture: the worker subprocess owns its own event loop, and a clean `rc=0` exit is the normal termination path for `hermes chat -q`. The dispatcher can only observe the absence of a terminal transition after the fact.

### Key file/line references

| Component | File | Lines |
|---|---|---|
| Completion contract (system prompt) | `agent/prompt_builder.py` | 286-395 |
| L1 nudge construction | `agent/kanban_stop.py` | 69-101 |
| L1 nudge budget | `agent/kanban_stop.py` | 22 |
| L1 injection site | `agent/conversation_loop.py` | 8663-8695 |
| Worker spawn + prompt | `hermes_cli/kanban_db.py` | 11074-11123 |
| L2 crash detection | `hermes_cli/kanban_db.py` | 9192-9489 |
| L2 protocol-violation classification | `hermes_cli/kanban_db.py` | 9259-9276 |
| L2 violation streak | `hermes_cli/kanban_db.py` | 9142-9189 |
| L2 violation limit | `hermes_cli/kanban_db.py` | 9133 |
| Worker context builder (retry guidance) | `hermes_cli/kanban_db.py` | 11369+ |
| Conversation loop exit (budget) | `agent/conversation_loop.py` | 2140-2144 |
| Conversation loop exit (max iter) | `agent/conversation_loop.py` | 2094 |

## 5. Implications for a Fix

A fix implementer should focus on the gap between L1 and L2:

- **L1 is the last line of defense inside the worker process.** If the model ignores the nudge and the nudge budget is exhausted, the worker *will* exit cleanly. Increasing `max_attempts` or making the nudge more forceful (e.g., injecting a synthetic tool-call rather than a user message) could reduce the violation rate.
- **L2 is the safety net.** It correctly detects the violation and retries, but it cannot prevent the worker from exiting. The bounded retry (streak of 3) is the final backstop before human intervention.
- **The fundamental fix** would require either: (a) a deterministic runtime hook that *blocks* clean exit until a terminal tool is called (e.g., a post-loop gate in `conversation_loop.py` that intercepts `finish_reason=stop` + no terminal tool and forces one more turn regardless of budget), or (b) a wrapper that rewrites the worker's exit code to non-zero when the task is still running (so the dispatcher classifies it as a crash, not a clean exit, and the retry budget applies immediately).

Option (a) is the minimal change: in `agent/conversation_loop.py`, after the main loop exits (around line 8663), add a hard gate that *prevents* clean exit if the task is still `running` and no terminal tool was called — by issuing one final synthetic turn with a `kanban_complete` or `kanban_block` tool-call injection, or by returning a non-zero exit code from the `hermes chat -q` process.
