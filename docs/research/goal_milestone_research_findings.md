# Goal/Milestone System — Research Findings

**Task:** t_76937116 — Research existing goal/milestone models and codebase structure
**Date:** 2026-09-01
**Scope:** Janus repository — data models, services, persistence, CLI, integrations
**Constraint:** No implementation changes. Research output only.

---

## 1. Executive Summary

The Janus codebase has a **basic but functional Goal system** that is tightly coupled to tasks via `related_tasks: list[str]`. The system supports:

- Goal CRUD with title as immutable persistence identity
- Two progress paths: metric-based (numeric KPIs) and task-based (completion counting)
- Deadline storage as ISO date strings
- Attention Engine integration for stagnation detection
- Weekly Review integration for progress reporting

**What is missing (gaps to fill):**
- No `Milestone` entity — milestones are only discussed in docs, not implemented
- No execution planning or scheduling infrastructure
- No shared task assignment/derivation mechanism (tasks are standalone, linked to goals only by title string)
- No deadline enforcement or proactive deadline-driven scheduling
- No cross-domain progress aggregation (workouts → goals is aspirational, not built)

---

## 2. Current Data Models

### 2.1 Goal (`src/janus/models/goal.py`)

```python
@dataclass
class Goal:
    title: str                              # persistence identity, immutable in MVP
    description: str = ""
    status: str = "active"                  # active | completed | inactive
    deadline: str | None = None             # ISO date YYYY-MM-DD
    metric_name: str | None = None          # e.g. "Body fat %"
    metric_unit: str | None = None          # e.g. "%", "PLN", "kg"
    start_value: float | None = None        # baseline
    current_value: float | None = None      # latest
    target_value: float | None = None       # desired outcome
    direction: str | None = None            # "increase" | "decrease"
    related_tasks: list[str] = None         # supporting task titles (deduped, ordered)
```

**Key observations:**
- Title is the sole persistence identity (no UUID, no slug)
- `related_tasks` is a list of task **title strings** — fragile reference by string, not ID
- `deadline` is a plain `str`, not a `date` object (validated at parse time only)
- Status is a string enum, validated in `__post_init__`
- No `milestones` field, no `parent_goal` field, no `domain` field

### 2.2 Task (`src/janus/models/task.py`)

```python
@dataclass
class Task:
    title: str
    due_date: date | None = None
    priority: int = 1
    state: str | None = None                # todo | in_progress | blocked
    progress: int | None = None             # 0-100
    extra_metadata: list[str] | None = None
```

