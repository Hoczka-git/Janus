# JANUS Structured Observability Log Schema & Integration Spec

**Date:** 2026-09-02
**Status:** Ready for implementation
**Depends on:** `logging_observability_survey_findings.md`, `daily_briefing_pipeline_map.md`

---

## 1. Goal

Add a **non-disruptive, structured observability channel** to the JANUS daily briefing pipeline so that every invocation emits machine-parseable JSON events. This enables:

- Post-hoc analysis of briefing content (e.g., "how many attention items on average?")
- Failure debugging (Telegram send failures, Calendar API auth issues)
- Operational monitoring when the briefing is eventually automated via cron
- Audit trail of CLI usage

**Non-goal:** Do NOT replace or alter the existing `print()`-based CLI output. The observability channel is purely additive.

---

## 2. JSON Schema

### 2.1 Canonical Event Envelope

Every log line is a single JSON object on one line (JSONL / NDJSON):

```json
{
  "ts": "2026-09-02T08:00:00.123456+02:00",
  "level": "info",
  "logger": "janus.services.daily_briefing",
  "event": "briefing.assembled",
  "duration_ms": 42.1,
  "data": { ... }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ts` | string (ISO 8601) | Yes | UTC or local-with-offset timestamp |
| `level` | string | Yes | `debug`, `info`, `warning`, `error` |
| `logger` | string | Yes | Dotted Python logger name |
| `event` | string | Yes | Stable event identifier (snake_case) |
| `duration_ms` | float | No | Elapsed wall-clock time in milliseconds |
| `data` | object | Yes | Event-specific payload (see per-event schemas below) |

### 2.2 Per-Event Payloads

#### `cli.command_invoked`

```json
{
  "event": "cli.command_invoked",
  "data": {
    "command": "today",
    "argv": ["janus", "today"]
  }
}
```

#### `briefing.data_collected`

```json
{
  "event": "briefing.data_collected",
  "data": {
    "today": "2026-09-02",
    "calendar_event_count": 5,
    "today_event_count": 2,
    "task_count": 18,
    "active_goal_count": 4
  }
}
```

#### `briefing.attention_scored`

```json
{
  "event": "briefing.attention_scored",
  "data": {
    "item_count": 7,
    "top_score": 150,
    "categories": {
      "overdue_task": 2,
      "due_today": 1,
      "in_progress_task": 2,
      "upcoming_event": 1,
      "goal_stalled": 1
    }
  }
}
```

#### `briefing.assembled`

```json
{
  "event": "briefing.assembled",
  "data": {
    "attention_item_count": 7,
    "has_suggested_focus": true,
    "suggested_focus_category": "overdue_task"
  }
}
```

#### `briefing.telegram_send`

```json
{
  "event": "briefing.telegram_send",
  "data": {
    "chat_id": "123456789",
    "message_length_chars": 420
  }
}
```

#### `briefing.telegram_sent`

```json
{
  "event": "briefing.telegram_sent",
  "data": {
    "ok": true,
    "message_id": 12345
  }
}
```

#### `briefing.telegram_error`

```json
{
  "level": "error",
  "event": "briefing.telegram_error",
  "data": {
    "chat_id": "123456789",
    "error": "Bot was blocked by the user"
  }
}
```

#### `briefing.calendar_error`

```json
{
  "level": "error",
  "event": "briefing.calendar_error",
  "data": {
    "error": "token.json not found",
    "calendar_ids": ["JOB_CALENDAR_ID"]
  }
}
```

#### `briefing.io_error`

```json
{
  "level": "error",
  "event": "briefing.io_error",
  "data": {
    "path": "/home/dan11hermes/workspaces/janus/data/tasks.md",
    "error": "FileNotFoundError"
  }
}
```

---

## 3. Integration Points

All injections are in `src/janus/today.py`, `src/janus/services/daily_briefing.py`, `src/janus/services/attention.py`, and `src/janus/integrations/telegram.py`.

