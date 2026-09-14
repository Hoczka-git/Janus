# Goal Health, Progress Signals, and Stalled-Goal Detection — Design Specification

**Task:** t_8318e9e3
**Date:** 2026-09-06
**Status:** Draft — ready for implementation planning
**Integration:** Required (touches attention engine, weekly review, goal model, CLI, observability)

---

## 1. Purpose and Scope

This spec defines the extension of Janus's goal management with three interconnected capabilities:

1. **Goal health model** — a composite health state for each active goal, derived from automated signals, that surfaces at a glance whether a goal is on track, at risk, or stalled.
2. **Progress signal types** — the individual signal types that feed health assessment, how they are emitted by existing services, and how they are aggregated into a health assessment.
3. **Stalled-goal detection** — the logic, thresholds, timing, and notification/flagging behavior for detecting goals that are not making meaningful progress.

**Out of scope for this spec:**
- Milestone CRUD (already designed in `DESIGN_EXECUTION_PLANNING.md`).
- Measurement collection mechanism (already designed — see goal-driven measurement collection tasks).
- Execution planning / next-action sequencing (separately specified).
- Research → finding → decision → action loop closure (separately specified).
- Implementation. This is a design document only.

---

## 2. Research Foundation

The parent research task (t_11af88e5) identified these gaps and recommendations. This spec adopts them as design inputs.

### 2.1 Findings (from t_11af88e5)

| Gap | Description |
|-----|-------------|
| No historical progress tracking | Progress is computed from current state only; no trend history. |
| No metric snapshots | No append-only log of metric values over time. |
| No inactivity-based stall signal | Current stall is binary (all tasks done → stalled); no time-based inactivity detection. |
| No composite health score | No aggregated health state across all signal types. |
| Passive measurement requirements | Goals can define measurements but nothing checks/flags when measurements are overdue. |
| No goal → research/decision link | Goals are not connected to research artifacts or decisions. |

### 2.2 Adopted Recommendations

1. Extend `assess_goal_stall()` with `measurement_due`, `no_recent_activity`, and `progress_slow` signals.
2. Add metric snapshot logging (append-only `data/metric_history.md`).
3. Extend `GoalReview` with `progress_delta` and `days_since_last_activity`.
4. Add active measurement-requirement checking in the attention engine.
5. Add a `goal health` CLI command.

---

## 3. Current State (as of 2026-09-06)

### 3.1 What already exists

The codebase already has significant groundwork that this spec builds on:

**Goal model** (`src/janus/models/goal.py`):
- `status`: active | completed | inactive
- `deadline`: ISO date string
- `metric_name`, `metric_unit`, `start_value`, `current_value`, `target_value`, `direction`
- `related_tasks: list[str]` — task titles (deduped, ordered)
- `milestones: list[dict]` — already stored on the model
- `measurement_requirements: list[dict]` — already stored on the model (from measurement collection design)

**Milestone model** (`src/janus/models/milestone.py`):
- `title`, `goal_title`, `description`, `deadline`, `status` (open | in_progress | completed | skipped), `order`

**Attention engine** (`src/janus/services/attention.py`):
- `assess_goal_stall(goal, today, open_task_titles, all_task_titles)` — already returns multiple `StallSignal` tuples
- Existing signals: `goal_overdue` (100), `goal_deadline_today` (90), `goal_deadline_soon` (60), `milestone_slipped` (50), `milestone_deadline_soon` (55), `goal_inactive` (30), `goal_stalled` (40, fallback)
- Goal deadline signals take precedence over milestone deadline signals
- `get_attention_items()` picks the highest-scoring signal per goal and produces an `AttentionItem`

**Goal progress** (`src/janus/services/goal_progress.py`):
- `compute_goal_progress(goal, completed_task_titles)` — metric path prioritized over task-based path
- Returns `None` for completed/inactive goals or missing config

**Weekly review** (`src/janus/services/weekly_review.py`):
- `GoalReview` model: `goal`, `progress`, `progress_detail`, `completed_related_tasks`, `missing_related_tasks`, `suggested_next_step`, `all_related_tasks_completed`
- Delegates progress computation to `compute_goal_progress`

