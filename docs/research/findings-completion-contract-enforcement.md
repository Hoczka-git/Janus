# Completion Contract Enforcement Points

A control-flow map of where the kanban completion contract is enforced: where
`kanban_complete` is expected to be called, where the worker lifecycle ends, and
where the supervisor nudge is delivered.

---

## 1. The Contract

A dispatcher-spawned worker (a `hermes -p <profile> chat -q "work kanban task
<tid>"` subprocess) MUST terminate its task by calling exactly one of:

- `kanban_complete` — implementation done, handoff to downstream
- `kanban_block` — needs human input or external dependency
- `kanban_request_review` — implementation done, awaiting same-card review

A worker process that exits without calling one of these is a **protocol
violation**. The dispatcher detects this on its next tick and reclaims the
task for bounded retry.

---

## 2. Worker Entry (the spawn side)

### 2.1 `_default_spawn` — `hermes_cli/kanban_db.py:11074`

Fires `hermes -p <assignee> --cli chat -q "work kanban task <tid>"` as a
subprocess. Injects env vars that pin the worker to its board, workspace, and
task:

- `HERMES_KANBAN_TASK`, `HERMES_KANBAN_WORKSPACE`, `HERMES_KANBAN_BOARD`,
  `HERMES_KANBAN_DB`, `HERMES_KANBAN_CLAIM_LOCK`, `HERMES_KANBAN_RUN_ID`
- `HERMES_KANBAN_GOAL_MODE=1` + `HERMES_KANBAN_GOAL_MAX_TURNS=<n>` for
  goal-mode tasks
- `HERMES_SESSION_SOURCE=kanban` (tags sessions so they are filtered from
  interactive session lists)

Returns the child PID so subsequent dispatch ticks can detect crashes.

### 2.2 Worker prompt — `tools/kanban_tools.py:560` / `kanban_db.py:11369`

The first turn begins with `kanban_show()` output, which is built by
`build_worker_context()` in `kanban_db.py:11369`. This context contains the
task title, body, prior attempts, parent handoffs, and the **Kanban Task
Protocol** instructions (the block at the top of this prompt) that tell the
worker to call `kanban_complete`, `kanban_block`, `kanban_heartbeat`, or
`kanban_comment`.

---

## 3. The Three Valid Terminal Handoffs (worker-initiated)

### 3.1 `kanban_complete` → `_handle_complete()` — `tools/kanban_tools.py:655`

**Call chain:**
1. Worker calls `kanban_complete(summary=..., metadata=..., created_cards=..., artifacts=...)`
2. `_handle_complete()` (`tools/kanban_tools.py:655`)
   - Rejects delegated-child mutation (`_reject_delegated_child_mutation`)
   - Enforces worker-task ownership (`_enforce_worker_task_ownership`)
   - Redacts summary/result/metadata
   - Stamps worker session metadata (`_stamp_worker_session_metadata`)
   - **Goal-mode gate**: `_goal_mode_handoff_rejection()` (`tools/kanban_tools.py:254`)
     — rejects completion if judge says acceptance criteria unmet
   - Merges artifacts into metadata
3. `kb.complete_task()` (`kanban_db.py:5534`)
   - Verifies parents satisfied
   - Verifies created_cards (raises `HallucinatedCardsError` on phantoms)
   - Enforces repo-sync gate (`_enforce_repo_sync_gate`)
   - `UPDATE tasks SET status='done' ...`
   - Closes the run (`_end_run` outcome="completed")
   - Clears failure counter, recomputes ready dependents, cleans workspace
4. `_fire_kanban_lifecycle_hook("kanban_task_completed", ...)` (`kanban_db.py:5771`)

**Error rejections that keep the task in-flight** (worker can retry):
- `HallucinatedCardsError` — phantom created_cards ids
- `ArtifactPreservationError` — scratch artifact missing/oversize
- `RepoSyncGateError` — uncommitted/unpushed changes
- Goal judge rejection

### 3.2 `kanban_block` → `_handle_block()` — `tools/kanban_tools.py:833`

**Call chain:**
1. Worker calls `kanban_block(reason=..., kind=...)`
2. `_handle_block()` (`tools/kanban_tools.py:833`)
   - Rejects delegated-child mutation, enforces ownership
   - **Goal-mode gate**: only `needs_input`/`capability` kinds allowed for
     goal-mode tasks; other kinds are rejected with "call kanban_complete
     instead" (`tools/kanban_tools.py:859-882`)