### 3.1 `src/janus/__init__.py` — CLI Dispatch

| Insertion | After line | Event |
|-----------|-----------|-------|
| Log `cli.command_invoked` | Inside `main()` before command dispatch | `cli.command_invoked` |

```python
# Pseudocode
logger = logging.getLogger("janus.cli")
logger.info("cli.command_invoked", extra={"data": {"command": command, "argv": sys.argv}})
```

### 3.2 `src/janus/today.py:27` — `_build_today_briefing()`

| Insertion | After line | Event |
|-----------|-----------|-------|
| Log `briefing.data_collected` | After collecting `today_events`, `tasks`, `goals` | `briefing.data_collected` |

```python
# After line ~40 in today.py (_build_today_briefing)
logger = logging.getLogger("janus.services.briefing")
logger.info("briefing.data_collected", extra={"data": {
    "today": today.isoformat(),
    "calendar_event_count": len(all_events),
    "today_event_count": len(today_events),
    "task_count": len(tasks),
    "active_goal_count": sum(1 for g in goals if g.status == "active"),
}})
```

### 3.3 `src/janus/services/attention.py:157` — `get_attention_items()`

| Insertion | After line | Event |
|-----------|-----------|-------|
| Log `briefing.attention_scored` | After sort, before return | `briefing.attention_scored` |

```python
# After line 156 (sort), before return in attention.py
logger = logging.getLogger("janus.services.attention")
logger.info("briefing.attention_scored", extra={"data": {
    "item_count": len(items),
    "top_score": items[0].score if items else 0,
    "categories": dict(Counter(item.category for item in items)),
}})
```

### 3.4 `src/janus/services/daily_briefing.py:32` — `create_daily_briefing()`

| Insertion | After line | Event |
|-----------|-----------|-------|
| Log `briefing.assembled` | After DailyBriefing constructed | `briefing.assembled` |

```python
# After line 33 in daily_briefing.py
logger = logging.getLogger("janus.services.daily_briefing")
logger.info("briefing.assembled", extra={"data": {
    "attention_item_count": len(attention_items),
    "has_suggested_focus": suggested_focus is not None,
    "suggested_focus_category": suggested_focus.category if suggested_focus else None,
}})
```

### 3.5 `src/janus/integrations/telegram.py:78` — `send_briefing()`

| Insertion | After line | Event |
|-----------|-----------|-------|
| Log `briefing.telegram_send` | After `text = format_telegram_message(briefing)` | `briefing.telegram_send` |
| Log `briefing.telegram_sent` | After successful `urllib.request.urlopen` | `briefing.telegram_sent` |
| Log `briefing.telegram_error` | In `except` block | `briefing.telegram_error` |

```python
# Before send
logger.info("briefing.telegram_send", extra={"data": {"chat_id": chat_id, "message_length_chars": len(text)}})

# After successful response
logger.info("briefing.telegram_sent", extra={"data": {"ok": True, "message_id": body.get("result", {}).get("message_id")}})

# On exception
logger.error("briefing.telegram_error", extra={"data": {"chat_id": chat_id, "error": str(exc)}})
```

### 3.6 `src/janus/today.py` — `_build_today_briefing()` Error Wrapping

Wrap the data collection in try/except to catch Google Calendar auth errors and file I/O errors:

```python
try:
    all_events = list_upcoming_events()
except Exception as exc:
    logger = logging.getLogger("janus.integrations.google_calendar")
    logger.error("briefing.calendar_error", extra={"data": {"error": str(exc)}})
    all_events = []

try:
    tasks = load_tasks()
except FileNotFoundError as exc:
    logger = logging.getLogger("janus.integrations.markdown_tasks")
    logger.error("briefing.io_error", extra={"data": {"path": str(exc.filename), "error": "FileNotFoundError"}})
    tasks = []
```

---

## 4. Configuration & Environment Variables

