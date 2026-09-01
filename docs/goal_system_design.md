# Goal System — Architecture Design

> **Status:** Discovery review complete. Not implemented. Not committed.
> **Source:** Based on `docs/goal_system_discovery.md` (brief) and full repository archaeology.
> **Companion file for implementation:** This document + `docs/goal_system_discovery.md`.

---

## 1. Executive Summary

1. Janus currently has a 4-field Goal dataclass: `title`, `description`, `status`, `related_tasks`. No metric, no target, no progress, no deadline.
2. Goal is used by Attention Engine (stagnation detection only), Daily Briefing (pass-through), and Weekly Review (boolean progress based on related task completion).
3. Existing persistence is a single `data/goals.md` markdown file with a custom parser; missing file raises `FileNotFoundError`.
4. The current model is too limited for measurable outcomes — it cannot represent "reduce body fat from 23% to 15%" or "save 10,000 PLN".
5. Recommended direction: Goal = Outcome with optional metric fields. Not all goals have metrics; metric-less goals fall back to task-based progress.
6. Progress is a first-class optional concept: `compute_goal_progress(goal) -> Optional[float]` where float is 0.0–100.0.
7. Metric goals store `start_value`, `current_value`, `target_value`, `direction`, `metric_name`, `metric_unit` — all optional. No measurement history in Goal.
8. Task-based progress is the legacy-compatible fallback when no metric fields are present. Tasks remain supporting actions, not the primary progress source for metric goals.
9. `goal complete` is always manual. Target achievement does NOT auto-complete.
10. Weekly Review progress changes from `bool` to `Optional[float]`; all usage sites updated.
11. Persistence evolves additively in `data/goals.md`; no migration script; backward compatible.
12. MVP CLI: `list`, `show`, `add`, `update`, `complete` — 5 commands, ~6 production files changed/created.
13. No plugin system, no generic progress providers, no automatic cross-domain integration in MVP.
14. After adversarial review: architecture holds up with minor semantic clarifications; no structural changes required.
15. Architecture is ready for implementation planning.

---

## 2. Current Goal Architecture

### 2.1 Existing model

File: `src/janus/models/goal.py` (13 lines)

```python
@dataclass
class Goal:
    title: str
    description: str = ""
    status: str = "active"
    related_tasks: list[str] = None

    def __post_init__(self):
        if self.related_tasks is None:
            self.related_tasks = []
```

Fields:
- `title: str` — required, no uniqueness constraint
- `description: str` — optional, free text
- `status: str` — `"active"`, `"completed"`, or `"inactive"` (validated by parser, not by model)
- `related_tasks: list[str]` — list of task titles (strings, not Task references)

No validation on `status` in the model itself; parser validates.

### 2.2 Persistence

File: `src/janus/integrations/markdown_goals.py` (70 lines)

```python
PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOALS_PATH = PROJECT_ROOT / "data" / "goals.md"

def load_goals() -> list[Goal]:
    if not GOALS_PATH.exists():
        raise FileNotFoundError(...)
    # Parse ## Goal: blocks with Description:, Status:, Related tasks: fields
```

Format example (`data/goals.md`):

```
# Goals

## Goal: Complete autumn endurance challenge
Description: Complete a meaningful endurance event during autumn.
Status: active
Related tasks:
- Prepare training plan
- Buy running shoes

## Goal: Maintain regular training
Description: Build a consistent training routine.
Status: active
Related tasks:
- Prepare training plan
```

Key behaviors:
- Missing file → `FileNotFoundError` (hard fail)
- Malformed status → `ValueError`
- Missing title → `ValueError`
- Only `load_goals()` exists; no `save_goal`, no `update_goal`

### 2.3 Services

No dedicated Goal service exists. Goal logic is embedded in:
- `services/attention.py` — stagnation detection
- `services/weekly_review.py` — progress calculation (boolean)
- No `services/goals.py`

### 2.4 Consumers

| Consumer | File | How it uses Goals |
|----------|------|-------------------|
| Attention Engine | `services/attention.py` | For each active goal with related_tasks: if all existing related tasks are completed and none open → `AttentionItem(category="goal_stalled", score=40)` |
| Daily Briefing | `services/daily_briefing.py` → `today.py` | Passes goals list to `create_daily_briefing` → Attention Engine; stalled goal can become `suggested_focus` |
| Weekly Review | `services/weekly_review.py` → `weekly.py` | For each active goal: checks related_tasks against completed/open tasks; sets `GoalReview.progress = True` if any related task completed; suggests first open task as next step |
| Today CLI tests | `tests/test_today.py` | Uses `_make_goal()` helper, mocks `load_goals` |
| Weekly Review tests | `tests/test_weekly_review.py` | 475 lines; 30+ tests covering parsing, service logic, CLI rendering |
| Attention tests | `tests/test_attention.py` | 8 goal-specific tests (stagnation, inactive, completed, missing tasks, no related tasks) |

### 2.5 Dependencies

```
Goal (models/goal.py)
  ↑
  ├── Attention Engine (services/attention.py) — stagnation only
  ├── Weekly Review (services/weekly_review.py) — task-based progress
  ├── Daily Briefing (services/daily_briefing.py) — pass-through
  └── Today CLI (today.py) — rendering
```

### 2.6 Architecture diagram

```
                   ┌──────────────┐
                   │    Goal      │
                   │ (models/     │
                   │  goal.py)    │
                   └──────┬───────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
   Attention Engine   Weekly Review   Daily Briefing
   (stagnation)       (task progress) (pass-through)
          │               │               │
          └───────────────┼───────────────┘
                          ▼
                   Attention Items
                   (ranked, scored)
```

### 2.7 Existing data

`data/goals.md` contains 2 goals, both task-based:

1. **Complete autumn endurance challenge** — active, related tasks: "Prepare training plan", "Buy running shoes"
2. **Maintain regular training** — active, related tasks: "Prepare training plan"

---

## 3. Problems With the Current Model

