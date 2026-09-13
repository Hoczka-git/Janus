# Observability Log Verification Report

**Task:** t_d22c0394 — Verify observability logs and document instrumentation
**Date:** 2026-09-02
**Commit under test:** 7046ca2 (feat: structured observability logging in daily briefing pipeline)

---

## Summary

The structured observability logging is **fully functional** across all instrumented paths. All 41 dedicated observability tests pass, and end-to-end CLI runs confirm correct event emission, field completeness, JSON parseability, and briefing_id correlation propagation. No regressions detected (579 total tests pass).

---

## Architecture

### Transport
- **stderr only** — structured JSON event envelopes
- **stdout remains clean** — user-facing `print()` output only
- Default level: **WARNING** (silent — errors/warnings only)
- `--verbose` / `-v` flag: enables **INFO** level to surface all events

### Log Format
```
<timestamp> [<LEVEL>] <logger_name> {<json_envelope>}
```
Example:
```
2026-09-02 07:35:02,295 [INFO] janus {"event": "janus.command.started", "command": "today", "subcommand": null, "briefing_id": "8631dbcf...", "pid": 6339, "timestamp": "2026-09-02T05:35:02.295349+00:00"}
```

The prefix is fixed-width enough that splitting on `' ', 3` reliably separates metadata from the JSON envelope.

### Configuration
```bash
# Silent (default) — errors/warnings only
janus today

# Verbose — all structured events visible on stderr
janus today --verbose
janus today -v
```

No environment variables or config file options control logging behavior. The only switch is the CLI `--verbose` flag.

---

## Instrumented Events (12 total)

| # | Event Name | Emitter | Key Fields |
|---|-----------|---------|------------|
| 1 | `janus.command.started` | `__init__.py:main()` | command, subcommand, briefing_id, pid, timestamp |
| 2 | `janus.command.finished` | `__init__.py:main()` | command, subcommand, briefing_id, status, error, duration_ms, pid, timestamp |
| 3 | `janus.briefing.generation_started` | `today.py`, `weekly_review.py` | briefing_type, briefing_id, timestamp |
| 4 | `janus.briefing.generation_finished` | `today.py`, `weekly_review.py` | briefing_type, briefing_id, duration_ms, source_calendars, events_total, events_today, tasks_loaded, goals_loaded, attention_items, attention_by_category, suggested_focus_present, completed_tasks, open_tasks, goal_reviews, timestamp |
| 5 | `janus.source.calendar_fetched` | `google_calendar.py` | briefing_id, calendar_id, calendar_name, events_returned, parse_errors, timestamp |
| 6 | `janus.source.tasks_loaded` | `markdown_tasks.py` | briefing_id, file_path, lines_scanned, tasks_loaded, parse_errors, timestamp |
| 7 | `janus.source.goals_loaded` | `markdown_goals.py` | briefing_id, file_present, file_path, goals_loaded, validation_errors, timestamp |
| 8 | `janus.engine.attention_computed` | `attention.py` | briefing_id, items_returned, category_counts, max_score, min_score, timestamp |
| 9 | `janus.delivery.telegram_sent` | `telegram.py`, `telegram_weekly.py` | briefing_id, delivery_type, message_chars, message_lines, chat_id, api_response_ms, api_status, api_error, timestamp |
| 10 | `janus.service.task_write` | `tasks.py` | operation, briefing_id, task_title, previous_state, new_state, new_progress, timestamp |
| 11 | `janus.service.goal_write` | `goals.py` | operation, briefing_id, goal_title, changes, timestamp |

### Event Flow — Daily Briefing Path
```
command.started
  └─ briefing.generation_started
       ├─ source.calendar_fetched (per calendar)
       ├─ source.tasks_loaded
       ├─ source.goals_loaded
       ├─ engine.attention_computed
       └─ briefing.generation_finished
command.finished
```

### Event Flow — Weekly Review Path
```
command.started
  └─ briefing.generation_started
       ├─ source.goals_loaded
       ├─ source.tasks_loaded
       └─ briefing.generation_finished
command.finished
```

---

## Verification Results

### 1. Expected Events with Correct Fields ✅

End-to-end CLI run of `janus today --verbose` produces exactly 7 events:
1. `janus.command.started`
2. `janus.briefing.generation_started`
3. `janus.source.tasks_loaded`
4. `janus.source.goals_loaded`
5. `janus.engine.attention_computed`
6. `janus.briefing.generation_finished`
7. `janus.command.finished`

All events carry their full expected field set — verified programmatically by parsing each JSON envelope and comparing keys against the schema.

**Weekly path** (`janus weekly --verbose`) produces 6 events (same flow minus `attention_computed`, plus weekly-specific counters `completed_tasks`, `open_tasks`, `goal_reviews`).

### 2. Logs Are Parseable/Structured ✅

Every line emitted to stderr is valid JSON (after the fixed prefix). Verified by parsing 7 daily + 6 weekly log lines through `json.loads()` — all succeed.

The format is:
```
<ISO-timestamp> [<LEVEL>] <dotted.logger.name> {<json-object>}
```