3. `kb.block_task()` (`kanban_db.py:6432`)
   - Routes by kind: `dependency` → `todo`; `needs_input`/`capability`/`None`
     → `blocked`; loop-exhausted → `triage`
   - Closes the run (`_end_run` outcome="blocked")
4. `_fire_kanban_lifecycle_hook("kanban_task_blocked", ...)` (`kanban_db.py:6533,6649`)

### 3.3 `kanban_request_review` → `_handle_request_review()` — `tools/kanban_tools.py:914`

**Call chain:**
1. Worker calls `kanban_request_review(summary=..., metadata=..., reviewer=...)`
2. `_handle_request_review()` (`tools/kanban_tools.py:914`)
   - Rejects delegated-child mutation, enforces ownership
   - **Goal-mode gate**: `_goal_mode_handoff_rejection()` (`tools/kanban_tools.py:956`)
3. `kb.request_review()` (`kanban_db.py:6733`)
   - Transitions task to `review` status
   - Records implementer provenance on `review_requested` event
   - Closes the run

---

## 4. Goal-Mode Supervisor Nudge

### 4.1 `_run_kanban_goal_loop_q()` — `cli.py:21384`

After the worker's first turn, if `HERMES_KANBAN_GOAL_MODE=1`, the CLI calls
`_run_kanban_goal_loop_q(cli, first_response)`. This wires the worker's
`run_conversation` into `run_kanban_goal_loop()`.

### 4.2 `run_kanban_goal_loop()` — `hermes_cli/goals.py:2168`

Ralph-style goal loop. Each iteration:

1. Check task status via `task_status_fn()` → `kb.goal_run_status()`
   (`kanban_db.py:4960`). Returns `"done"`, `"blocked"`, `"review"`,
   `"changes_requested"`, or `None` (still running).
2. If status is terminal → return outcome (`completed_by_worker`,
   `blocked_by_worker`, `review_requested_by_worker`).
3. Judge the latest response against goal_text via `judge_goal()`.
4. **`verdict == "done"`** but task still open → **FINALIZE NUDGE**:
   - First time: feeds `KANBAN_GOAL_FINALIZE_TEMPLATE` (`goals.py:2158`):
     "The work looks complete, but the task is still open. If the task is
     genuinely done, call kanban_complete now with a short summary..."
   - Sets `nudged_to_finalize = True`
   - Runs another turn
   - If still not finalized after second chance → `block_fn(reason="...never
     called kanban_complete after a finalize nudge...")` → outcome
     `"blocked_budget"`
5. **`verdict == "continue"`** → `KANBAN_GOAL_CONTINUATION_TEMPLATE`
   (`goals.py:2144`)
6. **Turn budget exhausted** → `block_fn(reason="Goal-mode worker exhausted
   its turn budget...")` → outcome `"blocked_budget"`

### 4.3 Nudge delivery path

The nudge is delivered as a synthetic user message fed back into the worker's
`run_conversation()` in the SAME session (`cli.py:21432`). The worker sees it
as a continuation prompt, not an external signal.

---

## 5. Dispatcher Reclaim Paths (worker did NOT call a terminal handoff)

These run inside `dispatch_once()` → `_dispatch_once_locked()`
(`kanban_db.py:10171,10253`). All are best-effort; a failure never breaks the
dispatch loop.

### 5.1 `reap_worker_zombies()` — `kanban_db.py:8506`

Called at the TOP of `_dispatch_once_locked()` (`kanban_db.py:10305`). Non-blocking
`os.waitpid(-1, WNOHANG)` reaps all dead children and records their raw exit
status into `_recent_worker_exits[pid] = (raw_status, timestamp)`.

### 5.2 `release_stale_claims()` — `kanban_db.py:5042`

Resets `running` tasks whose `claim_expires` is in the past. For host-local
claims with a live PID and a fresh heartbeat, the claim is **extended**
instead of reclaimed (prevents false reclaims during long LLM calls). If the
PID is dead or the heartbeat is older than
`DEFAULT_CLAIM_HEARTBEAT_MAX_STALE_SECONDS` (1h), the task is reclaimed and
the run is closed with `outcome="reclaimed"`.

### 5.3 `detect_crashed_workers()` — `kanban_db.py:9192`

For each `running` task with a host-local claim and non-NULL worker_pid:
calls `_pid_alive()`. If dead, classifies the exit via
`_classify_worker_exit()` (`kanban_db.py:8463`):

