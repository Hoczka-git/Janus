# Janus Daily Briefing — Architecture & Task Retrieval Research Report

## Question Investigated
What is the daily briefing feature's route/handler, the query that fetches tasks, and any existing filtering/sorting/pagination?

---

## Current State

### 1. Route / Handler Entry Point

**File:** `src/janus/__init__.py` (`main()` function)

The CLI dispatches two commands that trigger the daily briefing:

| Command | Handler |
|---------|---------|
| `janus today` | `show_today()` — prints to stdout |
| `janus telegram` | `show_telegram()` — sends via Telegram |

Both delegate to the same data-collection helper.

---

### 2. Data Collection & Briefing Assembly

**File:** `src/janus/today.py`

```python
def _build_today_briefing() -> "DailyBriefing":
    today = date.today()
    all_events = list_upcoming_events()
    today_events = [e for e in all_events if e.start.date() == today]
    tasks = load_tasks()
    goals = load_goals()
    return create_daily_briefing(today_events, tasks, goals, today)
```

**Key observation:** No filtering/pagination/sorting of tasks happens at this layer. ALL open tasks and ALL active goals are passed through.

---

### 3. Task Retrieval

**File:** `src/janus/integrations/markdown_tasks.py`

```python
def load_tasks() -> list[Task]:
    """Load open tasks from data/tasks.md."""
    # Reads file, parses lines starting with "- [ ]"
    # Returns ALL open (not completed) tasks
```

- **Query:** Line-by-line scan of `data/tasks.md`
- **Filter:** Only lines starting with `- [ ]` (open tasks). Lines with `- [x]` are skipped.
- **No sorting, no pagination, no priority filtering at load time.**

**File:** `src/janus/models/task.py`

```python
@dataclass
class Task:
    title: str
    due_date: date | None = None
    priority: int = 1  # default 1
    state: str | None = None  # "todo" | "in_progress" | "blocked"
    progress: int | None = None  # 0-100
```

---

### 4. Goal Retrieval

**File:** `src/janus/integrations/markdown_goals.py`

```python
def load_goals() -> list[Goal]:
    """Load goals from data/goals.md."""
    # Parses ## Goal: blocks
    # Returns ALL goals (no status filter at load)
```

- **No filtering at load time** — all goals are returned regardless of status.

---

### 5. Event Retrieval

**File:** `src/janus/integrations/google_calendar.py`

```python
def list_upcoming_events() -> list[Event]:
    # Reads config.toml for calendar IDs
    # Calls Google Calendar API per calendar
    # maxResults=10 per calendar (Google's default pagination)
    # Filters: timeMin=now, singleEvents=True, orderBy="startTime"
    # Returns combined + sorted list
```

- **Pagination:** `maxResults=10` per calendar (Google API default, not configurable)
- **Sorting:** By start time (all-day first, then timed)
- **Filtering:** `timeMin=now` (future events only)

---

### 6. Attention Engine (Sorting & Focus Determination)

**File:** `src/janus/services/attention.py`

```python
def get_attention_items(events, tasks, goals, today, now=None) -> list[AttentionItem]:
```

**How many tasks are returned today:**
- ALL open tasks that meet at least one scoring criterion
- No hard limit at the engine level
- **Renderer limits to 3** (`attention_items[:3]` in both `show_today()` and `format_telegram_message()`)

**How 'focus' is determined:**

The `suggested_focus` is the single highest-scoring `AttentionItem`:

```python
suggested_focus = attention_items[0] if attention_items else None
```

Scoring criteria (deterministic, sorted by `-score, category, title`):

| Condition | Score |
|-----------|-------|
| Overdue (due_date < today) | +100 |
| Due today (due_date == today) | +80 |
| Priority >= 3 | +50 |
| Priority == 2 (only if already qualifies) | +20 |
| State == "blocked" | +30 |
| State == "in_progress" | +30 |
| Upcoming event (today, future) | +10 |
| Goal stalled (all related tasks completed/missing) | +40 |

---

### 7. Briefing Data Model

**File:** `src/janus/models/daily_briefing.py`

```python
@dataclass
class DailyBriefing:
    events: list["Event"]          # today's events only
    attention_items: list["AttentionItem"]  # ALL scored items
    suggested_focus: "AttentionItem | None"  # top item
```

---

### 8. Rendering (CLI & Telegram)

**CLI (`show_today()`):**
- Prints ALL today's events (schedule section)
- Prints top 3 attention items (numbered 1-3)
- Prints suggested focus (single item) if any
- No pagination, no "load more"

**Telegram (`format_telegram_message()`):**
- Same 3-item limit for attention items
- Compact emoji-formatted message
- Same single focus item

---

## Concrete Locations Summary

| Component | File | Function/Line |
|-----------|------|---------------|
| CLI dispatch | `src/janus/__init__.py` | `main()` |
| CLI render | `src/janus/today.py` | `show_today()` (line 44) |
| Telegram render | `src/janus/today.py` | `show_telegram()` (line 81) |
| Briefing builder | `src/janus/today.py` | `_build_today_briefing()` (line 27) |
| Task loader | `src/janus/integrations/markdown_tasks.py` | `load_tasks()` (line 14) |
| Goal loader | `src/janus/integrations/markdown_goals.py` | `load_goals()` (line 21) |
| Event loader | `src/janus/integrations/google_calendar.py` | `list_upcoming_events()` (line 123) |
| Briefing service | `src/janus/services/daily_briefing.py` | `create_daily_briefing()` (line 17) |
| Attention engine | `src/janus/services/attention.py` | `get_attention_items()` (line 29) |
| Briefing model | `src/janus/models/daily_briefing.py` | `DailyBriefing` (line 9) |
| Attention model | `src/janus/models/attention.py` | `AttentionItem` (line 7) |

---

## Gaps / Notes for Implementer

1. **No server-side route:** Janus is a CLI app, not a web server. There's no HTTP endpoint; the "route" is the CLI command `janus today` / `janus telegram`.

2. **No pagination on tasks:** `load_tasks()` returns ALL open tasks. If there are 100 open tasks, all are scored by the attention engine, but only top 3 are shown. The engine itself returns all scored items (no limit).

3. **No "focus" flag on tasks:** Focus is purely score-derived at runtime. There's no stored "focused" or "pinned" task state.

4. **Google Calendar pagination:** Hardcoded `maxResults=10` per calendar. If a calendar has >10 upcoming events, some are silently dropped.

5. **Data sources:**
   - Tasks: `data/tasks.md` (markdown)
   - Goals: `data/goals.md` (markdown)
   - Events: Google Calendar API (requires credentials)

6. **Filtering happens at:**
   - Task load: open vs. completed (checkbox)
   - Event load: future only (`timeMin=now`), today only (in `_build_today_briefing`)
   - Goal load: none (all goals loaded, status filter in attention engine)
   - Attention scoring: threshold-based (score > 0)
   - Rendering: top-3 slice

---

## Recommendation

For any implementer making a targeted change:
- To add task filtering/sorting: modify `get_attention_items()` in `attention.py` or add a new layer in `_build_today_briefing()` in `today.py`
- To change the focus algorithm: modify scoring in `attention.py`
- To increase the shown items limit: change `[:3]` slices in `today.py:65` and `telegram.py:61`
- To add pagination to Google Calendar: modify `maxResults` in `google_calendar.py:110`
