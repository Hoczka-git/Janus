# Goal System — Implementation Plan (Revised)

> **Status:** Implementation-ready. Not implemented yet. Not committed.
> **Source:** `docs/goal_system_design.md` (approved architecture) + implementation corrections applied.
> **Primary implementation contract:** This document.

---

## 1. CORRECTIONS APPLIED (vs. original plan)

| # | Correction | Change |
|---|------------|--------|
| 1 | `compute_goal_progress` contract | Added `completed_task_titles: set[str] | None = None` parameter; single function handles both metric and task-based with clear priority |
| 2 | `start_value == target_value` logic | Handle equality BEFORE increase/decrease target validation in `compute_metric_progress` |
| 3 | Documentation count | Goal adds 7 new fields (metric_name, metric_unit, start_value, current_value, target_value, direction, deadline) for 11 total fields (title, description, status, deadline, metric_name, metric_unit, start_value, current_value, target_value, direction, related_tasks) |
| 4 | Remove `delete_goal()` | Removed from `goals.py` service and all documentation |
| 5 | Real `data/goals.md` | Use `tests/` temp fixtures only; do NOT modify production `data/goals.md` for example data |
| 6 | Title immutability | Goal title is immutable in MVP; title is the natural persistence identity; no title change operation |
| 7 | `progress_detail` format | Remove duplicated percentage: `"20.0 → 15.0, decrease"` not `"62.5% (20.0 → 15.0, decrease)"` when progress line already shows percentage |
| 8 | Duplicate related_tasks | Dedup preserving order on add/update; `update_goal_fields` with `add_related_task` skips if already present |
| 9 | `compute_task_based_progress` bounds | Validate `0 <= completed_count <= len(related_tasks)`; raise ValueError if violated |
| 10 | Unknown markdown fields | Explicitly documented: ignored on parse, NOT preserved through `update_goal` rewrite (only known fields survive) |
| 11 | Weekly Review delegation | Weekly Review calls `compute_goal_progress` with task context; does NOT duplicate metric/task priority logic |

---

## 2. PHASE A — DOMAIN MODEL

### File: `src/janus/models/goal.py`
**Action:** MODIFY (13 lines → ~50 lines)

**Current:** 4-field Goal dataclass (title, description, status, related_tasks). Basic `__post_init__` for related_tasks default.

**New:** 11-field Goal dataclass with full validation in `__post_init__`.

```python
from dataclasses import dataclass

@dataclass
class Goal:
    # Required
    title: str                              # persistence identity, immutable in MVP

    # Optional descriptive
    description: str = ""
    status: str = "active"                  # active | completed | inactive
    deadline: str | None = None             # ISO date YYYY-MM-DD

    # Optional metric fields (7 new)
    metric_name: str | None = None          # e.g. "Body fat %"
    metric_unit: str | None = None          # e.g. "%", "PLN", "kg"
    start_value: float | None = None        # baseline
    current_value: float | None = None      # latest
    target_value: float | None = None       # desired outcome
    direction: str | None = None            # "increase" | "decrease"

    # Task relationship
    related_tasks: list[str] = None         # supporting task titles (deduped, ordered)

    def __post_init__(self):
        if self.related_tasks is None:
            self.related_tasks = []
        # Dedup preserving order
        self.related_tasks = self._dedup_related_tasks(self.related_tasks)
        if self.status not in ("active", "completed", "inactive"):
            raise ValueError(
                f"Invalid goal status: {self.status!r}. "
                f"Allowed: active, completed, inactive"
            )
        if self.direction is not None and self.direction not in ("increase", "decrease"):
            raise ValueError(
                f"Invalid direction: {self.direction!r}. "
                f"Allowed: increase, decrease"
            )

    @staticmethod
    def _dedup_related_tasks(tasks: list[str]) -> list[str]:
        """Deduplicate preserving order."""
        seen = set()
        result = []
        for t in tasks:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result
```

**Immutability contract:** Title is never changed after creation. No `update_goal_fields` key for title. No CLI command to rename. Persistence identity = title.

---

## 3. PHASE B — PERSISTENCE

### File: `src/janus/integrations/markdown_goals.py`
**Action:** MODIFY (~70 lines → ~150 lines)

**Current signatures and behaviors:**
```python
PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOALS_PATH = PROJECT_ROOT / "data" / "goals.md"

def load_goals() -> list[Goal]:
    """Raises FileNotFoundError when file missing (TO BE CHANGED)."""
```

**New signatures:**
```python
def load_goals() -> list[Goal]:
    """Parse data/goals.md. Returns [] if file missing (changed from raising FileNotFoundError)."""

def save_goal(goal: Goal) -> None:
    """Append new goal to file. Raises ValueError if title empty."""

def update_goal(goal: Goal) -> None:
    """In-place rewrite of existing goal block by title. Raises ValueError if not found or title empty."""
```

**Parser — new fields recognized (in addition to existing Description:, Status:, Related tasks:):**

| Line prefix | Field | Parsing behavior |
|-------------|-------|------------------|
| `Metric:` | `metric_name` | string, stripped |
| `Unit:` | `metric_unit` | string, stripped |
| `Start:` | `start_value` | `float(value)`, ValueError on malformed |
| `Current:` | `current_value` | `float(value)`, ValueError on malformed |
| `Target:` | `target_value` | `float(value)`, ValueError on malformed |
| `Direction:` | `direction` | validate "increase"/"decrease", else ValueError |
| `Deadline:` | `deadline` | validate ISO date YYYY-MM-DD, else ValueError |

