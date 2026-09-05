# JANUS Briefing System & Observability Gaps — Findings Report

**Task**: t_cafbe5f0 — Investigate current JANUS briefing system and observability gaps
**Date**: 2026-09-02
**Scope**: `src/janus/`, `tests/`, `config/`, `data/`, `pyproject.toml`
**Constraint**: Research only — no implementation changes

---

## 1. How the Daily Briefing Is Currently Generated and Delivered

### 1.1 CLI Entry Points (No Automation)

The briefing pipeline is triggered **on-demand via CLI** — no cron, systemd timer, or event-driven trigger exists. The dispatcher lives in `src/janus/__init__.py:main()`:

| Command | Handler | Rendering | Delivery |
|---------|---------|-----------|----------|
| `janus today` | `janus.today.show_today()` | stdout `print()` | Terminal |
| `janus telegram` | `janus.today.show_telegram()` | `format_telegram_message()` | Telegram Bot API |
| `janus weekly` | `janus.weekly.show_weekly()` | stdout `print()` | Terminal |
| `janus telegram-weekly` | `janus.telegram_weekly_cli.send_weekly_telegram()` | `format_weekly_message()` | Telegram Bot API |

### 1.2 Daily Briefing Pipeline

```
main() → show_today() / show_telegram()
         └─► _build_today_briefing()               [today.py:27]
              ├─► list_upcoming_events()            [google_calendar.py:123]
              │    └─► list_events(calendar_id)     [google_calendar.py:100]
              ├─► load_tasks()                      [markdown_tasks.py:14]
              ├─► load_goals()                      [markdown_goals.py:21]
              └─► create_daily_briefing()           [daily_briefing.py:17]
                   └─► get_attention_items()         [attention.py:29]
                        └─► returns sorted list[AttentionItem]
```

**Data flow**:
1. `_build_today_briefing()` collects today's events (filtered from Google Calendar), open tasks, and active goals
2. `create_daily_briefing()` delegates to the Attention Engine for deterministic prioritization
3. The Attention Engine scores items by: overdue (+100), due today (+80), high priority (+50), blocked (+30), in-progress (+30), upcoming event (+10), stalled goal (+40)
4. Items are sorted by `(-score, category, title)` — deterministic ordering
5. Top item becomes `suggested_focus`; top 3 become `attention_items`

### 1.3 Weekly Review Pipeline

```
main() → show_weekly()
         └─► create_weekly_review()                 [weekly_review.py:33]
              ├─► load_goals()
              ├─► load_tasks()
              ├─► _read_completed_task_titles()     [weekly_review.py:18]
              └─► compute_goal_progress()            [goal_progress.py:10]
```

### 1.4 Telegram Delivery

- **Daily**: `src/janus/integrations/telegram.py:send_briefing()` — POST to `https://api.telegram.org/bot{bot_token}/sendMessage`
- **Weekly**: `src/janus/integrations/telegram_weekly.py:send_weekly()` — identical pattern
- Config loaded from `config/config.toml` via `tomllib` (bot_token, chat_id)
- Uses `urllib.request` (no `requests` dependency)
- Error handling: checks `body["ok"]`; raises `RuntimeError` on API error

### 1.5 Data Sources

| Source | File | Format | Parser |
|--------|------|--------|--------|
| Google Calendar | `integrations/google_calendar.py` | Google Calendar API v3 JSON | `parse_event()` |
| Tasks | `integrations/markdown_tasks.py` | `data/tasks.md` (markdown checklist) | `load_tasks()` |
| Goals | `integrations/markdown_goals.py` | `data/goals.md` (structured markdown) | `load_goals()` |
| Workouts | `integrations/workout_md.py` | `data/workouts.md` (key=value) | `load_workouts()` |

**Note**: Workouts are loaded by `workout_cli.py` but are NOT wired into either briefing pipeline — they exist as a standalone feature.

---

## 2. What Logging/Observability Already Exists

### 2.1 No Logging Library

**There is zero logging infrastructure in JANUS.** Specifically:

- `import logging` — **0 matches** in entire codebase
- `structlog`, `loguru`, `opentelemetry`, `sentry` — **0 matches**
- `pyproject.toml` dependencies: only `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`, `pyyaml` (runtime), `pytest` (dev)

### 2.2 Current Output/Error Pattern

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

| Exception | Where | Meaning |
|-----------|-------|---------|
| `FileNotFoundError` | `telegram.py`, `markdown_tasks.py` | Missing config or data file |
| `ValueError` | Services, models | Validation failures, not-found records |
| `RuntimeError` | `telegram.py`, `telegram_weekly.py` | Telegram API errors |
| `TypeError` | Tested in goals service | Wrong types |

### 2.4 Existing Diagnostics (Non-Logging)

- `scripts/validate_ci.py` — standalone CI structural check (prints OK/ERROR, no logging)
- `verification.py` — verification pipeline with PASS/FAIL dataclasses (`CheckResult`, `VerificationReport`) but uses return values + `print(json.dumps(...))`, not logs, for reporting