**Persistence** (`src/janus/integrations/markdown_goals.py`):
- `data/goals.md` format with `## Goal:` blocks
- Unknown fields ignored on parse, not preserved through rewrite

### 3.2 What is missing

| Missing | Impact |
|---------|--------|
| No `progress_slow` signal | Goals with open tasks but negligible progress are not differentiated from healthy goals. |
| No `measurement_due` signal | Goals with overdue measurement requirements are not surfaced. |
| No `no_recent_activity` signal (time-based) | Goals with no activity over a configurable window are not flagged distinct from binary stall. |
| No composite health state | Each goal gets individual signals but no aggregated health label (healthy/at-risk/stalled). |
| No metric snapshot history | Progress trends cannot be computed; `progress_delta` in weekly review would be unavailable. |
| No `days_since_last_activity` on GoalReview | Weekly review cannot report how long a goal has been inactive. |
| No `goal health` CLI command | Health state is not inspectable without reading attention items. |
| No notification/flagging behavior spec | When a goal becomes stalled or at-risk, there is no defined mechanism for alerting or flagging. |

---

## 4. Goal Health Model

### 4.1 Health States

Each active goal can be assigned exactly one of four health states, evaluated from the set of signals that fire for that goal. The health state is a derived attribute, not a stored field — it is computed on demand from current signals.

| State | Label | Definition | Typical signals present |
|-------|-------|------------|------------------------|
| `healthy` | On track | Goal has open related tasks in progress, or metric progress is improving, and no warning/alert signals fire. | Possibly `goal_deadline_soon` if within 7 days but tasks are open (not stalled). |
| `watch` | At risk | Goal has a warning signal but no blocking signal. Progress may be slow, a measurement is overdue, or a milestone deadline is approaching. | `progress_slow`, `measurement_due`, `milestone_deadline_soon`, `goal_inactive` (if higher signals absent) |
| `stalled` | Stalled | Goal has no open related tasks and no upcoming milestone/deadline that would explain the pause; or a milestone/goal deadline has passed with no open tasks. | `goal_stalled`, `goal_overdue`, `milestone_slipped`, `no_recent_activity` |
| `completed` | Completed | Goal status is `completed`. No signals evaluated. | N/A |

**Inactive goals** (status=`inactive`) are excluded from health evaluation entirely — they are not healthy, watch, or stalled; they are paused by intent.

**Completed goals** are always `completed` state.

### 4.2 Health State Resolution Order

When multiple signals fire for the same goal, the health state is determined by the highest-severity signal, using this severity order (lowest to highest):

1. `goal_deadline_soon` (60) — does NOT by itself downgrade health if open tasks exist (the goal is active and working toward the deadline). Only downgrades to `watch` if combined with `progress_slow` or no open tasks.
2. `milestone_deadline_soon` (55) — same logic as goal_deadline_soon.
3. `measurement_due` (new, scored 45) — downgrades to `watch`.
4. `progress_slow` (new, scored 40) — downgrades to `watch`.
5. `goal_inactive` (30) — downgrades to `watch` (low severity, but indicates no forward momentum).
6. `goal_stalled` (40) — downgrades to `stalled`.
7. `milestone_slipped` (50) — downgrades to `stalled`.
8. `goal_overdue` (100) — downgrades to `stalled`.
9. `no_recent_activity` (new, scored 35) — downgrades to `stalled` (distinct from `goal_inactive`: this means the goal is active but has had no measurable activity for a configured window).

**Resolution rule:** The health state is the state corresponding to the highest-severity signal that fired. If no signal fires, the state is `healthy`.

**Exception:** `goal_deadline_soon` and `milestone_deadline_soon` do NOT downgrade a goal to `watch` if there are open related tasks AND no `progress_slow` signal. The goal is actively working toward the deadline. The soon-deadline signal alone indicates urgency, not a health problem.

### 4.3 Health State Diagram