### 4.1 New File: `src/janus/logging_config.py`

A new module that initializes the root JANUS logger with a JSON formatter:

```python
"""Logging configuration for Janus — structured JSON output."""

import logging
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON."""
    
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        # Support extra={"data": {...}} pattern
        if hasattr(record, "data"):
            obj["data"] = record.data
        if record.exc_info and record.exc_info[0] is not None:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str)


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
) -> None:
    """Configure JANUS structured logging.
    
    Args:
        level: log level (DEBUG, INFO, WARNING, ERROR)
        log_file: optional path to log file (rotating). If None, logs to stderr.
    """
    root = logging.getLogger("janus")
    root.setLevel(getattr(logging, level.upper()))
    
    formatter = JsonFormatter()
    
    if log_file:
        handler: logging.Handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stderr)
    
    handler.setFormatter(formatter)
    root.addHandler(handler)
```

### 4.2 New Config Keys in `config/config.example.toml`

```toml
[logging]
level = "INFO"
# Optional: path to log file. If unset, logs go to stderr.
# log_file = "data/logs/briefing.log"
```

### 4.3 Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `JANUS_LOG_LEVEL` | `INFO` | Override log level |
| `JANUS_LOG_FILE` | (unset → stderr) | Override log destination |

These are read at CLI entry point (`main()`) and passed to `setup_logging()`.

---

## 5. Implementation Plan

### Step 1: Add logging config module (~30 min)

**File:** `src/janus/logging_config.py` (NEW)

- Implement `JsonFormatter` class
- Implement `setup_logging()` function
- No new dependencies required (stdlib only)

### Step 2: Wire up logging in CLI entry point (~10 min)

**File:** `src/janus/__init__.py`

- Import `setup_logging` and call it at the top of `main()`
- Log `cli.command_invoked` before command dispatch

### Step 3: Inject observability into briefing pipeline (~20 min)

**Files:**
- `src/janus/today.py` — add data_collected log + error wrapping
- `src/janus/services/daily_briefing.py` — add assembled log
- `src/janus/services/attention.py` — add attention_scored log

### Step 4: Inject observability into Telegram integration (~15 min)

**File:** `src/janus/integrations/telegram.py`

- Log `briefing.telegram_send`, `briefing.telegram_sent`, `briefing.telegram_error`

### Step 5: Update config example and README (~5 min)

**Files:**
- `config/config.example.toml` — add `[logging]` section
- `README.md` — document env vars (if applicable)

### Step 6: Tests (~20 min)

**File:** `tests/test_logging.py` (NEW)

- Test `JsonFormatter` produces valid JSON
- Test `setup_logging()` attaches correct handler
- Test each integration point emits expected events (mock-based)

---

## 6. File-Level Change Summary

| File | Change Type | What |
|------|-------------|------|
| `src/janus/logging_config.py` | **NEW** | `JsonFormatter` + `setup_logging()` |
| `src/janus/__init__.py` | MODIFY | Call `setup_logging()`, log `cli.command_invoked` |
| `src/janus/today.py` | MODIFY | Log `briefing.data_collected`, add error wrapping |
| `src/janus/services/daily_briefing.py` | MODIFY | Log `briefing.assembled` |
| `src/janus/services/attention.py` | MODIFY | Log `briefing.attention_scored` |
| `src/janus/integrations/telegram.py` | MODIFY | Log `telegram_send`, `telegram_sent`, `telegram_error` |
| `config/config.example.toml` | MODIFY | Add `[logging]` section |
| `tests/test_logging.py` | **NEW** | Unit tests for formatter + integration points |

**Estimated total effort:** ~2 hours.

---

## 7. Design Decisions & Trade-offs

### 7.1 stdlib `logging` vs `structlog`

**Chosen:** stdlib `logging` with custom `JsonFormatter`.