| kind | meaning | action |
|------|---------|--------|
| `clean_exit` (rc=0) | Worker finished conversationally without calling `kanban_complete`/`kanban_block` | **Protocol violation** — emit `protocol_violation` event |
| `rate_limited` (rc=75) | Worker bailed on provider quota | Requeue without counting failure |
| `nonzero_exit` | Real error | Emit `crashed` event |
| `signaled` | OOM/SIGKILL | Emit `crashed` event |
| `unknown` | Not in reap registry | Emit `crashed` event |

**Protocol violation accounting** (`kanban_db.py:9400-9466`):
- Stamps `last_failure_error` on the task
- Computes `_protocol_violation_streak()` (`kanban_db.py:9142`)
- If streak < `_PROTOCOL_VIOLATION_FAILURE_LIMIT` (3): task returns to
  `ready` for retry (no `_record_task_failure`)
- If streak >= limit: trips circuit breaker → `_record_task_failure()`
  → `blocked` with `gave_up` event

### 5.4 `enforce_max_runtime()` — `kanban_db.py:8763`

Sends SIGTERM, waits 5s, then SIGKILL for tasks where elapsed wall time
exceeds per-task `max_runtime_seconds`. Closes the run with
`outcome="timed_out"` and emits a `timed_out` event.

### 5.5 `detect_stale_running()` — `kanban_db.py:8890`

Disabled by default (`stale_timeout_seconds=0`). When enabled, reclaims tasks
that have run longer than the threshold AND have no recent heartbeat.
Closes the run with `outcome="stale"`.

### 5.6 `reconcile_orphaned_running()` — `kanban_db.py:9020`

Catches `running` tasks with broken claim bookkeeping (NULL claim_lock or
claim_expires) that the other reclaim paths cannot see. Requeues to `ready`.

---

## 6. Plugin Lifecycle Hooks (observer-only)

Registered in `hermes_cli/plugins.py:269-354`. All fire AFTER the mutation
commits and are fully best-effort (failures swallowed).

| hook | fire site | file:line |
|------|-----------|-----------|
| `kanban_task_claimed` | dispatcher, before worker spawn | `kanban_db.py:4767` |
| `kanban_task_completed` | inside `complete_task()` | `kanban_db.py:5771` |
| `kanban_task_blocked` | inside `block_task()` (×2) + review escalation | `kanban_db.py:6533,6649,6724` |
| `on_kanban_worker_spawned` | after spawn_fn returns + PID persisted | `kanban_db.py:249` |
| `on_kanban_worker_exited` | from `detect_crashed_workers()` | `kanban_db.py:9483` |
| `on_kanban_worker_stale_claim` | from `release_stale_claims()` | `kanban_db.py:5193` |
| `on_kanban_dispatch_tick` | after `_dispatch_once_locked()` | `kanban_db.py:350` |
| `on_kanban_task_updated` | after non-lifecycle task mutations | `kanban_db.py:287` |

The `kanban_task_completed` hook is the key signal for downstream automation
(e.g., the replenishment plugin listens for it to fan out child tasks).

---

## 7. Worker Exit → Exit Code Contract

`cli.py:22064-22088` sets the worker's exit code:

- Exit 0: success (worker called a terminal handoff)
- Exit 1: generic failure
- Exit 75 (`KANBAN_RATE_LIMIT_EXIT_CODE`): provider rate-limit / quota wall

The dispatcher maps exit 75 to a `rate_limited` exit kind, releasing the task
back to `ready` without incrementing the failure counter.

---

## 8. Control Flow Summary (ASCII)