### 2.5 What's Already Documented

Two prior research artifacts exist in the repo root:

1. **`research_observability_logging.md`** (214 lines) — Research report from t_8da8ead6. Covers: pipeline map, no-logging finding, recommended insertion points (5 priority tiers), library choice (stdlib `logging`), conventions.
2. **`OBSERVABILITY_PLAN.md`** (515 lines) — Detailed instrumentation plan from t_abd4c594. Covers: 12 event types with exact schemas, field propagation strategy (`briefing_id`), per-file instrumentation map, implementation order, verification steps.

These documents are comprehensive and this report aligns with them — see §4 for the recommended integration approach.

---

## 3. Where Structured Logs Could Be Injected

### 3.1 Priority 1 — Pipeline Entry/Exit (High Value, Low Risk)

| File | Function | What to Log |
|------|----------|-------------|
| `src/janus/__init__.py` | `main()` | Command invocation, args, success/failure, duration |
| `src/janus/today.py` | `_build_today_briefing()` | Start/finish; counts: events, tasks, goals, attention items |
| `src/janus/services/weekly_review.py` | `create_weekly_review()` | Start/finish; counts: completed tasks, open tasks, goal reviews |

### 3.2 Priority 2 — Data Source Fetch (High Value for Debugging)

| File | Function | What to Log |
|------|----------|-------------|
| `src/janus/integrations/google_calendar.py` | `list_upcoming_events()` | Calendar IDs queried, event count per calendar, API latency |
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
| `src/janus/services/tasks.py` | `add_task()`, `complete_task()`, `set_task_state()`, `set_task_progress()` | Title, operation, success |
| `src/janus/services/goals.py` | `add_goal()`, `update_goal_fields()`, `complete_goal()` | Title, operation, changes |
| `src/janus/services/goal_progress.py` | `compute_goal_progress()` | Goal title, path taken (metric vs task), result |

### 3.6 Propagation Strategy

The recommended approach (from `OBSERVABILITY_PLAN.md`) is explicit `briefing_id` passing:

```
main()                          ← briefing_id = uuid.uuid4().hex
  ├─ _build_today_briefing(briefing_id)
  │    ├─ list_upcoming_events(briefing_id=briefing_id)
  │    ├─ load_tasks(briefing_id=briefing_id)
  │    ├─ load_goals(briefing_id=briefing_id)
  │    └─ create_daily_briefing(...)
  │         └─ get_attention_items(briefing_id=briefing_id)
  ├─ show_today() / show_telegram()
  │    └─ send_briefing(briefing, briefing_id=briefing_id)
  └─ show_weekly()
       └─ create_weekly_review(briefing_id=briefing_id)
```

Each function accepts `briefing_id: str | None = None` — defaults to `None` so existing callers (tests, direct scripts) don't break.

---

## 4. Recommended Format/Schema

### 4.1 Library Choice

**Python stdlib `logging`** — zero new dependencies. Reasons:
- JANUS has only 4 runtime deps — adding a logging library is disproportionate
- Industry standard, well-understood
- Structured output achievable via JSON message + standard formatter
- Future-proof for when automation is added

### 4.2 Output Format

Each log line is a single line on **stderr** (stdout remains exclusive to user-facing `print()` output):

```
2026-09-01T10:00:00.123456+02:00 [INFO] janus.today {"event": "janus.briefing.generation_finished", "briefing_id": "a1b2c3d4", "events_today": 3, "tasks_loaded": 7, ...}
```

The entire event envelope is a JSON string in the `msg` argument; the formatter prepends `asctime [levelname] name`.

### 4.3 Event Catalog (12 Event Types)

| Event | Level | When |
|-------|-------|------|
| `janus.command.started` | INFO | Once per CLI invocation, at top of `main()` |
| `janus.command.finished` | INFO/WARNING | Once per CLI invocation, at end of `main()` |
| `janus.briefing.generation_started` | INFO | When `_build_today_briefing()` or `create_weekly_review()` begins |
| `janus.briefing.generation_finished` | INFO | When generation returns — counts by source |
| `janus.source.calendar_fetched` | INFO | Once per calendar after API call |
| `janus.source.tasks_loaded` | INFO | When `load_tasks()` returns |
| `janus.source.goals_loaded` | INFO | When `load_goals()` returns |
| `janus.source.workouts_loaded` | INFO | When `load_workouts()` returns (contingent) |
| `janus.engine.attention_computed` | INFO | When `get_attention_items()` returns |
| `janus.delivery.telegram_sent` | INFO/WARNING | After Telegram POST completes |
| `janus.service.task_write` | INFO | After successful task mutation |
| `janus.service.goal_write` | INFO | After successful goal mutation |

### 4.4 Canonical Event Envelope

```json
{
  "event": "janus.briefing.generation_finished",
  "briefing_id": "a1b2c3d4",
  "briefing_type": "daily",
  "duration_ms": 845,
  "source_calendars": 2,
  "events_total": 5,
  "events_today": 3,
  "tasks_loaded": 7,
  "goals_loaded": 2,
  "attention_items": 9,
  "attention_by_category": {"overdue_task": 2, "due_today": 3},
  "suggested_focus_present": true,
  "timestamp": "2026-09-01T10:00:00.123Z"
}
```

