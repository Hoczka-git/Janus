# Structured Observability Log Schema — JANUS Daily Briefing

**Task**: t_8088c47d  
**Date**: 2026-09-02  
**Status**: Design doc — no implementation  
**Parent research**: t_cafbe5f0 (findings), t_abd4c594 (instrumentation plan)

---

## 1. Purpose

Gain visibility into the daily/weekly briefing pipeline: generation health, data-source reliability, delivery success, and end-to-end latency — without adding runtime dependencies or changing the user-facing `print()` contract.

---

## 2. Canonical schema

Every log line is a single JSON object on **stderr**. The logger name (`janus.<module>`) and level prefix the JSON; the JSON itself is the event envelope and is the source of truth for parsers.

### 2.1 Common fields (all events)

| Field       | Type   | Example                      | Notes                                              |
|-------------|--------|------------------------------|----------------------------------------------------|
| `event`     | string | `"janus.briefing.generation_finished"` | Constant per event type; identifies the event      |
| `briefing_id` | string \| null | `"a1b2c3d4"`            | UUID4 correlator — shared by all log lines in one CLI invocation; `null` for service-layer events outside a briefing context |
| `timestamp` | string | `"2026-09-01T10:00:00.123456+02:00"` | ISO 8601 with microseconds and timezone offset — generated at emit time, UTC preferred for machine parsing |

**Serialization**: The `msg` argument to `logger.info/warning()` is `json.dumps(envelope)`. The formatter prepends `%(asctime)s [%(levelname)s] %(name)s`. Result:

```
2026-09-02T09:00:00.123456+02:00 [INFO] janus.today {"event": "janus.briefing.generation_finished", "briefing_id": "a1b2c3d4", ...}
```

This is parseable as "prefix + whitespace + JSON" — grep/sed/jq-friendly without a custom formatter.

### 2.2 Event catalog

#### P1 — Pipeline entry/exit

**`janus.command.started`** (INFO) — once per CLI invocation, top of `main()` after command identification.

| Field        | Type   | Example   | Notes                                                      |
|--------------|--------|-----------|------------------------------------------------------------|
| `command`    | string | `"today"` | `sys.argv[1]` — one of: `today`, `telegram`, `weekly`, `telegram-weekly`, `task`, `goal`, `workout` |
| `subcommand` | string \| null | `"add"` | For `task`/`goal`/`workout` subcommands; `null` otherwise |
| `briefing_id`| string | `"a1b2c3d4"` | UUID4 — generated here, propagated downstream           |
| `pid`        | int    | `12345`   | `os.getpid()`                                              |

**`janus.command.finished`** (INFO on success, WARNING on error) — end of `main()`.

| Field        | Type   | Example   | Notes                                                      |
|--------------|--------|-----------|------------------------------------------------------------|
| `command`    | string | `"today"` | Same as in `.started`                                      |
| `subcommand` | string \| null | `"add"` | Same                                                       |
| `briefing_id`| string | `"a1b2c3d4"` | Same                                                      |
| `status`     | string | `"ok"` \| `"error"` | Clean exit vs caught exception / non-zero exit       |
| `error`      | string \| null | `"Telegram API error: ..."` | Exception message if `status=error`; **never** include secrets or full tracebacks |
| `duration_ms`| int    | `1234`    | Wall-clock ms from `.started` to `.finished` (monotonic clock) |

#### P1 — Briefing generation

**`janus.briefing.generation_started`** (INFO) — when `_build_today_briefing()` or `create_weekly_review()` begins.

| Field          | Type   | Example   | Notes                                      |
|----------------|--------|-----------|--------------------------------------------|
| `briefing_type`| string | `"daily"` \| `"weekly"` | Which pipeline                         |
| `briefing_id`  | string | `"a1b2c3d4"` | Propagated from `command.started`       |

**`janus.briefing.generation_finished`** (INFO) — when generation returns.

