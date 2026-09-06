# Goal Management & Health/Progress Patterns — Research Summary

## Question Investigated

What is the current state of the goal management subsystem in Janus — data models, existing signals, health/progress/stalled concepts, and CRUD/query paths — and what abstractions can be reused vs. gaps that a new feature must fill?

## Scope & Constraints

- Read-only research; no implementation changes.
- Focus on: goal model, progress/health signals, stall detection, milestones, next-action derivation, persistence, CLI, observability.
- Source: `src/janus/`, `tests/`, `reports/`, `docs/` in branch `wt/t_11af88e5`.

---

## 1. Architecture Overview

```
CLI (goals_cli.py)
  └─ Service (services/goals.py) — CRUD
       └─ Progress (services/goal_progress.py) — metric/task progress
            └─ Model (models/goal.py) — Goal dataclass
                 └─ Persistence (integrations/markdown_goals.py) — data/goals.md

Attention Engine (services/attention.py) — goal stagnation detection
  └─ Daily Briefing (services/daily_briefing.py) — suggested_focus
       └─ Today CLI / Telegram

Weekly Review (services/weekly_review.py) — goal progress + next step
  └─ Weekly CLI / Telegram

Next Action Engine (services/next_action.py) — rules-based execution planning
```

---

## 2. Goal Model — `src/janus/models/goal.py:4-67`

```python
@dataclass
class Goal:
    title: str                              # persistence identity, immutable in MVP
    description: str = ""
    status: str = "active"                  # active | completed | inactive
    deadline: str | None = None             # ISO date YYYY-MM-DD
    metric_name: str | None = None
    metric_unit: str | None = None
    start_value: float | None = None
    current_value: float | None = None
    target_value: float | None = None
    direction: str | None = None            # "increase" | "decrease"
    related_tasks: list[str] = None         # supporting task titles (deduped, ordered)
    milestones: list[dict] | None = None     # list of milestone dicts
    measurement_requirements: list[dict] | None = None
```

Validation: `status` ∈ {active, completed, inactive}; `direction` ∈ {increase, decrease}; title non-empty; related_tasks deduped.

---

## 3. Goal CRUD Service — `src/janus/services/goals.py:20-195`

| Operation | Function | Notes |
|-----------|----------|-------|
| Create | `add_goal(...)` | Validates via Goal; rejects duplicate title |
| Read | `get_goal(title)` | Exact title match |
| Update | `update_goal_fields(title, **kwargs)` | Title immutable; add/remove related task, measurement reqs |
| Complete | `complete_goal(title)` | Sets status=completed |
| Delete | — | Not implemented; inactive instead |

Observability: emits `service.goal.mutated` on add/update via `janus._log.emit`.

---

## 4. Goal Progress Calculation — `src/janus/services/goal_progress.py:10-115`

Centralized single source of truth. Priority:

1. **Metric path** — if `metric_name`, `target_value`, `direction`, `start_value`, `current_value` all present → `_compute_metric_progress()`
2. **Task-based path** — elif `related_tasks` non-empty AND `completed_task_titles` provided → `_compute_task_based_progress()`
3. **Otherwise** → `None`

Returns `None` for completed/inactive goals, missing metric fields, no tasks + no titles, or invalid metric config.

Metric progress handles: increase/decrease, degenerate maintain-at-X (start==target), negative values, percentages.

Task-based: `(completed_count / total) * 100.0`; validates count bounds.

---

## 5. Persistence Layer — `src/janus/integrations/markdown_goals.py:25-426`

Data file: `data/goals.md`. Format supports:
- Standard fields (Description, Status, Deadline, Metric, Unit, Start, Current, Target, Direction)
- Related tasks (list under `Related tasks:`)
- Milestones section (`## Milestones` with `### Milestone: <title> (order: N)` blocks)
- Measurement requirements section (`Measurement requirements:` with `- metric:` blocks)

Unknown fields ignored on parse, NOT preserved through `update_goal` rewrite.

---