**Unknown field behavior (explicit documentation):**

> Unknown fields (anything not in the recognized set above) are **ignored on parse**. They are NOT preserved through `update_goal` rewrite — only known fields survive. This is acceptable for MVP: unknown fields are rare, and if preservation is needed in future, a separate raw-line preservation mechanism can be added. For now, `update_goal` rewrites the goal block from the Goal dataclass only.

**`_format_goal_block(goal: Goal) -> list[str]` output:**

```
## Goal: <title>
Description: <desc>           # if non-empty
Status: <status>              # always
Metric: <metric_name>         # if not None
Unit: <metric_unit>           # if not None
Start: <start_value>          # if not None
Current: <current_value>      # if not None
Target: <target_value>        # if not None
Direction: <direction>        # if not None
Deadline: <deadline>          # if not None
Related tasks:                # if related_tasks non-empty
- <task1>
- <task2>
```

**`save_goal`:** Append `_format_goal_block(goal)` + blank line to end of file.

**`update_goal`:** Read all lines, find block starting with `## Goal: <title>`, replace with new `_format_goal_block(goal)`, write back.

**No modifications to `data/goals.md` for example data.** Any example goals go into test fixtures in `tests/` only.

---

## 4. PHASE C — GOAL SERVICE

### File: `src/janus/services/goals.py`
**Action:** CREATE (~100 lines)

**Public API — no `delete_goal`:**

```python
from janus.models.goal import Goal
from janus.integrations.markdown_goals import load_goals, save_goal, update_goal

def add_goal(
    title: str,
    description: str = "",
    status: str = "active",
    deadline: str | None = None,
    metric_name: str | None = None,
    metric_unit: str | None = None,
    start_value: float | None = None,
    current_value: float | None = None,
    target_value: float | None = None,
    direction: str | None = None,
    related_tasks: list[str] | None = None,
) -> Goal:
    """Validate and persist new Goal. Returns the created Goal.
    Title is the persistence identity — immutable in MVP.
    Raises ValueError on validation failure.
    """

def get_goal(title: str) -> Goal:
    """Load a single Goal by exact title.
    Raises ValueError if not found or multiple found.
    """

def update_goal_fields(title: str, **kwargs) -> Goal:
    """Update specific fields of an existing Goal.
    Title is NOT updatable (immutable in MVP).
    Valid kwargs: description, status, deadline, metric_name, metric_unit,
                  start_value, current_value, target_value, direction,
                  add_related_task, remove_related_task
    Returns the updated Goal.
    Raises ValueError if goal not found or validation fails.
    """

def complete_goal(title: str) -> Goal:
    """Set status='completed'. Returns updated Goal. Raises ValueError if not found."""
```

**`update_goal_fields` — `add_related_task` dedup behavior:**

When `add_related_task` is in kwargs:
- If task already in `goal.related_tasks` → skip (no change)
- If task not in list → append

**No `delete_goal` anywhere.** Not in service, not in CLI, not in docs.

---

## 5. PHASE D — PROGRESS CALCULATION (CENTRALIZED)

### File: `src/janus/services/goal_progress.py`
**Action:** CREATE (~80 lines)

**One function, both paths, single priority rule — single source of truth:**

```python
from janus.models.goal import Goal

def compute_goal_progress(
    goal: Goal,
    completed_task_titles: set[str] | None = None,
) -> float | None:
    """Compute progress for a Goal.

    Priority (when goal.status == "active"):
    1. Metric path: if metric_name, target_value, direction, start_value,
       current_value all present → compute_metric_progress()
    2. Task-based path: elif related_tasks non-empty AND
       completed_task_titles is not None → compute_task_based_progress()
    3. Otherwise → None

    Returns None for: completed/inactive goals, missing metric fields,
    no tasks and no completed_task_titles provided.
    """

def compute_metric_progress(
    start_value: float,
    current_value: float,
    target_value: float,
    direction: str,
) -> float:
    """Low-level metric progress. Raises ValueError on invalid config.
    Handles start_value == target_value BEFORE direction validation.
    """

def compute_task_based_progress(
    related_tasks: list[str],
    completed_count: int,
) -> float:
    """Task-based progress percentage.
    Validates: related_tasks non-empty, 0 <= completed_count <= len(related_tasks).
    Raises ValueError if validation fails.
    """
```

**`compute_metric_progress` — exact logic with equality-first handling:**

```python
def compute_metric_progress(start_value, current_value, target_value, direction):
    if direction not in ("increase", "decrease"):
        raise ValueError(
            f"Invalid direction: {direction!r}. Allowed: increase, decrease"
        )

    # Degenerate maintain-at-X goal — handle BEFORE direction consistency check
    if start_value == target_value:
        return 100.0 if current_value == target_value else 0.0

    if direction == "increase":
        if target_value < start_value:
            raise ValueError(
                f"Invalid increase goal: target ({target_value}) must be "
                f"greater than start ({start_value})"
            )
        if current_value <= start_value:
            return 0.0
        if current_value >= target_value:
            return 100.0
        return (current_value - start_value) / (target_value - start_value) * 100.0

    # direction == "decrease"
    if target_value > start_value:
        raise ValueError(
            f"Invalid decrease goal: target ({target_value}) must be "
            f"less than start ({start_value})"
        )
    if current_value >= start_value:
        return 0.0
    if current_value <= target_value:
        return 100.0
    return (start_value - current_value) / (start_value - target_value) * 100.0
```

