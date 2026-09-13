# Findings: Observability Patterns & Review-Loop Lifecycle Hooks

**Scope:** Janus domain-logic layer + Hermes agent/orchestration kanban subsystem.
**Goal:** Current capabilities, gaps, recommended instrumentation points, and existing code that partially addresses review-cycle metrics.

---

## 1. Existing Observability / Metrics Infrastructure

### 1.1 Janus (domain-logic layer)

**Status: essentially none.**

| Capability | Location | Notes |
|---|---|---|
| Logging | — | No `logging` import anywhere in `src/janus/`. Output uses plain `print()` to stdout/stderr. |
| Metrics library | — | No Prometheus / StatsD / OpenTelemetry. `pyproject.toml` depends only on `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`, `pytest`. |
| Dashboard | — | Janus has no dashboard. It is a CLI-driven domain layer (`janus today`, `janus task add`, etc.). |
| Analytics / stats | `src/janus/services/workout_analytics.py`, `src/janus/services/goal_progress.py` | Deterministic aggregations over markdown files — workout summaries, goal progress. No persistence of results beyond printing. |
| Attention engine | `src/janus/services/attention.py` | Deterministic scoring (overdue, blocked, stagnant goals). Produces ranked `AttentionItem` list. No storage. |

**Key files:**
- `src/janus/__init__.py` — CLI entry point; all `print()`.
- `src/janus/services/tasks.py` — task CRUD to `data/tasks.md`.
- `src/janus/models/task.py` — `ALLOWED_STATES = frozenset({"todo", "in_progress", "blocked"})`.

### 1.2 Hermes (kanban orchestration layer)

**Status: structured event audit trail + aggregate stats, no external metrics export.**

| Capability | Location | Notes |
|---|---|---|
| Structured event log | `hermes_cli/kanban_db.py:1444-1449` | `task_events` table: `id, task_id, run_id, kind, payload, created_at`. Every state change appends an event. |
| Run history | `hermes_cli/kanban_db.py:1458-1478` | `task_runs` table: claim state, PID, heartbeat, runtime cap, summary, outcome. Multiple rows per task. |
| Aggregate stats | `hermes_cli/kanban_db.py:11267-11300` | `board_stats()` → per-status counts, per-assignee counts, oldest `ready` age. |
| Single-task age | `hermes_cli/kanban_db.py:11331-11345` | `task_age()` → `created_age_seconds`, `started_age_seconds`, `time_to_complete`. |
| Block-loop breaker | `hermes_cli/kanban_db.py:127-134` | `BLOCK_RECURRENCE_LIMIT = 2` — escalates to `triage` after 2 unblock↔re-block cycles for the same reason. |
| Failure circuit-breaker | `hermes_cli/kanban_db.py:1080-1082` | `consecutive_failures` on `tasks` table; `max_retries` / `DEFAULT_FAILURE_LIMIT`. |
| Notification events | `gateway/kanban_watchers.py:266` | `TERMINAL_KINDS` includes `completed`, `blocked`, `gave_up`, `crashed`, `timed_out`, `status`, `archived`, `unblocked`, `block_loop_detected`, `review_requested`, `changes_requested`. |
| Logging | `gateway/kanban_watchers.py:27` | `logger = logging.getLogger("gateway.run")`. `_log = logging.getLogger(__name__)` in `kanban_db.py:95`. |
| Dashboard | `hermes dashboard` | Renders `review` column; uses `board_stats()` and `task_age()` under the hood. |

**Gap:** No export to Prometheus / JSON endpoint / time-series DB. Stats are computed on demand from SQL, not streamed.

---

## 2. Review Lifecycle Implementation

### 2.1 Canonical model: Model A (Native Review Lane)

Per `docs/decisions/003-canonical-review-topology.md`, review is a phase of the **same** task — not a separate child.

```
 ┌──────────┐  request_review()   ┌──────────┐  kanban_complete()   ┌──────────┐
 │ running  │ ──────────────────▶ │  review  │ ──────────────────▶ │   done   │
 │ (implem) │                     │(reviewer)│                     │          │
 └──────────┘                     └──────────┘                     └──────────┘
       ▲                                │                                │
       │   request_changes()            │                                │
       └────────────────────────────────┘                                │
       │                                                                 │
       └────── reopen_review_task() ──────────────────────────────────────┘
```

