# JANUS Observability & Logging Patterns — Research Report

**Task**: t_8da8ead6 — Research existing observability and logging patterns in JANUS
**Date**: 2026-09-01
**Scope**: `src/janus/`, `scripts/`, `pyproject.toml`

---

## 1. How Daily Briefings Are Generated and Triggered

### 1.1 CLI Entry Points

The briefing pipeline is triggered **on-demand via CLI** — no cron, scheduler, or
daemon exists. The dispatcher lives in `src/janus/__init__.py` (`main()`):

| Command | Handler | Rendering | Delivery |
|---------|---------|-----------|----------|
| `janus today` | `janus.today.show_today()` | stdout print | Terminal |
| `janus telegram` | `janus.today.show_telegram()` | formatted message | Telegram API |
| `janus weekly` | `janus.weekly.show_weekly()` | stdout print | Terminal |
| `janus telegram-weekly` | `janus.telegram_weekly_cli.send_weekly_telegram()` | formatted message | Telegram API |

### 1.2 Daily Briefing Pipeline (`src/janus/today.py`)

```
main() → show_today() / show_telegram()
         └─► _build_today_briefing()          [line 27]
              ├─► list_upcoming_events()       [google_calendar.py]  → list[Event]
              ├─► load_tasks()                 [markdown_tasks.py]   → list[Task]
              ├─► load_goals()                 [markdown_goals.py]   → list[Goal]
              └─► create_daily_briefing()      [daily_briefing.py]
                   └─► get_attention_items()    [attention.py]
                        └─► returns sorted list[AttentionItem]
```

### 1.3 Weekly Review Pipeline (`src/janus/weekly.py`)

```
main() → show_weekly()
         └─► create_weekly_review()            [weekly_review.py]
              ├─► load_goals()
              ├─► load_tasks()
              ├─► _read_completed_task_titles()
              └─► compute_goal_progress()       [goal_progress.py]
```

### 1.4 Telegram Delivery

- Daily: `src/janus/integrations/telegram.py` → `send_briefing()` — POST to Telegram Bot API
- Weekly: `src/janus/integrations/telegram_weekly.py` → `send_weekly()` — same pattern
- Config loaded from `config/config.toml` via `tomllib`

### 1.5 No Automated Triggers

There is **no cron, systemd timer, or event-driven trigger**. Briefings only run
when the user types a command. The `cronjob` and `schedule` searches in code
returned zero matches — only docs mention CI triggers (unrelated).

---

## 2. Existing Logging/Telemetry Libraries and Conventions

### 2.1 No Logging Library

**There is no logging infrastructure in JANUS.** Specifically:

- `import logging` — **0 matches** in entire codebase
- `structlog`, `loguru`, `opentelemetry`, `sentry` — **0 matches**
- `pyproject.toml` dependencies: only `google-api-python-client`, `google-auth-httplib2`,
  `google-auth-oauthlib`, `pyyaml` (runtime), `pytest` (dev)

### 2.2 Current Error/Output Pattern

The codebase uses **plain `print()`** for all output:

| Stream | Usage | Example |
|--------|-------|---------|
| `stdout` | Normal output | `print("JANUS — TODAY")`, `print(f"- {event.title}")` |
| `stderr` | Error messages | `print(f"Error: invalid date: {s}", file=sys.stderr)` |
| `sys.exit(1)` | Fatal CLI errors | After printing error to stderr |

Error handling pattern:
1. Service layer raises `ValueError` with descriptive message
2. CLI handler catches it, prints to stderr, calls `sys.exit(1)`

### 2.3 Exception Conventions

- `FileNotFoundError` — missing config or data files
- `ValueError` — validation failures, not-found records
- `RuntimeError` — Telegram API errors (`send_briefing`)
- `TypeError` — wrong types (tested in goals service)

### 2.4 Existing Diagnostics (Non-Logging)

- `scripts/validate_ci.py` — standalone CI structural check (prints OK/ERROR, no logging)
- `verification.py` — verification pipeline with PASS/FAIL dataclasses (`CheckResult`)
  but uses return values, not logs, for reporting

---

## 3. Recommended Insertion Points for Structured Logs

### 3.1 Priority 1 — Pipeline Entry/Exit (High Value, Low Risk)

| File | Function | What to Log |
|------|----------|-------------|
| `src/janus/__init__.py` | `main()` | `janus.<command>` invocation, args, success/failure, duration |
| `src/janus/today.py` | `_build_today_briefing()` | Start/finish, counts: events, tasks, goals, attention items |
| `src/janus/weekly.py` | `show_weekly()` | Start/finish, counts: completed tasks, open tasks, goals |

### 3.2 Priority 2 — Data Source Fetch (High Value for Debugging)