**`compute_task_based_progress` — with bounds validation:**

```python
def compute_task_based_progress(related_tasks, completed_count):
    if not related_tasks:
        raise ValueError("related_tasks must be non-empty")
    total = len(related_tasks)
    if not (0 <= completed_count <= total):
        raise ValueError(
            f"completed_count ({completed_count}) must be between 0 and "
            f"len(related_tasks) ({total})"
        )
    return (completed_count / total) * 100.0
```

**`compute_goal_progress` — full implementation:**

```python
def compute_goal_progress(goal, completed_task_titles=None):
    if goal.status != "active":
        return None

    # Metric path — has priority
    if (goal.metric_name and goal.target_value is not None
            and goal.direction and goal.start_value is not None
            and goal.current_value is not None):
        try:
            return compute_metric_progress(
                goal.start_value,
                goal.current_value,
                goal.target_value,
                goal.direction,
            )
        except ValueError:
            return None  # invalid metric config → no progress

    # Task-based path
    if goal.related_tasks and completed_task_titles is not None:
        completed_count = sum(1 for rt in goal.related_tasks if rt in completed_task_titles)
        return compute_task_based_progress(goal.related_tasks, completed_count)

    return None
```

---

## 6. PHASE E — CLI

### File: `src/janus/goals_cli.py`
**Action:** CREATE (~200 lines)

**5 handlers — no `delete_goal` command:**

```python
def handle_goal_list(args: list[str]) -> None: ...
def handle_goal_show(args: list[str]) -> None: ...
def handle_goal_add(args: list[str]) -> None: ...
def handle_goal_update(args: list[str]) -> None: ...
def handle_goal_complete(args: list[str]) -> None: ...
```

**`handle_goal_list` output format:**

```
JANUS — GOALS
============================================================

ACTIVE (2):
  Reduce body fat percentage        62.5%  20.0 → 15.0, decrease
  Prepare Japan trip                33.3%  1/3 tasks completed

COMPLETED (1):
  Run 5 km without stopping        100.0%  5.0 → 5.0, increase

INACTIVE (0):
  —
```

**`handle_goal_show` output format:**

```
JANUS — GOAL: Reduce body fat percentage
============================================================

  Status:      active
  Deadline:    2027-03-31
  Metric:      Body fat %
  Unit:        %
  Start:       23.0
  Current:     20.0
  Target:      15.0
  Direction:   decrease
  Progress:    62.5%

  Related tasks:
    - Strength training plan (open)
    - Running schedule (open)
    - Nutrition review (completed)
```

**`progress_detail` format (corrected — no duplicate %):**
- Metric: `"20.0 → 15.0, decrease"` — percentage shown once in `Progress:` line
- Task-based: `"1/3 tasks completed"` — percentage shown once in `Progress:` line
- N/A: `"N/A"` — no percentage

**`handle_goal_add` flags:**
`--description`, `--metric`, `--unit`, `--start`, `--current`, `--target`, `--direction`, `--deadline`, `--related-task` (repeatable), `--status` (active/completed/inactive, default: active)

**`handle_goal_update` flags:**
`--description`, `--metric`, `--unit`, `--start`, `--current`, `--target`, `--direction`, `--deadline`, `--status`, `--add-related-task` (repeatable), `--remove-related-task` (repeatable)

**No `--title` flag ever.** Title is positional only, immutable.

**Error handling:** Missing title → stderr + exit 1. Invalid float → stderr + exit 1. Unknown flag → stderr + exit 1. Goal not found → stderr + exit 1.

---

## 7. PHASE F — CLI DISPATCH

### File: `src/janus/__init__.py`
**Action:** MODIFY (~10 lines added)

Add after existing imports:
```python
from janus.goals_cli import (
    handle_goal_list,
    handle_goal_show,
    handle_goal_add,
    handle_goal_update,
    handle_goal_complete,
)
```

Add `elif command == "goal":` branch with 5 subcommands, matching `task` subcommand pattern.

---

## 8. PHASE G — WEEKLY REVIEW (DELEGATION, NOT DUPLICATION)

### File: `src/janus/models/weekly_review.py`
**Action:** MODIFY (1 field added)

```python
@dataclass
class GoalReview:
    goal: Goal
    progress: float | None = None          # from compute_goal_progress
    progress_detail: str | None = None     # human-readable, NO duplicate %
    completed_related_tasks: list[str] = []
    missing_related_tasks: list[str] = []
    suggested_next_step: str | None = None
    all_related_tasks_completed: bool = False
```

### File: `src/janus/services/weekly_review.py`
**Action:** MODIFY (~30 lines changed)

**Change:** Instead of inline metric/task priority logic, delegate to `compute_goal_progress`:

```python
from janus.services.goal_progress import compute_goal_progress

def create_weekly_review() -> WeeklyReview:
    goals = load_goals()
    tasks = load_tasks()
    completed_set = {t.title for t in tasks if t.state == "done"}

    reviews = []
    for goal in goals:
        review = GoalReview(goal=goal)

        # Delegate ALL progress computation to central service
        prog = compute_goal_progress(goal, completed_task_titles=completed_set)
        review.progress = prog

        if prog is not None:
            if goal.metric_name:
                review.progress_detail = (
                    f"{goal.current_value} → {goal.target_value}, {goal.direction}"
                )
            else:
                completed_count = sum(
                    1 for rt in goal.related_tasks if rt in completed_set
                )
                review.progress_detail = (
                    f"{completed_count}/{len(goal.related_tasks)} tasks completed"
                )
        else:
            review.progress_detail = "N/A"

        # ... rest of existing logic (completed_related_tasks, missing, suggested, all_completed)
```

**Key:** Weekly Review does NOT decide metric vs task priority. It passes `completed_set` and trusts `compute_goal_progress`.

### File: `src/janus/weekly.py`
**Action:** MODIFY (~15 lines changed)

Change progress rendering:
```python
# Before:
if gr.progress:
    print("✓ Progress made")
else:
    print("⚠ No progress recorded")

# After:
if gr.progress is not None:
    print(f"Progress: {gr.progress:.1f}%")
    if gr.progress_detail:
        print(f"  {gr.progress_detail}")
else:
    print("Progress: N/A")
```

---

## 9. PHASE H — TESTS

### File: `tests/test_markdown_goals.py` (CREATE)

All tests use temp fixtures ONLY. Does NOT modify `data/goals.md`.

```python
def _write_goals_file(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file
```

#### Test categories and cases:

**Model validation:**
- `test_goal_default_fields` — Goal("X") → status="active", direction=None, related_tasks=[]
- `test_goal_all_fields` — Full Goal with metric fields → no error
- `test_invalid_status` — Goal("X", status="pending") → ValueError
- `test_invalid_direction` — Goal("X", direction="sideways") → ValueError
- `test_dedup_preserves_order` — Goal("X", related_tasks=["A","B","A","C"]) → ["A","B","C"]
- `test_dedup_empty` — Goal("X", related_tasks=[]) → []
- `test_dedup_none` — Goal("X") → []

**Persistence round-trip (temp files only):**
- `test_roundtrip_minimal` — Goal("X") → save → load → equal
- `test_roundtrip_metric` — Full metric Goal → save → load → all fields preserved
- `test_roundtrip_task_only` — Task-based Goal → save → load → tasks preserved, metric fields None
- `test_roundtrip_deadline` — Goal with deadline → save → load → deadline preserved
- `test_save_appends` — Save two goals → file has two `## Goal:` blocks
- `test_update_replaces` — Save goal, modify, update_goal → file has one updated block
- `test_update_not_found` — update_goal with title not in file → ValueError
- `test_missing_file_returns_empty` — Monkeypatch GOALS_PATH to nonexistent → load_goals() returns []

**Backward compatibility:**
- `test_old_format_parses` — Load existing `data/goals.md` content (2 task-based goals) → 2 goals with correct fields, metric None
- `test_mixed_format` — File with old-style + new metric goal → both parse correctly
- `test_unknown_field_ignored_on_parse` — Goal block with `Foo: bar` → parses, `Foo` not in Goal
- `test_unknown_field_not_preserved_on_update` — Save goal with unknown field, update_goal, reload → unknown field gone

**New field parsing:**
- `test_parse_metric` through `test_parse_deadline` (7 tests)
- `test_malformed_start_raises` through `test_invalid_deadline_raises` (5 tests)

**Unknown field behavior:**
- `test_unknown_field_not_preserved_on_update` — Verify unknown fields lost after update_goal

**Duplicate related_tasks:**
- `test_duplicate_related_tasks_dedup` — Goal construction dedup preserves order

### File: `tests/test_goal_progress.py` (CREATE)

#### Metric increase:
| Test | start | current | target | → |
|------|-------|---------|--------|---|
| `test_increase_halfway` | 0 | 50 | 100 | 50.0 |
| `test_increase_three_quarter` | 140 | 170 | 200 | 75.0 |
| `test_increase_at_target` | 0 | 100 | 100 | 100.0 |
| `test_increase_beyond_target` | 0 | 120 | 100 | 100.0 |
| `test_increase_at_start` | 0 | 0 | 100 | 0.0 |
| `test_increase_below_start` | 100 | 80 | 200 | 0.0 |

#### Metric decrease:
| Test | start | current | target | → |
|------|-------|---------|--------|---|
| `test_decrease_body_fat` | 23 | 20 | 15 | 62.5 |
| `test_decrease_at_target` | 23 | 15 | 15 | 100.0 |
| `test_decrease_beyond_target` | 23 | 10 | 15 | 100.0 |
| `test_decrease_at_start` | 23 | 23 | 15 | 0.0 |
| `test_decrease_above_start` | 23 | 25 | 15 | 0.0 |

#### Edge cases:
| Test | Input | Expected |
|------|-------|----------|
| `test_start_equals_target_at_target` | start=80, current=80, target=80, increase | 100.0 |
| `test_start_equals_target_drifted` | start=80, current=82, target=80, increase | 0.0 |
| `test_negative_values_debt` | start=-5000, current=-2000, target=0, increase | 60.0 |
| `test_percentages` | start=23.0, current=20.0, target=15.0, decrease | 62.5 |
| `test_absolute_units_pln` | start=0, current=4500, target=10000, increase | 45.0 |
| `test_absolute_units_kg` | start=80, current=82, target=90, increase | 20.0 |