```
hermes -p <profile> chat -q "work kanban task <tid>"
│
├─ build_worker_context()  ← kanban_db.py:11369
│   (task title, body, prior attempts, parent handoffs,
│    Kanban Task Protocol instructions)
│
├─ Worker first turn
│   ├─ Worker calls kanban_complete() ──► _handle_complete()
│   │   ├─ Goal judge gate (reject if unmet)
│   │   ├─ kb.complete_task() ──► status='done'
│   │   ├─ _end_run(outcome="completed")
│   │   └─ _fire_kanban_lifecycle_hook("kanban_task_completed")
│   │
│   ├─ Worker calls kanban_block() ──► _handle_block()
│   │   ├─ Goal mode kind gate
│   │   ├─ kb.block_task() ──► status='blocked'/'todo'/'triage'
│   │   ├─ _end_run(outcome="blocked")
│   │   └─ _fire_kanban_lifecycle_hook("kanban_task_blocked")
│   │
│   ├─ Worker calls kanban_request_review() ──► _handle_request_review()
│   │   ├─ Goal judge gate
│   │   ├─ kb.request_review() ──► status='review'
│   │   └─ _end_run(outcome="review_requested")
│   │
│   └─ Worker produces text but NO terminal call
│       ├─ [goal_mode] → run_kanban_goal_loop() ──► judge_goal()
│       │   ├─ verdict="continue" → continuation prompt (loop)
│       │   ├─ verdict="done" + still open → FINALIZE NUDGE (1st time)
│       │   ├─ verdict="done" + nudged before → block_fn() → blocked_budget
│       │   └─ budget exhausted → block_fn() → blocked_budget
│       │
│       └─ [non-goal] → process exits rc=0
│
Dispatcher tick (dispatch_once → _dispatch_once_locked)
│
├─ reap_worker_zombies()  ← os.waitpid, record exit statuses
├─ release_stale_claims()  ← TTL-expired claims → reclaim or extend
├─ detect_crashed_workers()  ← PID liveness check
│   ├─ clean_exit (rc=0) + task running → protocol_violation event
│   │   └─ _protocol_violation_streak >= 3 → breaker trip → blocked
│   ├─ rate_limited (rc=75) → requeue, no failure counted
│   └─ nonzero/signaled → crashed event → _record_task_failure()
├─ detect_stale_running()  ← disabled by default (stale_timeout=0)
├─ enforce_max_runtime()  ← SIGTERM+SIGKILL on max_runtime_seconds
├─ reconcile_orphaned_running()  ← broken claim bookkeeping
│
└─ On success: promoted (todo→ready), spawned (ready→running)
```

---

## 9. Key Files and Line Numbers

| concern | file | line(s) |
|---------|------|---------|
| Worker spawn | `hermes_cli/kanban_db.py` | 11074–11270 |
| Worker context builder | `hermes_cli/kanban_db.py` | 11369–11560 |
| `kanban_complete` handler | `tools/kanban_tools.py` | 655–830 |
| `kanban_block` handler | `tools/kanban_tools.py` | 833–911 |
| `kanban_request_review` handler | `tools/kanban_tools.py` | 914–989 |
| `complete_task()` (DB) | `hermes_cli/kanban_db.py` | 5534–5778 |
| `block_task()` (DB) | `hermes_cli/kanban_db.py` | 6432–6657 |
| `request_review()` (DB) | `hermes_cli/kanban_db.py` | 6733–6988 |
| `_end_run()` | `hermes_cli/kanban_db.py` | 4362–4416 |
| Goal judge gate | `tools/kanban_tools.py` | 254–273 |
| Goal loop (CLI wiring) | `cli.py` | 21384–21482 |
| `run_kanban_goal_loop()` | `hermes_cli/goals.py` | 2168–2298 |
| Finalize nudge template | `hermes_cli/goals.py` | 2158–2165 |
| Continuation nudge template | `hermes_cli/goals.py` | 2144–2153 |
| `_dispatch_once_locked()` | `hermes_cli/kanban_db.py` | 10253–10370 |
| `dispatch_once()` | `hermes_cli/kanban_db.py` | 10171–10250 |
| `detect_crashed_workers()` | `hermes_cli/kanban_db.py` | 9192–9489 |
| `release_stale_claims()` | `hermes_cli/kanban_db.py` | 5042–5206 |
| `enforce_max_runtime()` | `hermes_cli/kanban_db.py` | 8763–8880 |
| `detect_stale_running()` | `hermes_cli/kanban_db.py` | 8890–9017 |
| `reconcile_orphaned_running()` | `hermes_cli/kanban_db.py` | 9020–9100 |
| `_classify_worker_exit()` | `hermes_cli/kanban_db.py` | 8463–8503 |
| `_protocol_violation_streak()` | `hermes_cli/kanban_db.py` | 9142–9189 |
| `_record_task_failure()` | `hermes_cli/kanban_db.py` | 9492–9600 |
| Worker exit code contract | `cli.py` | 22064–22088 |
| Plugin hook registry | `hermes_cli/plugins.py` | 269–354 |
| Lifecycle hook fire | `hermes_cli/kanban_db.py` | 188–260 |
| Gateway dispatcher watcher | `gateway/kanban_watchers.py` | 1291–1490 |