| File | Function | What to Log |
|------|----------|-------------|
| `src/janus/integrations/google_calendar.py` | `list_upcoming_events()` | Calendar IDs queried, event count per calendar, API latency, auth refresh |
| `src/janus/integrations/google_calendar.py` | `list_events()` | Raw fetch result count, parse failures |
| `src/janus/integrations/markdown_tasks.py` | `load_tasks()` | File path, lines parsed, tasks loaded, parse errors |
| `src/janus/integrations/markdown_goals.py` | `load_goals()` | Goals loaded, validation failures (line number) |
| `src/janus/integrations/workout_md.py` | `load_workouts()` | Workouts loaded, parse errors |

### 3.3 Priority 3 — Attention Engine (Medium Value, Good for Tuning)

| File | Function | What to Log |
|------|----------|-------------|
| `src/janus/services/attention.py` | `get_attention_items()` | Items by category, score distribution, filtered events |

### 3.4 Priority 4 — Delivery Layer (High Value for Reliability)

| File | Function | What to Log |
|------|----------|-------------|
| `src/janus/integrations/telegram.py` | `send_briefing()` | Message size (chars), chat_id (non-secret), API response, errors |
| `src/janus/integrations/telegram_weekly.py` | `send_weekly()` | Same as above |

### 3.5 Priority 5 — Service Layer (Low Value Now, Foundation for Future)

| File | Function | What to Log |
|------|----------|-------------|
| `src/janus/services/tasks.py` | `add_task()`, `complete_task()`, `set_task_state()` | Title, operation, success |
| `src/janus/services/goals.py` | `add_goal()`, `update_goal()`, `complete_goal()` | Title, operation, changes |
| `src/janus/services/goal_progress.py` | `compute_goal_progress()` | Goal title, path taken (metric vs task), result |

---

## 4. Recommended Approach

### 4.1 Library Choice

Use Python's built-in `logging` module. Reasons:

- Zero new dependencies (JANUS has only 4 runtime deps — keep it minimal)
- Industry standard, well-understood, no learning curve
- Configurable levels (DEBUG/INFO/WARNING/ERROR) for CLI vs. daemon contexts
- Structured output achievable via `Formatter` with key=value pairs (no structlog needed)

### 4.2 Integration Strategy

1. **Phase 1 — Silent by default**: Set `logging.basicConfig(level=WARNING)` so normal
   CLI use is unchanged. Add `logger.info()` calls at pipeline boundaries.
2. **Phase 2 — Verbose mode**: Add `--verbose` / `-v` flag to enable INFO-level output
   without changing stdout contract.
3. **Phase 3 — File logging (optional)**: When automated triggers are added (cron/systemd),
   redirect logs to `~/.janus/logs/` for post-mortem debugging.

### 4.3 Conventions to Establish

- Module-level logger: `logger = logging.getLogger(__name__)` — enables per-module level control
- **Never log secrets**: redact `bot_token`, `chat_id`, credentials paths
- Keep stdout contract intact: `print()` for user-facing output, `logger.*()` for diagnostics
- Structured extras: `logger.info("briefing built", extra={"events": 3, "tasks": 7, "goals": 2})`
- Context in errors: include file paths, counts, identifiers — but not PII

---

## 5. Key Files Reference

| File | Role |
|------|------|
| `src/janus/__init__.py` | CLI dispatcher — `main()` |
| `src/janus/today.py` | Daily briefing orchestration |
| `src/janus/weekly.py` | Weekly review orchestration |
| `src/janus/services/daily_briefing.py` | Briefing model assembly |
| `src/janus/services/attention.py` | Attention scoring engine |
| `src/janus/services/weekly_review.py` | Weekly review assembly |
| `src/janus/services/goal_progress.py` | Goal progress computation |
| `src/janus/services/tasks.py` | Task CRUD service |
| `src/janus/services/goals.py` | Goal CRUD service |
| `src/janus/integrations/google_calendar.py` | Google Calendar API client |
| `src/janus/integrations/markdown_tasks.py` | Task markdown parser |
| `src/janus/integrations/markdown_goals.py` | Goals markdown parser |
| `src/janus/integrations/telegram.py` | Daily Telegram delivery |
| `src/janus/integrations/telegram_weekly.py` | Weekly Telegram delivery |
| `src/janus/telegram_weekly_cli.py` | Weekly Telegram CLI renderer |
| `src/janus/tasks_cli.py` | Task CLI handlers |
| `src/janus/goals_cli.py` | Goal CLI handlers |
| `src/janus/workout_cli.py` | Workout CLI handlers |
| `src/janus/verification.py` | Verification pipeline (dataclass-based, not logging) |
| `pyproject.toml` | Dependencies — no logging library |

---

## 6. Summary of Findings

1. **Briefings are CLI-triggered only** — no automation exists. The pipeline is
   synchronous and single-shot: load → score → format → deliver.
2. **Zero logging infrastructure** — the codebase uses `print()` exclusively.
   Error handling is `ValueError` + stderr + `sys.exit(1)`.
3. **Natural attachment points are well-defined** — the service/integration split
   creates clear boundaries where logs can be inserted without crossing concerns.
4. **Python stdlib `logging` is the right fit** — no new dependencies, minimal
   footprint, future-proof for when automation is added.

---

*End of report.*