#### Invalid configuration:
| Test | Input | Expected |
|------|-------|----------|
| `test_invalid_increase_target_not_greater` | start=100, current=50, target=50, increase | ValueError |
| `test_invalid_decrease_target_not_less` | start=50, current=50, target=100, decrease | ValueError |

#### `compute_goal_progress` with full Goal objects:
| Test | Goal configuration | Expected |
|------|-------------------|----------|
| `test_metric_goal_full` | metric_name, start, current, target, direction all set | correct float |
| `test_metric_goal_missing_current` | metric_name set, current_value=None | None |
| `test_metric_goal_missing_start` | metric_name set, start_value=None | None |
| `test_metric_goal_missing_target` | metric_name set, target_value=None | None |
| `test_metric_goal_missing_direction` | metric_name set, direction=None | None |
| `test_task_based_goal` | no metric, related_tasks=['A','B','C'] (no completed_count) | None |
| `test_no_metric_no_tasks` | no metric, no related_tasks | None |
| `test_completed_goal` | status='completed', metric fields set | None |
| `test_inactive_goal` | status='inactive', metric fields set | None |
| `test_metric_plus_tasks_metric_prioritizes` | metric fields AND related_tasks | metric progress (not task-based) |
| `test_goal_with_completed_task_titles` | related_tasks=['A','B','C'], completed_task_titles={'A'} | 33.33... |
| `test_goal_without_completed_task_titles` | related_tasks=['A','B','C'], completed_task_titles=None | None (task path not taken) |

#### Task-based progress:
| Test | Input | Expected |
|------|-------|----------|
| `test_task_based_one_of_three` | related_tasks=['A','B','C'], completed_count=1 | 33.33... |
| `test_task_based_all_complete` | related_tasks=['A','B','C'], completed_count=3 | 100.0 |
| `test_task_based_none_complete` | related_tasks=['A','B','C'], completed_count=0 | 0.0 |
| `test_task_based_invalid_count_negative` | completed_count=-1 | ValueError |
| `test_task_based_invalid_count_over` | completed_count=4, len=3 | ValueError |
| `test_task_based_empty_tasks` | related_tasks=[] | ValueError |

### File: `tests/test_goals_cli.py` (CREATE)

Uses capsys to capture stdout/stderr.

| Test | Command | Expected |
|------|---------|----------|
| `test_list_empty` | `goal list` with no goals | "No goals defined" or empty sections |
| `test_show_not_found` | `goal show "Nonexistent"` | stderr error, exit 1 |
| `test_add_success` | `goal add "X" --metric "BF%" --start 23 --current 20 --target 15 --direction decrease` | stdout confirmation, goal persisted |
| `test_add_missing_title` | `goal add` with no title | stderr, exit 1 |
| `test_add_invalid_status` | `goal add "X" --status "pending"` | stderr, exit 1 |
| `test_add_invalid_direction` | `goal add "X" --direction "sideways"` | stderr, exit 1 |
| `test_add_invalid_float` | `goal add "X" --start "abc"` | stderr, exit 1 |
| `test_add_invalid_date` | `goal add "X" --deadline "bad"` | stderr, exit 1 |
| `test_update_success` | `goal update "X" --current 19` | stdout confirmation, current_value updated |
| `test_update_not_found` | `goal update "Nonexistent" --current 19` | stderr, exit 1 |
| `test_update_add_task` | `goal update "X" --add-related-task "New task"` | task added |
| `test_update_add_duplicate_task` | `goal update "X" --add-related-task "Existing task"` | no change (dedup) |
| `test_update_remove_task` | `goal update "X" --remove-related-task "Task"` | task removed |
| `test_complete_success` | `goal complete "X"` | status="completed" |
| `test_complete_not_found` | `goal complete "Nonexistent"` | stderr, exit 1 |
| `test_unknown_flag` | `goal add "X" --bogus` | stderr, exit 1 |
| `test_list_with_metric_goal` | After adding metric goal | Shows progress in output |
| `test_list_with_task_goal` | After adding task-based goal | Shows task progress |
| `test_show_metric_goal` | After adding metric goal | Shows all metric fields |
| `test_show_task_goal` | After adding task-based goal | Shows related tasks |

### File: `tests/test_weekly_review.py` (MODIFY existing)

**Existing tests to update (boolean → float):**
- `test_completed_related_task_produces_progress` (line 166): `assert review.goals[0].progress is True` → `assert review.goals[0].progress == 100.0`
- `test_open_related_task_reported_as_remaining` (line 183): `assert review.goals[0].progress is False` → `assert review.goals[0].progress == 0.0`
- `test_exact_title_matching` (line 282): `assert review.goals[0].progress is True` → `assert review.goals[0].progress == 100.0`
- `test_multiple_goals_all_active` (lines 316-317): `training.progress is True` → `training.progress == 100.0`; `groceries.progress is False` → `groceries.progress == 0.0`
- `test_weekly_output_includes_goal_with_progress` (line 408): `assert "✓ Progress made" in out` → `assert "Progress: 100.0%" in out`
- `test_weekly_output_includes_goal_without_progress` (line 426): `assert "⚠ No progress recorded" in out` → `assert "Progress: 0.0%" in out`

