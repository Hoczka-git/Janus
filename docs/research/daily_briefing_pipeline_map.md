# JANUS Daily Briefing Pipeline Map

**Generated:** 2026-09-02
**Scope:** End-to-end data flow for the JANUS daily briefing (`janus today` / `janus telegram`)
**Constraint:** Read-only research — no implementation changes

---

## 1. Entry Point

The daily briefing is triggered via CLI command dispatch in `src/janus/__init__.py:main()`.

```
janus today      → show_today()      → stdout (terminal)
janus telegram   → show_telegram()   → Telegram bot API
```

Both commands call the same data-collection pipeline (`_build_today_briefing()`)
and differ only in the final output renderer.

**File:** `src/janus/__init__.py:23-26`

---

## 2. Data Sources

The briefing aggregates data from three independent sources:

### 2.1 Google Calendar (External API)

- **File:** `src/janus/integrations/google_calendar.py`
- **Function:** `list_upcoming_events() -> list[Event]`
- **Config:** `config/config.toml` → `[google_calendar].calendars` (list of calendar IDs)
- **Auth:** OAuth 2.0 via `credentials.json` + cached `token.json`
- **Scope:** `calendar.readonly`
- **Behavior:**
  - Loads calendar IDs from config
  - For each calendar, fetches up to 10 upcoming events via Google Calendar API v3
  - Parses events into `Event` dataclass (title, start, end, all_day, source)
  - Sorts by start time (all-day events last)
  - Returns combined list from all configured calendars

### 2.2 Tasks (Markdown File)

- **File:** `src/janus/integrations/markdown_tasks.py`
- **Function:** `load_tasks() -> list[Task]`
- **Source file:** `data/tasks.md`
- **Format:** `- [ ] Title | due: YYYY-MM-DD | priority: N | state: todo|in_progress|blocked | progress: 0-100`
- **Behavior:**
  - Parses only open tasks (lines starting with `- [ ]`)
  - Extracts metadata: due_date, priority, state, progress
  - Returns list of `Task` dataclass instances

### 2.3 Goals (Markdown File)

- **File:** `src/janus/integrations/markdown_goals.py`
- **Function:** `load_goals() -> list[Goal]`
- **Source file:** `data/goals.md`
- **Format:** Structured markdown blocks (`## Goal: Title`, `Status: active`, `Related tasks:`, etc.)
- **Behavior:**
  - Parses goal blocks into `Goal` dataclass
  - Returns empty list if file missing (no error)
  - Validates fields (status, direction, numeric values)

---

## 3. Transformation Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                     _build_today_briefing()                      │
│                     (src/janus/today.py:27)                     │
│                                                                  │
│  1. Get today's date                                             │
│  2. Fetch all upcoming events (Google Calendar)                  │
│  3. Filter events to today only (e.start.date() == today)        │
│  4. Load open tasks (data/tasks.md)                              │
│  5. Load active goals (data/goals.md)                            │
│  6. Call create_daily_briefing(today_events, tasks, goals, today) │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  create_daily_briefing()                         │
│              (src/janus/services/daily_briefing.py:17)           │
│                                                                  │
│  1. Delegate to Attention Engine:                                │
│     get_attention_items(events, tasks, goals, today)             │
│  2. Take top-scoring item as suggested_focus                     │
│  3. Return DailyBriefing(                                        │
│       events=events,                                             │
│       attention_items=attention_items,                           │
│       suggested_focus=suggested_focus                            │
│     )                                                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   get_attention_items()                          │
│              (src/janus/services/attention.py:29)                │
│                                                                  │
│  For each task:                                                  │
│    - Overdue by N days: score += 100                             │
│    - Due today: score += 80                                      │
│    - Priority >= 3: score += 50                                  │
│    - Priority == 2 (if already qualifies): score += 20           │
│    - State == blocked: score += 30                               │
│    - State == in_progress: score += 30                           │
│                                                                  │
│  For each event (today, future):                                 │
│    - Upcoming event: score = 10, reason = "Starts in N minutes"  │
│                                                                  │
│  For each active goal:                                           │
│    - All related tasks completed (stalled): score += 40          │
│    - Has open related tasks: skipped (not stalled)               │
│    - Missing references: skipped                                 │
│                                                                  │
│  Sort: highest score first, then category, then title            │
│  Return: sorted list[AttentionItem]                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Output Destinations

### 4.1 Terminal (stdout)

