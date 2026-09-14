# Goal System Discovery Report

## Question Investigated

What is the current state of the Goal System in Janus — its models, tracking logic, task/calendar integration points, and existing milestone/action concepts — and what are the gaps relevant to execution planning?

## Scope & Constraints

- Read-only research; no implementation changes.
- Focus on goal-related code paths: models, services, persistence, CLI, attention engine, daily briefing, weekly review, calendar integration.

---

## 1. Architecture Overview

Janus is a file-backed personal operations system. All state lives in markdown files under `data/`. The goal subsystem spans 6 layers:

```
CLI (goals_cli.py)
  └─ Service (services/goals.py) — CRUD
       └─ Progress (services/goal_progress.py) — centralized metric/task progress
            └─ Model (models/goal.py) — Goal dataclass
                 └─ Persistence (integrations/markdown_goals.py) — data/goals.md

Attention Engine (services/attention.py) — goal stagnation detection
  └─ Daily Briefing (services/daily_briefing.py) — suggested_focus selection
       └─ Today CLI / Telegram delivery

Weekly Review (services/weekly_review.py) — goal progress + suggested next step
  └─ Weekly CLI / Telegram delivery
```

---

## 2. Goal Model

**File:** `src/janus/models/goal.py`

```python
@dataclass
class Goal:
    title: str                              # persistence identity, immutable in MVP
    description: str = ""
    status: str = "active"                  # active | completed | inactive
    deadline: str | None = None             # ISO date YYYY-MM-DD
    metric_name: str | None = None          # e.g. "Body fat %"
    metric_unit: str | None = None          # e.g. "%", "PLN", "kg"
    start_value: float | None = None
    current_value: float | None = None
    target_value: float | None = None
    direction: str | None = None            # "increase" | "decrease"
    related_tasks: list[str] = None         # supporting task titles (deduped, ordered)
```

**Validation:** `status` must be active/completed/inactive; `direction` must be increase/decrease; title must be non-empty; related_tasks deduped preserving order.

**Persistence identity:** Title is immutable in MVP (no rename).

---

## 3. Goal CRUD Service

**File:** `src/janus/services/goals.py`

| Operation | Function | Notes |
|-----------|----------|-------|
| Create | `add_goal(...)` | Validates via Goal constructor; rejects duplicate title |
| Read | `get_goal(title)` | Exact title match; raises if not found or multiple |
| Update | `update_goal_fields(title, **kwargs)` | Title immutable; supports add/remove related task |
| Complete | `complete_goal(title)` | Sets status='completed' |
| Delete | — | Not implemented; goals can be set to inactive |

---

## 4. Goal Progress Calculation

**File:** `src/janus/services/goal_progress.py`

Centralized, single source of truth. Priority order:

1. **Metric path** — if `metric_name`, `target_value`, `direction`, `start_value`, `current_value` all present → `_compute_metric_progress()`
2. **Task-based path** — elif `related_tasks` non-empty AND `completed_task_titles` provided → `_compute_task_based_progress()`
3. **Otherwise** → `None`

Returns `None` for completed/inactive goals, missing metric fields, or no tasks + no titles.

**Metric progress:** Handles increase/decrease, degenerate maintain-at-X (start==target), negative values, percentages, absolute units.

**Task-based progress:** `(completed_count / total) * 100.0`; validates count bounds.

---

## 5. Persistence Layer

**File:** `src/janus/integrations/markdown_goals.py`
**Data file:** `data/goals.md`

Format:
```markdown
# Goals

## Goal: <title>
Description: <text>
Status: active | completed | inactive
Deadline: YYYY-MM-DD
Metric: <name>
Unit: <unit>
Start: <float>
Current: <float>
Target: <float>
Direction: increase | decrease
Related tasks:
- <task title>
```

**Behavior:** Unknown fields ignored on parse, NOT preserved through `update_goal` rewrite. Malformed values raise `ValueError` with line number.

---

## 6. CLI Commands

**File:** `src/janus/goals_cli.py`