```
                    No signals fire
                    ───────────────
                           │
                           ▼
                        healthy
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
         progress_slow  measurement    milestone/
         or goal_inactive  _due        deadline_soon
              │            │            │
              │            │            │
              ▼            ▼            ▼
                        watch
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
         goal_stalled  milestone_   goal_overdue
                        slipped     or
                           │       no_recent_activity
                           │            │
                           ▼            ▼
                         stalled
```

---

## 5. Progress Signal Types

### 5.1 Signal Taxonomy

Signals are the individual data points that feed health assessment. They are emitted by services during normal operation and consumed by the health assessment function. Each signal has a type, a score, a reason string, and a timestamp.

**Signal types (existing + new):**

| Signal | Type | Source | Score | Severity | Fires when |
|--------|------|--------|-------|----------|------------|
| `goal_overdue` | deadline | attention.py | 100 | critical | Goal deadline passed AND no open related tasks |
| `goal_deadline_today` | deadline | attention.py | 90 | critical | Goal deadline is today |
| `goal_deadline_soon` | deadline | attention.py | 60 | warning | Goal deadline within 7 days (future) |
| `milestone_slipped` | deadline | attention.py | 50 | critical | Milestone deadline passed AND status not completed/skipped |
| `milestone_deadline_soon` | deadline | attention.py | 55 | warning | Milestone deadline within 7 days (future) AND not completed/skipped |
| `goal_stalled` | stall | attention.py | 40 | critical | All related tasks completed, no higher signal fires |
| `goal_inactive` | inactivity | attention.py | 30 | warning | All tasks done, no future milestone/deadline |
| `progress_slow` | progress | NEW | 40 | warning | Goal has open tasks but progress delta over lookback window is below threshold |
| `measurement_due` | measurement | NEW | 45 | warning | One or more measurement requirements for the goal are overdue |
| `no_recent_activity` | inactivity | NEW | 35 | critical | Goal has had no metric update and no task completion within the configured inactivity window |

### 5.2 Signal Data Model

```python
@dataclass
class GoalSignal:
    """A single signal emitted for a goal at a point in time."""
    signal: str              # signal identifier (matches StallSignal.signal)
    score: int
    reason: str
    timestamp: datetime      # when the signal was evaluated
    stale_after: timedelta | None  # optional: auto-resolve after this duration
```

Signals are NOT persisted by default. They are computed on demand by `assess_goal_health(goal, today, context)` which returns a list of `GoalSignal` objects. For observability, the attention engine emits the signal set as part of its existing `engine.attention.computed` log event (extended with a `goal_signals` field).

### 5.3 Signal Emission Points

| Signal | Emitted by | When |
|--------|-----------|------|
| All deadline signals | `assess_goal_stall()` in attention.py | During `get_attention_items()` call and any direct call to `assess_goal_stall()` |
| `goal_stalled`, `goal_inactive` | `assess_goal_stall()` in attention.py | Same as above |
| `progress_slow` | `assess_goal_health()` (new function) | When metric history is available and lookback window has elapsed |
| `measurement_due` | `assess_goal_health()` (new function) | When measurement requirements exist and the last recorded measurement is older than the frequency interval |
| `no_recent_activity` | `assess_goal_health()` (new function) | When no metric snapshot and no task completion exists within the inactivity window |

### 5.4 Signal Aggregation into Health Assessment

The health assessment function `assess_goal_health(goal, context)` is the single entry point for computing a goal's health state. It:

1. Calls `assess_goal_stall()` to get existing signals (deadline + stall + inactive).
2. Computes new signals (`progress_slow`, `measurement_due`, `no_recent_activity`) using available context.
3. Applies the health state resolution order (§4.2) to determine the health state.
4. Returns a `GoalHealthAssessment` dataclass.

```python
@dataclass
class GoalHealthAssessment:
    goal_title: str
    health_state: str                    # healthy | watch | stalled | completed
    signals: list[GoalSignal]            # all signals that fired
    dominant_signal: GoalSignal | None   # highest-severity signal (None if healthy)
    progress: float | None               # current progress % (from compute_goal_progress)
    progress_delta: float | None         # change in progress over lookback window (new)
    days_since_last_activity: int | None # days since last metric update or task completion
    measurement_overdue_count: int       # number of overdue measurement requirements
    evaluated_at: datetime
```

