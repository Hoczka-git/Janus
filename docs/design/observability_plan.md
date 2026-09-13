# JANUS Structured Observability Log Schema & Instrumentation Plan

**Task**: t_abd4c594  
**Date**: 2026-09-01  
**Status**: Plan only — do not implement  
**Based on**: Research report from t_8da8ead6  

---

## 1. Library & Configuration

### 1.1 Library
Python stdlib `logging` — zero new dependencies (pyproject.toml has 4 runtime deps; adding a logging library is disproportionate).

### 1.2 Initial Configuration (one-time setup)
Add a module `src/janus/logging_config.py` with:

```python
import logging
import sys

def setup_logging(verbose: bool = False) -> None:
    """Configure JANUS logging. Call once from main() before any other module runs."""
    level = logging.INFO if verbose else logging.WARNING
    # Use a simple formatter — key=value pairs are easy to grep/parse later.
    fmt = "%(asctime)s [%(levelname)s] %(name)s %(message)s"
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger("janus")
    root.setLevel(level)
    root.addHandler(handler)
    # Silence noisy third-party loggers by default.
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    logging.getLogger("google_auth_httplib2").setLevel(logging.WARNING)
```

**Transport**: stderr only. stdout remains exclusive to user-facing `print()` output — this is the existing contract and must stay intact.

**Default behavior**: silent (WARNING and above only). `--verbose` / `-v` flag enables INFO. This is Phase 1; file logging (Phase 3) is out of scope for this plan.

### 1.3 Per-module loggers
Every module that emits logs uses:

```python
logger = logging.getLogger(__name__)
```

This gives `janus.today`, `janus.integrations.google_calendar`, etc. — matching the package hierarchy and enabling per-module level control later.

---

## 2. Log Event Catalog

### 2.1 Event: `janus.command.started`

**When**: Fires once per CLI invocation, at the top of `main()` after the command is identified but before any downstream work.

**Purpose**: Correlate the full run. Every other log in the same process carries the same `briefing_id`, making it possible to reconstruct a single invocation from its log lines.

**Level**: INFO

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.command.started"` | Constant; identifies the event |
| `command` | string | `"today"`, `"telegram"`, `"weekly"`, `"telegram-weekly"`, `"task"`, `"goal"`, `"workout"` | The `sys.argv[1]` value |
| `subcommand` | string \| null | `"add"`, `"complete"`, `"list"` | For `task`/`goal`/`workout` commands; null for `today`/`weekly` |
| `briefing_id` | string | `"a1b2c3d4"` | UUID4 — shared by all log lines in this process |
| `pid` | int | `12345` | `os.getpid()` — useful when multiple instances run |
| `timestamp` | string | `"2026-09-01T10:00:00.000Z"` | ISO 8601 UTC — `datetime.now(timezone.utc).isoformat()` |

**Exact location**: `src/janus/__init__.py`, inside `main()`, right after `command = sys.argv[1]` and the usage-check early return, before the first `if command == ...` branch. Generate `briefing_id` once here and pass it downstream (see §3 on propagation).

---

### 2.2 Event: `janus.command.finished`

**When**: Fires once per CLI invocation, at the end of `main()` (or in a `try/except/finally` around the dispatch) — after the command completes or errors.

**Purpose**: Mark the end of the run, record success/failure and total duration. Paired with `janus.command.started`, gives per-command latency and error rate.

**Level**: INFO on success, WARNING on error

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.command.finished"` | Constant |
| `command` | string | `"today"` | Same as in `.started` |
| `subcommand` | string \| null | `"add"` | Same as in `.started` |
| `briefing_id` | string | `"a1b2c3d4"` | Same as in `.started` |
| `status` | string | `"ok"` \| `"error"` | `"ok"` for clean exit, `"error"` for caught exception / non-zero exit |
| `error` | string \| null | `"Telegram API error: ..."` | Exception message if status=error, else null. Do NOT include secrets. |
| `duration_ms` | int | `1234` | Wall-clock ms from `.started` to `.finished` |
| `pid` | int | `12345` | Same process |