**Key observations:**
- `due_date` is a proper `date` object (unlike Goal's `deadline: str`)
- `state` uses checkbox `[x]` as completion authority; `state` field is workflow-only
- No `goal_id` field — tasks have no back-reference to goals
- No `milestone_id` field
- No `assigned_to` or `shared_with` field
- `extra_metadata` is a catch-all list for forward-compatible fields

### 2.3 Other Models (no goal/milestone relationship)

| Model | File | Goal relationship |
|-------|------|-------------------|
| `Event` | `models/event.py` | None |
| `Workout` | `models/workout.py` | None |
| `StrengthWorkout` | `models/workout.py` | None |
| `RunningWorkout` | `models/workout.py` | None |
| `AttentionItem` | `models/attention.py` | None |
| `DailyBriefing` | `models/daily_briefing.py` | None |
| `GoalReview` | `models/weekly_review.py` | Wraps Goal + progress |
| `WeeklyReview` | `models/weekly_review.py` | Aggregates GoalReviews |

---

## 3. Current Services

### 3.1 Goal Service (`src/janus/services/goals.py`)

- `add_goal(...)` — validates, checks duplicate title, persists
- `get_goal(title)` — exact title lookup
- `update_goal_fields(title, **kwargs)` — partial update, title immutable
- `complete_goal(title)` — sets status to "completed"

**No milestone operations. No scheduling. No deadline enforcement.**

### 3.2 Goal Progress (`src/janus/services/goal_progress.py`)

- `compute_goal_progress(goal, completed_task_titles)` — single source of truth
  - Priority: metric path > task-based path
  - Returns `None` for completed/inactive goals or missing config
- `_compute_metric_progress(...)` — handles increase/decrease, degenerate maintain-at-X
- `_compute_task_based_progress(...)` — simple ratio with bounds validation

**No milestone-based progress. No cross-domain aggregation.**

### 3.3 Task Service (`src/janus/services/tasks.py`)

- `add_task(title, due_date, priority)` — appends to `tasks.md`
- `complete_task(title)` — flips checkbox to `[x]`
- `list_tasks()` — loads open tasks
- `set_task_state(title, state)` — workflow state update
- `set_task_progress(title, progress)` — 0-100 progress update

**No goal assignment. No milestone assignment. No derivation from goals.**

### 3.4 Weekly Review (`src/janus/services/weekly_review.py`)

- `create_weekly_review()` — aggregates goals + tasks into `WeeklyReview`
- Reports completed/open tasks, goal progress, suggested next steps
- Detects missing related tasks (referenced but not in task file)

**No milestone tracking. No deadline proximity warnings.**

### 3.5 Attention Engine (`src/janus/services/attention.py`)

- `get_attention_items(events, tasks, goals, today)` — deterministic scoring
- Goal stagnation detection: all related tasks completed → suggests next milestone
- Task overdue/due-today/blocked/in-progress scoring
- Event proximity scoring

**Only place where "milestone" concept appears in code logic (as a suggestion, not entity).**

### 3.6 Daily Briefing (`src/janus/services/daily_briefing.py`)

- `create_daily_briefing(events, tasks, goals, today)` — delegates to Attention Engine
- Returns top-3 attention items + suggested focus

---

## 4. Persistence Layer

### 4.1 Goals (`src/janus/integrations/markdown_goals.py`)

- **File:** `data/goals.md`
- Format: Markdown with `## Goal:` headers, field lines (`Description:`, `Status:`, `Metric:`, etc.)
- `load_goals()` — parses file, returns `list[Goal]`
- `save_goal(goal)` — appends block
- `update_goal(goal)` — replaces block by title match
- Unknown fields ignored on parse, NOT preserved through rewrite

**Current `data/goals.md` content:**
```
## Goal: Complete autumn endurance challenge
## Goal: Maintain regular training
```
Both use only `related_tasks` — no metrics, no deadlines.

### 4.2 Tasks (`src/janus/integrations/markdown_tasks.py`)

- **File:** `data/tasks.md`
- Format: `- [ ] Title | due: ... | priority: ... | state: ... | progress: ...`
- `load_tasks(path)` — parses open tasks only
- `_parse_task_line(line, line_num)` — regex-based metadata extraction
- `_format_task_line(task)` — serializes back to markdown

**No goal/milestone reference stored in task lines.**

---

## 5. CLI Surface

### 5.1 Goal CLI (`src/janus/goals_cli.py`)

| Command | Handler | Description |
|---------|---------|-------------|
| `janus goal list` | `handle_goal_list` | All goals grouped by status with progress |
| `janus goal show <title>` | `handle_goal_show` | Single goal detail + related tasks |
| `janus goal add <title> [opts]` | `handle_goal_add` | Create goal with full field support |
| `janus goal update <title> [opts]` | `handle_goal_update` | Partial field update |
| `janus goal complete <title>` | `handle_goal_complete` | Mark completed |

**Flags:** `--description`, `--status`, `--deadline`, `--metric`, `--unit`, `--start`, `--current`, `--target`, `--direction`, `--related-task`, `--add-related-task`, `--remove-related-task`

**No milestone subcommands. No scheduling commands.**

### 5.2 Task CLI (`src/janus/tasks_cli.py`)

| Command | Handler | Description |
|---------|---------|-------------|
| `janus task list` | `handle_task_list` | All open tasks |
| `janus task add <title> [opts]` | `handle_task_add` | Create task |
| `janus task complete <title>` | `handle_task_complete` | Mark done |
| `janus task state <title> [opts]` | `handle_task_state` | Update workflow state |
| `janus task progress <title> [opts]` | `handle_task_progress` | Update progress % |

**Flags:** `--due`, `--priority`, `--state`, `--pct`

**No `--goal` flag. No `--milestone` flag. No assignment mechanism.**

---

## 6. Integration Points

### 6.1 Google Calendar (`src/janus/integrations/google_calendar.py`)

- `list_upcoming_events()` — fetches from configured calendars
- Returns `list[Event]` sorted by start time
- Events feed into Daily Briefing and Attention Engine

**No goal/milestone event creation. Read-only.**

### 6.2 Telegram (`src/janus/integrations/telegram.py`)

- `send_briefing(briefing)` — formats and sends Daily Briefing
- `format_telegram_message(briefing)` — compact message format

**No goal-specific Telegram commands. No milestone notifications.**

---

## 7. Deadline Handling Patterns

| Entity | Field | Type | Enforcement |
|--------|-------|------|-------------|
| `Goal` | `deadline` | `str` (ISO date) | None — stored but never compared to today |
| `Task` | `due_date` | `date` | Attention Engine scores overdue/due-today |
| `Event` | `start` | `datetime` | Attention Engine scores upcoming |

**Key finding:** Goal deadlines are **not used anywhere in the codebase**. They are stored, displayed in `goal show`, but never drive any logic (unlike Task due dates which feed the Attention Engine).

---

## 8. Shared Task Assignment / Derivation

**Current state:** There is **no shared task assignment or derivation mechanism**.

- Tasks are standalone entities in `data/tasks.md`
- Goals reference tasks by title string via `related_tasks: list[str]`
- No task has a `goal_id` or `shared_with` field
- No derivation: tasks are never auto-generated from goals or milestones
- No assignment: no concept of task ownership or delegation

**Implication:** Any milestone system will need to either:
1. Extend `Task` with a `milestone_id` / `goal_id` field, or
2. Maintain a separate milestone→task mapping in the milestone entity

---

## 9. Execution Planning / Scheduling Infrastructure

**Current state:** There is **none**.

- No scheduler, no planner, no executor
- No concept of "next action derived from goal state"
- Weekly Review suggests "first open related task" as next step — this is the closest thing to planning
- Attention Engine surfaces what needs attention — this is the closest thing to scheduling

---

## 10. Recommended Change Locations

For a Milestone system implementation, these are the exact files and modules that will need changes:

### New Files to Create
| File | Purpose |
|------|---------|
| `src/janus/models/milestone.py` | `Milestone` dataclass |
| `src/janus/services/milestones.py` | Milestone CRUD + progress |
| `src/janus/integrations/markdown_milestones.py` | Milestone persistence |
| `src/janus/milestones_cli.py` | Milestone CLI commands |

### Existing Files to Modify
| File | Change |
|------|--------|
| `src/janus/models/goal.py` | Add `milestones: list[str]` field (or parent-child) |
| `src/janus/models/task.py` | Add `milestone_id: str | None` field |
| `src/janus/services/goals.py` | Milestone relationship management |
| `src/janus/services/goal_progress.py` | Milestone-based progress path |
| `src/janus/services/tasks.py` | Derive tasks from milestones |
| `src/janus/services/weekly_review.py` | Milestone reporting |
| `src/janus/services/attention.py` | Milestone stagnation detection |
| `src/janus/services/daily_briefing.py` | Milestone-aware briefing |
| `src/janus/integrations/markdown_goals.py` | Parse/persist milestone references |
| `src/janus/integrations/markdown_tasks.py` | Parse/persist `milestone_id` |
| `src/janus/goals_cli.py` | Milestone subcommands on goals |
| `src/janus/tasks_cli.py` | `--milestone` flag on task add/update |
| `src/janus/today.py` | Milestone-aware today view |
| `src/janus/weekly.py` | Milestone reporting in weekly review |
| `src/janus/models/__init__.py` | Export `Milestone` |

### Test Files to Create/Modify
| File | Change |
|------|--------|
| `tests/test_milestones.py` | New — milestone model + service tests |
| `tests/test_markdown_milestones.py` | New — milestone persistence tests |
| `tests/test_goals_service.py` | Modify — milestone relationship tests |
| `tests/test_goal_progress.py` | Modify — milestone progress tests |
| `tests/test_weekly_review.py` | Modify — milestone reporting tests |
| `tests/test_attention.py` | Modify — milestone stagnation tests |

---

## 11. Key Design Decisions Needed

1. **Milestone identity:** Title (like Goal) or UUID? Title immutability is the current pattern.
2. **Milestone→Task relationship:** Reference by title (current pattern) or ID (more robust)?
3. **Milestone progress:** Metric-based (like Goal), task-based (like Goal), or completion-based (all tasks done)?
4. **Milestone→Goal hierarchy:** Child of goal, or sibling with link?
5. **Deadline inheritance:** Do milestones inherit goal deadline, or have their own?
6. **Scheduling:** Should milestones drive task due dates automatically?
7. **Cross-domain:** Should milestones aggregate progress from workouts, nutrition, etc.?

---

## 12. What Does NOT Need to Change

- `Event` model — no goal/milestone relationship needed
- `Workout` models — no direct goal/milestone relationship (future consideration)
- `AttentionItem` — already generic enough to cover milestones
- `DailyBriefing` — already delegates to Attention Engine
- Google Calendar integration — read-only, no milestone event creation needed initially
- Telegram integration — already sends briefing, no milestone-specific commands needed initially

---

## 13. Risks & Constraints

1. **String-reference fragility:** Current `related_tasks: list[str]` is brittle. Adding `milestone_id: list[str]` to Task repeats the same pattern. Consider UUID migration.
2. **Markdown persistence:** Adding many fields to goals.md/tasks.md will make the format more complex. Consider whether the markdown format scales.
3. **Title immutability:** If titles cannot change, any UI must enforce this strictly.
4. **No database:** All persistence is file-based. Concurrent access is not handled.
5. **No API layer:** All operations are CLI-only. No programmatic API for external integrations to push milestone data.

---

**End of research note.**