---

## 6. Stalled-Goal Detection Logic

### 6.1 Definition of Stalled

A goal is **stalled** when it is in status `active` but has no forward momentum — no open tasks to drive it, no upcoming milestones or deadlines that explain the pause, and no recent activity that would indicate work is happening outside the task system.

A goal is **not stalled** when:
- It has at least one open related task (work is scheduled), OR
- It has an upcoming milestone or deadline (work is planned), OR
- It has had measurable activity (metric update or task completion) within the inactivity window.

### 6.2 Stalled Detection Signals

Stalled detection uses three signals, in order of specificity:

#### 6.2.1 `goal_stalled` (existing, score 40)

Fires when:
- All related tasks are completed (exist in file, none open), AND
- There are existing related tasks (at least one task title that exists in the file), AND
- No higher-severity signal fires (goal_overdue, goal_deadline_today, goal_deadline_soon, milestone_slipped all score higher).

This is the existing binary stall detection, retained as a fallback per the current attention engine design.

#### 6.2.2 `no_recent_activity` (new, score 35)

Fires when ALL of the following are true:
- Goal status is `active`.
- No metric snapshot has been recorded for this goal within the configured inactivity window (default: 30 days).
- No related task has been completed within the configured inactivity window (default: 30 days).
- No upcoming milestone deadline exists (all milestones are either in the past, completed, skipped, or have no deadline).
- No upcoming goal deadline exists (goal deadline is either in the past, or more than 30 days in the future).

**Inactivity window:** Configurable per-goal via `goal.inactivity_window_days` field (default 30). When not set, uses the system default.

**Distinction from `goal_inactive` (30):** `goal_inactive` fires when all tasks are done and there's simply nothing planned next (no future milestones/deadlines). `no_recent_activity` fires when the goal is active but there's been no evidence of work for a sustained period — a stronger signal that the goal may have been abandoned in practice even though it's still marked active.

**Relationship between the two:** When `no_recent_activity` fires, `goal_inactive` is suppressed (the stronger signal takes precedence). Both can be suppressed by any higher-severity signal (deadline signals, milestone signals).

#### 6.2.3 `goal_overdue` (existing, score 100)

Fires when:
- Goal deadline has passed (deadline < today), AND
- No open related tasks exist.

This is the strongest stall signal — the goal had a deadline and missed it with no active work.

### 6.3 Thresholds and Timing

| Parameter | Default | Configurable | Description |
|-----------|---------|--------------|-------------|
| `deadline_soon_window_days` | 7 | System-wide (constant) | Days-before-deadline that triggers `goal_deadline_soon` / `milestone_deadline_soon` |
| `inactivity_window_days` | 30 | Per-goal (`inactivity_window_days`), system default | Days without activity before `no_recent_activity` fires |
| `progress_slow_threshold` | 5% per 14 days | System-wide (constant) | Minimum progress delta over lookback window to avoid `progress_slow` |
| `progress_lookback_days` | 14 | System-wide (constant) | Window over which progress delta is measured for `progress_slow` |
| `measurement_due_grace_days` | 2 | System-wide (constant) | Grace period after measurement frequency interval before `measurement_due` fires |

### 6.4 Stalled → Notification/Flagging Behavior

When a goal enters the `stalled` health state, the following behaviors are defined:

#### 6.4.1 Attention Engine (primary channel)

The stalled goal appears as an `AttentionItem` with:
- `category` = the dominant signal category (e.g., `goal_stalled`, `goal_overdue`, `milestone_slipped`, `no_recent_activity`)
- `score` = the dominant signal's score
- `reason` = the dominant signal's reason

This is already implemented for existing signals. New signals (`no_recent_activity`) follow the same path.

#### 6.4.2 Weekly Review (secondary channel)

The weekly review extends `GoalReview` with:
- `health_state: str` — the computed health state
- `days_since_last_activity: int | None` — days since last metric update or task completion
- `progress_delta: float | None` — progress change over the lookback window