| Command | Handler | Key flags |
|---------|---------|-----------|
| `goal list` | `handle_goal_list` | Groups by status, shows progress |
| `goal show <title>` | `handle_goal_show` | Full details + related task states |
| `goal add <title>` | `handle_goal_add` | `--description`, `--status`, `--deadline`, `--metric`, `--unit`, `--start`, `--current`, `--target`, `--direction`, `--related-task` |
| `goal update <title>` | `handle_goal_update` | Same flags + `--add-related-task`, `--remove-related-task` |
| `goal complete <title>` | `handle_goal_complete` | Sets status=completed |

---

## 7. Task Integration Points

### 7.1 Goal → Task Link

- `Goal.related_tasks: list[str]` — ordered list of task titles (deduped).
- Link is **by title** (exact match), not by ID.
- Tasks are loaded from `data/tasks.md` via `markdown_tasks.load_tasks()` (open only) and raw file parsing (for completed tasks).

### 7.2 Task Model

**File:** `src/janus/models/task.py`

```python
@dataclass
class Task:
    title: str
    due_date: date | None = None
    priority: int = 1
    state: str | None = None        # todo | in_progress | blocked
    progress: int | None = None    # 0-100
    extra_metadata: list[str] | None = None
```

### 7.3 Task Service

**File:** `src/janus/services/tasks.py`

- `add_task(title, due_date, priority)` — append to file
- `complete_task(title)` — flip checkbox to `[x]`
- `set_task_state(title, state)` — update state metadata
- `set_task_progress(title, progress)` — update progress metadata
- `list_tasks()` — return open tasks

---

## 8. Attention Engine — Goal Stagnation Detection

**File:** `src/janus/services/attention.py`

**Stall detection logic** (lines 120-153):
- Only active goals with `related_tasks` are evaluated.
- If any related task is open → not stalled.
- If all related tasks are completed (exist but none open) → **stalled** (score=40, category=`goal_stalled`).
- If related tasks don't exist at all → not stalled (missing refs ignored).
- Stall reason: *"All linked tasks are completed. Define the next milestone, add a new action, or mark the goal as complete."*

**Scoring hierarchy:**
- Overdue task: 100
- Due today: 80
- High priority (3): 50
- Blocked task: 30
- In-progress task: 30
- Goal stalled: 40
- Upcoming event: 10

**Sort:** Deterministic — highest score first, then category, then title.

---

## 9. Daily Briefing — Suggested Focus

**File:** `src/janus/services/daily_briefing.py`

- Delegates to `get_attention_items()`.
- `suggested_focus = attention_items[0]` — single top-scoring item (not a list).
- Renderer (`today.py`) shows top 3 attention items + 1 suggested focus.

**Model:** `DailyBriefing.suggested_focus: AttentionItem | None`

---

## 10. Weekly Review — Goal Progress & Next Step

**File:** `src/janus/services/weekly_review.py`

**File:** `src/janus/models/weekly_review.py`

```python
@dataclass
class GoalReview:
    goal: Goal
    progress: float | None
    progress_detail: str | None
    completed_related_tasks: list[str]
    missing_related_tasks: list[str]
    suggested_next_step: str | None    # first open related task
    all_related_tasks_completed: bool
```

**Logic:**
- For each active goal, classifies related tasks as completed/open/missing.
- `suggested_next_step` = first open related task (by order in `related_tasks`).
- If all related tasks completed → `all_related_tasks_completed=True`, no suggested next step.
- Delegates progress computation to `compute_goal_progress()`.

---

## 11. Calendar Integration

**File:** `src/janus/integrations/google_calendar.py`

- Read-only Google Calendar API.
- `list_upcoming_events()` — fetches from configured calendars.
- Events feed into the Attention Engine (upcoming events get score=10).
- **No goal-calendar connection** — goal deadlines are plain strings, not synced to calendar events.

---

## 12. Current Data State

**`data/goals.md`:**
- "Complete autumn endurance challenge" (active) — related: "Prepare training plan", "Buy running shoes"
- "Maintain regular training" (active) — related: "Prepare training plan"

**`data/tasks.md`:**
- 3 open tasks, 7 completed tasks.
- "Prepare training plan" is open (priority 3) — shared by both goals.

---

## 13. Gaps Relevant to Execution Planning

### 13.1 Milestones — MISSING

