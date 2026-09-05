# Janus Daily Briefing — Data Sources Findings

**Task:** t_88a16528 — Locate and document Janus briefing data sources
**Date:** 2026-08-31
**Scope:** Read-only investigation of the daily briefing data pipeline

---

## 1. Overview — How the Daily Briefing Is Built

The daily briefing screen is assembled by `janus/today.py` (`_build_today_briefing()`) and rendered in two modes:

- `show_today()` — CLI stdout output
- `show_telegram()` → `send_briefing()` — Telegram message delivery

The pipeline:

```
Google Calendar API ──→ list_upcoming_events() ──→ today_events (filtered to today)
data/tasks.md ────────→ load_tasks() ────────────→ tasks (OPEN ONLY)
data/goals.md ────────→ load_goals() ────────────→ goals
                              │
                              ▼
                    create_daily_briefing(events, tasks, goals, today)
                              │
                              ▼
                    Attention Engine (get_attention_items)
                              │
                              ▼
                    DailyBriefing(events, attention_items, suggested_focus)
                              │
                              ▼
                    Renderer (today.py / telegram.py) — limits to 3 items
```

---

## 2. Data Sources

### 2.1 Events — Google Calendar

| Aspect | Detail |
|--------|--------|
| **File** | `src/janus/integrations/google_calendar.py` |
| **Function** | `list_upcoming_events()` (line 123) |
| **Source** | Google Calendar API v3 (`service.events().list(...)`) |
| **Config** | `config/config.toml` → `[google_calendar].calendars[]` (id + name) |
| **Auth** | OAuth via `credentials.json` / `token.json` |
| **Filter** | `timeMin = now`, `maxResults=10`, `singleEvents=True`, `orderBy="startTime"` |
| **Per-calendar limit** | 10 events per calendar (no pagination across calendars) |
| **Post-filter** | `today.py:35-38` — client-side filter: `e.start.date() == today` |
| **Sort** | All-day first, then by `start` datetime (line 137-140) |
| **Model** | `Event(title, start, end, all_day, source)` |

### 2.2 Tasks — Markdown File

| Aspect | Detail |
|--------|--------|
| **File** | `src/janus/integrations/markdown_tasks.py` |
| **Function** | `load_tasks()` (line 14) |
| **Source** | `data/tasks.md` (project root) |
| **Filter** | **OPEN ONLY** — skips lines not starting with `- [ ]` |
| **Parser** | `_parse_task_line()` — extracts title, due_date, priority, state, progress, extra_metadata |
| **Model** | `Task(title, due_date, priority, state, progress, extra_metadata)` |
| **States** | `ALLOWED_STATES = {"todo", "in_progress", "blocked"}` — `done` is NOT a valid state |

**Critical:** `load_tasks()` returns only open tasks. Completed tasks (`- [x]`) are filtered out at the loader level (line 25: `if not line.startswith("- [ ]"): continue`).

### 2.3 Goals — Markdown File

| Aspect | Detail |
|--------|--------|
| **File** | `src/janus/integrations/markdown_goals.py` |
| **Function** | `load_goals()` (line 21) |
| **Source** | `data/goals.md` (project root) |
| **Parser** | Line-by-line block parser triggered by `## Goal:` headers |
| **Fields parsed** | title, description, status, deadline, metric_name, metric_unit, start_value, current_value, target_value, direction, related_tasks |
| **Model** | `Goal(title, description, status, deadline, metric_name, metric_unit, start_value, current_value, target_value, direction, related_tasks)` |
| **Statuses** | `"active"`, `"completed"`, `"inactive"` |

---

## 3. Tasks Requiring Attention

The Attention Engine (`src/janus/services/attention.py`) produces a ranked list of `AttentionItem` objects.

### 3.1 Scoring Rules

| Condition | Score | Category |
|-----------|-------|----------|
| Overdue (due_date < today) | +100 | `overdue_task` |
| Due today (due_date == today) | +80 | `due_today` |
| Priority >= 3 | +50 | `high_priority_task` |
| Priority == 2 (only if already qualifies) | +20 | (accumulates) |
| State = blocked | +30 | `blocked_task` |
| State = in_progress | +30 | `in_progress_task` |
| Upcoming event (today, future) | +10 | `upcoming_event` |
| Goal stalled (all related tasks completed) | +40 | `goal_stalled` |

### 3.2 Inclusion Rules

- Task qualifies if `score > 0`
- Priority 2 alone does NOT qualify (only accumulates if other conditions already triggered)
- In-progress tasks always get +30 (even with no other triggers)
- Events: only today's future events (past events excluded)
- Goals: only `status == "active"` with non-empty `related_tasks` where ALL existing related tasks are completed

### 3.3 Sort/Filter Logic

```python
items.sort(key=lambda i: (-i.score, i.category, i.title))
```

- Primary: descending score
- Secondary: category name (alphabetical)
- Tertiary: title (alphabetical) — deterministic tie-breaking

### 3.4 Pagination / Limits

- **Engine:** Returns ALL qualifying items (no limit)
- **Renderer (today.py:65):** `attention_items[:3]` — displays max 3
- **Renderer (telegram.py:61):** `attention_items[:3]` — same limit
- **DailyBriefing model:** Holds full list; renderer slices