A goal in `stalled` state is flagged in the weekly review summary with its dominant signal reason. This is a reporting channel, not a proactive alert.

#### 6.4.3 CLI (inspection channel)

A new `goal health` CLI command displays the health assessment for one or all goals:

```
janus goal health              # all goals, sorted by health state severity
janus goal health <title>     # single goal detail
```

Output includes: health state, all signals with scores and reasons, progress, progress delta, days since last activity, measurement overdue count.

#### 6.4.4 Telegram / Delivery (deferred)

Proactive Telegram notification when a goal transitions into `stalled` state is NOT specified in this design. It is a future integration point that depends on:
- A persisted signal log (to detect transitions, not just current state)
- A notification policy (which stalled goals to notify about, frequency limits)

This is explicitly out of scope. The current design only covers inspection (CLI) and reporting (weekly review, attention engine).

---

## 7. Metric Snapshot History

### 7.1 Purpose

Metric snapshot history enables:
- `progress_slow` signal (comparing current progress to progress N days ago)
- `progress_delta` in weekly review
- `days_since_last_activity` computation
- Future trend analysis and charts

### 7.2 Storage

Append-only file: `data/metric_history.md`

Format (one entry per line, markdown comments for readability):

```markdown
# Metric History
# Format: ISO-timestamp | goal_title | metric_name | value | source
# 2026-09-06T10:00:00+02:00 | Body fat reduction | Body fat % | 20.0 | manual
# 2026-09-13T10:00:00+02:00 | Body fat reduction | Body fat % | 19.5 | manual
```

Each entry:
- `timestamp`: ISO datetime with timezone
- `goal_title`: goal title (persistence identity)
- `metric_name`: the metric being recorded
- `value`: float
- `source`: how the value was obtained (`manual` | `measurement` | `import`)

### 7.3 When Snapshots Are Recorded

| Trigger | Action |
|---------|--------|
| User sets `current_value` on a goal via `goal update --current` | Append snapshot with source=`manual` |
| Measurement collection delivers a value for a goal's metric | Append snapshot with source=`measurement` |
| External import of goal metric data | Append snapshot with source=`import` |

Snapshots are recorded by the service layer (`goals.py` `update_goal_fields` and the measurement collection runner), NOT by the persistence layer. The persistence layer only manages the file format.

### 7.4 Snapshot Query

A new function `get_metric_snapshots(goal_title, since, until)` returns all snapshots for a goal within a time range, sorted by timestamp. Used by:
- `assess_goal_health()` to compute `progress_slow` and `days_since_last_activity`
- Weekly review to compute `progress_delta`

---

## 8. Progress Signal: `progress_slow`

### 8.1 Definition

`progress_slow` fires when a goal has been active for at least `progress_lookback_days` (default 14) and the progress delta over that window is below `progress_slow_threshold` (default 5 percentage points).

### 8.2 Computation

```
progress_delta = current_progress - progress_at_lookback_start
```

Where:
- `current_progress` = `compute_goal_progress(goal)` using current metric values and task completion state
- `progress_at_lookback_start` = `compute_goal_progress(goal)` using metric values from the most recent snapshot on or before `(today - lookback_days)`, and task completion state...

**Task completion state for lookback:** Task completion timestamps are not currently recorded. For the initial implementation, the lookback progress for task-based goals uses the current completed task set (conservative: if tasks were completed within the lookback window, they count; if they were completed before, they also count — the signal may be weaker for task-based goals until task completion timestamps are recorded).

**Metric-based goals:** For metric-based goals, the lookback progress is computed from the metric snapshot at the start of the lookback window. This is accurate.

### 8.3 Fires When

- Goal status is `active`
- Goal has metric OR task-based progress configured
- `progress_delta` is computable (snapshots exist for metric goals; task-based is always computable but less precise)
- `progress_delta < progress_slow_threshold` (default 5%)
- AND `progress_delta` is not negative enough to indicate regression (a goal losing progress is a different problem — consider adding `progress_regressing` signal in the future, out of scope for now)
- AND no higher-severity signal fires (deadline signals, stall signals)

### 8.4 Does NOT Fire When

