## Attention Engine Integration

Once calendar events are loaded and aggregated, the Attention Engine makes Janus prioritize information instead of merely displaying it. This section describes how to integrate an Attention Engine with the multi-calendar setup.

### When to add attention

- The project already has events loaded from multiple calendars
- There are tasks or goals that need prioritization
- The goal is to answer "what deserves attention right now?" not just "what's on the calendar?"

### Architecture

The pipeline is three inputs feeding a deterministic scorer that produces ranked items:

```
Events ───────┐
              │
Tasks ────────┼──> Attention Engine ──> Ranked Attention Items
              │
Goals ────────┘
```

**Key constraint:** the engine is pure functions over dataclasses. No database, no LLM, no plugin system, no rule engine, no dependency injection. The scorer is transparent and testable.

### Model

Add an `AttentionItem` dataclass:

```python
from dataclasses import dataclass

@dataclass
class AttentionItem:
    title: str
    reason: str
    score: int
    category: str
```

Categories are domain-specific. For Janus:

- `overdue_task`
- `due_today`
- `high_priority_task`
- `upcoming_event`
- `goal_stalled`

Keep categories minimal — only what real data demands.

### Scoring rules

Implement deterministic scoring with explicit values. Example initial values:

| Condition | Score |
|-----------|-------|
| Overdue task | +100 |
| Task due today | +80 |
| Priority 3 task | +50 |
| Priority 2 task (only when already qualifying) | +20 |
| Upcoming event today | +10 |
| Stalled goal (all related tasks completed) | +40 |

A single item can accumulate multiple scores when multiple conditions apply. Example: overdue priority-3 task = 100 + 50 = 150.

**Priority 2 rule:** priority 2 contributes only when the task already qualifies through another condition (e.g. due today). Do not surface ordinary priority-2 tasks without a reason.

**Completed tasks:** never appear as attention items. The task loader already filters them out, but the engine should be defensive.

### Every item needs a reason

The `reason` field must be human-readable and causal. Examples:

- "Overdue by 3 days"
- "Due today"
- "High priority task"
- "Starts in 45 minutes"
- "All linked tasks are completed. No next action is defined."

Do not use generic reasons like "Requires attention" or "Important item". The user should understand immediately why an item surfaced.

### Goal stagnation detection

This is the most valuable new behavior: detect when an active long-term goal has no actionable open task.

A goal is stalled when:

1. `goal.status == "active"`
2. `goal.related_tasks` is non-empty
3. Every related task title that exists in the task file (open or completed) has no open task

**Conservative logic:** if a goal references a task title that does not exist at all in the task file, do NOT mark it as stalled. Missing references are already surfaced by Weekly Review. Only detect the clear case: "all existing related tasks are completed and there are no open related tasks."

To implement this, the engine needs to know which task titles exist in the full markdown file (both `[ ]` and `[x]` entries), not just the open tasks loaded by the task service. Load the file separately in the engine:

```python
def _load_all_task_titles(tasks_path: Path) -> set[str]:
    """Return set of all task titles (open and completed) from the markdown file."""
    titles: set[str] = set()
    with tasks_path.open() as f:
        for line in f:
            line = line.strip()
            if line.startswith("- [") or line.startswith("- [x]"):
                content = line[5:].strip()
                title = content.split("|", 1)[0].strip()
                if title:
                    titles.add(title)
    return titles
```

Then in stagnation detection:

```python
open_task_titles = {t.title for t in tasks}
all_task_titles = _load_all_task_titles(tasks_path)

for goal in goals:
    if goal.status != "active":
        continue
    if not goal.related_tasks:
        continue

    # Check if any related task is open
    has_open_related = any(
        any(t.title == rt for t in tasks)
        for rt in goal.related_tasks
    )
    if has_open_related:
        continue  # not stalled

    # Which related tasks exist in the file?
    existing_related = [rt for rt in goal.related_tasks
                        if rt in all_task_titles or rt in open_task_titles]
    if not existing_related:
        continue  # all missing references — don't mark as stalled

    # All existing related tasks are completed
    items.append(AttentionItem(
        title=goal.title,
        reason="All linked tasks are completed. No next action is defined.",
        score=40,
        category="goal_stalled",
    ))
```

### Timezone-aware event filtering

When filtering upcoming events, use a `now` parameter that defaults to `datetime.now().astimezone()` but can be injected in tests:

```python
def get_attention_items(
    events: list[Event],
    tasks: list[Task],
    goals: list[Goal],
    today: date,
    now: datetime | None = None,
) -> list[AttentionItem]:
    if now is None:
        now = datetime.now().astimezone()
    ...
```

This lets tests control the "current time" without mocking `datetime.now()` globally. Pass a mock `now` when creating events for test scenarios.

### Deterministic sorting

Sort by `(-score, category, title)`. This ensures:

- Highest score first
- Deterministic tie-breaking (category then title)
- No dependence on input ordering

### Daily Briefing integration

The Daily Briefing changes from:

```
Events ── Tasks ──> Daily Briefing (schedule + separate task lists)
```

to:

```
Events ── Tasks ── Goals ──> Attention Engine ──> Daily Briefing (attention items)
```

**DailyBriefing model changes:**

Old shape:
```python
@dataclass
class DailyBriefing:
    events: list[Event]
    overdue_tasks: list[Task]
    due_today_tasks: list[Task]
    high_priority_tasks: list[Task]
    suggested_focus: list[Task]
```

New shape:
```python
@dataclass
class DailyBriefing:
    events: list[Event]
    attention_items: list[AttentionItem]
    suggested_focus: AttentionItem | None
```

**create_daily_briefing signature changes:**

Old:
```python
def create_daily_briefing(events, tasks, today) -> DailyBriefing:
```

New:
```python
def create_daily_briefing(events, tasks, goals, today) -> DailyBriefing:
```

It delegates to `get_attention_items()` and takes the first item as `suggested_focus`.

**Renderer changes:**

- `REQUIRES ATTENTION` section shows ranked `AttentionItem`s with their reasons (not separate "Overdue:" / "Due today:" / "High priority:" sections)
- Maximum 3 items displayed in the renderer (not in the engine)
- `SUGGESTED FOCUS` shows the highest-ranked item with its reason

### Telegram integration

Update `format_telegram_message()` to use the new `DailyBriefing` shape:

- Replace `briefing.overdue_tasks`, `briefing.due_today_tasks`, `briefing.high_priority_tasks` with `briefing.attention_items`
- Replace `briefing.suggested_focus` (list of Tasks) with `briefing.suggested_focus` (single `AttentionItem | None`)
- Show `attention_items[:3]` with their reasons
- Show `suggested_focus.title` and `suggested_focus.reason`

### Test coverage

Add `tests/test_attention.py` with:

**Tasks:**
- Overdue task detected (with correct score and reason)
- Task due today detected
- Future task ignored unless otherwise important
- Priority 3 task detected
- Priority 2 scoring behavior (only when qualifying)
- Task with no due date (never overdue)
- Score accumulation (overdue + priority 3)
- Completed task excluded
- Multiple tasks correctly sorted

**Events:**
- Upcoming event today included (with `now` parameter)
- Past event today excluded
- Future-day event excluded
- Event scoring (+10)

**Goals:**
- Active goal with open related task is not stalled
- Active goal with all related tasks completed is stalled
- Inactive goal ignored
- Completed goal ignored
- Missing related task does not automatically create stalled attention
- Goal with no related tasks ignored

**Sorting:**
- Higher score first
- Deterministic tie-breaking
- Multiple categories correctly ordered

**Daily Briefing integration:**
- Attention items appear in Daily Briefing
- Maximum 3 items displayed (renderer limit, not engine limit)
- Highest-ranked item becomes Suggested Focus
- Empty attention state (no items, no focus)
- Existing schedule rendering still works

**Important:** tests must NOT modify `data/tasks.md` or `data/goals.md`. Use direct model construction or temporary files.

### What NOT to add

- SQLite, PostgreSQL, Pydantic, SQLModel, ORM
- LLM, OpenAI API, LangChain, CrewAI, AutoGen, agent framework
- Plugin framework, generic rules engine, event bus, dependency injection
- Event-driven architecture, async processing
- Infrastructure for hypothetical future requirements

Keep it: simple dataclasses, pure functions, deterministic scoring, small services, explicit tests.

### Verification

After implementing:

1. `uv run pytest` — full suite passes
2. `uv run janus today` — shows attention items with reasons from both calendars + goals
3. `uv run janus weekly` — still works
4. `git status --short` — only intended files changed
5. No credentials/tokens/config in Git

### Related skills

- `google-calendar-multi` — calendar loading and aggregation
- `python-stdlib-http-testing` — testing urllib-based integrations