Parse strategy: `line.split(' ', 3)` → timestamp, level bracketed, logger name + space + JSON.

### 3. Error Scenarios ✅

**Unknown command** (`janus unknown_cmd --verbose`):
- `janus.command.finished` emitted at **WARNING** level
- `status: "error"`, `error: "Unknown command: unknown_cmd"`
- `duration_ms: 0`

**Missing Telegram config** (`janus telegram --verbose`):
- `janus.command.finished` emitted at **WARNING** level
- `status: "error"`, `error: "Config file not found: ..."`
- Full event chain through briefing generation is preserved
- Exception re-raised (correct behavior — preserves exit code 1)

**Missing goals file** (`janus.source.goals_loaded`):
- Emits with `file_present: false`, `goals_loaded: 0` — graceful degradation (returns `[]`)

### 4. No Regressions ✅

- **579 total tests pass** (all existing + 41 new observability tests)
- **Stdout cleanliness verified** — when `--verbose`, stdout contains ONLY the formatted briefing; all log lines go to stderr
- **Briefing output unchanged** — content identical to pre-instrumentation output

### 5. briefing_id Propagation ✅

A single UUID-hex `briefing_id` is generated at command start and propagated through every downstream layer:
- `today.py` → `daily_briefing.py` → `attention.py`
- `weekly_review.py` → `markdown_tasks.py` / `markdown_goals.py`
- `google_calendar.py`

Verified: all 7 events in a single `today` run share the same `briefing_id`.

### 6. Secret Redaction ✅

Telegram integration **never logs `bot_token`**. The test `test_telegram_sent_no_bot_token_leaked` confirms token absence from log output. The `chat_id` is logged (needed for debugging delivery issues).

---

## How to Use These Logs

### Running with Observability
```bash
janus today --verbose          # Daily briefing with logs on stderr
janus weekly --verbose         # Weekly review with logs on stderr
janus telegram --verbose       # Send daily to Telegram (logs API round-trip)
```

### Parsing Logs
```bash
# Extract just JSON envelopes from stderr
janus today --verbose 2>&1 >/dev/null | while read -r line; do
    echo "$line" | awk -F ' ' '{print $4}'
done | jq .

# Count events by type
janus today --verbose 2>&1 >/dev/null | grep -oP '"event":\s*"\K[^"]+' | sort | uniq -c

# Filter errors only (default level without --verbose shows these)
janus today 2>&1 | grep '\[WARNING\]'
```

### Correlating Events
All events sharing a `briefing_id` belong to a single command invocation. This enables:
- End-to-end latency analysis (duration_ms at each stage)
- Failure correlation (which data source failed during a briefing)
- Delivery tracking (telegram_sent.api_status per chat_id)

---

## Gaps and Observations

### 1. No File Log Handler
Logs go to stderr only. No persistent log file is written. For production use (cron jobs, systemd), stderr capture must be configured externally (e.g., `2>> /var/log/janus.log` or systemd journal).

**Recommendation:** Add an optional `--log-file <path>` argument or `JANUS_LOG_FILE` env var for persistent logging. Not blocking.

### 2. Service-Layer `briefing_id` Always Null
Events `janus.service.task_write` and `janus.service.goal_write` emit with `briefing_id: null` because CLI command handlers (`handle_task_add`, `handle_goal_add`) do not pass a briefing_id to the service layer. These are **write** operations, not read/briefing operations, so this is partially expected — but it means write operations can't be correlated with the command that triggered them.

**Impact:** Low — write commands (task add, goal add) generate their own `command.started/finished` events with a `briefing_id`, so correlation is possible at the command level, just not at the service-event level.

### 3. No Metrics/Alerting Integration
Logs are structured but not exported to any metrics system (Prometheus, StatsD, etc.). Currently useful only for human inspection and post-hoc log analysis.

**Future consideration:** Export counters (events by type, error rates) to a metrics backend.

### 4. Single-Line Events Only
Each event is one JSON line. No multi-line events (no stack traces in log events — exceptions appear only as `error: "string"` in the envelope). This is intentional (parseability), but means full tracebacks require separate stderr output from Python's exception printer (which does happen — see error scenarios above).

---

## Configuration Reference

| Setting | Method | Default | Effect |
|---------|--------|---------|--------|
| Log level | CLI `--verbose` / `-v` | WARNING | INFO when verbose |
| Destination | Hardcoded | stderr | No option for file |
| Format | Hardcoded | `timestamp [LEVEL] logger JSON` | Not configurable |
| Third-party silencing | Hardcoded | WARNING | `googleapiclient`, `google_auth_httplib2` silenced |

---

## Conclusion

The observability instrumentation is **production-ready** for its current scope:
- Events are well-structured and consistently formatted
- briefing_id correlation works across all layers
- Secret redaction is effective
- Briefing output is unaffected (no regressions)
- Tests cover all event types, field sets, error paths, and stdout cleanliness

**Recommended next steps (non-blocking):**
1. Optional: add persistent log file support
2. Optional: propagate briefing_id into service-layer write events
3. Optional: integrate with log aggregation (filebeat, systemd-journald, etc.) for production deployments