## 6. Milestones — `src/janus/models/milestone.py:4-31`, `src/janus/services/milestone.py:44-158`

```python
@dataclass
class Milestone:
    title: str
    goal_title: str
    description: str = ""
    deadline: str | None = None
    status: str = "open"                    # open | in_progress | completed | skipped
    order: int = 0
```

CRUD operations in `milestone.py`: add (auto-assigns order = max+1), get, update, complete.

Task-to-milestone membership is NOT stored — derived dynamically by `derive_milestone_tasks()` in `services/next_action.py`.

---

## 7. Next Action Engine — `src/janus/services/next_action.py:156-248`

Rules-based engine with priority order:

- **R1** — Open task in current/next milestone (earliest non-terminal)
- **R2** — Open task outside any milestone
- **R3** — Next open/in_progress milestone (no open tasks)
- **R4** — First uncompleted milestone in sequence (all done/skipped)
- **R5** — No next action

Returns `NextAction(title, kind, reason, goal_title, score=0)`.

---

## 8. Attention Engine — Existing Health/Progress Signals

**File:** `src/janus/services/attention.py:66-359`

This is the primary existing "health/progress" signal infrastructure. Uses `StallSignal` dataclass with score + category.

### Signal hierarchy (current implementation):

| Signal | Score | Condition |
|--------|-------|-----------|
| `goal_overdue` | 100 | Goal deadline passed, no open tasks |
| `goal_deadline_today` | 90 | Goal deadline is today |
| `goal_deadline_soon` | 60 | Goal deadline within 7 days |
| `milestone_deadline_soon` | 55 | Milestone deadline within 7 days |
| `milestone_slipped` | 50 | Milestone deadline passed, status ≠ completed/skipped |
| `goal_stalled` | 40 | All related tasks completed, no higher signal fires |
| `goal_inactive` | 30 | All tasks done, no future milestones/deadlines |

### Precedence rules:
- Goal deadline signals suppress milestone deadline signals (when goal_deadline_signal_fired, milestone signals skipped)
- Highest-scoring signal wins per goal (deterministic)

### Task-based signals:
- Overdue task: 100
- Due today: 80
- High priority (≥3): 50
- Blocked task: 30
- In-progress task: 30

---

## 9. Weekly Review — `src/janus/services/weekly_review.py:42-131`

```python
@dataclass
class GoalReview:
    goal: Goal
    progress: float | None
    progress_detail: str | None
    completed_related_tasks: list[str]
    missing_related_tasks: list[str]
    suggested_next_step: str | None
    all_related_tasks_completed: bool
```

Classifies related tasks as completed/open/missing. Delegates progress to `compute_goal_progress()`. Uses `derive_next_action()` for suggested next step.

---

## 10. Task Model — `src/janus/models/task.py:7-26`

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

---

## 11. Observability — `src/janus/_log.py:43-87`

Structured event logging via `emit(logger, event, **kwargs)`. Produces JSON envelope with:
- `event` (canonical dot-separated identifier)
- `message` (human-readable)
- `data` (event-specific payload)
- Optional: `trace_id`, `span_id`, `correlation_id`, `duration_ms`, `error`

Events used by goal subsystem:
- `service.goal.mutated` — on add/update
- `source.goals.loaded` — on load
- `engine.attention.computed` — on attention computation
- `briefing.generation.started/finished` — weekly review

---

## 12. Existing Abstractions That Can Be Reused

| Abstraction | Location | Reuse potential |
|-------------|----------|-----------------|
| `Goal` model | `models/goal.py` | Direct extension (new fields) |
| `Milestone` model | `models/milestone.py` | Already implemented |
| `compute_goal_progress()` | `services/goal_progress.py` | Centralized logic — extend with new paths |
| `derive_next_action()` | `services/next_action.py` | Rules engine — extend with new rules |
| `StallSignal` + `assess_goal_stall()` | `services/attention.py` | Direct extension for new signals |
| `AttentionItem` | `models/attention.py` | Already generic (title, reason, score, category) |
| `GoalReview` | `models/weekly_review.py` | Extend with new fields |
| `_log.emit()` | `_log.py` | Add new events for new signals |
| Markdown persistence | `integrations/markdown_goals.py` | Add new sections/fields |
| CLI handler pattern | `goals_cli.py` | Add new subcommands |