### 4.5 What Never Goes in Logs

- `bot_token` — never, in any form
- `chat_id` — log it (it's not a public secret), but flag for user confirmation
- File contents (task titles are OK — user data, not secrets)
- Full exception tracebacks in INFO events — use `str(e)` only

### 4.6 Default Behavior

- **Silent by default**: `logging.WARNING` and above only
- **`--verbose` / `-v` flag**: enables INFO-level output without changing stdout contract
- **Phase 3 (future)**: file logging to `~/.janus/logs/` when automated triggers are added

---

## 5. Key Files Reference

| File | Role | Instrumentation Priority |
|------|------|------------------------|
| `src/janus/__init__.py` | CLI dispatcher — `main()` | P1 |
| `src/janus/today.py` | Daily briefing orchestration | P1 |
| `src/janus/weekly.py` | Weekly review orchestration (thin) | P1 |
| `src/janus/services/daily_briefing.py` | Briefing model assembly | — (covered by today.py) |
| `src/janus/services/attention.py` | Attention scoring engine | P3 |
| `src/janus/services/weekly_review.py` | Weekly review assembly | P1 |
| `src/janus/services/goal_progress.py` | Goal progress computation | P5 |
| `src/janus/services/tasks.py` | Task CRUD service | P5 |
| `src/janus/services/goals.py` | Goal CRUD service | P5 |
| `src/janus/integrations/google_calendar.py` | Google Calendar API client | P2 |
| `src/janus/integrations/markdown_tasks.py` | Task markdown parser | P2 |
| `src/janus/integrations/markdown_goals.py` | Goals markdown parser | P2 |
| `src/janus/integrations/workout_md.py` | Workout markdown parser | P2 (contingent) |
| `src/janus/integrations/telegram.py` | Daily Telegram delivery | P4 |
| `src/janus/integrations/telegram_weekly.py` | Weekly Telegram delivery | P4 |
| `src/janus/telegram_weekly_cli.py` | Weekly Telegram CLI renderer | — (thin) |
| `src/janus/tasks_cli.py` | Task CLI handlers | — |
| `src/janus/goals_cli.py` | Goal CLI handlers | — |
| `src/janus/workout_cli.py` | Workout CLI handlers | — |
| `src/janus/verification.py` | Verification pipeline (dataclass-based) | — |
| `pyproject.toml` | Dependencies — no logging library | — |

---

## 6. Existing Test Infrastructure (Relevant for Verification)

Tests use `unittest.mock.patch` extensively to mock data sources — this pattern is compatible with logging instrumentation:

- `tests/test_today.py` — `_capture_show_today()` mocks `list_upcoming_events`, `load_tasks`, `load_goals`, and `date`
- `tests/test_daily_briefing.py` — Tests `create_daily_briefing()` directly with model instances
- `tests/test_weekly_review.py` — Uses `tmp_path` fixture to create temp `tasks.md` / `goals.md`
- `tests/test_attention.py` — Tests scoring logic in isolation
- `tests/test_telegram.py` — Mocks `urllib.request.urlopen` with `_MockResponse`

**Verification approach after implementation**: `python -m pytest tests/ -q` — existing tests must still pass. The `briefing_id` parameter defaults to `None`, so no test changes are required for the core instrumentation.

---

## 7. Summary of Findings

1. **Briefings are CLI-triggered only** — no automation exists. The pipeline is synchronous and single-shot: load → score → format → deliver.
2. **Zero logging infrastructure** — the codebase uses `print()` exclusively. Error handling is `ValueError` + stderr + `sys.exit(1)`.
3. **Natural attachment points are well-defined** — the service/integration split creates clear boundaries where logs can be inserted without crossing concerns.
4. **Two prior research documents exist** (`research_observability_logging.md`, `OBSERVABILITY_PLAN.md`) and provide detailed schemas — this report confirms and synthesizes their findings.
5. **Python stdlib `logging` is the right fit** — no new dependencies, minimal footprint, future-proof for when automation is added.
6. **Workouts exist but are not wired into briefing pipelines** — instrumentation is contingent on future integration.
7. **Test infrastructure is compatible** — mocking patterns already in place will not conflict with logging; `briefing_id` defaults to `None` preserve backward compatibility.

---

## 8. Recommended Next Steps

1. **Review & approve** this findings document + the existing `OBSERVABILITY_PLAN.md`
2. **Create implementation task** for `src/janus/logging_config.py` (the `setup_logging()` entry point)
3. **Create implementation task** for P1 instrumentation (`main()`, `_build_today_briefing()`, `create_weekly_review()`)
4. **Create implementation task** for P2–P5 instrumentation (sources, engine, delivery, services)
5. **Add `--verbose` flag** to `main()` dispatch
6. **Verify** with existing test suite after each phase

---

*End of report.*