### 2.2 State machine

| From | Transition | To | DB function | Tool handler |
|---|---|---|---|---|
| `running` (implem) | `request_review()` | `review` | `kanban_db.py:6501` | `kanban_tools.py:898` |
| `review` (reviewer) | `kanban_complete()` | `done` | `kanban_db.py:…` (complete_task) | `kanban_tools.py:…` |
| `review` (reviewer) | `request_changes(reason)` | `ready`/`todo` | `kanban_db.py:6663` | `kanban_tools.py:976` |
| `review` (reviewer) | `kanban_block()` | `blocked` | `kanban_db.py:…` (block_task) | `kanban_tools.py:…` |
| `review` | `reopen_review_task()` | `ready`/`todo` | `kanban_db.py:6962` | CLI `hermes kanban reopen-review` |

### 2.3 Review dispatch

- `review_dispatch_enabled()` (`kanban_db.py:9608-9625`) — config flag, default `true`.
- `_dispatch_once_locked()` enumerates `review_rows` (`kanban_db.py:10310-10410`).
- Reviewer workers force-loaded with `sdlc-review` skill (`kanban_db.py:10395-10397`).
- Budget sharing: review + ready spawns share `max_spawn` so neither starves the other.

### 2.4 Prompt-level guidance

`agent/prompt_builder.py:317-328` (KANBAN_GUIDANCE):

> When this same task needs review before it is final, call `kanban_request_review(summary=..., metadata=..., reviewer=<optional-profile>)`. The reviewer approves with `kanban_complete`, returns actionable rework with `kanban_request_changes`, or uses `kanban_block` only for a genuine external escalation. **Review is not a block, so repeated review cycles do not trip unblock-loop detection.**

---

## 3. How Tasks Transition between Implementation and Review

### 3.1 Implementer → Review

1. Implementer worker finishes, calls `kanban_request_review(summary, metadata, reviewer)`.
2. `_handle_request_review()` enforces worker-task ownership, validates summary, redacts, calls `kb.request_review()`.
3. `request_review()` (kanban_db.py:6501):
   - Checks parents satisfied.
   - If task is `running` under a live claim, requires `expected_run_id` or `force=True`.
   - If `reviewer` is `None`, reads prior reviewer provenance from the latest `changes_requested` event payload (`kanban_db.py:6561-6598`).
   - `UPDATE tasks SET status='review', claim_lock=NULL, claim_expires=NULL, worker_pid=NULL [, assignee=reviewer]`.
4. Dispatcher picks up `review` task on next tick, spawns reviewer worker.

### 3.2 Review → Implementer (changes requested)

1. Reviewer worker calls `kanban_request_changes(reason=...)`.
2. `_handle_request_changes()` enforces ownership, validates reason, redacts.
3. `request_changes()` (kanban_db.py:6663):
   - Validates task is `running` with active run.
   - Verifies `claimed` event `source_status == 'review'`.
   - Reads implementer from latest `review_requested` event.
   - `_landing_status_after_parents()` → `ready` if parents done, else `todo`.
   - `_end_run(..., outcome="changes_requested", summary=reason)`.
   - Emits `changes_requested` event with payload `{reason, implementer, reviewer, status}` (`kanban_db.py:6767-6778`).
4. Reviewer provenance is persisted so the next `request_review()` reuses it automatically.
5. Notifier (`kanban_watchers.py:655-670`) wakes origin with reason + reviewer + implementer.

### 3.3 Review → Done

`kanban_complete()` → `complete_task()` resets `consecutive_failures`, sets status `done`.

---

## 4. Existing Rejection Reason Tracking

### 4.1 Stored data

| Event kind | Payload | Location |
|---|---|---|
| `changes_requested` | `{reason, implementer, reviewer, status}` | `kanban_db.py:6767-6778` |
| `review_requested` | `{summary, metadata, reviewer, implementer}` | `kanban_db.py:6621+` (implied by request_review) |
| `review_reopened` | `{status, implementer}` | `kanban_db.py:7018+` |