---

## 13. Gaps the New Feature Must Fill

### 13.1 No Historical Progress Tracking
Progress computed from current state only. No trend, no velocity, no "days since last measurement."

**Gap:** Cannot detect "progressing slowly" or "regressing."

### 13.2 No Metric History / Snapshots
No `measurement_log.md` or similar. Cannot show trend lines or detect plateau.

**Gap:** Metric-based goals have no memory.

### 13.3 No Inactivity-Based Stall Signal
Current stall is binary (all tasks done → stalled). No "days since last task completed" heuristic.

**Gap:** Cannot surface "no recent activity" before all tasks complete.

### 13.4 No Goal-Level Deadline vs. Milestone Precedence in Scoring
Goal deadlines suppress milestone deadlines (good), but there's no combined signal for "goal deadline approaching + milestone also approaching."

### 13.5 No "Goal Health" Composite
No single health score that combines progress, deadline proximity, and activity recency.

### 13.6 No Goal Progress History for Trend Analysis
Weekly review reports current progress only. Cannot answer "is this goal improving?"

### 13.7 Measurement Requirements Are Passive
`measurement_requirements` are stored but not actively checked by any service. No "measurement due" signal in attention engine (noted in `docs/design/measurement_collection_design.md`).

### 13.8 No Goal → Research/Decision Link
Research artifacts and decisions are not linked to goals (noted in roadmap item "Close the research → finding → decision → action loop").

---

## 14. Roadmap Context

From `docs/roadmap.md:101-102`:
```
- [ ] Extend goal management with goal health, progress signals, and stalled-goal detection
```

This task directly addresses that roadmap item.

---

## 15. Recommendations

| Priority | Recommendation | Rationale |
|----------|----------------|-----------|
| 1 | **Extend `assess_goal_stall()`** with new signals: `measurement_due` (35), `no_recent_activity` (35), `progress_slow` (45) | Reuses existing `StallSignal` infrastructure; minimal change |
| 2 | **Add metric snapshot logging** — append-only `data/metric_history.md` when `current_value` updated | Enables trend analysis; low complexity |
| 3 | **Extend `GoalReview`** with `progress_delta`, `days_since_last_activity` | Weekly review needs richer health data |
| 4 | **Active measurement requirement checking** — add to attention engine | Closes gap between stored requirements and actual prompting |
| 5 | **Add `goal health` CLI command** — composite health dashboard | User-facing value; reuses all computed signals |

---

## 16. Key File References

| File | Role |
|------|------|
| `src/janus/models/goal.py` | Goal dataclass |
| `src/janus/models/milestone.py` | Milestone dataclass |
| `src/janus/models/attention.py` | AttentionItem model |
| `src/janus/models/weekly_review.py` | GoalReview / WeeklyReview |
| `src/janus/models/task.py` | Task dataclass |
| `src/janus/services/goals.py` | Goal CRUD |
| `src/janus/services/goal_progress.py` | Centralized progress |
| `src/janus/services/milestones.py` | Milestone CRUD |
| `src/janus/services/next_action.py` | Next-action rules engine |
| `src/janus/services/attention.py` | Stall detection + scoring |
| `src/janus/services/weekly_review.py` | Weekly review |
| `src/janus/integrations/markdown_goals.py` | Goal persistence |
| `src/janus/goals_cli.py` | CLI handlers |
| `src/janus/_log.py` | Observability logging |

---

## 17. Remaining Uncertainty

- No performance benchmarks on large goal/task sets (current data is tiny)
- No user research on how milestones are actually used in practice
- No existing user feedback on the quality of current stall detection
- No historical data to validate "slow progress" or "inactivity" thresholds