**Exact location**: `src/janus/__init__.py`, `main()`. Wrap the dispatch in:

```python
import time
start = time.monotonic()
try:
    # existing dispatch logic
except Exception as e:
    logger.warning("janus.command.finished", extra={..., "status": "error", "error": str(e), ...})
    raise   # or sys.exit(1) depending on current contract
else:
    logger.info("janus.command.finished", extra={..., "status": "ok", ...})
```

---

### 2.3 Event: `janus.briefing.generation_started`

**When**: Fires when `_build_today_briefing()` begins (daily) or `create_weekly_review()` begins (weekly). These are the two briefing-construction paths.

**Purpose**: Mark the start of data collection + assembly. Paired with `.finished`, gives briefing-generation latency broken out from the full command (which may include rendering/printing/Telegram delivery).

**Level**: INFO

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.briefing.generation_started"` | Constant |
| `briefing_type` | string | `"daily"` \| `"weekly"` | Which pipeline |
| `briefing_id` | string | `"a1b2c3d4"` | Propagated from `janus.command.started` |
| `timestamp` | string | ISO 8601 UTC | |

**Exact locations**:
- Daily: `src/janus/today.py`, inside `_build_today_briefing()`, first line after the function entry.
- Weekly: `src/janus/services/weekly_review.py`, inside `create_weekly_review()`, first line after the function entry.

---

### 2.4 Event: `janus.briefing.generation_finished`

**When**: Fires when `_build_today_briefing()` returns (daily) or `create_weekly_review()` returns (weekly).

**Purpose**: Record what was collected — counts by source, attention-item breakdown, suggested-focus presence. This is the primary health metric for the briefing pipeline.

**Level**: INFO

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.briefing.generation_finished"` | Constant |
| `briefing_type` | string | `"daily"` \| `"weekly"` | |
| `briefing_id` | string | `"a1b2c3d4"` | |
| `duration_ms` | int | `845` | Wall-clock ms for this generation step only |
| `source_calendars` | int | `2` | Number of Google Calendar sources queried (daily only; 0 for weekly) |
| `events_total` | int | `5` | Raw events fetched from all calendars before today-filter (daily only) |
| `events_today` | int | `3` | Events after today-filter (daily only; 0 for weekly) |
| `tasks_loaded` | int | `7` | Open tasks loaded from tasks.md |
| `goals_loaded` | int | `3` | Active + inactive goals loaded from goals.md |
| `attention_items` | int | `9` | Items returned by attention engine (daily only; 0 for weekly) |
| `attention_by_category` | object | `{"overdue_task": 2, "due_today": 3, ...}` | Category breakdown from attention engine (daily only) |
| `suggested_focus_present` | bool | `true` | Whether a top attention item was selected as focus (daily only) |
| `completed_tasks` | int | `12` | Completed task titles read from tasks.md (weekly only) |
| `open_tasks` | int | `5` | Open task titles (weekly only) |
| `goal_reviews` | int | `2` | GoalReview objects produced (weekly only) |
| `timestamp` | string | ISO 8601 UTC | |

**Exact locations**:
- Daily: `src/janus/today.py`, inside `_build_today_briefing()`, just before `return`.
- Weekly: `src/janus/services/weekly_review.py`, inside `create_weekly_review()`, just before `return`.

Note: `attention_by_category` is available from the `AttentionItem.category` field on each item returned by `get_attention_items()`. Count them in the caller.

---

### 2.5 Event: `janus.source.calendar_fetched`

**When**: Fires once per calendar after `list_events(calendar_id)` returns — inside `list_upcoming_events()`, in the loop over calendars.

**Purpose**: Track per-calendar health: how many events each calendar contributes, whether the API call succeeded. Useful when one calendar is silently empty or failing.

**Level**: INFO

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.source.calendar_fetched"` | Constant |
| `briefing_id` | string \| null | `"a1b2c3d4"` | Propagated when called from a briefing context; null when called standalone |
| `calendar_id` | string | `"primary"` | From config — the Google Calendar ID |
| `calendar_name` | string | `"Work"` | Human-readable name from config |
| `events_returned` | int | `4` | Number of events parsed from this calendar |
| `parse_errors` | int | `0` | Events that failed `parse_event()` — currently always 0 because parse_event raises; track if behavior changes |
| `timestamp` | string | ISO 8601 UTC | |