- **Pro:** Zero dependencies, already in every Python installation.
- **Pro:** Familiar to all Python engineers.
- **Con:** stdlib `logging`'s `extra={}` pattern is slightly verbose (no native context binding).
- **Con:** No automatic trace correlation (not needed for MVP).

**Future migration:** If context binding or async logging becomes critical, `structlog` can be swapped in as a drop-in replacement by replacing `JsonFormatter` with `structlog.processors.JSONRenderer`.

### 7.2 Separate observability vs CLI output

**Chosen:** Keep `print()` for user-facing output, add `logging` for observability.

- **Pro:** Zero UX disruption.
- **Pro:** Observability channel is independently suppressible/duplicable.
- **Con:** Two output mechanisms to maintain (acceptable).

### 7.3 `extra={"data": {...}}` pattern

Using `logger.info("event_name", extra={"data": {...}})` instead of embedding data in the message:

- **Pro:** Machine-parseable — `data` is always a structured object, not a formatted string.
- **Pro:** Event name is in the message field, consistent with logging best practices.
- **Con:** Slightly more verbose than f-strings.

---

## 8. Example Log Session

```
$ janus today
{"ts":"2026-09-02T08:00:00.001+02:00","level":"info","logger":"janus.cli","event":"cli.command_invoked","data":{"command":"today","argv":["janus","today"]}}
{"ts":"2026-09-02T08:00:00.042+02:00","level":"info","logger":"janus.services.briefing","event":"briefing.data_collected","data":{"today":"2026-09-02","calendar_event_count":5,"today_event_count":2,"task_count":18,"active_goal_count":4}}
{"ts":"2026-09-02T08:00:00.045+02:00","level":"info","logger":"janus.services.attention","event":"briefing.attention_scored","data":{"item_count":7,"top_score":150,"categories":{"overdue_task":2,"due_today":1,"in_progress_task":2,"upcoming_event":1,"goal_stalled":1}}}
{"ts":"2026-09-02T08:00:00.046+02:00","level":"info","logger":"janus.services.daily_briefing","event":"briefing.assembled","data":{"attention_item_count":7,"has_suggested_focus":true,"suggested_focus_category":"overdue_task"}}
```

```
$ janus telegram
{"ts":"2026-09-02T08:00:00.001+02:00","level":"info","logger":"janus.cli","event":"cli.command_invoked","data":{"command":"telegram","argv":["janus","telegram"]}}
{"ts":"2026-09-02T08:00:00.042+02:00","level":"info","logger":"janus.services.briefing","event":"briefing.data_collected","data":{"today":"2026-09-02","calendar_event_count":5,"today_event_count":2,"task_count":18,"active_goal_count":4}}
{"ts":"2026-09-02T08:00:00.045+02:00","level":"info","logger":"janus.services.attention","event":"briefing.attention_scored","data":{"item_count":7,"top_score":150,"categories":{"overdue_task":2,"due_today":1,"in_progress_task":2,"upcoming_event":1,"goal_stalled":1}}}
{"ts":"2026-09-02T08:00:00.046+02:00","level":"info","logger":"janus.services.daily_briefing","event":"briefing.assembled","data":{"attention_item_count":7,"has_suggested_focus":true,"suggested_focus_category":"overdue_task"}}
{"ts":"2026-09-02T08:00:01.500+02:00","level":"info","logger":"janus.integrations.telegram","event":"briefing.telegram_send","data":{"chat_id":"123456789","message_length_chars":420}}
{"ts":"2026-09-02T08:00:01.850+02:00","level":"info","logger":"janus.integrations.telegram","event":"briefing.telegram_sent","data":{"ok":true,"message_id":12345}}
```

---

## 9. Out of Scope (Future Work)

- Automated scheduling (handled separately)
- Log rotation / retention policies
- Structured logging for task/goal/workout mutations (audit trail)
- External log shipping (ELK, Loki, etc.)
- Metrics aggregation (Prometheus counters)
- OpenTelemetry tracing