- Goal has no progress configuration (no metric, no related tasks)
- Lookback window has not elapsed since goal creation or last metric update
- Progress delta >= threshold
- Higher-severity signal is already firing (the goal is already stalled or at critical deadline)

---

## 9. Progress Signal: `measurement_due`

### 9.1 Definition

`measurement_due` fires when a goal has one or more `measurement_requirements` whose collection frequency indicates a measurement should have been collected but was not.

### 9.2 Computation

For each `measurement_requirement` on the goal:
1. Look up the most recent metric snapshot for that metric on that goal.
2. If no snapshot exists → measurement is due (no data collected at all).
3. If the most recent snapshot is older than `(frequency_interval + grace_days)` from today → measurement is due.
4. If the most recent snapshot is within the interval → not due.

Frequency is parsed from the requirement's `frequency` field:
- `daily` → interval_days = 1
- `twice_weekly` → interval_days = 3 (every 3 days approximates twice per week)
- `weekly` → interval_days = 7
- `biweekly` → interval_days = 14
- `monthly` → interval_days = 30

### 9.3 Score and Severity

Score: 45 (warning severity, between `milestone_deadline_soon` (55) and `progress_slow` (40)).

Fires when at least one measurement is due. The signal reason lists the overdue metrics.

### 9.4 Does NOT Fire When

- Goal has no `measurement_requirements`
- All measurements are within their frequency window
- Higher-severity signal is already firing

---

## 10. Affected Components

### 10.1 New Files

| File | Purpose |
|------|---------|
| `src/janus/services/goal_health.py` | `assess_goal_health()`, `GoalHealthAssessment`, `GoalSignal`, health state resolution logic, `get_metric_snapshots()` |
| `src/janus/integrations/metric_history.py` | Append-only metric snapshot persistence (read/write `data/metric_history.md`) |
| `src/janus/cli/goal_health_cli.py` | `goal health` CLI command (or extend `goals_cli.py`) |

### 10.2 Existing Files to Modify

| File | Change |
|------|--------|
| `src/janus/models/goal.py` | Add `inactivity_window_days: int | None` field (optional, per-goal override of system default) |
| `src/janus/services/attention.py` | Add `no_recent_activity` signal to `assess_goal_stall()`; extend `get_attention_items()` observability to include goal signals in log event |
| `src/janus/services/weekly_review.py` | Extend `GoalReview` with `health_state`, `days_since_last_activity`, `progress_delta`; compute and populate them |
| `src/janus/models/weekly_review.py` | Extend `GoalReview` dataclass with new fields |
| `src/janus/services/goals.py` | On `update_goal_fields` with `current_value`, trigger metric snapshot recording via `metric_history.append_snapshot()` |
| `src/janus/integrations/markdown_goals.py` | Parse/persist `InactivityWindowDays` field in markdown format; preserve unknown fields through rewrite (pre-existing gap — unknown fields are currently dropped) |
| `src/janus/models/__init__.py` | Export new types as needed |
| `data/metric_history.md` | New file, created on first snapshot (not pre-created) |

### 10.3 Test Files

| File | Change |
|------|--------|
| `tests/test_goal_health.py` | New — health state resolution, signal computation, progress_slow, measurement_due, no_recent_activity |
| `tests/test_metric_history.py` | New — snapshot append, query, parsing |
| `tests/test_attention_extended.py` | Extend — add `no_recent_activity` tests |
| `tests/test_weekly_review.py` | Extend — add health_state and progress_delta tests |
| `tests/test_goals_service.py` | Extend — add metric snapshot trigger tests |

---

## 11. Interfaces

### 11.1 `assess_goal_health(goal, context) -> GoalHealthAssessment`

Primary entry point for health assessment.

```python
def assess_goal_health(
    goal: Goal,
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    metric_snapshots: list[MetricSnapshot] | None = None,
    completed_task_dates: dict[str, date] | None = None,
) -> GoalHealthAssessment:
```

- `metric_snapshots`: pre-loaded snapshots for this goal. If None, loaded from `metric_history`.
- `completed_task_dates`: mapping of task title → completion date. If None, task-based progress delta is not computed (only current state is used).