---

## 4. Tasks Marked as Done

**The daily briefing does NOT receive done tasks.**

- `load_tasks()` filters them out at the loader level
- The Attention Engine never sees completed tasks
- The `DailyBriefing` model has no field for completed tasks

### How to Get Done Tasks (for future use)

Two existing patterns in the codebase read completed tasks directly from the raw markdown:

1. **`goals_cli.py:59-67`** — reads `- [x]` lines from `TASKS_PATH`:
   ```python
   completed_titles = {t.title for t in tasks if t.state == "done"}  # from load_tasks (always empty)
   # Also read completed tasks from raw file (load_tasks filters them out)
   for line in _md_tasks.TASKS_PATH.read_text().splitlines():
       if line.startswith("- [x] "):
           ...
   ```

2. **`services/weekly_review.py:18-30`** — `_read_completed_task_titles()`:
   ```python
   if line.startswith("- [x]"):
       content = line[5:].strip()
       title = content.split(" | ", 1)[0].strip() if " | " in content else content
   ```

**Note:** `state: done` is explicitly rejected by the parser (`markdown_tasks.py:100`). The ONLY authority for completion is the `- [x]` checkbox.

---

## 5. Suggested Focus Candidates

| Aspect | Detail |
|--------|--------|
| **Source** | `attention_items[0]` — highest-scored item after sort |
| **Null case** | `None` if no attention items qualify |
| **Can be** | Any category: overdue_task, due_today, high_priority_task, blocked_task, in_progress_task, goal_stalled, upcoming_event |
| **Model field** | `DailyBriefing.suggested_focus: AttentionItem | None` |
| **Display** | Renderer shows it separately under "SUGGESTED FOCUS" |

---

## 6. Data Models Summary

### DailyBriefing (`models/daily_briefing.py`)
```python
@dataclass
class DailyBriefing:
    events: list[Event]
    attention_items: list[AttentionItem] = field(default_factory=list)
    suggested_focus: AttentionItem | None = None
```

### AttentionItem (`models/attention.py`)
```python
@dataclass
class AttentionItem:
    title: str
    reason: str
    score: int
    category: str
```

### Task (`models/task.py`)
```python
@dataclass
class Task:
    title: str
    due_date: date | None = None
    priority: int = 1
    state: str | None = None      # "todo" | "in_progress" | "blocked"
    progress: int | None = None   # 0-100
    extra_metadata: list[str] | None = None
```

### Goal (`models/goal.py`)
```python
@dataclass
class Goal:
    title: str
    description: str = ""
    status: str = "active"        # "active" | "completed" | "inactive"
    deadline: str | None = None
    metric_name: str | None = None
    metric_unit: str | None = None
    start_value: float | None = None
    current_value: float | None = None
    target_value: float | None = None
    direction: str | None = None  # "increase" | "decrease"
    related_tasks: list[str] = None
```

### Event (`models/event.py`)
```python
@dataclass
class Event:
    title: str
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    source: str | None = None
```

---

## 7. Key Files Reference

| File | Role |
|------|------|
| `src/janus/today.py` | CLI entry point — `_build_today_briefing()`, `show_today()`, `show_telegram()` |
| `src/janus/services/daily_briefing.py` | `create_daily_briefing()` — orchestrates the pipeline |
| `src/janus/services/attention.py` | `get_attention_items()` — scoring + ranking engine |
| `src/janus/models/daily_briefing.py` | `DailyBriefing` dataclass |
| `src/janus/models/attention.py` | `AttentionItem` dataclass |
| `src/janus/models/task.py` | `Task` dataclass + `ALLOWED_STATES` |
| `src/janus/models/goal.py` | `Goal` dataclass |
| `src/janus/models/event.py` | `Event` dataclass |
| `src/janus/integrations/google_calendar.py` | `list_upcoming_events()`, `list_events()` |
| `src/janus/integrations/markdown_tasks.py` | `load_tasks()` — open tasks only |
| `src/janus/integrations/markdown_goals.py` | `load_goals()` |
| `src/janus/integrations/telegram.py` | `send_briefing()`, `format_telegram_message()` |
| `tests/test_daily_briefing.py` | Unit tests for briefing + attention integration |
| `tests/test_attention.py` | Unit tests for attention scoring/sorting |
| `tests/test_today.py` | CLI output tests |

---

## 8. Gaps / Observations

1. **No done-task visibility in briefing** — The briefing cannot show recently completed tasks because `load_tasks()` filters them out and there's no separate "completed tasks" feed.

2. **Hard limit of 10 events per calendar** — `list_events()` uses `maxResults=10` with no pagination. Busy days with >10 calendar events will be silently truncated.

3. **Renderer-side limit (3 items)** — The attention engine returns all qualifying items but the renderer slices to 3. This is not configurable.

4. **No time-based decay** — A task overdue by 30 days scores the same as one overdue by 1 day (both +100).

5. **Goal stagnation detection is binary** — Either stalled (all related completed) or not. No partial progress signal in the attention list.

6. **Markdown parsing is line-based** — No structured query layer. All filtering/scoring happens in Python after full file read.