### 4.2 Derived signals

- **Review round count** = count of `changes_requested` events for a task (can be computed: `SELECT COUNT(*) FROM task_events WHERE task_id = ? AND kind = 'changes_requested'`).
- **Per-round timestamps** = `created_at` of each `changes_requested` event.
- **Elapsed** = `MIN(created_at)` of first `review_requested` to `MAX(created_at)` of last terminal event.

### 4.3 Formatting for delivery

`_safe_review_reason()` (`kanban_watchers.py:36-49`) — redacts secrets, replaces local paths, truncates to 160 chars.

---

## 5. Current Capabilities vs. Gaps

### Capabilities (already exists)

| Capability | Mechanism |
|---|---|
| Full audit trail of every state change | `task_events` table |
| Run-level attempt history | `task_runs` table |
| Per-status / per-assignee counts | `board_stats()` |
| Single-task age | `task_age()` |
| Block-loop breaker (generic) | `BLOCK_RECURRENCE_LIMIT` + `block_loop_detected` event |
| Failure circuit-breaker (dispatch) | `consecutive_failures` + `max_retries` |
| Review-event notification | `kanban_watchers.py` wakes subscribers on `review_requested` / `changes_requested` |
| Reviewer provenance persistence | `changes_requested` payload carries `reviewer`, reused by next `request_review()` |
| Re-review support without re-specifying reviewer | `request_review()` reads prior `changes_requested` event |

### Gaps

| Gap | Impact |
|---|---|
| **No review-round counter column** | Counting review rounds requires a `COUNT(kind='changes_requested')` query; not surfaced as a first-class metric. |
| **No automated circuit breaker for review cycles** | `prompt_builder.py:327` explicitly says "review cycles do not trip unblock-loop detection." A task CAN spin indefinitely implement → review → changes → implement → review. |
| **No review-specific elapsed/time-in-review metric** | Must be derived from `task_events` timestamps manually. |
| **No structured metrics export** | `board_stats()` / `task_age()` are SQL-level; no JSON endpoint, no Prometheus `/metrics`. |
| **Janus layer has zero observability** | No logging, no metrics, no event tracking in domain services. |
| **`consecutive_failures` is preserved across review** | By design (`kanban_db.py:6742-6745`, `#35072`) — review transitions don't reset the breaker. But there's no review-specific recurrence counter. |
| **`run_id` on older events is NULL** | Pre-migration `task_events` have `run_id = NULL` (`kanban_db.py:2708-2712`), so per-run attribution is impossible for old rows. |
| **No per-review-reviewer timing** | Can't easily answer "how long did reviewer X spend on task Y" without joining `task_runs` manually. |

---

## 6. Recommended Instrumentation Points

### 6.1 Minimal — extend existing tables

| Where | What | Why |
|---|---|---|
| `request_review()` (`kanban_db.py:6501`) | Append `review_requested` event with `round` counter (computed from prior `changes_requested` count) | Enables `review_rounds` as a first-class metric. |
| `request_changes()` (`kanban_db.py:6663`) | Already emits `changes_requested`. Add `round` to payload. | Enables per-round audit. |
| `reopen_review_task()` (`kanban_db.py:6962`) | Already emits `review_reopened`. Add `round`. | Completes the round cycle. |
| `board_stats()` (`kanban_db.py:11267`) | Add `review_rounds_total` (sum across tasks) and `max_review_rounds` (any single task). | Dashboard-visible summary. |
| New query: `review_rounds_for_task(conn, task_id)` | `SELECT COUNT(*) FROM task_events WHERE task_id = ? AND kind IN ('changes_requested', 'review_requested')` | Reusable accessor. |

### 6.2 Optional — recurrence breaker for review loops

| Where | What |
|---|---|
| `request_changes()` | Increment a `review_recurrences` counter on the task row (or in a new column). If it exceeds a configurable `REVIEW_RECURRENCE_LIMIT` (e.g., 3), route to `triage` instead of `ready`/`todo` — mirror `block_task` semantics. |
| Config: `kanban.review_recurrence_limit` | Default `0` (= unlimited, no behavioral change). Opt-in. |