No milestone concept exists. The stall detection reason text mentions "Define the next milestone" but there is no model, persistence, or logic for milestones.

**Extension point:** Add `Milestone` dataclass with title, deadline, status, related_tasks. Link to Goal. Add to `data/goals.md` format or separate `data/milestones.md`.

### 13.2 Next Actions — PARTIAL

- Weekly review provides `suggested_next_step` (first open related task).
- Attention engine surfaces stalled goals with a prompt to "add a new action."
- No explicit "next action" model or field — it's derived, not stored.

**Extension point:** Add `next_action` field to Goal or derive from task ordering. Consider explicit "next action" as a first-class concept.

### 13.3 Stall Detection — BINARY

Current: stalled / not stalled. No gradations (e.g., "progressing slowly," "no recent activity," "deadline approaching").

**Extension point:** Add time-based signals (days since last completed task, deadline proximity). Extend scoring in attention engine.

### 13.4 Calendar/Task Connection — MISSING

- Goals have deadlines (string) but no calendar events are created.
- Tasks have due dates but no calendar integration.
- Events from calendar feed only into attention scoring, not into goal/task linking.

**Extension point:** On goal deadline, surface as attention item. Optionally create calendar events for goal milestones.

### 13.5 Task Dependencies — MISSING

No dependency graph between tasks. `related_tasks` is a flat list with ordering but no semantics (blocks, depends-on, etc.).

**Extension point:** Add dependency metadata to tasks. Enable critical-path analysis.

### 13.6 Execution Sequencing — MISSING

No concept of "what should I do right now to advance goal X" beyond the first open task. No time-blocking, no scheduling.

**Extension point:** Priority queue across goals, considering deadline urgency, task dependencies, and user capacity.

### 13.7 Goal Progress History — MISSING

Progress is computed from current state only. No historical tracking of metric values or completion timestamps.

**Extension point:** Log metric snapshots or task completion events to a history file.

---

## 14. Recommendations

| Priority | Recommendation | Rationale |
|----------|----------------|-----------|
| 1 | **Add Milestone model** — child of Goal with title, deadline, status, related_tasks. Extend `data/goals.md` format. | The stall detection already references milestones; this closes the gap. |
| 2 | **Extend stall detection** — add deadline proximity, days-since-activity signals. | Binary stall is insufficient for execution planning. |
| 3 | **Explicit next action** — store on Goal or derive from ordered related_tasks with dependency awareness. | Weekly review already derives it; making it first-class enables better sequencing. |
| 4 | **Goal deadline → attention** — surface approaching goal deadlines in the attention engine. | Currently only task due dates and calendar events are scored. |
| 5 | **Task dependencies** — add `depends_on` metadata to tasks. | Enables critical-path analysis and better next-action selection. |
| 6 | **Progress history** — log metric snapshots over time. | Enables trend analysis and richer weekly reviews. |

---

## 15. Key File Reference

| File | Role |
|------|------|
| `src/janus/models/goal.py` | Goal dataclass |
| `src/janus/services/goals.py` | CRUD service |
| `src/janus/services/goal_progress.py` | Centralized progress calculation |
| `src/janus/integrations/markdown_goals.py` | Markdown persistence |
| `src/janus/goals_cli.py` | CLI handlers |
| `src/janus/services/attention.py` | Goal stagnation detection |
| `src/janus/services/daily_briefing.py` | Suggested focus selection |
| `src/janus/services/weekly_review.py` | Goal progress + next step |
| `src/janus/models/weekly_review.py` | GoalReview / WeeklyReview models |
| `src/janus/models/task.py` | Task dataclass |
| `src/janus/services/tasks.py` | Task write service |
| `src/janus/integrations/markdown_tasks.py` | Task markdown persistence |
| `src/janus/integrations/google_calendar.py` | Calendar integration |
| `data/goals.md` | Goal data file |
| `data/tasks.md` | Task data file |

---

## 16. Remaining Uncertainty

- No performance benchmarks on large goal/task sets (current data is tiny).
- No user research on how milestones are actually used in practice.
- Calendar write scope (read-only currently) — unclear if write access is desired.
- No existing user feedback on the current stall detection quality.
