# Janus Planning & Calendar Integration — Findings Report

## Question Investigated

1. How does daily/weekly planning currently work?
2. Is calendar availability data already accessible or does it need integration?
3. What are the existing data models for tasks, events, and time blocks?
4. Any existing overload detection or focus block logic?

---

## 1. Current Daily/Weekly Planning Flow

### Daily (`janus today`)
```
Google Calendar API ──► list_upcoming_events() ──► Event objects
data/tasks.md ────────► load_tasks() ──────────► Task objects
data/goals.md ────────► load_goals() ──────────► Goal objects
                                │
                                ▼
                    create_daily_briefing() ──► DailyBriefing
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
            show_today()            send_briefing()
            (CLI render)            (Telegram delivery)
```

**Components:**
- `src/janus/today.py` — renderer with `show_today()` and `show_telegram()`
- `src/janus/services/daily_briefing.py` — assembles the briefing
- `src/janus/services/attention.py` — deterministic scoring engine
- `src/janus/models/daily_briefing.py` — `DailyBriefing` model
- `src/janus/models/attention.py` — `AttentionItem` model

**Attention Engine scoring:**
| Category | Score | Trigger |
|----------|-------|---------|
| `overdue_task` | 100 | due_date < today |
| `due_today` | 80 | due_date == today |
| `high_priority_task` | 50 | priority >= 3 |
| `goal_stalled` | 40 | all related tasks completed |
| `blocked_task` | 30 | state == blocked |
| `in_progress_task` | 30 | state == in_progress |
| `upcoming_event` | 10 | event starting soon |

**Sort order:** highest score → category alphabetical → title alphabetical.

**Renderer limit:** Top 3 attention items shown (recent commit `1230b1c` expanded to top 3 suggested focus items).

### Weekly (`janus weekly`)
- `src/janus/weekly.py` — renderer
- `src/janus/services/weekly_review.py` — aggregates completed tasks, open tasks, goal progress
- `src/janus/models/weekly_review.py` — `WeeklyReview`, `GoalReview`

---

## 2. Calendar Availability Data

### Already accessible (EXISTS, read-only)

**Integration:** `src/janus/integrations/google_calendar.py`
- OAuth-based authentication (scope: `calendar.readonly`)
- Multi-calendar support via `config/config.toml`
- `get_calendar_service()` — handles token refresh
- `parse_event()` — converts Google API response to `Event` model (handles both timed and all-day events)
- `list_events(calendar_id)` — fetches up to `maxResults=10` events from a specific calendar
- `list_upcoming_events()` — loads config, queries all calendars, merges + sorts by start time

**Configuration** (`config/config.example.toml`):
```toml
[google_calendar]
[[google_calendar.calendars]]
id = "JOB_CALENDAR_ID"
name = "Job"
[[google_calendar.calendars]]
id = "PERSONAL_CALENDAR_ID"
name = "Personal"
```

### Current limitations (READ-ONLY scope constraints)
- **No write access** — cannot create/modify/delete events
- **maxResults=10** hardcoded — limited forward visibility (only next 10 events per calendar)
- **No free/busy query** — Google Calendar API supports `freebusy` queries but they are not used
- **No busy-hour aggregation** — no logic to compute "I'm busy 9-12, free 12-1, busy 1-5"
- **No recurrence expansion logic** beyond `singleEvents=true` (Google handles basic expansion)
- **No location, attendees, reminders, or color metadata** — event model is minimal

### What needs integration for full planning
1. **Free/busy computation** — identify available time slots
2. **Calendar write scope** (optional, requires user consent) — create focus blocks
3. **maxResults increase** or pagination — full-day or full-week visibility
4. **Conflict detection** — overlapping events

---

## 3. Existing Data Models

### Event (`models/event.py`)
```python
@dataclass
class Event:
    title: str
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    source: str | None = None  # calendar name from config
```
- No duration, location, attendees, recurrence, status
- No color or category metadata
- `end` can be None (all-day events have no end)

