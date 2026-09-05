# JANUS Logging & Observability Survey — Findings

**Date:** 2026-09-02
**Scope:** Full repository survey of `src/janus/`, `tests/`, `config/`, `scripts/`
**Method:** File listing, content search (logging/telemetry/schedule keywords), source reading

---

## 1. Current Logging Approach and Gaps

### 1.1 What exists

**No structured logging library is used anywhere in the codebase.**

Searched for and confirmed absence of:
- `import logging` / `getLogger` / `logger.` — **0 matches**
- `structlog` — **0 matches**
- `loguru` — **0 matches**
- `telemetry` / `observability` / `metrics` / `tracing` — **0 matches**

### 1.2 How output is currently produced

All user-facing output uses `print()` to `sys.stdout`; errors use `print(..., file=sys.stderr)`.

| Location | Pattern | Purpose |
|----------|---------|---------|
| `src/janus/tasks_cli.py` | `print("Added task: ...")` | Confirm task creation |
| `src/janus/tasks_cli.py` | `print(f"Error: ...", file=sys.stderr)` | Validation errors |
| `src/janus/goals_cli.py` | `print("JANUS — GOALS")` | Goal list/show output |
| `src/janus/workout_cli.py` | `print(f"Added workout: ...")` | Confirm workout |
| `src/janus/today.py` | `print("JANUS — TODAY")` | Daily briefing render |
| `src/janus/weekly.py` | `print("JANUS — WEEKLY REVIEW")` | Weekly review render |
| `src/janus/verification.py` | `print(json.dumps(report.to_dict(), indent=2))` | Verification report |
| `scripts/validate_ci.py` | `print(f"ci.yml: OK ...")` | CI validation |

### 1.3 Gaps

| Gap | Impact |
|-----|--------|
| No structured log output | Cannot machine-parse events, filter by level, or aggregate |
| No log levels (DEBUG/INFO/WARN/ERROR) | No way to suppress verbose output or escalate errors |
| No log persistence | All output is ephemeral — nothing written to files or external systems |
| No request/operation tracing | No way to trace a single operation across modules |
| No metrics | No counts of operations, timing, error rates |
| No error context | Errors print a string but lack stack traces, context vars, or correlation IDs |
| No audit trail | Task/goal/workout mutations are not logged as events |
| No health/readiness signals | No structured signal that the system is operational or degraded |

---

## 2. Existing Scheduled/Briefing Jobs

### 2.1 Briefing capabilities (manual CLI, not scheduled)

Janus has **two briefing renderers** but **no scheduler** — they are invoked manually via CLI:

| Command | Entry point | Service | Description |
|---------|-------------|---------|-------------|
| `janus today` | `src/janus/today.py:show_today()` | `services/daily_briefing.py` | Schedule + attention items + suggested focus |
| `janus telegram` | `src/janus/today.py:show_telegram()` | `services/daily_briefing.py` + `integrations/telegram.py` | Same briefing sent to Telegram |
| `janus weekly` | `src/janus/weekly.py:show_weekly()` | `services/weekly_review.py` | Completed/open tasks + goal progress |

### 2.2 Briefing content

**Daily Briefing** (`services/daily_briefing.py`):
- Today's Google Calendar events (via `integrations/google_calendar.py`)
- Attention items from the Attention Engine (`services/attention.py`) — overdue tasks, blocked tasks, due-today, upcoming events, stalled goals
- Suggested focus (top-scored attention item, max 3 items)

**Weekly Review** (`services/weekly_review.py`):
- Completed task titles (parsed from `data/tasks.md`)
- Open task titles
- Goal progress (delegated to `services/goal_progress.py`)

### 2.3 Delivery integrations

| Integration | File | Purpose |
|-------------|------|---------|
| Telegram daily | `integrations/telegram.py` | Send daily briefing via Telegram Bot API |
| Telegram weekly | `integrations/telegram_weekly.py` | Send weekly review via Telegram Bot API |

### 2.4 Scheduler gap

**No scheduling infrastructure exists.** Searched for: `schedule`, `cron`, `apscheduler`, `celery`, `timer`, `periodic` — **zero matches in source code.**

The `janus today` and `janus weekly` commands are designed to be run manually or via an external scheduler (e.g., cron, Hermes cron jobs). There is no built-in mechanism for:
- Time-based triggering
- Retry on failure
- Scheduling state tracking
- Missed-run detection

---

## 3. Recommended Logging Library / Format

### 3.1 Recommendation: Python stdlib `logging` with structured JSON formatter

**Primary choice:** Use Python's built-in `logging` module with a custom JSON formatter (no new dependency required).

**Rationale:**
- **Zero new dependencies** — `logging` is in stdlib, already available
- **Familiar to all Python engineers** — no learning curve
- **Configurable per-module** — `logging.getLogger("janus.services.briefing")`, `logging.getLogger("janus.integrations.telegram")`, etc.
- **Level-based filtering** — DEBUG for dev, INFO for normal ops, WARNING/ERROR for issues
- **Structured output possible** — a custom `Formatter` can emit JSON lines for machine parsing
- **Compatible with file/external handlers** — `FileHandler`, `SysLogHandler`, HTTP handlers available

### 3.2 Alternative: `structlog`

If richer structured logging is desired later, `structlog` is the gold standard for Python structured logging. It binds context to log entries and outputs JSON natively. However, it adds a dependency and is recommended only when stdlib `logging` proves insufficient.

### 3.3 Proposed structured format

For observability logs (not user-facing CLI output), emit JSON lines:

```json
{"ts":"2026-09-02T08:00:00+00:00","level":"info","logger":"janus.services.daily_briefing","msg":"briefing_generated","events":3,"attention_items":5,"suggested_focus":"Review Q3 goals"}
{"ts":"2026-09-02T08:00:01+00:00","level":"error","logger":"janus.integrations.telegram","msg":"send_failed","error":"Bot was blocked","chat_id":"..."}
```

### 3.4 Separation of concerns

| Output type | Mechanism | Destination |
|-------------|-----------|-------------|
| User-facing CLI output | `print()` (unchanged) | stdout/stderr |
| Operational/observability logs | `logging` with JSON formatter | File or stderr (configurable) |
| Audit events (task/goal mutations) | `logging` (INFO level) | Structured log |

This preserves the existing CLI UX while adding a parallel observability channel.

### 3.5 Implementation scope (future work)

- Create a `janus/logging_config.py` module that configures the root logger with a JSON formatter
- Replace `print(..., file=sys.stderr)` error messages with `logger.warning()` or `logger.error()` where operational visibility matters
- Add INFO-level log entries at service boundaries (briefing generated, task added, goal completed, telegram sent)
- Add ERROR-level log entries for integration failures (Telegram API errors, Google Calendar auth failures, file I/O errors)
- Consider a rotating file handler for persistent logs

---

## 4. Summary

| Aspect | Current State | Gap |
|--------|---------------|-----|
| Logging library | None | No structured logging |
| Log output | `print()` to stdout/stderr | No levels, no persistence, no structure |
| Telemetry/Metrics | None | No operational visibility |
| Scheduled jobs | None | Briefings are manual CLI only |
| Briefing content | Rich (daily + weekly) | Exists but not automated |
| Delivery channels | Telegram (daily + weekly) | Works but triggered manually |
| Audit trail | None | Mutations not logged |

**Bottom line:** JANUS has zero observability infrastructure. The CLI works well for interactive use but provides no operational signal for automation, debugging, or monitoring. The recommended first step is adopting stdlib `logging` with a JSON formatter, adding service-boundary log entries, and eventually connecting briefing commands to a scheduler (either Hermes cron or system cron).