**Remove:**
- `test_missing_goals_file_raises` (line 123) → replace with `test_missing_goals_file_returns_empty`

**New tests to add:**
| Test | Checks |
|------|--------|
| `test_metric_goal_in_weekly_review` | Metric goal → progress is float, progress_detail is `"current → target, direction"` |
| `test_metric_goal_missing_current_in_weekly` | Metric goal with current_value=None → progress=None, detail="N/A" |
| `test_completed_goal_no_progress_in_weekly` | status="completed" → progress=None |
| `test_no_metric_no_tasks_no_progress` | Goal with neither → progress=None, detail="N/A" |
| `test_task_based_goal_in_weekly_review` | Task-based goal → progress is float, detail is `"X/Y tasks completed"` |

---

## 10. PHASE I — MANUAL VERIFICATION

After all phases complete:
1. Run full test suite → all tests pass
2. Run `janus goal list` → existing goals show correctly
3. Run `janus goal add` with metric goal → goal created, appears in list
4. Run `janus goal update --current` → progress updates
5. Run `janus goal complete` → goal marked completed
6. Run `janus weekly` → weekly review shows float progress
7. Verify existing `data/goals.md` still valid — no changes made

---

## 11. IMPLEMENTATION ORDER (minimizes broken intermediate states)

| Phase | Files | What it produces | What breaks if stopped here |
|-------|-------|-----------------|----------------------------|
| **A** | `models/goal.py` (MODIFY) | 11-field Goal, validation, dedup | Nothing breaks — old code that imports Goal still works (new fields have defaults) |
| **B** | `integrations/markdown_goals.py` (MODIFY) | `load_goals` returns `[]`, parses 7 new fields, `save_goal`, `update_goal` | `load_goals` behavior change is backward compatible for all callers; one test needs update |
| **C** | `services/goal_progress.py` (CREATE) | `compute_goal_progress`, metric + task functions | Nothing breaks — new module, no callers yet |
| **D** | `services/goals.py` (CREATE) | `add_goal`, `get_goal`, `update_goal_fields`, `complete_goal` | Nothing breaks — new module |
| **E** | `goals_cli.py` (CREATE) + `__init__.py` (MODIFY) | 5 CLI commands wired up | Nothing breaks — CLI not wired until `__init__.py` change; wiring is additive |
| **F** | `models/weekly_review.py` (MODIFY), `services/weekly_review.py` (MODIFY), `weekly.py` (MODIFY) | Weekly Review delegates to progress service, renders float | Existing weekly tests need assertion updates (boolean→float); weekly review still works for task-based goals |
| **G** | `tests/test_markdown_goals.py` (CREATE), `tests/test_goal_progress.py` (CREATE), `tests/test_goals_cli.py` (CREATE), `tests/test_weekly_review.py` (MODIFY) | Full test coverage | Tests not yet written — no functional regression, just incomplete coverage |
| **H** | Manual verification | All commands work | After G |

**No phase leaves the repo in a broken state.** Each phase is additive or backward-compatible.

---

## 12. FILES OUT OF SCOPE — NO CHANGE (26+ files)

**Production code (no changes):**
```
src/janus/services/attention.py        — no change
src/janus/today.py                      — no change
src/janus/services/daily_briefing.py    — no change
src/janus/models/attention.py           — no change
src/janus/models/event.py               — no change
src/janus/models/task.py                — no change
src/janus/services/tasks.py             — no change
src/janus/integrations/markdown_tasks.py — no change
src/janus/tasks_cli.py                  — no change
src/janus/workout_cli.py                — no change
src/janus/services/workout_analytics.py — no change
src/janus/models/workout.py             — no change
src/janus/integrations/workout_md.py    — no change
src/janus/models/daily_briefing.py      — no change
src/janus/integrations/telegram.py      — no change
```

**Test files (existing, no new tests for these):**
```
tests/test_attention.py                 — no change
tests/test_daily_briefing.py            — no change
tests/test_today.py                     — no change
tests/test_task_state_progress.py       — no change
tests/test_task_state_progress_cli.py   — no change
tests/test_task_complete.py             — no change
tests/test_task_write.py                — no change
tests/test_tasks_cli.py                 — no change
tests/test_fitness.py                   — no change
tests/test_workout_analytics.py         — no change
tests/test_workout_cli.py               — no change
tests/test_telegram.py                  — no change
tests/test_google_calendar.py           — no change
```

**Data files (NO modifications):**
```
data/goals.md                           — never touched for example data
data/tasks.md                           — never touched
data/workouts.md                        — never touched
```

---

## 13. IMPLEMENTATION CONTRACT

### Files expected to CHANGE (MODIFY) — 8 files

| File | Change | Lines affected (est.) |
|------|--------|----------------------|
| `src/janus/models/goal.py` | Add 7 optional metric fields + validation in `__post_init__` + dedup | 13 → ~50 |
| `src/janus/integrations/markdown_goals.py` | Fix missing-file (return `[]`); add parsing for 7 new fields; add `save_goal()`, `update_goal()`; add `_format_goal_block()` | ~70 → ~150 |
| `src/janus/services/weekly_review.py` | Use `compute_goal_progress()` for all goals; set `progress_detail`; handle completed/inactive | ~30 lines changed |
| `src/janus/models/weekly_review.py` | Change `GoalReview.progress: bool` → `float \| None`; add `progress_detail: str \| None` | ~5 lines changed |
| `src/janus/weekly.py` | Render float progress + detail; show "N/A" for None | ~15 lines changed |
| `src/janus/__init__.py` | Add `goal` subcommand dispatch (import + 5 subcommands) | ~15 lines added |
| `tests/test_weekly_review.py` | Update ~6 assertions from boolean to float; update ~2 CLI rendering assertions; add ~5 new tests for metric goals in weekly review; fix `test_missing_goals_file_raises` to expect `[]` | ~30 lines changed |