### Task (`models/task.py`)
```python
@dataclass
class Task:
    title: str
    due_date: date | None = None
    priority: int = 1
    state: str | None = None      # todo | in_progress | blocked
    progress: int | None = None   # 0-100
    extra_metadata: list[str] | None = None
```
- No time estimate, no calendar link, no time block reference
- States: `todo`, `in_progress`, `blocked` (completion = `[x]` checkbox, not a state)
- Priority is integer >= 1 (no upper bound enforced)

### Goal (`models/goal.py`)
```python
@dataclass
class Goal:
    title: str
    description: str = ""
    status: str = "active"           # active | completed | inactive
    deadline: str | None = None      # ISO date YYYY-MM-DD
    metric_name: str | None = None
    metric_unit: str | None = None
    start_value: float | None = None
    current_value: float | None = None
    target_value: float | None = None
    direction: str | None = None     # increase | decrease
    related_tasks: list[str] | None = None
```
- Two progress paths: metric-based or task-based (delegated to `services/goal_progress.py`)
- `related_tasks` links to task titles (string references, not object references)

### DailyBriefing (`models/daily_briefing.py`)
```python
@dataclass
class DailyBriefing:
    events: list[Event]
    attention_items: list[AttentionItem] = field(default_factory=list)
    suggested_focus: AttentionItem | None = None
```
- Recently expanded to support top 3 focus items (commit `1230b1c`)

### AttentionItem (`models/attention.py`)
```python
@dataclass
class AttentionItem:
    title: str
    reason: str
    score: int
    category: str
    focus: bool = False  # True when in top suggested focus set
```

### WeeklyReview (`models/weekly_review.py`)
```python
@dataclass
class WeeklyReview:
    completed_tasks: list[str]
    open_tasks: list[str]
    goals: list[GoalReview]
```

### ⚠️ No Time Block Model Exists
There is no data structure representing a focus block, time block, scheduled work period, or availability window. The concept of "blocking 2 hours for deep work" does not exist in the codebase.

---

## 4. Overload Detection & Focus Block Logic

### Overload detection: NONE
- No logic for detecting scheduling overload (too many events + too many tasks)
- No conflict detection (overlapping calendar events)
- No "busy hours" vs "free hours" computation
- No workload scoring or capacity estimation

### Focus block logic: PARTIAL (suggestion-only)
- `AttentionItem.focus` flag exists — marks items as part of the suggested focus set
- `DailyBriefing.suggested_focus` — top-scored item (or top 3 in recent version)
- **What it does:** Recommends what to work on
- **What it does NOT do:**
  - Block calendar time for deep work
  - Identify free time slots in schedule
  - Create calendar events for focus blocks
  - Estimate task duration or count time needed
  - Warn when there's not enough free time

---

## 5. Summary: What Exists vs What's Missing

| Capability | Status | Location |
|-----------|--------|----------|
| Calendar event reading | ✅ EXISTS | `integrations/google_calendar.py` |
| Multi-calendar support | ✅ EXISTS | config.toml |
| Daily briefing assembly | ✅ EXISTS | `services/daily_briefing.py` |
| Attention scoring engine | ✅ EXISTS | `services/attention.py` |
| Weekly review aggregation | ✅ EXISTS | `services/weekly_review.py` |
| Goal progress tracking | ✅ EXISTS | `services/goal_progress.py` |
| Task CRUD (add/complete/state/progress) | ✅ EXISTS | `services/tasks.py` |
| Goal CRUD | ✅ EXISTS | `services/goals.py` |
| Telegram delivery | ✅ EXISTS | `integrations/telegram.py`, `integrations/telegram_weekly.py` |
| Markdown persistence (tasks/goals) | ✅ EXISTS | `integrations/markdown_tasks.py`, `integrations/markdown_goals.py` |
| Free/busy slot computation | ❌ MISSING | — |
| Overload detection | ❌ MISSING | — |
| Focus block scheduling | ❌ MISSING | — |
| Task duration estimation | ❌ MISSING | — |
| Conflict detection (overlapping events) | ❌ MISSING | — |
| Calendar write access (create events) | ❌ MISSING | — |
| Time block data model | ❌ MISSING | — |
| Busy-hours aggregation | ❌ MISSING | — |

---

## 6. Recommended Minimal Integration Points

For adding planning/calendar-aware capabilities:

### A. Free/Busy Computation (new service)
- **Where:** `src/janus/services/freebusy.py` (new)
- **Input:** Calendar events for a date range
- **Output:** List of free time slots (gaps between events)
- **Dependencies:** Existing `list_upcoming_events()` — but needs maxResults increase or pagination
- **Algorithm:** Sort events, merge overlaps, find gaps

### B. Overload Detection (new service)
- **Where:** `src/janus/services/overload.py` (new)
- **Input:** Events + tasks + config thresholds
- **Output:** Warning level + reason (e.g., "6 hours of meetings, 5 tasks due today")
- **Dependencies:** Existing `list_upcoming_events()`, `load_tasks()`
- **Rules:** Count busy hours vs available hours; count overdue + due-today tasks

### C. Time Block Model (new model)
- **Where:** `src/janus/models/time_block.py` (new)
- **Fields:** `start`, `end`, `title`, `type` (focus | meeting | break), `source` (manual | auto)
- **Persistence:** Optional — could live in `data/time_blocks.md` or just be computed

### D. Integration with Today Briefing
- Extend `_build_today_briefing()` to also compute free slots and overload warnings
- Add sections to `DailyBriefing`:
  - `free_slots: list[TimeBlock]`
  - `overload_warning: str | None`
- Extend `show_today()` renderer to display these

### E. (Optional) Calendar Write Access
- **Scope change:** `calendar.readonly` → `calendar.events` (requires re-auth)
- **New methods:** `create_event()`, `update_event()`, `delete_event()`
- **Use case:** Auto-create focus blocks in calendar
- **Risk:** User must re-run OAuth flow; broader permission scope

---

## 7. Key Constraints

1. **Calendar API is read-only** — any write operations require scope upgrade + user re-auth
2. **maxResults=10** — limited forward visibility; full-day planning needs this increased
3. **No historical calendar data** — only upcoming events are fetched
4. **No duration data on tasks** — tasks have due dates but no estimated hours
5. **String-based task references** — goals reference tasks by title, not by ID

---

## 8. Evidence Sources

- `src/janus/integrations/google_calendar.py` — Google Calendar integration (lines 1-144)
- `src/janus/today.py` — Daily briefing renderer (lines 1-104)
- `src/janus/services/daily_briefing.py` — Briefing assembly (lines 1-36)
- `src/janus/services/attention.py` — Attention engine (lines 1-157)
- `src/janus/weekly.py` — Weekly renderer (lines 1-50)
- `src/janus/services/weekly_review.py` — Weekly review service (lines 1-102)
- `src/janus/models/event.py` — Event model (lines 1-11)
- `src/janus/models/task.py` — Task model (lines 1-26)
- `src/janus/models/goal.py` — Goal model (lines 1-51)
- `src/janus/models/daily_briefing.py` — DailyBriefing model (lines 1-12)
- `src/janus/models/attention.py` — AttentionItem model (lines 1-20)
- `src/janus/models/weekly_review.py` — WeeklyReview models (lines 1-23)
- `src/janus/services/goal_progress.py` — Goal progress computation (lines 1-115)
- `src/janus/services/tasks.py` — Task CRUD service (lines 1-231)
- `src/janus/integrations/markdown_tasks.py` — Task persistence (lines 1-199)
- `src/janus/integrations/markdown_goals.py` — Goal persistence (lines 1-220)
- `src/janus/integrations/telegram.py` — Telegram delivery (lines 1-113)
- `src/janus/integrations/telegram_weekly.py` — Weekly Telegram delivery (lines 1-109)
- `src/janus/__init__.py` — CLI entry point / command dispatch (lines 1-90)
- `config/config.example.toml` — Configuration template (lines 1-12)
- `tests/test_daily_briefing.py` — Daily briefing tests (lines 1-172)
- `tests/test_attention.py` — Attention engine tests (lines 1-288)
- `tests/test_google_calendar.py` — Google Calendar integration tests
- `tests/test_weekly_review.py` — Weekly review tests
- `docs/vision.md` — System vision document
- `docs/roadmap.md` — Strategic roadmap
- `docs/decisions/001-hermes-janus-system-model.md` — ADR-001 system model decision