Returns a `GoalHealthAssessment` with the computed health state, all signals, and supporting data.

### 11.2 `get_metric_snapshots(goal_title, since=None, until=None) -> list[MetricSnapshot]`

Queries the metric history file for snapshots matching the goal title and optional time range.

```python
@dataclass
class MetricSnapshot:
    timestamp: datetime
    goal_title: str
    metric_name: str
    value: float
    source: str  # manual | measurement | import
```

### 11.3 `append_metric_snapshot(snapshot: MetricSnapshot) -> None`

Appends a single snapshot to `data/metric_history.md`. Creates the file with header if it doesn't exist.

### 11.4 CLI: `goal health`

```
janus goal health [<title>]
```

- Without title: lists all active goals with health state, sorted by severity (stalled first, then watch, then healthy), showing dominant signal and score.
- With title: shows full `GoalHealthAssessment` for that goal.

---

## 12. Acceptance Criteria

### 12.1 Goal Health Model

- [ ] An active goal with no signals fires is assessed as `healthy`.
- [ ] An active goal with only `goal_deadline_soon` or `milestone_deadline_soon` AND open related tasks is assessed as `healthy` (not `watch`).
- [ ] An active goal with `goal_deadline_soon` or `milestone_deadline_soon` AND `progress_slow` is assessed as `watch`.
- [ ] An active goal with `measurement_due` is assessed as `watch`.
- [ ] An active goal with `progress_slow` (and no higher signal) is assessed as `watch`.
- [ ] An active goal with `goal_inactive` (and no higher signal) is assessed as `watch`.
- [ ] An active goal with `goal_stalled`, `milestone_slipped`, `goal_overdue`, or `no_recent_activity` is assessed as `stalled`.
- [ ] A completed goal is always assessed as `completed` (no signals evaluated).
- [ ] An inactive goal is excluded from health assessment (not healthy, watch, or stalled).

### 12.2 Progress Signals

- [ ] `progress_slow` fires when progress delta over the lookback window is below threshold for a metric-based goal with sufficient history.
- [ ] `progress_slow` does NOT fire when progress delta >= threshold.
- [ ] `progress_slow` does NOT fire when higher-severity signal is already present.
- [ ] `measurement_due` fires when at least one measurement requirement's frequency window has elapsed without a new snapshot.
- [ ] `measurement_due` does NOT fire when all measurements are within their frequency window.
- [ ] `measurement_due` does NOT fire when the goal has no measurement requirements.
- [ ] `no_recent_activity` fires when no metric snapshot and no task completion exists within the inactivity window, and no upcoming milestone/deadline exists.
- [ ] `no_recent_activity` does NOT fire when a metric snapshot exists within the window.
- [ ] `no_recent_activity` does NOT fire when a related task was completed within the window.
- [ ] `no_recent_activity` does NOT fire when an upcoming milestone or goal deadline exists.

### 12.3 Stalled-Goal Detection

- [ ] Existing `goal_stalled` behavior is preserved (all tasks done, no higher signal).
- [ ] `goal_overdue` continues to fire only when no open tasks exist.
- [ ] `no_recent_activity` is suppressed when `goal_inactive` would also fire (stronger signal wins).
- [ ] `no_recent_activity` is suppressed by any deadline/milestone signal.
- [ ] Goal deadline signals continue to suppress milestone deadline signals (existing precedence preserved).

### 12.4 Metric Snapshot History

- [ ] Setting `current_value` on a goal via the service layer appends a snapshot to `data/metric_history.md`.
- [ ] `get_metric_snapshots(goal_title, since, until)` returns correct snapshots filtered by time range.
- [ ] Metric history file is created on first snapshot (not pre-created).
- [ ] Snapshots are append-only (existing entries are never modified or deleted by the system).

### 12.5 Weekly Review Integration

- [ ] `GoalReview` includes `health_state` computed from the same logic as `assess_goal_health`.
- [ ] `GoalReview` includes `days_since_last_activity` (0 if a snapshot or task completion exists today).
- [ ] `GoalReview` includes `progress_delta` for metric-based goals with sufficient history.
- [ ] Weekly review output flags stalled goals with their dominant signal reason.