**Exact location**: `src/janus/integrations/google_calendar.py`, inside `list_upcoming_events()`, in the `for calendar_id, calendar_name in calendars:` loop, after `events = list_events(calendar_id)` returns and before `all_events.extend(events)`.

Note: `briefing_id` is not naturally available here. Propagation options (pick one when implementing):
- (a) Pass `briefing_id` as an optional kwarg through `list_upcoming_events()` → `list_events()`.
- (b) Use `contextvars` — set a context var in `_build_today_briefing()` and read it in the calendar module.
- (c) Omit `briefing_id` from this event and correlate by timestamp only.

Option (a) is the simplest and most explicit; recommend it.

---

### 2.6 Event: `janus.source.tasks_loaded`

**When**: Fires when `load_tasks()` returns — inside `load_tasks()` before the return, or in the caller after the call.

**Purpose**: Confirm the tasks source is working: file found, lines parsed, tasks loaded. Currently `load_tasks()` raises `FileNotFoundError` if the file is missing — that's a failure path, not logged here (it propagates as an error and shows up in `janus.command.finished` with status=error).

**Level**: INFO

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.source.tasks_loaded"` | Constant |
| `briefing_id` | string \| null | `"a1b2c3d4"` | Propagated from caller |
| `file_path` | string | `"/home/.../data/tasks.md"` | Absolute path of the file read |
| `lines_scanned` | int | `42` | Total lines read from the file |
| `tasks_loaded` | int | `7` | Open tasks parsed (excludes completed `[x]` lines) |
| `parse_errors` | int | `0` | Lines that raised ValueError during parse — currently propagated as exceptions; track if behavior changes to log+skip |
| `timestamp` | string | ISO 8601 UTC | |

**Exact location**: `src/janus/integrations/markdown_tasks.py`, inside `load_tasks()`, just before `return tasks`.

---

### 2.7 Event: `janus.source.goals_loaded`

**When**: Fires when `load_goals()` returns.

**Purpose**: Same as tasks_loaded for the goals source. Note: `load_goals()` returns `[]` (not an exception) when the file is missing — log the empty result so a missing file is visible in diagnostics rather than silently producing no goals.

**Level**: INFO

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.source.goals_loaded"` | Constant |
| `briefing_id` | string \| null | `"a1b2c3d4"` | |
| `file_present` | bool | `true` \| `false` | Whether goals.md existed at load time |
| `file_path` | string | `"/home/.../data/goals.md"` | |
| `goals_loaded` | int | `3` | Goal blocks parsed |
| `validation_errors` | int | `0` | Lines that raised ValueError — currently propagated; track if changed |
| `timestamp` | string | ISO 8601 UTC | |

**Exact location**: `src/janus/integrations/markdown_goals.py`, inside `load_goals()`, just before `return goals`.

---

### 2.8 Event: `janus.engine.attention_computed`

**When**: Fires when `get_attention_items()` returns.

**Purpose**: Expose the attention engine's output distribution — how many items per category, the score range. Useful for tuning scoring weights without reading the rendered output.

**Level**: INFO

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.engine.attention_computed"` | Constant |
| `briefing_id` | string \| null | `"a1b2c3d4"` | |
| `items_returned` | int | `9` | Length of the returned list |
| `category_counts` | object | `{"overdue_task": 2, "due_today": 3, "high_priority_task": 1, "upcoming_event": 2, "goal_stalled": 1}` | Count of items per `AttentionItem.category` |
| `max_score` | int | `150` | Highest score in the returned list |
| `min_score` | int | `10` | Lowest score (excludes zero-score items which are filtered out) |
| `timestamp` | string | ISO 8601 UTC | |

**Exact location**: `src/janus/services/attention.py`, inside `get_attention_items()`, just before `return items`.

---