### Files expected to CREATE (NEW) — 3 files

| File | Lines (est.) | Responsibility |
|------|-------------|---------------|
| `src/janus/services/goals.py` | ~100 | CRUD service: `add_goal`, `get_goal`, `update_goal_fields`, `complete_goal` (no `delete_goal`) |
| `src/janus/services/goal_progress.py` | ~80 | `compute_goal_progress(goal, completed_task_titles=None)`, `compute_metric_progress`, `compute_task_based_progress` |
| `src/janus/goals_cli.py` | ~200 | 5 CLI handlers: `handle_goal_list`, `handle_goal_show`, `handle_goal_add`, `handle_goal_update`, `handle_goal_complete` |

### Files expected to CREATE (NEW, tests) — 3 files

| File | Lines (est.) | Responsibility |
|------|-------------|---------------|
| `tests/test_markdown_goals.py` | ~200 | Parser + persistence tests: model validation, backward compatibility, missing file, round-trip, new field parsing, save/update |
| `tests/test_goal_progress.py` | ~150 | Progress calculation tests: metric increase/decrease, edge cases, task-based, full Goal objects, metric+tasks semantics |
| `tests/test_goals_cli.py` | ~200 | CLI tests: list/show/add/update/complete, validation, error cases, output format |

### Files explicitly OUT OF SCOPE (NO CHANGE) — 26+ files

See Section 12 — all production modules except the 8 files in the contract, plus all existing test files except `test_weekly_review.py`.

### Definition of Done

1. **Model:** `Goal` dataclass has all 11 fields with correct validation in `__post_init__`. Invalid status raises ValueError. Invalid direction raises ValueError. Title immutable.

2. **Persistence:** `load_goals()` returns `[]` on missing file; parses 7 new optional fields; `save_goal()` and `update_goal()` work correctly; backward compatible with existing `data/goals.md`. Unknown fields ignored on parse, not preserved through rewrite.

3. **Service:** `add_goal`, `get_goal`, `update_goal_fields`, `complete_goal` all work; validation errors raise `ValueError`. No `delete_goal`.

4. **Progress:** `compute_goal_progress` returns correct float for all cases; returns None for non-computable cases. `compute_metric_progress` raises ValueError on invalid config. `compute_task_based_progress` validates bounds. Equality-first logic in metric progress.

5. **CLI:** All 5 commands work; validation errors exit with code 1 and message on stderr; output format matches design. No `delete_goal` command.

6. **Dispatch:** `janus goal <subcommand>` works from CLI.

7. **Weekly Review:** `GoalReview.progress` is `float | None`; weekly review service computes correct progress via delegation; weekly CLI renders float + detail; "N/A" for None. No duplicate % in progress_detail.

8. **Tests:** All new test files created; all existing tests still pass (with required updates to `test_weekly_review.py`); full test suite green.

9. **Backward compatibility:** Existing 2 goals in `data/goals.md` still load correctly; no data migration needed. `test_missing_goals_file_raises` updated to expect `[]`.

10. **Title immutability:** No title change operation in service or CLI.

11. **Centralized progress:** `compute_goal_progress` is the ONLY place that decides metric vs task priority.

12. **No out-of-scope features:** None of the 10 excluded features present.

### Verification commands

```bash
# After Phase A (model):
PYTHONPATH=src python -c "from janus.models.goal import Goal; g = Goal(title='Test', status='active'); print(g)"

# After Phase B (persistence):
PYTHONPATH=src python -c "from janus.integrations.markdown_goals import load_goals; print(len(load_goals()))"

# After Phase C (service):
PYTHONPATH=src python -c "from janus.services.goals import add_goal; g = add_goal('Test Goal'); print(g)"

# After Phase D (progress):
PYTHONPATH=src python -c "from janus.models.goal import Goal; from janus.services.goal_progress import compute_goal_progress; g = Goal(title='Test', metric_name='X', start_value=0, current_value=50, target_value=100, direction='increase'); print(compute_goal_progress(g))"

# After Phase E+F (CLI):
PYTHONPATH=src python -c "import sys; sys.argv=['janus','goal','list']; from janus import main; main()"

# Full test suite:
PYTHONPATH=src /home/dan11hermes/.local/bin/uv run pytest tests/ -v

# Targeted goal tests:
PYTHONPATH=src /home/dan11hermes/.local/bin/uv run pytest tests/test_markdown_goals.py tests/test_goal_progress.py tests/test_goals_cli.py tests/test_weekly_review.py -v
```

### Expected commit boundary

One commit containing all changes for the MVP:

```
feat: add Goal System MVP (metric goals, progress, CLI)

- Extend Goal model to 11 fields (title immutable, 7 new optional metric fields)
- Add validation for status and direction, dedup related_tasks in __post_init__
- Update markdown_goals.py: return [] on missing file (was FileNotFoundError),
  parse 7 new fields (Metric, Unit, Start, Current, Target, Direction, Deadline),
  add save_goal() and update_goal() persistence functions,
  unknown fields ignored on parse and not preserved through update rewrite
- Create services/goal_progress.py: compute_goal_progress(goal, completed_task_titles=None),
  compute_metric_progress (equality-first), compute_task_based_progress (bounds-checked)
- Create services/goals.py: add_goal, get_goal, update_goal_fields (no delete_goal)
- Create goals_cli.py: 5 commands (list, show, add, update, complete)
- Wire goal subcommand in __init__.py
- Update Weekly Review: GoalReview.progress bool → float | None, add progress_detail,
  delegate to compute_goal_progress, no duplicate % in detail
- Update weekly.py renderer for float progress with detail
- Add tests: test_markdown_goals.py, test_goal_progress.py, test_goals_cli.py
- Update tests/test_weekly_review.py: boolean→float assertions, add metric goal tests,
  fix test_missing_goals_file_raises to expect []

Co-Authored-By: Hermes Agent <hermestool@nousresearch.com>
```

**Do NOT commit until:**
- All phases A-I complete
- Full test suite passes (326+ existing tests + new goal tests)
- Manual verification complete (goal add/show/update/complete/list all work; weekly review shows float progress)
- No modifications to production `data/goals.md`
- `tests/test_weekly_review.py` updated for boolean→float transition

---

## 14. SCOPE BOUNDARIES

### In scope for MVP (10 items)

1. Goal model with 11 fields (title immutable, 7 new optional metric fields)
2. `compute_goal_progress(goal, completed_task_titles=None) -> float | None`
3. Persistence in `data/goals.md` with additive format (return `[]` on missing file)
4. `save_goal()`, `update_goal()` persistence functions (no `delete_goal`)
5. `goals.py` service with `add_goal`, `get_goal`, `update_goal_fields`, `complete_goal`
6. CLI: `list`, `show`, `add`, `update`, `complete` — 5 commands
7. Weekly Review: `GoalReview.progress` changes from `bool` to `float | None`, delegates to progress service
8. `progress_detail` field (no duplicate %)
9. Task-based progress fallback for goals without metric fields
10. Metric + tasks: metric progress primary, task completion shown as separate signal

### Out of scope — explicitly excluded (10 items)

| Feature | Reason |
|---------|--------|
| `time_range` goals | Not in model; known limitation; deferred |
| AI coaching / recommendations | Not in scope per design |
| Charts / dashboards | Not in scope per design |
| Goal hierarchies (parent/child goals) | Not requested; adds complexity |
| Complex habit tracking | Not requested |
| Automatic target completion | Explicitly rejected in design review |
| `paused` / `abandoned` / `cancelled` status expansion | `inactive` covers all three per review |
| Derived progress from workouts (auto-derive current_value) | Milestone 3, not MVP |
| Measurement history domain | Milestone 4, not MVP |
| New Attention Engine signals (deadline approaching, etc.) | Milestone 2, deferred |
| `goal progress` convenience command | Covered by `goal update --current` |
| `goal delete` CLI command | Optional, may be deferred; service has no delete_goal |
| Plugin system / generic progress providers | Explicitly rejected |
| `goal migrate` command | No migration needed |
| `load_tasks()` return `[]` on missing file | Out of scope — only fix `load_goals()` |
| Stricter goal validation (title uniqueness, metric/target consistency) | Future enhancement |
| Refactoring `markdown_tasks.py` or `load_tasks()` | No change needed |
| Modifications to `data/goals.md` for example data | Use test fixtures only |

### Scope creep red flags to watch

1. Adding `time_range` field — do not add. Document as known limitation.
2. Adding `paused` status — do not add. Use `inactive`.
3. Auto-completing goal when target reached — do not implement. `complete` is manual.
4. Creating `Measurement` domain — do not create. `current_value` stays on Goal for MVP.
5. Adding derived progress from workouts — do not add. Milestone 3 only.
6. Refactoring `load_tasks()` to return `[]` on missing file — out of scope. Only fix `load_goals()`.
7. Adding new Attention signals — out of scope. Existing stagnation detection unchanged.
8. Creating `services/goal_derived_progress.py` — out of scope. Future milestone.
9. Adding goal title uniqueness validation — out of scope. Allow duplicates for now.
10. Adding `goal delete` CLI command — out of scope. Not in MVP.

---

## 15. FINAL VERIFICATION

Before claiming the goal is done:

1. **Read `docs/goal_system_design.md`** — confirms source of truth (already read, content current)
2. **Read all relevant existing files** — confirms no unseen contradictions (done: goal.py, markdown_goals.py, weekly_review.py, weekly.py, __init__.py, goals_cli.py)
3. **Verify repository state** — `git status --short` shows only `data/tasks.md` as pre-existing modification (not in scope), no unintended changes
4. **No material contradictions found** — the implementation plan aligns with the design document and existing codebase

**Ready to implement.** The plan is complete, internally consistent, and grounded in the existing codebase. No speculative changes will be made. All phases A-I will be implemented in order, with targeted tests after each phase. The final verification will include full test suite and manual CLI verification.

---

*End of implementation plan. Ready for execution.*