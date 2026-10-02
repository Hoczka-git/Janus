"""Rule-based proposal engine — deterministic transformation of WeeklyPlan to ActionProposal.

This module implements the V1 Action Proposal Engine using explicit,
deterministic rules. It is a pure function: no side effects, no I/O,
no state mutation.

Design reference: docs/design/action_proposal_engine_v1.md
"""

from __future__ import annotations

from datetime import date

from janus.models.policy import RiskLevel
from janus.models.task import Task
from janus.planner.models import (
    PlanningContext,
    Priority,
    RiskSeverity,
    WeeklyPlan,
)
from janus.proposal.models import ActionProposal, ActionType, ProposalStatus


# Mapping from Priority enum to Task.priority int value
_PRIORITY_TO_INT: dict[Priority, int] = {
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
}


class RuleBasedProposalEngine:
    """Deterministic, rule-based implementation of ActionProposalEngine.

    Transforms a WeeklyPlan into a list of ActionProposal objects using
    explicit rules. The engine is pure: it has no side effects and does
    not modify any external state.

    Rules:
        1. Overdue task in plan -> RESCHEDULE_TASK
        2. Goal without tasks -> CREATE_TASK
        3. Priority mismatch -> CHANGE_PRIORITY
        4. Planned task with suggested_day -> CREATE_CALENDAR_EVENT
        5. High-severity risk -> UPDATE_TASK
    """

    def generate(
        self,
        plan: WeeklyPlan,
        context: PlanningContext,
    ) -> list[ActionProposal]:
        """Generate action proposals from a weekly plan.

        Args:
            plan: The weekly plan to transform into proposals.
            context: The planning context with goals, tasks, calendar.

        Returns:
            A list of validated action proposals. May be empty if no
            actions are proposed.
        """
        proposals: list[ActionProposal] = []
        seen: set[tuple[ActionType, str | None]] = set()

        proposals.extend(self._rule_overdue_tasks(plan, context, seen))
        proposals.extend(self._rule_missing_tasks(plan, context, seen))
        proposals.extend(self._rule_priority_mismatch(plan, context, seen))
        proposals.extend(self._rule_calendar_entries(plan, context, seen))
        proposals.extend(self._rule_risks(plan, context, seen))

        return proposals

    # -- Rule 1: Overdue tasks -> RESCHEDULE_TASK --

    def _rule_overdue_tasks(
        self,
        plan: WeeklyPlan,
        context: PlanningContext,
        seen: set[tuple[ActionType, str | None]],
    ) -> list[ActionProposal]:
        """Rule 1: Overdue tasks in the plan -> RESCHEDULE_TASK."""
        proposals = []
        today = date.today()
        for planned in plan.planned_tasks:
            task = self._find_task(context, planned.task_id)
            if task and task.due_date and task.due_date < today:
                key = (ActionType.RESCHEDULE_TASK, planned.task_id)
                if key not in seen:
                    seen.add(key)
                    proposals.append(ActionProposal(
                        action_type=ActionType.RESCHEDULE_TASK,
                        target_id=planned.task_id,
                        parameters={
                            "new_due_date": planned.suggested_day.isoformat(),
                            "old_due_date": task.due_date.isoformat(),
                        },
                        reason=(
                            f"Task '{planned.task_id}' is overdue "
                            f"(was due {task.due_date.isoformat()}) and is "
                            f"scheduled for {planned.suggested_day.isoformat()}"
                        ),
                        source="rule:overdue",
                        risk=RiskLevel.MEDIUM,
                        status=ProposalStatus.PROPOSED,
                        metadata={"goal_id": planned.goal_id},
                    ))
        return proposals

    # -- Rule 2: Goals without tasks -> CREATE_TASK --

    def _rule_missing_tasks(
        self,
        plan: WeeklyPlan,
        context: PlanningContext,
        seen: set[tuple[ActionType, str | None]],
    ) -> list[ActionProposal]:
        """Rule 2: Goals without tasks -> CREATE_TASK."""
        proposals = []
        planned_goal_ids = {pt.goal_id for pt in plan.planned_tasks}

        for goal in context.goals:
            if not goal.related_tasks and goal.title not in planned_goal_ids:
                key = (ActionType.CREATE_TASK, goal.title)
                if key not in seen:
                    seen.add(key)
                    proposals.append(ActionProposal(
                        action_type=ActionType.CREATE_TASK,
                        target_id=goal.title,
                        parameters={
                            "title": f"Work on: {goal.title}",
                            "goal_id": goal.title,
                        },
                        reason=f"Goal '{goal.title}' has no tasks and needs a concrete action",
                        source="rule:missing_task",
                        risk=RiskLevel.LOW,
                        status=ProposalStatus.PROPOSED,
                    ))
        return proposals

    # -- Rule 3: Priority mismatches -> CHANGE_PRIORITY --

    def _rule_priority_mismatch(
        self,
        plan: WeeklyPlan,
        context: PlanningContext,
        seen: set[tuple[ActionType, str | None]],
    ) -> list[ActionProposal]:
        """Rule 3: Priority mismatches -> CHANGE_PRIORITY."""
        proposals = []
        for planned in plan.planned_tasks:
            task = self._find_task(context, planned.task_id)
            if task:
                planned_priority_int = _PRIORITY_TO_INT.get(planned.priority, 2)
                if task.priority != planned_priority_int:
                    key = (ActionType.CHANGE_PRIORITY, planned.task_id)
                    if key not in seen:
                        seen.add(key)
                        proposals.append(ActionProposal(
                            action_type=ActionType.CHANGE_PRIORITY,
                            target_id=planned.task_id,
                            parameters={
                                "new_priority": planned_priority_int,
                                "old_priority": task.priority,
                            },
                            reason=(
                                f"Task '{planned.task_id}' priority should be "
                                f"{planned.priority.value} (currently {task.priority})"
                            ),
                            source="rule:priority_mismatch",
                            risk=RiskLevel.LOW,
                            status=ProposalStatus.PROPOSED,
                            metadata={"goal_id": planned.goal_id},
                        ))
        return proposals

    # -- Rule 4: Planned tasks with suggested_day -> CREATE_CALENDAR_EVENT --

    def _rule_calendar_entries(
        self,
        plan: WeeklyPlan,
        context: PlanningContext,
        seen: set[tuple[ActionType, str | None]],
    ) -> list[ActionProposal]:
        """Rule 4: Planned tasks with suggested_day -> CREATE_CALENDAR_EVENT."""
        proposals = []
        for planned in plan.planned_tasks:
            if not self._has_calendar_event(context, planned.task_id, planned.suggested_day):
                key = (ActionType.CREATE_CALENDAR_EVENT, planned.task_id)
                if key not in seen:
                    seen.add(key)
                    proposals.append(ActionProposal(
                        action_type=ActionType.CREATE_CALENDAR_EVENT,
                        target_id=planned.task_id,
                        parameters={
                            "title": planned.task_id,
                            "date": planned.suggested_day.isoformat(),
                            "goal_id": planned.goal_id,
                        },
                        reason=(
                            f"Task '{planned.task_id}' is scheduled for "
                            f"{planned.suggested_day.isoformat()} and needs a calendar entry"
                        ),
                        source="rule:calendar_entry",
                        risk=RiskLevel.LOW,
                        status=ProposalStatus.PROPOSED,
                    ))
        return proposals

    # -- Rule 5: High-severity risks -> UPDATE_TASK --

    def _rule_risks(
        self,
        plan: WeeklyPlan,
        context: PlanningContext,
        seen: set[tuple[ActionType, str | None]],
    ) -> list[ActionProposal]:
        """Rule 5: High-severity risks -> UPDATE_TASK."""
        proposals = []
        for risk in plan.risks:
            if risk.severity == RiskSeverity.HIGH:
                target = self._extract_target_from_risk(risk.description, context)
                key = (ActionType.UPDATE_TASK, target)
                if key not in seen:
                    seen.add(key)
                    proposals.append(ActionProposal(
                        action_type=ActionType.UPDATE_TASK,
                        target_id=target,
                        parameters={"risk_description": risk.description},
                        reason=f"High-severity risk identified: {risk.description}",
                        source="rule:risk",
                        risk=RiskLevel.HIGH,
                        status=ProposalStatus.PROPOSED,
                    ))
        return proposals

    # -- Helpers --

    def _find_task(self, context: PlanningContext, task_id: str) -> Task | None:
        """Find a task by title in the context."""
        for task in context.tasks:
            if task.title == task_id:
                return task
        return None

    def _has_calendar_event(
        self,
        context: PlanningContext,
        task_id: str,
        day: date,
    ) -> bool:
        """Check if a calendar event already exists for the task on the given day."""
        for event in context.calendar:
            if event.title == task_id and event.start and event.start.date() == day:
                return True
        return False

    def _extract_target_from_risk(self, description: str, context: PlanningContext) -> str | None:
        """Try to extract a task ID from a risk description."""
        for task in context.tasks:
            if task.title in description:
                return task.title
        return None