### 2.9 Event: `janus.delivery.telegram_sent`

**When**: Fires after `send_briefing()` (daily) or `send_weekly()` (weekly) completes successfully — inside those functions, before they return.

**Purpose**: Track delivery reliability: message size, API response, latency. This is the highest-value delivery observability because a silent Telegram failure is the worst outcome for a user who expects a morning message.

**Level**: INFO on success, WARNING on API error

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.delivery.telegram_sent"` | Constant |
| `briefing_id` | string \| null | `"a1b2c3d4"` | |
| `delivery_type` | string | `"daily"` \| `"weekly"` | Which delivery |
| `message_chars` | int | `342` | Length of the formatted message string |
| `message_lines` | int | `12` | Number of `\n`-separated lines |
| `chat_id` | string | `"123456789"` | **Redacted in sample docs, logged in production.** The chat_id is not a secret (it's the public chat identifier), but confirm this is acceptable. If unsure, log only the last 4 digits. |
| `api_response_ms` | int \| null | `234` | Wall-clock ms for the HTTP request. null if the request failed before completing. |
| `api_status` | string | `"ok"` \| `"error"` | `"ok"` if `body["ok"]` is true; `"error"` if the API returned an error body; `"exception"` if urllib raised. |
| `api_error` | string \| null | `"Bad Request: chat not found"` | The Telegram API `description` field on error; the exception message on exception. Never log the bot_token. |
| `timestamp` | string | ISO 8601 UTC | |

**Exact locations**:
- Daily: `src/janus/integrations/telegram.py`, inside `send_briefing()`, after the `with urllib.request.urlopen(req) as response:` block completes (success path) and in the exception handler (error path).
- Weekly: `src/janus/integrations/telegram_weekly.py`, inside `send_weekly()`, same pattern.

Note: `api_response_ms` requires wrapping the `urlopen` call with `time.monotonic()`. The existing code has no timing — add it.

---

### 2.10 Event: `janus.source.workouts_loaded`

**When**: Fires when `load_workouts()` returns (if/when this integration is used in a briefing path).

**Purpose**: Same pattern as tasks/goals for the workouts source.

**Level**: INFO

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.source.workouts_loaded"` | Constant |
| `briefing_id` | string \| null | | |
| `file_path` | string | | Path to workouts.md |
| `workouts_loaded` | int | | |
| `parse_errors` | int | `0` | |
| `timestamp` | string | ISO 8601 UTC | |

**Exact location**: `src/janus/integrations/workout_md.py`, inside `load_workouts()`, just before return.

**Status**: Contingent — include in the schema now for completeness, but only instrument when `load_workouts()` is actually called in a briefing pipeline path. Check whether it's currently wired into `today.py` or `weekly.py` before implementing.

---

### 2.11 Event: `janus.service.task_write`

**When**: Fires after a successful task write operation: `add_task()`, `complete_task()`, `set_task_state()`, `set_task_progress()`.

**Purpose**: Audit trail for task mutations. Low urgency (CLI-only, user sees the result), but useful for answering "when did I complete X?".

**Level**: INFO

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.service.task_write"` | Constant |
| `operation` | string | `"add"` \| `"complete"` \| `"set_state"` \| `"set_progress"` | Which mutation |
| `briefing_id` | string \| null | `null` | Task writes happen outside briefing context — null |
| `task_title` | string | `"Buy groceries"` | The task title — not a secret, but keep it to title only |
| `previous_state` | string \| null | `"todo"` | For set_state: the state before the change; null for add/complete |
| `new_state` | string \| null | `"in_progress"` | For set_state: the new state; for complete: `"completed"`; null for add |
| `new_progress` | int \| null | `45` | For set_progress: the new value; null otherwise |
| `timestamp` | string | ISO 8601 UTC | |

**Exact locations**: `src/janus/services/tasks.py` — at the end of `add_task()` (before return), `complete_task()` (after write, before return), `set_task_state()` (after write, before return), `set_task_progress()` (after write, before return).

---

### 2.12 Event: `janus.service.goal_write`

**When**: Fires after a successful goal write: `add_goal()`, `update_goal_fields()`, `complete_goal()`.

**Purpose**: Same audit-trail rationale as task_write.

**Level**: INFO

**Required fields**:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `event` | string | `"janus.service.goal_write"` | Constant |
| `operation` | string | `"add"` \| `"update"` \| `"complete"` | |
| `briefing_id` | string \| null | `null` | |
| `goal_title` | string | `"Run a marathon"` | |
| `changes` | object \| null | `{"status": "completed"}` | Key-value pairs that changed; null for add (full goal is new) |
| `timestamp` | string | ISO 8601 UTC | |

**Exact locations**: `src/janus/services/goals.py` — at the end of `add_goal()`, `update_goal_fields()`, `complete_goal()` (after the underlying write, before return).

---

## 3. Field Propagation: briefing_id and Timing

### 3.1 briefing_id
Generate once in `main()` with `uuid.uuid4().hex` (or `str(uuid.uuid4())`). Pass it to the briefing construction functions so all downstream logs carry the same correlator.

**Propagation paths**:

```
main()                          ← briefing_id generated here
  ├─ _build_today_briefing(briefing_id)
  │    ├─ list_upcoming_events(briefing_id=briefing_id)   [optional — see 2.5 note]
  │    ├─ load_tasks(briefing_id=briefing_id)             [optional]
  │    ├─ load_goals(briefing_id=briefing_id)             [optional]
  │    └─ create_daily_briefing(...)
  │         └─ get_attention_items(briefing_id=briefing_id)  [optional]
  ├─ show_today() / show_telegram()
  │    └─ send_briefing(briefing, briefing_id=briefing_id)
  └─ show_weekly()
       └─ create_weekly_review(briefing_id=briefing_id)
            ├─ load_goals(briefing_id=briefing_id)
            └─ load_tasks(briefing_id=briefing_id)
```

**Decision**: Pass `briefing_id` explicitly as an optional keyword argument on each function in the chain. Default `None` so existing callers (tests, direct scripts) don't break. This is the most explicit and testable approach — better than `contextvars` for a codebase this size.

### 3.2 Timing
Use `time.monotonic()` for all duration measurements (not `time.time()` — monotonic is not affected by system clock adjustments). Record start time at the beginning of each timed scope, compute `duration_ms = int((time.monotonic() - start) * 1000)` at the end.

---

## 4. Log Format

### 4.1 Output format
Each log line is a single line on stderr in this format:

```
2026-09-01T10:00:00.123456+02:00 [INFO] janus.today briefing.generation_finished briefing_id=a1b2c3d4 events_today=3 tasks_loaded=7 goals_loaded=2 attention_items=9 suggested_focus_present=true duration_ms=845
```

The `asctime` is ISO 8601 with microseconds and timezone offset (Python's default `%asctime` is not ISO — use a custom formatter or `datetime.now(timezone.utc).isoformat()` embedded in the message). **Recommendation**: put the timestamp inside the structured message rather than relying on `%(asctime)s`, because the structured fields are the source of truth and the format is parseable:

```
2026-09-01T10:00:00.123456+02:00 [INFO] janus.today {"event": "janus.briefing.generation_finished", "briefing_id": "a1b2c3d4", "events_today": 3, "tasks_loaded": 7, ...}
```

That is: each log call passes a single `msg` string that is a JSON object (the event envelope), and the formatter prepends the timestamp + level + logger name. This makes every line parseable as JSON-with-prefix. Alternative: use `extra=` dict and a custom `Formatter` that renders `extra` as JSON — but that's more code. The inline-JSON-message approach is simpler and achieves the same parseability.

### 4.2 What goes in the message vs. extra
- Use `extra=` only for fields that the formatter needs to interpolate into a template.
- For this plan, put the entire event envelope as a JSON string in the `msg` argument:

```python
import json
logger.info(json.dumps({
    "event": "janus.briefing.generation_finished",
    "briefing_id": briefing_id,
    "events_today": len(today_events),
    ...
}))
```

Then the formatter just prints: `%(asctime)s [%(levelname)s] %(name)s %(message)s` — and `%(message)s` is the JSON.

### 4.3 What never goes in logs
- `bot_token` — never, in any form.
- `chat_id` — log it per §2.9 (it's not a secret), but flag this for user confirmation.
- File contents (task titles are OK — they're user data, not secrets).
- Full exception tracebacks in INFO events — use `str(e)` only; tracebacks go to stderr via the exception handler, not into the structured log.

---

## 5. Instrumentation Summary by File

| File | Function(s) | Event(s) | Priority |
|------|-------------|----------|----------|
| `src/janus/__init__.py` | `main()` | `janus.command.started`, `janus.command.finished` | P1 |
| `src/janus/today.py` | `_build_today_briefing()` | `janus.briefing.generation_started`, `janus.briefing.generation_finished` | P1 |
| `src/janus/services/weekly_review.py` | `create_weekly_review()` | `janus.briefing.generation_started`, `janus.briefing.generation_finished` | P1 |
| `src/janus/integrations/google_calendar.py` | `list_upcoming_events()` (loop body) | `janus.source.calendar_fetched` | P2 |
| `src/janus/integrations/markdown_tasks.py` | `load_tasks()` | `janus.source.tasks_loaded` | P2 |
| `src/janus/integrations/markdown_goals.py` | `load_goals()` | `janus.source.goals_loaded` | P2 |
| `src/janus/integrations/workout_md.py` | `load_workouts()` | `janus.source.workouts_loaded` | P2 (contingent) |
| `src/janus/services/attention.py` | `get_attention_items()` | `janus.engine.attention_computed` | P3 |
| `src/janus/integrations/telegram.py` | `send_briefing()` | `janus.delivery.telegram_sent` | P2 |
| `src/janus/integrations/telegram_weekly.py` | `send_weekly()` | `janus.delivery.telegram_sent` | P2 |
| `src/janus/services/tasks.py` | `add_task()`, `complete_task()`, `set_task_state()`, `set_task_progress()` | `janus.service.task_write` | P5 |
| `src/janus/services/goals.py` | `add_goal()`, `update_goal_fields()`, `complete_goal()` | `janus.service.goal_write` | P5 |

**Not in scope for this plan**: service-layer logging for `goal_progress.py` (compute_goal_progress is called inside create_weekly_review, which already logs at the weekly level — adding more would be redundant for now).

---

## 6. New Files to Create

| File | Purpose |
|------|---------|
| `src/janus/logging_config.py` | `setup_logging(verbose: bool)` — called once from `main()` |

No new runtime dependencies. No `pyproject.toml` changes.

---

## 7. Implementation Order

1. **Step 0** — Create `src/janus/logging_config.py` with `setup_logging()`.
2. **Step 1** — Call `setup_logging()` from `main()` in `__init__.py`. Add `--verbose` flag parsing (check `sys.argv` for `-v`/`--verbose`; remove it from argv before dispatch so subcommands don't see it). Add `janus.command.started` and `janus.command.finished` in `main()`.
3. **Step 2** — Instrument `_build_today_briefing()` (generation_started/finished) and `create_weekly_review()` (same pair).
4. **Step 3** — Instrument the three data sources: calendar, tasks, goals (workouts contingent).
5. **Step 4** — Instrument the attention engine.
6. **Step 5** — Instrument both Telegram delivery functions.
7. **Step 6** — Instrument service write operations (tasks.py, goals.py) — lowest priority, can be deferred.

---

## 8. Verification After Implementation

After implementing, verify with:

```
python -m pytest tests/ -q          # existing tests still pass
janus today --verbose               # should emit INFO logs to stderr, printable output to stdout
janus telegram --verbose            # same, but triggers Telegram delivery
python -c "from janus import main; main()" with no args  # should be silent (WARNING+ only)
```

Check that:
- stdout is unchanged (only `print()` output).
- stderr gets JSON log lines on `--verbose`.
- stderr is silent without `--verbose`.
- `briefing_id` is consistent across all log lines in a single run.
- No bot_token appears in any log line.

---

*End of plan.*