| Field                     | Type   | Example   | Notes                                                      |
|---------------------------|--------|-----------|------------------------------------------------------------|
| `briefing_type`           | string | `"daily"` |                                                     |
| `briefing_id`             | string | `"a1b2c3d4"` |                                                  |
| `duration_ms`             | int    | `845`     | Generation step only (not full command)                   |
| `source_calendars`        | int    | `2`       | Calendars queried (daily only; 0 for weekly)             |
| `events_total`            | int    | `5`       | Raw events fetched before today-filter (daily only)       |
| `events_today`            | int    | `3`       | After today-filter (daily only; 0 for weekly)             |
| `tasks_loaded`            | int    | `7`       | Open tasks from `tasks.md`                                |
| `goals_loaded`            | int    | `3`       | Goal blocks from `goals.md`                               |
| `attention_items`         | int    | `9`       | Items returned by attention engine (daily only)           |
| `attention_by_category`   | object | `{"overdue_task":2,"due_today":3}` | Category breakdown (daily only)               |
| `suggested_focus_present` | bool   | `true`    | Whether top item was selected as focus (daily only)       |
| `completed_tasks`         | int    | `12`      | Completed task titles parsed (weekly only)                |
| `open_tasks`              | int    | `5`       | Open task titles (weekly only)                            |
| `goal_reviews`            | int    | `2`       | `GoalReview` objects produced (weekly only)               |

#### P2 — Data sources

**`janus.source.calendar_fetched`** (INFO) — once per calendar after `list_events()` returns, inside the loop in `list_upcoming_events()`.

| Field            | Type   | Example   | Notes                                                      |
|------------------|--------|-----------|------------------------------------------------------------|
| `briefing_id`    | string \| null | `"a1b2c3d4"` | Propagated when called from a briefing context; `null` standalone |
| `calendar_id`    | string | `"primary"` | Google Calendar ID from config                            |
| `calendar_name`  | string | `"Work"`  | Human-readable name from config                            |
| `events_returned`| int    | `4`       | Events parsed from this calendar                           |
| `parse_errors`   | int    | `0`       | Events that failed `parse_event()` — track if behavior changes from current raise-on-error |

**`janus.source.tasks_loaded`** (INFO) — when `load_tasks()` returns.

| Field          | Type   | Example   | Notes                                                      |
|----------------|--------|-----------|------------------------------------------------------------|
| `briefing_id`  | string \| null | `"a1b2c3d4"` |                                                     |
| `file_path`    | string | `"/home/.../data/tasks.md"` | Absolute path read                                   |
| `lines_scanned`| int    | `42`      | Total lines read                                           |
| `tasks_loaded` | int    | `7`       | Open tasks parsed (excludes `[x]` lines)                  |
| `parse_errors` | int    | `0`       | Lines that raised `ValueError` — track if behavior changes from current raise-on-error |

**`janus.source.goals_loaded`** (INFO) — when `load_goals()` returns.

| Field              | Type   | Example   | Notes                                                      |
|--------------------|--------|-----------|------------------------------------------------------------|
| `briefing_id`      | string \| null | `"a1b2c3d4"` |                                                  |
| `file_present`     | bool   | `true`    | Whether `goals.md` existed — `false` means empty result is silent file-missing, not no-goals |
| `file_path`        | string | `"/home/.../data/goals.md"` |                                              |
| `goals_loaded`     | int    | `3`       | Goal blocks parsed                                         |
| `validation_errors`| int    | `0`       | Lines that raised `ValueError` — track if behavior changes |

**`janus.source.workouts_loaded`** (INFO) — when `load_workouts()` returns. **Contingent** — include in schema now, instrument only when wired into a briefing path.

| Field          | Type   | Example   | Notes                                                      |
|----------------|--------|-----------|------------------------------------------------------------|
| `briefing_id`  | string \| null | —       |                                                            |
| `file_path`    | string | —         | Path to `workouts.md`                                      |
| `workouts_loaded`| int   | —         |                                                            |
| `parse_errors` | int    | `0`       |                                                            |

#### P3 — Attention engine

**`janus.engine.attention_computed`** (INFO) — when `get_attention_items()` returns.

| Field            | Type   | Example   | Notes                                                      |
|------------------|--------|-----------|------------------------------------------------------------|
| `briefing_id`    | string \| null | `"a1b2c3d4"` |                                                  |
| `items_returned` | int    | `9`       | Length of returned list                                    |
| `category_counts`| object | `{"overdue_task":2,"due_today":3,"upcoming_event":2}` | Count per `AttentionItem.category`        |
| `max_score`      | int    | `150`     | Highest score in returned list                             |
| `min_score`      | int    | `10`      | Lowest score (excludes zero-score items filtered out)      |

#### P4 — Delivery

**`janus.delivery.telegram_sent`** (INFO on success, WARNING on error) — after `send_briefing()` or `send_weekly()` completes.