- **Function:** `show_today()` in `src/janus/today.py:44`
- **Renderer:** Plain text via `print()`
- **Sections:**
  - `SCHEDULE` — today's events with time and source
  - `REQUIRES ATTENTION` — top 3 attention items with reasons
  - `SUGGESTED FOCUS` — single highest-scoring item (if any)

### 4.2 Telegram

- **Function:** `show_telegram()` in `src/janus/today.py:81`
- **Integration:** `src/janus/integrations/telegram.py:send_briefing()`
- **Config:** `config/config.toml` → `[telegram].bot_token` + `[telegram].chat_id`
- **Format:** Compact text with emoji markers (📅, ⚠, 🎯)
- **Transport:** HTTP POST to `https://api.telegram.org/bot{token}/sendMessage`
- **Top-N:** Same 3-item limit as terminal renderer

---

## 5. Scheduling

**Status: No automated scheduling exists.**

The daily briefing is purely manual — triggered by user invocation via CLI.
There is no cron job, systemd timer, launchd agent, or any other scheduling mechanism
in the current codebase.

The `janus telegram` command is designed to be scheduled externally (e.g., via cron
or Hermes cronjob), but no such configuration is present in the repository.

---

## 6. Observability Assessment

### Current State

- **Structured logging:** None. Zero usage of Python `logging` module anywhere in the codebase.
- **Output:** All user-facing output via `print()` to stdout.
- **Error handling:** Exceptions propagate to CLI (unhandled); no error logging.
- **Telemetry:** None. No metrics, no tracing, no event tracking.

### Injection Points (Non-Disruptive)

The following points are candidates for structured observability logs.
Each is chosen to avoid disrupting the existing data flow:

| # | Location | Event | Data Available |
|---|----------|-------|----------------|
| 1 | `_build_today_briefing()` — after data collection | `briefing.data_collected` | event_count, task_count, goal_count, today |
| 2 | `get_attention_items()` — after scoring | `briefing.attention_scored` | item_count, top_score, categories present |
| 3 | `create_daily_briefing()` — after assembly | `briefing.assembled` | attention_item_count, has_suggested_focus |
| 4 | `show_telegram()` — before send | `briefing.telegram_send` | chat_id, message_length |
| 5 | `send_briefing()` — after send | `briefing.telegram_sent` | response_ok, message_id (from Telegram response) |
| 6 | `main()` — command dispatch | `cli.command_invoked` | command, argv |

### Recommended Approach

Inject structured logging at the service layer (`daily_briefing.py`, `attention.py`)
rather than the integration layer, to keep observability concerns separate from I/O.

Use Python's standard `logging` module with a structured formatter (e.g., JSON lines)
to a local log file (`data/logs/briefing.log` or similar). This avoids coupling
observability to any specific output destination.

---

## 7. Data Flow Summary

```
CLI (janus today / janus telegram)
    │
    ├──► Google Calendar API ──────────► list[Event]
    │
    ├──► data/tasks.md ────────────────► list[Task]
    │
    ├──► data/goals.md ────────────────► list[Goal]
    │
    ▼
_build_today_briefing()
    │
    ├── Filter events to today
    │
    ▼
create_daily_briefing()
    │
    ├──► get_attention_items() ───────► list[AttentionItem] (scored, sorted)
    │
    ▼
DailyBriefing dataclass
    │
    ├──► show_today() ─────────────────► stdout (terminal)
    │
    └──► show_telegram() ──────────────► Telegram bot API
```

---

## 8. Key Files Reference

| File | Role |
|------|------|
| `src/janus/__init__.py` | CLI entry point, command dispatch |
| `src/janus/today.py` | Daily briefing renderer, data collection orchestrator |
| `src/janus/services/daily_briefing.py` | Briefing assembly (delegates to Attention Engine) |
| `src/janus/services/attention.py` | Deterministic scoring and ranking |
| `src/janus/models/daily_briefing.py` | DailyBriefing dataclass |
| `src/janus/models/attention.py` | AttentionItem dataclass |
| `src/janus/models/event.py` | Event dataclass |
| `src/janus/models/task.py` | Task dataclass |
| `src/janus/models/goal.py` | Goal dataclass |
| `src/janus/integrations/google_calendar.py` | Google Calendar API client |
| `src/janus/integrations/markdown_tasks.py` | Task markdown parser |
| `src/janus/integrations/markdown_goals.py` | Goal markdown parser |
| `src/janus/integrations/telegram.py` | Telegram bot sender |
| `config/config.example.toml` | Configuration template |
| `data/tasks.md` | Task data store |
| `data/goals.md` | Goal data store |