| Category | Finding |
|----------|---------|
| **BLOCKER** | Cannot represent measurable outcomes (body fat %, savings, running distance). Goal is purely task-anchored. |
| **SHOULD FIX** | `load_goals()` raises `FileNotFoundError` when `data/goals.md` missing. Other loaders (`load_tasks`, `load_workouts`) return empty list — Goal should match this pattern for consistency. |
| **DESIGN LIMITATION** | `status` validation exists only in parser, not in model `__post_init__`. Model accepts any string. |
| **DESIGN LIMITATION** | `related_tasks` stores task titles as strings with no reference integrity — deleted tasks leave dangling references (tested in `test_attention.py::test_missing_related_task_does_not_stall`). |
| **DESIGN LIMITATION** | Weekly Review progress is boolean (`True` if ANY related task completed). No granularity — 1 of 10 tasks completed = same as 10 of 10. |
| **OPTIONAL** | No `deadline` field. Goals can have implicit deadlines via related task due dates, but no goal-level deadline. |
| **OPTIONAL** | No `target_date` or time horizon. A goal like "run 100km in September" cannot be expressed. |

---

## 4. Recommended Goal Domain Model

### 4.1 Entities

**Goal** — the core entity. Represents a desired outcome.

```python
@dataclass
class Goal:
    # Required
    title: str

    # Optional descriptive fields
    description: str = ""
    status: str = "active"           # active | completed | inactive
    deadline: str | None = None      # ISO date YYYY-MM-DD, optional

    # Optional metric fields (all None for task-based goals)
    metric_name: str | None = None   # e.g. "Body fat %", "Savings balance"
    metric_unit: str | None = None   # e.g. "%", "PLN", "kg", "km"
    start_value: float | None = None # baseline measurement
    current_value: float | None = None # latest measurement
    target_value: float | None = None # desired outcome
    direction: str | None = None     # "increase" | "decrease" | None

    # Task relationship (backward compatible)
    related_tasks: list[str] = None  # task titles, supporting actions

    def __post_init__(self):
        if self.related_tasks is None:
            self.related_tasks = []
        # Validate status
        if self.status not in ("active", "completed", "inactive"):
            raise ValueError(
                f"Invalid goal status: {self.status!r}. "
                f"Allowed: active, completed, inactive"
            )
        # Validate direction if present
        if self.direction is not None and self.direction not in ("increase", "decrease"):
            raise ValueError(
                f"Invalid direction: {self.direction!r}. "
                f"Allowed: increase, decrease"
            )
```

### 4.2 Relationships

```
Goal 1 ──► N related_tasks (by title, supporting actions)
Goal 1 ──► 0..1 metric (via fields: metric_name, target_value, etc.)
Goal 1 ──► 0..1 deadline
```

Goal does NOT own tasks. Goal does NOT own measurements. Goal does NOT own milestones (future consideration).

### 4.3 Responsibilities

**Goal (model):**
- Validate status and direction
- Hold optional metric fields
- Keep backward compatibility with task-based goals

**Goal progress service (`services/goal_progress.py`):**
- `compute_goal_progress(goal: Goal) -> float | None`
- Metric-based if metric fields present
- Task-based fallback if no metric fields
- Returns None if no progress computable

**CLI (`goals_cli.py`):**
- Parse args, call persistence, call progress service, render output

**Persistence (`markdown_goals.py`):**
- Load/save/update goals in `data/goals.md`
- Parse new optional fields additively

### 4.4 Dataclass summary

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `title` | `str` | Yes | Unique-ish identifier |
| `description` | `str` | No | Free text |
| `status` | `str` | No (default "active") | active / completed / inactive |
| `deadline` | `str \| None` | No | ISO date |
| `metric_name` | `str \| None` | No | Metric label |
| `metric_unit` | `str \| None` | No | Unit label |
| `start_value` | `float \| None` | No | Baseline |
| `current_value` | `float \| None` | No | Latest |
| `target_value` | `float \| None` | No | Desired |
| `direction` | `str \| None` | No | increase / decrease |
| `related_tasks` | `list[str]` | No (default []) | Supporting task titles |

---

## 5. Progress Architecture

### 5.1 Metric-based progress (primary)

For a goal with metric fields:

```python
def compute_goal_progress(goal: Goal) -> float | None:
    if goal.metric_name is None or goal.target_value is None:
        return None  # not a metric goal

    if goal.direction == "increase":
        if goal.start_value is None or goal.current_value is None:
            return None
        if goal.start_value == goal.target_value:
            return 100.0 if goal.current_value == goal.target_value else 0.0
        if goal.target_value <= goal.start_value:
            return None  # invalid: target not above start
        if goal.current_value <= goal.start_value:
            return 0.0
        if goal.current_value >= goal.target_value:
            return 100.0
        return (goal.current_value - goal.start_value) / (goal.target_value - goal.start_value) * 100.0

    if goal.direction == "decrease":
        if goal.start_value is None or goal.current_value is None:
            return None
        if goal.start_value == goal.target_value:
            return 100.0 if goal.current_value == goal.target_value else 0.0
        if goal.target_value >= goal.start_value:
            return None  # invalid: target not below start
        if goal.current_value >= goal.start_value:
            return 0.0
        if goal.current_value <= goal.target_value:
            return 100.0
        return (goal.start_value - goal.current_value) / (goal.start_value - goal.target_value) * 100.0

    return None  # direction not set
```