### 6.3 Optional — time-in-review metric

| Where | What |
|---|---|
| `_end_run()` (`kanban_db.py:4335`) | Already stores `ended_at`. Join with `review_requested` claim time to compute reviewer wall time. |
| `task_runs` | Already has `profile`, `started_at`, `ended_at`, `outcome`. Sufficient for reviewer timing without schema change. |

### 6.4 Janus layer — observability baseline

| Where | What |
|---|---|
| `src/janus/services/*.py` | Add `logging.getLogger(__name__)` per module; log key state transitions (task added/completed, goal updated, workout logged). |
| `src/janus/__init__.py` | Add `--verbose` / `--quiet` flags and standard logging config. |

---

## 7. Existing Code that Partially Addresses These Metrics

| File:Line | Function / Table | What it already provides |
|---|---|---|
| `hermes_cli/kanban_db.py:1442-1449` | `task_events` table | Full audit log of every state change including review events. |
| `hermes_cli/kanban_db.py:1458-1478` | `task_runs` table | Attempt history with `started_at`, `ended_at`, `outcome`, `profile`. |
| `hermes_cli/kanban_db.py:11267-11300` | `board_stats()` | Per-status + per-assignee counts, oldest ready age. |
| `hermes_cli/kanban_db.py:11331-11345` | `task_age()` | `created_age_seconds`, `started_age_seconds`, `time_to_complete`. |
| `hermes_cli/kanban_db.py:127-134` | `BLOCK_RECURRENCE_LIMIT` | Generic block-loop breaker (2 recurrences → triage). Pattern to mirror for review. |
| `hermes_cli/kanban_db.py:6501-6660` | `request_review()` | Review entry + reviewer provenance from `changes_requested`. |
| `hermes_cli/kanban_db.py:6663-6779` | `request_changes()` | Changes-requested event with `{reason, implementer, reviewer, status}`. |
| `hermes_cli/kanban_db.py:6962-7025` | `reopen_review_task()` | Reopens review for implementer re-run + emits `review_reopened`. |
| `hermes_cli/kanban_db.py:9608-9625` | `review_dispatch_enabled()` | Config gate for auto-dispatch of review tasks. |
| `hermes_cli/kanban_db.py:10310-10410` | `_dispatch_once_locked` review loop | Spawns reviewer workers with `sdlc-review` skill. |
| `gateway/kanban_watchers.py:266` | `TERMINAL_KINDS` | `review_requested`, `changes_requested` are terminal events that wake subscribers. |
| `gateway/kanban_watchers.py:636-670` | review_requested / changes_requested handlers | Mobile-friendly notifications with reason + provenance. |
| `gateway/kanban_watchers.py:36-49` | `_safe_review_reason()` | Sanitizes review reasons for external delivery. |
| `agent/prompt_builder.py:317-328` | `KANBAN_GUIDANCE` | Worker prompt instructs implementer → reviewer handoff and explains review is not a block. |
| `tools/kanban_tools.py:898-973` | `_handle_request_review()` | Tool handler with ownership enforcement, goal-judge gating, redaction. |
| `tools/kanban_tools.py:976-1021` | `_handle_request_changes()` | Tool handler with ownership enforcement, redaction. |

---

## 8. Summary for Implementation

The review lifecycle is **fully implemented** at the state-machine level (request → review → approve/changes/block) with durable event provenance. What is missing is:

1. **A review-round counter** — currently derivable from `task_events` COUNT but not surfaced.
2. **An optional review-loop breaker** — analogous to `BLOCK_RECURRENCE_LIMIT` but for `changes_requested` recurrences.
3. **Structured metrics export** — nothing currently exposes stats over HTTP / file.
4. **Janus-layer observability** — domain services use only `print()`.

All of (1)–(3) can be built on top of the existing `task_events` / `task_runs` schema without new tables. Item (4) is a separate concern in the Janus repository.