| Field            | Type   | Example   | Notes                                                      |
|------------------|--------|-----------|------------------------------------------------------------|
| `briefing_id`    | string \| null | `"a1b2c3d4"` |                                                  |
| `delivery_type`  | string | `"daily"` \| `"weekly"` | Which delivery                                  |
| `message_chars`  | int    | `342`     | Length of formatted message string                         |
| `message_lines`  | int    | `12`      | Number of `\n`-separated lines                             |
| `chat_id`        | string | `"123456789"` | **Not a secret** (public chat identifier) — confirm acceptability with user; if unsure, log only last 4 digits |
| `api_response_ms`| int \| null | `234`   | Wall-clock ms for HTTP request; `null` if request failed before completing |
| `api_status`     | string | `"ok"` \| `"error"` \| `"exception"` | `"ok"` if `body["ok"]` true; `"error"` if API returned error body; `"exception"` if `urllib` raised |
| `api_error`      | string \| null | `"Bad Request: chat not found"` | Telegram API `description` on error, or exception message; **never** log `bot_token` |

#### P5 — Service audit trail

**`janus.service.task_write`** (INFO) — after successful task mutation (`add_task`, `complete_task`, `set_task_state`, `set_task_progress`).

| Field            | Type   | Example   | Notes                                                      |
|------------------|--------|-----------|------------------------------------------------------------|
| `operation`      | string | `"add"` \| `"complete"` \| `"set_state"` \| `"set_progress"` | Which mutation                        |
| `briefing_id`    | null   | `null`    | Always `null` — task writes happen outside briefing context |
| `task_title`     | string | `"Buy groceries"` | Task title only — user data, not secret                  |
| `previous_state` | string \| null | `"todo"` | For `set_state`; `null` for `add`/`complete`              |
| `new_state`      | string \| null | `"in_progress"` | For `set_state`; `"completed"` for `complete`; `null` for `add` |
| `new_progress`   | int \| null | `45`    | For `set_progress`; `null` otherwise                       |

**`janus.service.goal_write`** (INFO) — after successful goal mutation (`add_goal`, `update_goal_fields`, `complete_goal`).

| Field      | Type   | Example   | Notes                                                      |
|------------|--------|-----------|------------------------------------------------------------|
| `operation`| string | `"add"` \| `"update"` \| `"complete"` |                                     |
| `briefing_id`| null  | `null`    | Always `null`                                             |
| `goal_title`| string | `"Run a marathon"` |                                                  |
| `changes`  | object \| null | `{"status":"completed"}` | Key-value pairs that changed; `null` for `add` (full goal is new) |

---

## 3. Transport & configuration

**Library**: Python stdlib `logging` — zero new dependencies (existing runtime deps: 4 packages; adding a logging library is disproportionate).

**Output stream**: `stderr` only. `stdout` remains exclusive to user-facing `print()` — this contract is untouchable.

**Default level**: `WARNING` and above only — silent by default. `--verbose` / `-v` flag enables `INFO`. Flag is parsed in `main()` before dispatch and removed from `sys.argv` so subcommands don't see it.

**New file**: `src/janus/logging_config.py` with `setup_logging(verbose: bool = False) -> None` — called once from `main()` before any other module runs. Also silences noisy third-party loggers (`googleapiclient`, `google_auth_httplib2`) to `WARNING` by default.

**Future extension** (not in this design): file logging to `~/.janus/logs/` when automated triggers (cron/systemd) are added. Phase 3.

---

## 4. Correlation: briefing_id propagation

Generate `briefing_id = uuid.uuid4().hex` once in `main()` and pass it explicitly as an optional keyword argument (`briefing_id: str | None = None`, default `None`) through every function in the chain. Default `None` keeps existing callers (tests, direct scripts) working without changes.

Propagation paths:

```
main()                              ← briefing_id generated here
  ├─ _build_today_briefing(briefing_id)
  │    ├─ list_upcoming_events(briefing_id=briefing_id)   [optional — see note]
  │    ├─ load_tasks(briefing_id=briefing_id)             [optional]
  │    ├─ load_goals(briefing_id=briefing_id)             [optional]
  │    └─ get_attention_items(briefing_id=briefing_id)    [optional]
  ├─ send_briefing(briefing, briefing_id=briefing_id)
  └─ create_weekly_review(briefing_id=briefing_id)
       ├─ load_goals(briefing_id=briefing_id)
       └─ load_tasks(briefing_id=briefing_id)
```

**Decision**: Explicit kwarg passing. Rationale: simplest, most explicit, and testable — better than `contextvars` for a codebase this size.

**Note on `list_upcoming_events`**: `briefing_id` is not naturally available in the calendar module. Three options: (a) pass as optional kwarg through `list_upcoming_events()` → `list_events()` [recommended — simplest and explicit]; (b) use `contextvars`; (c) omit `briefing_id` from this event and correlate by timestamp only. Option (a) selected.