**Semantics:**
- Returns `float` in range `[0.0, 100.0]` when computable
- Returns `None` when:
  - Goal has no metric fields
  - Key values missing (start, current, target)
  - Invalid direction configuration (target on wrong side of start)
  - `start_value == target_value` and `current_value != target_value` (degenerate — can't compute ratio; returns 0.0 as conservative default)

### 5.2 Task-based progress (fallback for non-metric goals)

When no metric fields are present:

```python
def compute_task_based_progress(goal: Goal) -> float | None:
    if not goal.related_tasks:
        return None  # no tasks → no task-based progress

    # Query task store to determine completion state
    completed = count_completed_related_tasks(goal.related_tasks)
    total = len(goal.related_tasks)

    if total == 0:
        return None
    return (completed / total) * 100.0
```

This replaces the current boolean `progress = True if any completed` with a percentage.

### 5.3 Worked examples

**Body fat goal (metric, decrease):**

```
Goal:
  title: Reduce body fat
  metric_name: Body fat %
  metric_unit: %
  start_value: 23.0
  current_value: 20.0
  target_value: 15.0
  direction: decrease

Progress:
  (23.0 - 20.0) / (23.0 - 15.0) * 100 = 62.5%
```

**Running distance goal (metric, increase):**

```
Goal:
  title: Run 100 km in September
  metric_name: Total distance
  metric_unit: km
  start_value: 0.0
  current_value: 52.3
  target_value: 100.0
  direction: increase

Progress:
  (52.3 - 0.0) / (100.0 - 0.0) * 100 = 52.3%
```

Note: time window (September) is NOT encoded in the Goal fields. This is a known MVP limitation — the current_value would need to be manually updated or derived from an external query later.

**Task-based goal (legacy-compatible):**

```
Goal:
  title: Prepare Japan trip
  status: active
  related_tasks:
    - Buy flights
    - Book hotels
    - Create itinerary

Task state:
  - Buy flights: completed
  - Book hotels: open
  - Create itinerary: open

Progress:
  1/3 * 100 = 33.3%
```

---

## 6. Persistence Recommendation

### 6.1 Format: `data/goals.md` (evolved, backward compatible)

The existing format is extended with optional fields. All new fields are optional and ignored by the legacy parser path.

**Example: metric goal**

```
## Goal: Reduce body fat percentage
Description: Reduce body fat percentage through training and nutrition.
Status: active
Metric: Body fat %
Unit: %
Start: 23.0
Current: 20.0
Target: 15.0
Direction: decrease
Deadline: 2027-03-31
Related tasks:
- Strength training plan
- Running schedule
- Nutrition review
```

**Example: task-based goal (legacy, still valid)**

```
## Goal: Complete autumn endurance challenge
Description: Complete a meaningful endurance event during autumn.
Status: active
Related tasks:
- Prepare training plan
- Buy running shoes
```

**Example: savings goal**

```
## Goal: Save 10000 PLN
Description: Build emergency fund.
Status: active
Metric: Savings balance
Unit: PLN
Start: 0.0
Current: 4500.0
Target: 10000.0
Direction: increase
Deadline: 2027-06-30
```

**Example: completed metric goal**

```
## Goal: Run 5 km without stopping
Description: First running milestone.
Status: completed
Metric: Continuous running distance
Unit: km
Start: 0.0
Current: 5.0
Target: 5.0
Direction: increase
```

### 6.2 Data ownership

| Data | Owner | Notes |
|------|-------|-------|
| Goal definition (title, description, status, deadline) | Goal | Core entity |
| Metric definition (metric_name, metric_unit, direction) | Goal | Optional descriptor |
| Target value | Goal | The desired outcome |
| Current value | Goal (MVP) | Shortcut for MVP — see Section 7 of review |
| Historical measurements | Future Measurement domain | NOT in goals.md; separate domain later |
| Related task titles | Goal | Strings, not references |
| Task completion state | Tasks domain | Queried by progress service, not owned by Goal |

### 6.3 Parser changes

`markdown_goals.py` parser extended to recognize new optional fields:

```
Metric: <value>
Unit: <value>
Start: <float>
Current: <float>
Target: <float>
Direction: increase | decrease
Deadline: YYYY-MM-DD
```

Backward compatibility:
- Old goals without these fields → fields remain `None` → task-based progress
- Missing file → return `[]` (NOT raise `FileNotFoundError` — aligns with other loaders)
- Malformed numeric values → `ValueError` with line number
- Unknown fields → ignored (preserved in raw data, not parsed)

### 6.4 Persistence API changes

```python
# Existing
load_goals() -> list[Goal]

# New
save_goal(goal: Goal) -> None        # append to goals.md
update_goal(goal: Goal) -> None      # replace existing goal by title
```

`save_goal` appends a new `## Goal:` block. `update_goal` rewrites the file, replacing the block with matching title.

---

## 7. CLI Design

### 7.1 MVP command set

| Command | Purpose | Example |
|---------|---------|---------|
| `janus goal list` | List all goals with status and progress | `janus goal list` |
| `janus goal show <title>` | Show single goal with full details and progress | `janus goal show "Reduce body fat"` |
| `janus goal add <title>` | Create a new goal with optional fields | `janus goal add "Save 10000 PLN" --metric "Savings" --unit PLN --start 0 --current 4500 --target 10000 --direction increase` |
| `janus goal update <title>` | Update goal fields | `janus goal update "Reduce body fat" --current 19.5` |
| `janus goal complete <title>` | Mark goal as completed (manual) | `janus goal complete "Reduce body fat"` |

### 7.2 `goal add` options

```
--description TEXT
--metric TEXT           (metric_name)
--unit TEXT             (metric_unit)
--start FLOAT
--current FLOAT
--target FLOAT
--direction increase|decrease
--deadline YYYY-MM-DD
--related-task TEXT     (repeatable)
--status active|completed|inactive  (default: active)
```

### 7.3 `goal update` options

```
--description TEXT
--metric TEXT
--unit TEXT
--start FLOAT
--current FLOAT
--target FLOAT
--direction increase|decrease
--deadline YYYY-MM-DD
--status active|completed|inactive
--add-related-task TEXT   (repeatable)
--remove-related-task TEXT (repeatable)
```

### 7.4 `goal list` output example

```
JANUS — GOALS
============================================================

ACTIVE (2):
  Reduce body fat percentage        62.5%  (20.0% → 15.0%, decrease)
  Prepare Japan trip                33.3%  (1/3 tasks completed)

COMPLETED (1):
  Run 5 km without stopping        100.0%  (5.0 km → 5.0 km, increase)

INACTIVE (0):
  —
```

### 7.5 `goal show` output example

```
JANUS — GOAL: Reduce body fat percentage
============================================================

  Status:      active
  Deadline:    2027-03-31
  Metric:      Body fat %
  Unit:        %
  Start:       23.0%
  Current:     20.0%
  Target:      15.0%
  Direction:   decrease
  Progress:    62.5%

  Related tasks:
    - Strength training plan (open)
    - Running schedule (open)
    - Nutrition review (completed)
```

### 7.6 `goal complete` contract

```
$ janus goal complete "Reduce body fat percentage"
Goal completed: Reduce body fat percentage
```

- Sets `status = "completed"`
- Does NOT modify `current_value`, `target_value`, or any metric fields
- Does NOT automatically trigger based on metric achievement
- User decides when goal is complete

---

## 8. Cross-Domain Integration

### 8.1 Tasks (existing)

Tasks are supporting actions for goals. Relationship is by title string.

- Task completion contributes to task-based progress for non-metric goals
- For metric goals, task completion is a supporting signal, NOT the progress source
- Weekly Review displays both: metric progress (if present) AND task completion status

### 8.2 Workouts / Workout Analytics (future)

**No direct Goal → Workout Analytics coupling in MVP.**

Future integration path (explicit, not plugin):

```
Goal: Run 100 km in September
  ├── current_value: 52.3 km  (manually set or derived)
  └── Future: query running workouts for September → sum distance_km → set as current_value
```

The derivation logic lives in a future service (e.g., `services/goal_derived_progress.py`), NOT in Goal model. Goal only stores the resulting `current_value`.

### 8.3 Future Nutrition / Body Metrics / Sleep / Wellness

Same pattern: future domain exposes a query function, Goal stores the result as `current_value`. No plugin system. No generic progress provider registry.

### 8.4 What Goal does NOT know about

- Workout implementation details
- Nutrition calorie calculations
- Body measurement protocols
- Sleep tracking mechanics
- How metrics are derived

Goal only knows: "I have a metric called X, my current value is Y, my target is Z."

---

## 9. Migration Strategy

### 9.1 Existing goals

Two existing goals in `data/goals.md`:

1. **Complete autumn endurance challenge** — task-based, no metric fields
2. **Maintain regular training** — task-based, no metric fields

Both remain valid under the new model. Their metric fields are simply `None`. They use task-based progress.

### 9.2 Backward compatibility

| Scenario | Behavior |
|----------|----------|
| Old goals.md without metric fields | Parsed as task-based goals; metric fields = None |
| New goals.md with metric fields | Parsed with metric fields populated |
| Mixed file (some old, some new) | Each goal parsed according to its own fields |
| Missing goals.md file | Return `[]` (changed from `FileNotFoundError`) |
| Old code calling `load_goals()` | Still returns `list[Goal]`; new fields are optional, old code ignores them |

### 9.3 No migration script

No automatic conversion. Existing goals stay as-is. User can manually add metric fields to existing goals via `janus goal update` when they want to convert a task-based goal to a metric goal.

### 9.4 Coexistence

Old and new Goal formats coexist in the same file. Parser handles both. No breaking change to existing functionality.

---

## 10. Phased Implementation Roadmap

### Milestone 1 — Core Goal Model + Persistence (MVP foundation)

**Objective:** Goal can be created, stored, loaded, and updated with optional metric fields.

**Files to CREATE:**
- `src/janus/models/goal.py` — modified (add optional metric fields + validation)
- `src/janus/services/goal_progress.py` — new (compute_goal_progress)
- `src/janus/goals_cli.py` — new (list/show/add/update/complete handlers)
- `tests/test_markdown_goals.py` — new (parser tests for old + new format)
- `tests/test_goal_progress.py` — new (progress calculation tests)
- `tests/test_goals_cli.py` — new (CLI tests)

**Files to MODIFY:**
- `src/janus/integrations/markdown_goals.py` — additive parser changes
- `src/janus/__init__.py` — dispatch `goal` subcommands
- `src/janus/services/weekly_review.py` — use float progress
- `src/janus/models/weekly_review.py` — `GoalReview.progress: float | None`
- `tests/test_weekly_review.py` — update assertions for float

**Persistence changes:**
- `data/goals.md` — add example metric goal alongside existing goals

**Tests:** 3 new test files + modifications to existing weekly review tests

**Migration risk:** Low — backward compatible parsing; no data migration

**Regression risk:** Low — existing Goal consumers (Attention, Daily Briefing) unaffected; Weekly Review progress type change is the only consumer change

**Complexity:** Low — additive changes, no abstractions

---

### Milestone 2 — Attention Engine + Daily Briefing integration

**Objective:** Goals with metrics surface progress signals in Daily Briefing.

**Files to MODIFY:**
- `src/janus/services/attention.py` — optional: new attention signals for goals (deadline approaching, no progress update, etc.) — scoped carefully
- `src/janus/today.py` — rendering updates if new attention signals added

**Files to CREATE:**
- Possibly `tests/test_goal_attention.py` — if new signals added

**Tests:** Attention signal tests if new signals added

**Migration risk:** None — additive attention signals

**Regression risk:** Low — existing stagnation detection unchanged

**Complexity:** Low-Medium — depends on how many new signals

**Note:** Per discovery brief: "Do not implement new attention signals during the first Goal milestone unless explicitly justified." This milestone is optional and can be deferred.

---

### Milestone 3 — Derived progress from domains (future)

**Objective:** Goals can auto-derive current_value from domain data (e.g., running distance from workouts).

**Files to CREATE:**
- `src/janus/services/goal_derived_progress.py` — new (explicit per-domain queries, NOT plugin)
- Possibly `tests/test_goal_derived_progress.py`

**Files to MODIFY:**
- `src/janus/goals_cli.py` — `goal update` could accept `--derive` flag (future)

**Persistence changes:** None — derived progress updates `current_value` in Goal

**Migration risk:** None

**Regression risk:** Low — derivation is explicit per domain

**Complexity:** Medium — requires domain query functions to exist first

**Prerequisites:** Workout Analytics must expose reusable query (e.g., "total running km in date range")

**Note:** This is BUILD LATER, not MVP.

---

### Milestone 4 — Measurement history domain (future)

**Objective:** Separate measurement history from Goal. Goal stores only current_value; history lives in a new domain.

**Files to CREATE:**
- `src/janus/models/measurement.py` — new
- `src/janus/integrations/markdown_measurements.py` — new (or separate storage)
- `src/janus/services/measurements.py` — new
- `tests/test_measurements.py` — new

**Files to MODIFY:**
- `src/janus/models/goal.py` — `current_value` becomes derived from latest measurement (or stays as manual shortcut)
- `src/janus/services/goal_progress.py` — query measurement service for current value

**Migration risk:** Medium — requires deciding whether existing current_value in goals.md migrates to measurement history

**Regression risk:** Medium — changes how current_value is sourced

**Complexity:** Medium-High — new domain with its own persistence

**Note:** This is BUILD LATER. For MVP, current_value lives on Goal directly.

---

## 11. Recommended MVP

### BUILD NOW

1. **Goal model with optional metric fields** — `models/goal.py` extended
2. **`compute_goal_progress(goal) -> float | None`** — metric-based with task fallback
3. **Persistence in `data/goals.md`** — additive format, backward compatible, no migration
4. **MVP CLI: list, show, add, update, complete** — 5 commands
5. **Weekly Review with float progress** — `GoalReview.progress: float | None`
6. **Manual goal completion** — target achievement does NOT auto-complete
7. **Status model: active / completed / inactive** — sufficient for MVP

### BUILD LATER

1. **Derived progress from workouts** — explicit query, not plugin
2. **Measurement history domain** — separate from Goal
3. **Milestone entities** — first-class milestones
4. **New Attention signals** — deadline approaching, no progress update, etc.
5. **Nutrition / Body Metrics / Sleep domains** — separate domains, feed into Goal current_value
6. **`goal progress` convenience command** — alias for `goal update --current`
7. **Goal validation stricter** — title uniqueness, metric/target consistency checks

### What MVP solves

- "I want to track reducing body fat from 23% to 15%" — metric goal with progress
- "I want to track saving 10,000 PLN" — metric goal with progress
- "I want to track my Japan trip planning" — task-based goal (legacy-compatible)
- "I want to see all my goals and their progress" — `goal list`
- "I want to record a new body fat measurement" — `goal update --current 19.5`
- "I finished my goal" — `goal complete`

### What MVP does NOT solve

- Auto-deriving progress from workouts
- Historical measurement storage
- Milestone tracking
- Automatic goal completion on target reached
- Cross-domain progress aggregation
- Predictive trajectory analysis

---

## 12. File-Level Implementation Map

| File | Action | Change |
|------|--------|--------|
| `src/janus/models/goal.py` | MODIFY | Add optional metric fields + status/direction validation |
| `src/janus/services/goal_progress.py` | CREATE | `compute_goal_progress(goal) -> float \| None`; task-based fallback |
| `src/janus/integrations/markdown_goals.py` | MODIFY | Parse new optional fields; return `[]` on missing file; backward compatible |
| `src/janus/goals_cli.py` | CREATE | `handle_goal_list`, `handle_goal_show`, `handle_goal_add`, `handle_goal_update`, `handle_goal_complete` |
| `src/janus/__init__.py` | MODIFY | Dispatch `goal` subcommands to handlers |
| `src/janus/services/weekly_review.py` | MODIFY | Use `compute_goal_progress` or task-based percentage; GoalReview.progress = float |
| `src/janus/models/weekly_review.py` | MODIFY | `GoalReview.progress: float \| None` |
| `src/janus/weekly.py` | MODIFY | Render float progress in CLI output |
| `src/janus/today.py` | NO CHANGE | Existing Goal usage unaffected |
| `src/janus/services/attention.py` | NO CHANGE | Existing stagnation detection unaffected (Milestone 2 only if justified) |
| `tests/test_markdown_goals.py` | CREATE | New file: parser tests (old + new format) |
| `tests/test_goal_progress.py` | CREATE | New file: progress calculation tests (metric + task-based + edge cases) |
| `tests/test_goals_cli.py` | CREATE | New file: CLI tests (list/show/add/update/complete) |
| `tests/test_weekly_review.py` | MODIFY | Update `GoalReview.progress` assertions from bool to float |
| `tests/test_attention.py` | NO CHANGE | Existing tests remain valid |
| `tests/test_daily_briefing.py` | NO CHANGE | Existing tests remain valid |
| `tests/test_today.py` | NO CHANGE | Existing tests remain valid |
| `data/goals.md` | MODIFY | Add example metric goal alongside existing task-based goals |

---

## 13. Risks

### 13.1 Overengineering risk

**Risk:** Adding abstractions (plugin system, generic progress providers, strategy pattern) that the repository doesn't need yet.

**Mitigation:** No plugin system in MVP. Explicit per-domain queries only when repetition appears. Metric fields are optional fields on Goal, not a separate entity.

### 13.2 Coupling risk

**Risk:** Goal becoming a central hub that knows about Tasks, Workouts, Nutrition, Sleep, etc.

**Mitigation:** Goal only stores metric fields and task titles. Domain-specific logic lives in domain services. Goal does not import workout models or nutrition models.

### 13.3 Migration risk

**Risk:** Breaking existing goals or existing consumers.

**Mitigation:** Additive parsing. No data migration. Existing goals remain valid task-based goals. Weekly Review is the only consumer with a type change (bool → float), and that change is explicit and tested.

### 13.4 Persistence risk

**Risk:** Parser complexity growing with each new field; ambiguity between old and new format.

**Mitigation:** New fields are optional and self-describing (named fields like `Metric:`, `Target:`). Parser ignores unknown fields. No positional parsing. Validation on numeric fields with line number reporting.

### 13.5 CLI complexity risk

**Risk:** `goal update` becoming a large command with too many options.

**Mitigation:** `update` only modifies fields the user specifies. Unspecified fields retain their current values. Options are flat, not nested. If `update` grows beyond ~15 options, consider splitting into `goal update-metric` and `goal update-tasks` subcommands — but not in MVP.

### 13.6 Current value vs measurement history risk

**Risk:** Storing `current_value` on Goal creates a shortcut that may be hard to migrate to a separate measurement domain later.

**Mitigation:** Accept this as a known MVP shortcut. Document it. When Measurement domain is created, `current_value` can be migrated to "latest measurement" query result. The migration is mechanical: replace `goal.current_value` with `measurements.latest(goal.metric_name)`.

---

## 14. Final Recommendation

**Goal = Outcome with optional metric.**

The simplest architecture that supports meaningful growth:

1. **Goal** is a dataclass with optional metric fields (`metric_name`, `metric_unit`, `start_value`, `current_value`, `target_value`, `direction`, `deadline`). All optional. A goal without these is a task-based goal (legacy-compatible).

2. **Progress** is computed by `compute_goal_progress(goal) -> float | None`. Metric-based when metric fields present; task-based percentage when no metric fields but related tasks exist; `None` when neither applies.

3. **Persistence** is `data/goals.md` with additive optional fields. No migration. No separate measurement storage in MVP.

4. **CLI** is 5 commands: `list`, `show`, `add`, `update`, `complete`. `complete` is always manual.

5. **Cross-domain integration** is explicit per-domain queries that set `current_value` on Goal. No plugin system. No generic progress provider registry.

6. **Weekly Review** receives `Optional[float]` progress and displays it. For metric goals: show metric progress + task completion as separate signal. For task-based goals: show task completion percentage.

This is simple, explicit, and extensible. It solves the immediate problem (measurable goals) without introducing abstractions for hypothetical future features.

---

## 15. Critical Design Review

> Adversarial review of the architecture above, conducted before implementation.
> Focus areas: Goal vs Measurement boundary, progress calculation edge cases,
> task-based vs metric progress semantics, goal completion contract, status model,
> Weekly Review compatibility, persistence format, CLI minimality, future integration.

### 15.1 Goal vs Measurement

**Finding:** The proposed model places `start_value`, `current_value`, `target_value` directly on Goal. This is a deliberate MVP shortcut, not a confusion with a Measurement domain.

**Analysis by example:**

| Goal type | What belongs to Goal | What belongs to future Measurements |
|-----------|---------------------|-------------------------------------|
| Body fat % | `metric_name="Body fat %"`, `target_value=15.0`, `direction="decrease"`, `current_value=20.0` (latest) | Historical body fat measurements: (date, value, method, notes) — separate domain |
| Body weight | `metric_name="Body weight"`, `target_value=80.0`, `current_value=82.0` | Historical weight log with timestamps — separate domain |
| Savings | `metric_name="Savings balance"`, `target_value=10000.0`, `current_value=4500.0` | Transaction history — separate domain (finance), not body measurement |
| Running distance (cumulative) | `metric_name="Total distance"`, `target_value=100.0`, `current_value=52.3`, `deadline=2026-09-30` | Individual workout records — already in Workout domain; aggregation is derived |
| Sleep duration | `metric_name="Avg sleep"`, `target_value=7.5`, `current_value=7.2` | Individual sleep records — separate domain |

**current_value on Goal is a good MVP shortcut because:**
- It solves the immediate problem: "what's my latest progress?"
- It avoids creating a Measurement domain before we know what measurements look like
- Migration to a Measurement domain is mechanical: replace `current_value` with "latest measurement query result"
- The shortcut does NOT prevent a future Measurement domain — it just delays it

**What this shortcut does NOT do:**
- Store historical measurements (correct — that's future domain's job)
- Automatically derive current_value from workouts (correct — that's future derived progress)
- Replace the need for a Measurement domain long-term (correct — it's a temporary shortcut)

**Verdict:** The boundary is clean. Goal owns the target and the latest value. Measurements (historical) belong elsewhere. MVP shortcut is justified and documented.

### 15.2 Progress calculation edge cases

Analysis of `compute_goal_progress(goal) -> float | None`:

| Edge case | Behavior | Verdict |
|-----------|----------|---------|
| `start_value == target_value`, `current_value == target_value` | Returns 100.0 | Correct — goal achieved from the start |
| `start_value == target_value`, `current_value != target_value` | Returns 0.0 (conservative) | Acceptable — degenerate case; "maintain at X" goal that drifted returns 0% progress. Alternative: return None. Recommendation: 0.0 is more useful for display |
| `current_value > target_value` (increase goal) | Returns 100.0 (capped) | Correct — target achieved; don't report >100% |
| `current_value < start_value` (increase goal) | Returns 0.0 | Correct — regression to baseline or below |
| `current_value > start_value` (decrease goal) | Returns 0.0 | Correct — moved away from target direction |
| `current_value < target_value` (decrease goal) | Returns 100.0 (capped) | Correct — target achieved |
| `current_value` missing | Returns None | Correct — can't compute without current |
| `start_value` missing | Returns None | Correct — can't compute without baseline. Alternative: infer start from first measurement. MVP: None is correct |
| `target_value` missing | Returns None | Correct — no target means no progress ratio. Goal can still exist as "improve X" without a specific target |
| `direction` missing | Returns None | Correct — can't determine progress direction |
| Negative values (e.g., debt: -5000 → 0) | Handled correctly by formula | `(−2000 − (−5000)) / (0 − (−5000)) * 100 = 60%` — mathematically valid |
| Percentages (body fat 23% → 15%) | Handled correctly | Unit is label only; math is unit-agnostic |
| Absolute units (PLN, kg, km) | Handled correctly | Same formula works regardless of unit |
| Invalid direction config (increase goal with target < start) | Returns None | Correct — configuration error, not a progress value |

**Semantic stability:** The function has a single, clear semantic: "what fraction of the distance from start to target has current covered, in the direction of target?" Returns None when this question cannot be answered. This is stable and testable.

**One clarification needed:** When `start_value == target_value` and `current_value != target_value`, the function returns 0.0. This is a design choice — an alternative is to return None (can't compute ratio when denominator is zero). Recommendation: return 0.0 because it's more useful for display ("no progress toward maintain-level goal") and avoids None propagation in Weekly Review. Document this choice explicitly.

### 15.3 Task-based progress vs metric progress

**The core question:** If a goal has both metric fields AND related_tasks, which progress is reported?

**Scenario analysis:**

1. **Goal has metric AND related_tasks; metric progress = 80%, task progress = 20%**
   - Tasks are supporting actions, not the outcome
   - Metric progress is THE progress (80%)
   - Task completion (20%) is a supporting signal: "you're doing the work, and it's paying off"
   - Display BOTH: "Progress: 80.0% (metric) | Tasks: 1/5 completed"

2. **Metric reached target (100%), but related_tasks still open**
   - Goal progress = 100% (target achieved)
   - Tasks still open — user may want to finish them
   - `goal complete` is still manual — user decides when goal is done
   - Display: "Progress: 100.0% (target achieved) | Tasks: 2/5 completed"

3. **All related_tasks completed, but metric target not reached**
   - Metric progress = e.g., 40% (not at target)
   - Task progress = 100% (all tasks done)
   - Task completion ≠ goal achievement
   - Goal should NOT auto-complete
   - Display: "Progress: 40.0% (metric) | All tasks completed — target not yet reached"

**Recommended semantics:**
- If metric fields present → metric progress is primary
- Task-based progress is ONLY used when NO metric fields present
- When both exist, display both as separate signals
- Task completion never overrides metric progress
- Task completion never auto-completes a goal

This is the most conservative semantics: metric goals stay metric goals; task-based goals stay task-based goals; no silent preference for one over the other when both exist.

### 15.4 Goal completion semantics

**`janus goal complete <title>` contract:**

1. **Always manual.** User explicitly runs `goal complete`.
2. **Sets `status = "completed"`.**
3. **Does NOT modify `current_value`, `target_value`, metric fields, or related_tasks.**
4. **Does NOT auto-trigger on target achievement.** Even if `current_value >= target_value` and progress = 100%, goal remains "active" until user completes it.
5. **Goal CAN be completed without reaching target.** User may decide a goal is no longer relevant, or that the outcome was achieved in a different way.

**Rationale:**
- Auto-completion on target reached would be surprising for goals where the user wants to do follow-up work (e.g., "Save 10000 PLN" — target reached, but user wants to set up auto-transfer task still)
- Manual completion gives user full control
- Status is a user decision, not a computed state

**Alternative considered and rejected:** Auto-complete when `progress == 100.0`. Rejected because: (a) some goals have targets that are milestones, not endpoints; (b) user may want to record the achievement moment vs. the cleanup moment; (c) introduces computed state that conflicts with manual status model.

### 15.5 Goal status model

**Current proposal:** `active`, `completed`, `inactive`

**Sufficiency analysis:**

| Status | Meaning | Needed? |
|--------|---------|---------|
| `active` | Goal is being worked on | Yes — default |
| `completed` | User declares goal achieved | Yes — manual completion |
| `inactive` | Goal is paused, abandoned, or not currently relevant | Yes — covers "paused", "abandoned", "cancelled" without needing separate statuses |

**Do we need `paused`?** No — `inactive` covers it. If user wants to resume, they set `status = active` again. Separate `paused` status adds complexity without clear benefit for MVP.

**Do we need `abandoned`?** No — `inactive` covers it. The distinction between "paused" and "abandoned" is semantic nuance that doesn't affect progress calculation or attention signals in MVP.

**Do we need `cancelled`?** No — same reasoning as `abandoned`.

**Recommendation:** Keep `active`, `completed`, `inactive`. Three states. Sufficient for MVP. If future need emerges for more granular inactive reasons, add a separate `inactive_reason` field rather than more status values.

### 15.6 Weekly Review compatibility

**Current state:** `GoalReview.progress: bool` — True if any related task completed.

**Proposed change:** `GoalReview.progress: float | None` — metric progress or task-based percentage.

**Impact analysis on all usage sites:**

| File | Current usage | Required change |
|------|---------------|-----------------|
| `models/weekly_review.py` | `progress: bool = False` | Change to `progress: float | None = None` |
| `services/weekly_review.py` | Sets `review.progress = True` if any completed | Compute float: metric progress if metric fields, else task-based percentage, else None |
| `weekly.py` (CLI renderer) | Prints "✓ Progress made" or "⚠ No progress recorded" | Print float with 1 decimal: "Progress: 62.5%" or "Progress: N/A" or "Progress: 33.3% (1/3 tasks)" |
| `tests/test_weekly_review.py` | Asserts `progress is True` / `progress is False` | Update assertions to float values |

**Is `float` 0–100 the best representation?**
- Yes — matches CLI display convention ("62.5%"), matches task progress percentage, consistent with `Task.progress` which is 0–100 integer.
- `0–1` would require multiplying/dividing by 100 at display boundaries. 0–100 is more direct.

**Is `Optional[float]` needed?**
- Yes — not all goals have measurable progress:
  - Goal with no metric fields and no related_tasks → None
  - Goal with metric fields but missing current_value → None
  - Goal with status "completed" or "inactive" → could return None or 100.0 for completed. Recommendation: return None for non-active goals (progress is a concept for active goals)

**Weekly Review output for different goal types:**

```
Task-based goal (3/10 tasks completed):
  Progress: 33.3% (3/10 tasks completed)

Metric goal (body fat 23%→15%, current 20%):
  Progress: 62.5% (20.0% → 15.0%)

Metric goal with tasks (body fat metric + 3 related tasks, 1 completed):
  Progress: 62.5% (metric)
  Tasks: 1/3 completed

Goal without measurable progress (no metric, no tasks):
  Progress: N/A

Completed goal:
  Progress: N/A (completed)
```

### 15.7 Persistence format

**Proposed format extension:**

```
Metric: <value>
Unit: <value>
Start: <float>
Current: <float>
Target: <float>
Direction: increase | decrease
Deadline: YYYY-MM-DD
```

**Backward compatibility:** ✅ New fields are optional. Old goals without them parse correctly with None values.

**Parser complexity:** Low — each new field is a named line starting with a known keyword. Parser uses `startswith()` checks (same pattern as existing `Description:`, `Status:`, `Related tasks:`).

**Ambiguity:** Low — field names are distinct. No positional reliance.

**Handling missing fields:** ✅ Fields default to None. Parser skips unknown fields.

**Validation:**
- `Start`, `Current`, `Target` → parse as float; malformed → ValueError with line number
- `Direction` → must be "increase" or "decrease"; invalid → ValueError
- `Deadline` → parse as YYYY-MM-DD; malformed → ValueError (or accept and store as string; recommendation: validate as date)
- `Metric`, `Unit` → free text strings; no validation beyond non-empty if present

**Duplicate fields:** If a goal block has two `Target:` lines, the last one wins (same behavior as existing parser for duplicate fields). This is acceptable for MVP — malformed goals are user error.

**Malformed numeric values:** Parser attempts `float(value)`. On ValueError, raises with line number. Same pattern as existing task parser.

**Recommendation:** Keep format minimal. Don't add sections, indentation, or structured substructures. Flat key-value lines are sufficient and match existing parser style.

### 15.8 CLI design minimality

**Proposed MVP: 5 commands (list, show, add, update, complete)**

**Is this minimal?** Yes — these 5 cover the core workflows:

| Workflow | Command | Necessary? |
|----------|---------|------------|
| See all goals | `list` | Yes |
| See one goal details | `show` | Yes |
| Create a goal | `add` | Yes |
| Record progress update | `update --current` | Yes |
| Mark goal done | `complete` | Yes |

**Could we drop any?**
- `show` — could be merged into `list` with a `--detail` flag, but separate command is cleaner for "show me this one goal"
- `complete` — could be `update --status completed`, but `complete` is more intentional and matches `task complete` pattern

**Could we need more?**
- `goal progress` as a separate command — NOT needed; `update --current` covers recording progress; `show` covers viewing progress
- `goal delete` — NOT in MVP; goals can be set to `inactive`
- `goal migrate` — NOT in MVP; no migration needed

**Is `goal update` too large?**
- Current proposal: ~12 optional flags (`--description`, `--metric`, `--unit`, `--start`, `--current`, `--target`, `--direction`, `--deadline`, `--status`, `--add-related-task`, `--remove-related-task`)
- This is manageable — each flag maps to one field
- If it grows further, consider splitting, but 12 flags is acceptable for a single-entity update command
- Recommendation: keep all in `update` for now; split only if it exceeds ~15 options or if subcommands make the workflow clearer

**Recommendation:** 5 commands is the right MVP set. No additions, no removals.

### 15.9 Future cross-domain integration

**Claim:** The recommended architecture allows future Fitness/Nutrition/Wellness/Body Metrics integration without redesigning Goal.

**Verification:**

1. **Goal stores `current_value` as a float.** Any domain can set this value. Fitness can set it from running distance. Nutrition can set it from calorie tracking. Body Metrics can set it from body fat measurements. The Goal model doesn't care where the number comes from.

2. **Goal stores `metric_name` and `metric_unit` as labels.** These are descriptive, not functional. They don't tie Goal to any domain. "Body fat %" is a label; Goal doesn't know about body fat measurement protocols.

3. **Derived progress is a future service, not a Goal feature.** When we want to auto-derive running distance from workouts, we create `services/goal_derived_progress.py` with an explicit function like `derive_running_distance_goal_progress(goal, workout_analytics_service)`. This function lives outside Goal. Goal only receives the resulting `current_value`.

4. **No plugin system.** Each domain integration is an explicit function. When we have 3+ domains doing similar derivation, we can refactor to a pattern — but not before.

5. **Goal does not import domain models.** Goal model has no dependency on workout models, nutrition models, or sleep models. This boundary is preserved.

**What could break this?**
- If Goal started storing domain-specific references (e.g., `workout_goal_id`, `nutrition_plan_id`) — DON'T do this
- If Goal started importing domain services — DON'T do this
- If Goal started computing domain-specific logic — DON'T do this

**As long as Goal remains:** "I have a metric label, a target, and a current value" — future domains can integrate without redesign.

**Verdict:** The architecture holds. No premature abstractions. Future integration is additive, not intrusive.

### 15.10 Problems found

| # | Problem | Severity | Fix |
|---|---------|----------|-----|
| 1 | `start_value == target_value` edge case: returning 0.0 vs None is a choice that should be explicit | Low | Document: return 0.0 for "maintain" goals that drifted; None alternative noted |
| 2 | Metric + tasks conflict: design says metric takes priority but doesn't explicitly say "display both" | Medium | Add explicit rule: when both present, display metric progress as primary AND task completion as separate signal |
| 3 | `current_value` on Goal is an MVP shortcut that should be flagged as temporary | Low | Document in persistence section and risks section (already done) |
| 4 | `deadline` field semantics unclear: is it a goal deadline or a measurement deadline? | Low | Clarify: deadline is the goal's target date for achieving the outcome, not a measurement deadline |
| 5 | Weekly Review `progress` change from `bool` to `float \| None` affects 4 files — not a large change but needs careful coordination | Low | Already mapped in file-level implementation plan |
| 6 | Parser raises `FileNotFoundError` on missing `goals.md` — inconsistent with other loaders | Medium | Fix: return `[]` instead (already in recommended changes) |
| 7 | `goal complete` contract: must be explicit that target achievement does NOT auto-complete | Medium | Document in CLI section and completion semantics (already done) |
| 8 | `inactive` status covers "paused", "abandoned", "cancelled" — but doesn't distinguish them | Low | Accept for MVP; note as future enhancement if needed |
| 9 | Time-bound goals (e.g., "Run 100km in September") can't encode the time window in MVP | Low | Document as known limitation; future: add `time_range` or rely on deadline + external query |
| 10 | `goal update` with 12 flags may feel large — worth monitoring as flags are added | Low | Accept for MVP; split if it grows beyond ~15 options |

**Total: 10 problems found. 0 structural changes required. 3 clarifications added to document. 7 already correctly handled.**

### 15.11 Decisions confirmed without change

1. ✅ Goal = Outcome with optional metric (not task container, not KPI-only, not plugin architecture)
2. ✅ Optional metric fields on Goal (start_value, current_value, target_value, direction, metric_name, metric_unit, deadline)
3. ✅ `compute_goal_progress(goal) -> float | None` with metric priority and task fallback
4. ✅ Float 0–100 progress representation (not 0–1)
5. ✅ Manual goal completion (target achievement does NOT auto-complete)
6. ✅ Status model: active / completed / inactive (three states sufficient for MVP)
7. ✅ Additive persistence in `data/goals.md` with backward compatibility
8. ✅ No migration script
9. ✅ No plugin system
10. ✅ No generic progress provider registry
11. ✅ 5-command MVP CLI (list, show, add, update, complete)
12. ✅ Task-based progress only when no metric fields present
13. ✅ Weekly Review progress: float | None

### 15.12 Corrections applied to recommendation

1. **Parser:** `load_goals()` now returns `[]` on missing file (not `FileNotFoundError`) — aligns with `load_tasks()` and `load_workouts()`
2. **Metric + tasks semantics:** When both present, metric progress is primary AND task completion is displayed as a separate signal — not silently choosing one
3. **start_value == target_value edge case:** Returns 0.0 (not None) for drifted "maintain" goals — more useful for display; documented explicitly
4. **Weekly Review float progress:** Explicitly shows "N/A" for goals without measurable progress and for completed/inactive goals
5. **Goal completion contract:** Explicitly documented that target achievement does NOT auto-complete; `goal complete` is always manual
6. **Deadline semantics:** Clarified as goal's target date for achieving the outcome, not a measurement deadline

### 15.13 Final revised recommendation

**Architecture is unchanged in structure.** The adversarial review confirmed the core design: Goal = Outcome with optional metric, progress as optional float, manual completion, additive persistence, no plugins, 5-command CLI.

**Three clarifications added:**
1. Metric + tasks: display both, metric primary
2. `start_value == target_value` edge case: return 0.0 for drifted goals
3. `load_goals()` returns `[]` on missing file (consistency fix)

**No structural changes. No new abstractions. No scope expansion.**

---

*End of document. Architecture ready for implementation planning.*