### 12.6 CLI

- [ ] `janus goal health` lists all active goals with health state, sorted by severity.
- [ ] `janus goal health <title>` shows full health assessment for a single goal.
- [ ] CLI output includes dominant signal, all signals, progress, progress delta, days since last activity.

### 12.7 Observability

- [ ] Attention engine log event `engine.attention.computed` includes goal signal breakdown (per-goal signal categories and scores) when goals are assessed.
- [ ] Metric snapshot writes are logged (optional, low priority — at minimum, no error is silent).

---

## 13. Design Decisions

### 13.1 Health state is derived, not stored

Health state is computed on demand from current signals. It is NOT persisted. Rationale: health is a view on current state, not an independent fact. Persisting it would create a consistency problem (stored health vs. current signals). The weekly review and CLI recompute it each time.

### 13.2 Signals are computed, not persisted (initial version)

Signals are computed on demand. Transition detection (e.g., "goal just became stalled") requires persisted signal history and is explicitly deferred. The current design supports inspection and reporting, not proactive alerting.

### 13.3 `no_recent_activity` uses a configurable inactivity window

Default 30 days. Per-goal override via `goal.inactivity_window_days`. Rationale: different goals have different natural cadences. A weekly check-in goal should not be flagged as inactive after 30 days; a daily tracking goal should.

### 13.4 Progress delta for task-based goals is imprecise initially

Without task completion timestamps, the lookback progress for task-based goals uses current completion state. This means `progress_slow` may not fire correctly for task-based goals until task completion timestamps are recorded (future improvement). Metric-based goals get accurate progress delta from snapshots.

### 13.5 Metric history is append-only markdown

Chosen for consistency with the rest of the Janus persistence layer (all files are markdown). An append-only line format keeps it simple and human-readable. If the volume of snapshots grows large, a switch to a structured format (JSON Lines, SQLite) can be made later without changing the interface.

### 13.6 Health state severity order is fixed

The severity order (§4.2) is a design constant, not configurable. If users need custom severity ordering, that's a future extension point. The current order reflects the judgment that missed deadlines and stalled goals are more severe than slow progress or overdue measurements.

---

## 14. Open Questions

1. **Task completion timestamps:** Should task completion dates be recorded now to enable accurate `progress_slow` for task-based goals and accurate `days_since_last_activity`? This is not required for the initial implementation (metric-based goals work fine), but it's a known limitation. Recommendation: record completion timestamps in a later task; the interface in §11.1 already accepts `completed_task_dates` so the function is ready when the data becomes available.

2. **Per-goal inactivity window default:** The system default is 30 days. Is this appropriate for all goal types, or should the default be higher (e.g., 45 or 60)? The per-goal override handles special cases; the system default should cover the common case.

3. **`progress_regressing` signal:** A goal whose metric value has moved away from the target (negative progress delta) is a distinct problem from slow progress. Is a separate `progress_regressing` signal needed, or should negative progress delta be folded into `progress_slow` with a higher score? Out of scope for this spec; noted for future consideration.

4. **Telegram proactive notification:** When a goal enters stalled state, should Hermes send a Telegram message? This requires persisted signal history for transition detection and a notification policy. Deferred beyond this spec.

---

## 15. Relationship to Other Design Documents

- **`DESIGN_EXECUTION_PLANNING.md`** — milestone model, next-action derivation, task-to-milestone membership. This spec builds on the milestone model and signal infrastructure introduced there.
- **`OBSERVABILITY_PLAN.md`** — structured log schema. The attention engine log event extension in §12.7 follows the existing schema pattern.
- **Goal-driven measurement collection design** — `measurement_requirements` field on Goal and collection scheduling. This spec consumes `measurement_requirements` for the `measurement_due` signal.
- **`docs/research/goal_milestone_research_findings.md`** — original research on the goal/milestone system. This spec addresses the gaps identified there (binary stall, no health model, no progress history).

---

*End of specification.*
