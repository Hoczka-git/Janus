"""CLI command handlers for 'janus plan week'.

Generates a weekly plan based on current goals, tasks, and calendar.
The plan is a proposal only — no side effects.

Design reference: ``docs/design/janus_weekly_planner_v1.md`` §9 (CLI).
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta

from janus.planner.models import (
    PlannedTask,
    PlanningContext,
    PlanningRisk,
    PlanningSignals,
    Priority,
    PriorityEntry,
    RiskSeverity,
    WeeklyPlan,
)
from janus.planner.protocol import WeeklyPlanner

logger = logging.getLogger(__name__)


def print_plan_help() -> None:
    """Print help for the 'janus plan' command."""
    print("Usage: janus plan <subcommand> [options]")
    print("")
    print("Generate weekly plans.")
    print("")
    print("Subcommands:")
    print("  week       Generate a weekly plan")
    print("")
    print("Options:")
    print("  -h, --help  Show this help message")


# ── Context builder ──────────────────────────────────────────────────────────


def _build_context() -> PlanningContext:
    """Build a planning context from current data.

    Loads active goals, open tasks, and calendar events for the current
    week. Computes deterministic signals (overdue, due soon, stalled).

    Never raises — missing data is treated as empty collections.
    """
    from janus.integrations.markdown_goals import load_goals
    from janus.integrations.markdown_tasks import load_tasks

    # Load goals (active only)
    try:
        all_goals = load_goals()
    except Exception:
        all_goals = []
    goals = [g for g in all_goals if g.status == "active"]

    # Load tasks (open only — the loader already filters)
    try:
        tasks = load_tasks()
    except Exception:
        tasks = []

    # Load calendar events for the current week
    try:
        from janus.integrations.google_calendar import list_upcoming_events
        calendar = list_upcoming_events()
    except Exception:
        calendar = []

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    # Filter calendar events to the current week
    week_events = []
    for event in calendar:
        if event.start is None:
            continue
        event_date = event.start.date() if hasattr(event.start, "date") else event.start
        if week_start <= event_date <= week_end:
            week_events.append(event)

    # Compute signals
    overdue_tasks: list[str] = []
    due_soon_tasks: list[str] = []
    for task in tasks:
        if task.due_date and task.due_date < today:
            overdue_tasks.append(task.title)
        elif task.due_date and 0 <= (task.due_date - today).days <= 7:
            due_soon_tasks.append(task.title)

    # Simple stalled goal detection: goals with no recent activity
    stalled_goals: list[str] = []
    for goal in goals:
        if not goal.recent_activity:
            stalled_goals.append(goal.title)

    # Calendar conflicts: tasks whose due date falls on a day with events
    calendar_conflicts: list[str] = []
    busy_days = {e.start.date() for e in week_events if e.start}
    for task in tasks:
        if task.due_date and task.due_date in busy_days:
            calendar_conflicts.append(
                f"Task '{task.title}' due on {task.due_date} conflicts with calendar event"
            )

    # Competing tasks: tasks sharing the same due date
    due_date_counts: dict[date, int] = {}
    for task in tasks:
        if task.due_date:
            due_date_counts[task.due_date] = due_date_counts.get(task.due_date, 0) + 1
    competing_tasks = {
        task.title: count
        for task in tasks
        if task.due_date and due_date_counts.get(task.due_date, 0) > 1
        for count in [due_date_counts[task.due_date]]
    }

    signals = PlanningSignals(
        overdue_tasks=overdue_tasks,
        due_soon_tasks=due_soon_tasks,
        stalled_goals=stalled_goals,
        calendar_conflicts=calendar_conflicts,
        competing_tasks=competing_tasks,
    )

    return PlanningContext(
        goals=goals,
        tasks=tasks,
        calendar=week_events,
        signals=signals,
    )


# ── Rule-based planner ───────────────────────────────────────────────────────


class RuleBasedPlanner:
    """A simple rule-based planner for when no LLM is available.

    This planner uses deterministic rules to generate a weekly plan:
    - Goals with overdue tasks or stalled status get HIGH priority
    - Tasks are scheduled based on due dates
    - Risks are identified from signals
    """

    def plan(self, context: PlanningContext) -> WeeklyPlan:
        """Generate a weekly plan using simple rules."""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        # Prioritize goals
        priorities = self._prioritize_goals(context, today)

        # Schedule tasks
        planned_tasks = self._schedule_tasks(context, today)

        # Identify risks
        risks = self._identify_risks(context)

        # Build summary
        summary = self._build_summary(context, week_start, week_end)

        return WeeklyPlan(
            week_summary=summary,
            priorities=priorities,
            planned_tasks=planned_tasks,
            risks=risks,
        )

    def _prioritize_goals(
        self, context: PlanningContext, today: date
    ) -> list[PriorityEntry]:
        """Assign priorities to goals based on signals."""
        priorities: list[PriorityEntry] = []

        for goal in context.goals:
            priority = Priority.MEDIUM
            reason = "Active goal"

            # Check for overdue tasks related to this goal
            goal_task_titles = set(goal.related_tasks or [])
            has_overdue = any(
                t.title in goal_task_titles and t.due_date and t.due_date < today
                for t in context.tasks
            )
            if has_overdue:
                priority = Priority.HIGH
                reason = "Has overdue tasks"

            # Stalled goals get high priority
            if goal.title in context.signals.stalled_goals:
                priority = Priority.HIGH
                reason = "Stalled goal — needs attention"

            # Goals with deadlines soon get high priority
            if goal.deadline:
                try:
                    deadline = date.fromisoformat(goal.deadline)
                    days_until = (deadline - today).days
                    if days_until < 0:
                        priority = Priority.HIGH
                        reason = "Deadline has passed"
                    elif days_until <= 7:
                        priority = Priority.HIGH
                        reason = f"Deadline in {days_until} days"
                except (ValueError, TypeError):
                    pass

            priorities.append(PriorityEntry(
                goal_id=goal.title,
                reason=reason,
                priority=priority,
            ))

        # Sort by priority (high first)
        priority_order = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
        priorities.sort(key=lambda p: priority_order.get(p.priority, 3))

        return priorities

    def _schedule_tasks(
        self, context: PlanningContext, today: date
    ) -> list[PlannedTask]:
        """Schedule tasks based on due dates and priority."""
        planned: list[PlannedTask] = []

        for task in context.tasks:
            # Determine suggested day
            if task.due_date:
                suggested_day = max(task.due_date, today)
            else:
                suggested_day = today

            # Find the goal this task supports
            goal_id = ""
            for goal in context.goals:
                if task.title in (goal.related_tasks or []):
                    goal_id = goal.title
                    break

            # Determine priority
            if task.due_date and task.due_date < today:
                task_priority = Priority.HIGH
            elif task.due_date and 0 <= (task.due_date - today).days <= 3:
                task_priority = Priority.HIGH
            else:
                task_priority = Priority.MEDIUM

            planned.append(PlannedTask(
                task_id=task.title,
                goal_id=goal_id,
                priority=task_priority,
                reason="Scheduled based on due date and priority",
                suggested_day=suggested_day,
            ))

        # Sort by suggested day, then by priority
        planned.sort(key=lambda t: (t.suggested_day, t.priority.value))

        return planned

    def _identify_risks(self, context: PlanningContext) -> list[PlanningRisk]:
        """Identify risks from signals."""
        risks: list[PlanningRisk] = []

        if context.signals.overdue_tasks:
            risks.append(PlanningRisk(
                description=f"Overdue tasks: {', '.join(context.signals.overdue_tasks)}",
                severity=RiskSeverity.HIGH,
            ))

        if context.signals.stalled_goals:
            risks.append(PlanningRisk(
                description=f"Stalled goals: {', '.join(context.signals.stalled_goals)}",
                severity=RiskSeverity.MEDIUM,
            ))

        if context.signals.calendar_conflicts:
            for conflict in context.signals.calendar_conflicts:
                risks.append(PlanningRisk(
                    description=conflict,
                    severity=RiskSeverity.MEDIUM,
                ))

        if context.signals.competing_tasks:
            competing = ", ".join(
                f"{title} ({count} tasks)"
                for title, count in context.signals.competing_tasks.items()
            )
            risks.append(PlanningRisk(
                description=f"Competing tasks: {competing}",
                severity=RiskSeverity.LOW,
            ))

        return risks

    def _build_summary(
        self, context: PlanningContext, week_start: date, week_end: date
    ) -> str:
        """Build a week summary string."""
        parts = []

        if context.signals.overdue_tasks:
            parts.append(f"{len(context.signals.overdue_tasks)} overdue task(s)")

        if context.signals.due_soon_tasks:
            parts.append(f"{len(context.signals.due_soon_tasks)} task(s) due soon")

        if context.signals.stalled_goals:
            parts.append(f"{len(context.signals.stalled_goals)} stalled goal(s)")

        date_range = f"{week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}"
        if parts:
            return f"Week of {date_range} — {', '.join(parts)}"
        return f"Week of {date_range}"


# ── Output formatting ────────────────────────────────────────────────────────


def _format_plan(plan: WeeklyPlan) -> str:
    """Format a WeeklyPlan for display.

    Output format per design doc §9:
        JANUS WEEKLY PLAN
        5–11 Oct 2026

        TOP PRIORITIES

        1. Career
           Prepare AI/Agent Engineering development plan

        RISKS

        ⚠ Career goal has no completed actions...

        PLANNED TASKS

        Monday
          ...
    """
    lines: list[str] = []
    lines.append("JANUS WEEKLY PLAN")
    lines.append("")

    if plan.week_summary:
        lines.append(plan.week_summary)
        lines.append("")

    if plan.priorities:
        lines.append("TOP PRIORITIES")
        lines.append("")
        for i, p in enumerate(plan.priorities, 1):
            lines.append(f"{i}. {p.goal_id}")
            lines.append(f"   {p.reason}")
            lines.append("")

    if plan.risks:
        lines.append("RISKS")
        lines.append("")
        for risk in plan.risks:
            if risk.severity == RiskSeverity.HIGH:
                icon = "⚠"
            elif risk.severity == RiskSeverity.MEDIUM:
                icon = "•"
            else:
                icon = "•"
            lines.append(f"{icon} {risk.description}")
        lines.append("")

    if plan.planned_tasks:
        lines.append("PLANNED TASKS")
        lines.append("")
        # Group by day
        by_day: dict[date, list[PlannedTask]] = {}
        for task in plan.planned_tasks:
            day = task.suggested_day
            if day not in by_day:
                by_day[day] = []
            by_day[day].append(task)

        for day in sorted(by_day.keys()):
            day_name = day.strftime("%A")
            lines.append(day_name)
            for task in by_day[day]:
                priority_marker = "!" if task.priority == Priority.HIGH else " "
                lines.append(f"  {priority_marker} {task.task_id}")
            lines.append("")

    return "\n".join(lines)


# ── CLI handler ──────────────────────────────────────────────────────────────


def handle_plan_week(args: list[str]) -> None:
    """Parse 'janus plan week' arguments and generate a weekly plan.

    Usage:
        janus plan week

    Options:
        -h, --help  Show this help message
    """
    if args and args[0] in ("-h", "--help"):
        print("Usage: janus plan week")
        print("")
        print("Generate a weekly plan based on current goals, tasks, and calendar.")
        print("")
        print("Options:")
        print("  -h, --help  Show this help message")
        return

    if args:
        print("Error: 'plan week' does not accept arguments", file=sys.stderr)
        sys.exit(1)

    context = _build_context()
    planner: WeeklyPlanner = RuleBasedPlanner()
    plan = planner.plan(context)

    print(_format_plan(plan))
