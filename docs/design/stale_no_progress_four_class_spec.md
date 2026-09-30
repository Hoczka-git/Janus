# Design: Four-Class Stale / No-Progress Detection

**Task:** t_aefc85ce  
**Status:** Draft — concrete enough for direct implementation  
**Integration:** Required (touches attention engine, progress tracking, health model)

---

## 1. Four Detection Categories

| Polish (design) | English (code/API) | Meaning | Derived from |
|---|---|---|---|
| `brak danych` | `no_data` | No metric snapshots and no completed related tasks exist for this goal. | Data layer absence |
| `brak wykonania` | `no_execution` | Data exists but no execution evidence: no open related tasks, no task completions within the window, no activity records. | Execution layer absence |
| `wykonanie bez efektu` | `execution_without_effect` | Execution evidence exists (tasks completed / activity records) but derived progress/effect metrics show zero delta over lookback. | Effect layer absence |
| `cel osiągnięty` | `goal_achieved` | Goal is either `status == "completed"` or metric progress >= 100% (or task-based 100%). | Positive termination |

These are mutually exclusive and ordered: `goal_achieved` > `execution_without_effect` > `no_execution` > `no_data`. The highest-matched class wins.

---

## 2. Signals and Thresholds

### 2.1 `no_data` thresholds
- `metric_snapshots` is empty (no `MetricSnapshot` for the goal's metric).
- `related_tasks` non-empty but `all_task_titles` contains none of them (tasks never defined / missing from file).
- `days_since_last_activity` is `None` (no timestamp reference exists).

### 2.2 `no_execution` thresholds
- At least one `related_task` exists in file (`all_task_titles`).
- `open_task_titles` is empty (nothing open).
- `completed_task_dates` is either empty or all completions older than `inactivity_window_days`.
- `activity_records` (EvidencePackage / dispatch / propagation) count == 0 within the window.

### 2.3 `execution_without_effect` thresholds
- Execution count > 0 within `progress_lookback_days` (default 14).
- `compute_goal_progress()` > 0% (goal has a measurable config).
- `progress_delta` < `progress_slow_threshold` (default 5%) over the lookback.
- No `goal_overdue` / `milestone_slipped` / `goal_deadline_today` dominates (those are critical stall, not effect absence).

### 2.4 `goal_achieved` thresholds
- Goal `status == "completed"` OR
- Metric-based: `current_value` meets `target_value` within `direction`. OR
- Task-based: `completed_count == len(related_tasks)` and goal marked complete.

---

## 3. Integration with Existing Progress Tracking

- Uses existing `compute_goal_progress()` (`src/janus/services/goal_progress.py`) for effect measurement.
- Uses existing `assess_goal_stall()` / `StallSignal` (`attention.py`) as input signal feed — the four-class detector does NOT replace stall detection; it consumes the same context (open tasks, metric snapshots, completed dates, milestones) and produces a coarser classification.
- Consumes `get_metric_snapshots()` (`metric_history` integration) and `completed_task_dates`.
- Does NOT persist its own state; it is computed on demand like `GoalHealthAssessment`.
- Integration point: a new service module (`src/janus/services/stale_detection.py`) exposes a single entry function that takes the same context tuple as `assess_goal_stall()`.

---

## 4. API Surface

```python
# src/janus/services/stale_detection.py

from enum import Enum
from dataclasses import dataclass
from datetime import date, datetime

class NoProgressClass(str, Enum):
    NO_DATA = "no_data"
    NO_EXECUTION = "no_execution"
    EXECUTION_WITHOUT_EFFECT = "execution_without_effect"
    GOAL_ACHIEVED = "goal_achieved"

@dataclass
class NoProgressResult:
    goal_title: str
    classification: NoProgressClass
    confidence: float  # 0.0-1.0, derived from evidence strength
    dominant_signal: str | None  # highest stall signal if any
    progress_delta: float | None
    days_since_last_activity: int | None
    evaluated_at: datetime

    def to_dict(self) -> dict: ...

def classify_no_progress(
    goal: Goal,
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    metric_snapshots: list | None = None,
    completed_task_dates: dict[str, date] | None = None,
    activity_evidence_count: int = 0,
    progress_lookback_days: int = 14,
    effect_threshold_percent: float = 5.0,
) -> NoProgressResult:
    ...
```

### Events / Hooks
- `stale_detection.classified` emitted after each `classify_no_progress()` call with `goal_title`, `classification`, `confidence`, `dominant_signal`.
- Query hook: `GET /goals/<title>/no-progress` (future CLI adapter) delegates to `classify_no_progress()`.

---

## 5. Concrete Implementation Notes

- New file: `src/janus/services/stale_detection.py`.
- Modify: none — fully additive. Uses existing `Goal`, `StallSignal`, `compute_goal_progress`, `get_metric_snapshots`.
- Tests: `tests/test_stale_detection.py` covering all four classes, boundary conditions (degenerate metric config, zero-related-tasks, exactly-at-threshold progress delta), and the mutual-exclusion order.
- No persistence changes; `NoProgressResult` is derived and transient.
