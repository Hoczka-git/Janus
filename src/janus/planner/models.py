"""Weekly Planner domain models.

These models are independent of any LLM provider.  They define the
input (:class:`PlanningContext`) and output (:class:`WeeklyPlan`) of
the weekly planning process, along with the deterministic signals
(:class:`PlanningSignals`) that are computed before the LLM is invoked.

The models follow the design doc ``docs/design/janus_weekly_planner_v1.md``
§4 (Domain model) and §5 (Deterministic signals).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from janus.models.event import Event
from janus.models.goal import Goal
from janus.models.task import Task


# ── Enums ────────────────────────────────────────────────────────────────────


class Priority(StrEnum):
    """Priority level for a goal or planned task.

    Members:
        HIGH   — top priority, should be addressed first.
        MEDIUM — important but not urgent.
        LOW    — can be deferred if necessary.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskSeverity(StrEnum):
    """Severity level for a planning risk.

    Members:
        LOW    — minor risk, unlikely to derail the plan.
        MEDIUM — moderate risk, may require attention.
        HIGH   — significant risk, likely to derail the plan.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ── Deterministic signals ────────────────────────────────────────────────────


@dataclass
class PlanningSignals:
    """Deterministic signals computed before the LLM is invoked.

    These signals are derived from the raw domain data (goals, tasks,
    calendar) by deterministic code.  The LLM receives these pre-computed
    signals instead of reconstructing them from raw data.

    Attributes:
        overdue_tasks: Titles of tasks whose due date has passed.
        due_soon_tasks: Titles of tasks due within the next 7 days.
        stalled_goals: Titles of goals with no recent activity.
        behind_target_goals: Titles of goals behind their target progress.
        calendar_conflicts: Human-readable descriptions of scheduling
            conflicts (e.g. overlapping events, double-booked slots).
        competing_tasks: Mapping of task title to the number of other
            tasks competing for the same time period.
    """

    overdue_tasks: list[str] = field(default_factory=list)
    due_soon_tasks: list[str] = field(default_factory=list)
    stalled_goals: list[str] = field(default_factory=list)
    behind_target_goals: list[str] = field(default_factory=list)
    calendar_conflicts: list[str] = field(default_factory=list)
    competing_tasks: dict[str, int] = field(default_factory=dict)


# ── Input model ──────────────────────────────────────────────────────────────


@dataclass
class PlanningContext:
    """Input to the weekly planner.

    Contains all the data the planner needs to generate a weekly plan:
    the user's goals, tasks, calendar events, and pre-computed
    deterministic signals.

    Attributes:
        goals: Active goals to plan around.
        tasks: Open (not completed) tasks.
        calendar: Calendar events for the planning period.
        signals: Pre-computed deterministic signals.
    """

    goals: list[Goal]
    tasks: list[Task]
    calendar: list[Event]
    signals: PlanningSignals = field(default_factory=PlanningSignals)


# ── Output models ────────────────────────────────────────────────────────────


@dataclass
class PriorityEntry:
    """A goal's priority ranking within the weekly plan.

    Attributes:
        goal_id: The goal's title (persistence identity).
        reason: Human-readable justification for the priority.
        priority: The priority level.
    """

    goal_id: str
    reason: str
    priority: Priority


@dataclass
class PlannedTask:
    """A task scheduled for a specific day in the weekly plan.

    Attributes:
        task_id: The task's title (persistence identity).
        goal_id: The goal this task supports.
        priority: The priority level for this task.
        reason: Human-readable justification for scheduling.
        suggested_day: The date this task is suggested for.
    """

    task_id: str
    goal_id: str
    priority: Priority
    reason: str
    suggested_day: date


@dataclass
class PlanningRisk:
    """A risk or conflict identified in the weekly plan.

    Attributes:
        description: Human-readable description of the risk.
        severity: How severe the risk is.
    """

    description: str
    severity: RiskSeverity


@dataclass
class WeeklyPlan:
    """The output of the weekly planner.

    Contains the complete weekly plan: a summary, goal priorities,
    scheduled tasks, and identified risks.

    Attributes:
        week_summary: A brief summary of the week's plan.
        priorities: Goal priorities, ordered by importance.
        planned_tasks: Tasks scheduled for specific days.
        risks: Risks and conflicts identified in the plan.
    """

    week_summary: str
    priorities: list[PriorityEntry] = field(default_factory=list)
    planned_tasks: list[PlannedTask] = field(default_factory=list)
    risks: list[PlanningRisk] = field(default_factory=list)