---

## 5. Timing

All duration measurements use `time.monotonic()` (not `time.time()` — monotonic is immune to system clock adjustments). Pattern:

```python
start = time.monotonic()
# ... work ...
duration_ms = int((time.monotonic() - start) * 1000)
```

---

## 6. What never goes in logs

- `bot_token` — never, in any form.
- `chat_id` — log it per §2.6 (it's not a secret) but confirm with user first.
- Full exception tracebacks in INFO events — use `str(e)` only; tracebacks go to stderr via the exception handler, not into the structured log.
- File contents beyond counts — task/goal titles are acceptable (user data, not credentials).

---

## 7. Output destination

| Phase | Destination | Trigger |
|-------|-------------|---------|
| 1 (this design) | `stderr` (human-readable during dev/debug; `jq`-parseable for scripts) | CLI `--verbose` |
| 3 (future) | `~/.janus/logs/janus-YYYY-MM-DD.jsonl` | Automated triggers (cron/systemd timer) |

No destination changes in this design — Phase 1 is stderr-only. File rotation, retention, and upload are out of scope.

---

## 8. Integration points

### 8.1 CLI dispatch (`src/janus/__init__.py:main()`)
- P1: `command.started` + `command.finished` wrap the entire dispatch.
- Parses and strips `--verbose`/`-v` before subcommand dispatch.

### 8.2 Daily briefing (`src/janus/today.py:_build_today_briefing()`)
- P1: `briefing.generation_started` + `briefing.generation_finished` wrap data collection + assembly.
- P2: delegates to `list_upcoming_events`, `load_tasks`, `load_goals` (each emits source events).
- P3: `create_daily_briefing()` → `get_attention_items()` emits engine event.

### 8.3 Weekly review (`src/janus/services/weekly_review.py:create_weekly_review()`)
- P1: same generation_started/finished pair as daily.
- P2: `load_goals`, `load_tasks` emit source events.
- P5: `compute_goal_progress()` calls are covered at the weekly level for now; per-call logging is future work.

### 8.4 Telegram delivery (`src/janus/integrations/telegram.py:send_briefing()` + `telegram_weekly.py:send_weekly()`)
- P4: `delivery.telegram_sent` after POST completes (success and error paths).
- Requires wrapping `urlopen` with `time.monotonic()` for `api_response_ms` — currently no timing exists.

### 8.5 Service layer (`src/janus/services/tasks.py`, `goals.py`)
- P5: `task_write` / `goal_write` after each successful mutation. Lowest priority — CLI-only, user sees result directly. Useful for "when did I complete X?" audits.

---

## 9. Instrumentation priority order

| Step | Scope | Events | Priority |
|------|-------|--------|----------|
| 0 | Create `src/janus/logging_config.py` with `setup_logging()` | — | — |
| 1 | `main()` — `--verbose` flag + `command.started`/`command.finished` | 2 | P1 |
| 2 | `_build_today_briefing()` + `create_weekly_review()` | 4 | P1 |
| 3 | Data sources: calendar, tasks, goals (workouts contingent) | 3–4 | P2 |
| 4 | Attention engine (`get_attention_items`) | 1 | P3 |
| 5 | Telegram delivery (both daily + weekly) | 2 | P4 |
| 6 | Service writes (`tasks.py`, `goals.py`) | 2 | P5 |

---

## 10. Verification after implementation

```
python -m pytest tests/ -q                 # existing tests still pass
janus today --verbose                       # INFO logs to stderr, printable output to stdout
janus telegram --verbose                    # same, triggers Telegram delivery
python -c "from janus import main; main()"  # silent (WARNING+ only)
```

Checks:
- stdout unchanged (only `print()` output).
- stderr gets JSON log lines on `--verbose`.
- stderr silent without `--verbose`.
- `briefing_id` consistent across all log lines in one run.
- No `bot_token` in any log line.

---

## 11. Relationship to prior artifacts

This design consolidates and supersedes:
- `research_observability_logging.md` (t_8da8ead6) — research report, 214 lines, 5 priority tiers.
- `OBSERVABILITY_PLAN.md` (t_abd4c594) — detailed instrumentation plan, 515 lines, 12 event types with exact schemas and file locations.
- `docs/research/briefing_observability_findings.md` (t_cafbe5f0) — findings report, 325 lines, confirms the above.

This doc is the canonical schema reference going forward — the prior artifacts are implementation-ready but scattered; this is the single source of truth for the schema contract.

---

*End of design.*
