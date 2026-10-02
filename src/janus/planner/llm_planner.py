"""LLM-based weekly planner implementation.

This module implements the :class:`WeeklyPlanner` interface using an LLM
to generate weekly plans.  It handles prompt building, response parsing,
validation, retry logic, and fallback handling.

Design reference: ``docs/design/janus_weekly_planner_v1.md`` §4, §5, §8
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Protocol

from janus._log import emit
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


# ── LLM client protocol ─────────────────────────────────────────────────────


class LLMClient(Protocol):
    """Protocol for LLM clients that can generate text.

    Implementations must provide a single ``generate`` method that takes
    a prompt string and returns the LLM's response as a string.

    This protocol is intentionally provider-agnostic — any LLM backend
    (OpenAI, Anthropic, local model, etc.) can be used as long as it
    satisfies this interface.
    """

    def generate(self, prompt: str) -> str:
        """Generate a response for the given prompt.

        Args:
            prompt: The prompt to send to the LLM.

        Returns:
            The LLM's response as a string.

        Raises:
            Exception: If the LLM call fails (provider error, timeout, etc.).
        """
        ...


# ── LLM weekly planner ──────────────────────────────────────────────────────


class LLMWeeklyPlanner:
    """LLM-based weekly planner.

    This planner uses an LLM to generate weekly plans from a
    :class:`PlanningContext`.  It builds a prompt from the context, calls
    the LLM, parses the response, validates the output, and handles errors
    with retry and fallback.

    The planner does **not** perform any side effects — it only generates
    a plan proposal.

    Attributes:
        _client: The LLM client to use for generating plans.
        _max_retries: Maximum number of retry attempts for transient failures.
        _fallback: Optional fallback planner to use when all retries fail.
    """

    def __init__(
        self,
        client: LLMClient,
        max_retries: int = 2,
        fallback: WeeklyPlanner | None = None,
    ) -> None:
        """Initialize the LLM weekly planner.

        Args:
            client: The LLM client to use for generating plans.
            max_retries: Maximum number of retry attempts for transient
                failures.  Must be >= 0.
            fallback: Optional fallback planner to use when all retries
                fail.  If ``None``, a :class:`RuntimeError` is raised
                after all retries are exhausted.
        """
        if max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {max_retries}")
        self._client = client
        self._max_retries = max_retries
        self._fallback = fallback

    # ── Public API ──────────────────────────────────────────────────────

    def plan(self, context: PlanningContext) -> WeeklyPlan:
        """Generate a weekly plan from the given context.

        Args:
            context: The planning context containing goals, tasks,
                calendar events, and pre-computed deterministic signals.

        Returns:
            A complete weekly plan with summary, priorities, scheduled
            tasks, and identified risks.

        Raises:
            ValueError: If the context is invalid or incomplete.
            RuntimeError: If the planner fails to generate a valid plan
                after all retries and no fallback is available.
        """
        prompt = self._build_prompt(context)

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.generate(prompt)
            except Exception as e:
                # LLM client errors are transient — retry
                last_error = e
                emit(
                    logger,
                    "planner.llm.attempt_failed",
                    span_id="plan",
                    attempt=attempt + 1,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    message=f"LLM planner attempt {attempt + 1} failed: {e}",
                    level=logging.WARNING,
                )
                continue

            # Parsing and validation errors are deterministic — do NOT retry
            try:
                plan = self._parse_response(response)
                self._validate_plan(plan, context)
            except ValueError:
                raise

            emit(
                logger,
                "planner.llm.success",
                span_id="plan",
                attempt=attempt + 1,
                message=f"LLM planner succeeded on attempt {attempt + 1}",
            )

            return plan

        # All retries exhausted — use fallback if available
        if self._fallback is not None:
            emit(
                logger,
                "planner.llm.fallback",
                span_id="plan",
                message="LLM planner failed, using fallback",
            )
            return self._fallback.plan(context)

        raise RuntimeError(
            f"LLM planner failed after {self._max_retries + 1} attempts: {last_error}"
        ) from last_error

    # ── Prompt building ─────────────────────────────────────────────────

    def _build_prompt(self, context: PlanningContext) -> str:
        """Build a prompt from the planning context.

        Args:
            context: The planning context.

        Returns:
            A prompt string to send to the LLM.
        """
        goals_text = self._format_goals(context.goals)
        tasks_text = self._format_tasks(context.tasks)
        calendar_text = self._format_calendar(context.calendar)
        signals_text = self._format_signals(context.signals)

        return f"""You are a weekly planning assistant. Generate a structured weekly plan based on the following context.

## Goals
{goals_text}

## Tasks
{tasks_text}

## Calendar Events
{calendar_text}

## Pre-computed Signals
{signals_text}

## Instructions
Generate a weekly plan with the following structure:
- week_summary: A brief summary of the week's plan (1-2 sentences)
- priorities: List of goal priorities, each with:
  - goal_id: The goal's title
  - reason: Why this goal has this priority
  - priority: "high", "medium", or "low"
- planned_tasks: List of planned tasks, each with:
  - task_id: The task's title
  - goal_id: The goal this task supports
  - priority: "high", "medium", or "low"
  - reason: Why this task is scheduled
  - suggested_day: The date this task is suggested for (YYYY-MM-DD)
- risks: List of risks, each with:
  - description: Description of the risk
  - severity: "low", "medium", or "high"

Output ONLY valid JSON matching this schema:
{{
  "week_summary": "string",
  "priorities": [
    {{"goal_id": "string", "reason": "string", "priority": "high|medium|low"}}
  ],
  "planned_tasks": [
    {{"task_id": "string", "goal_id": "string", "priority": "high|medium|low", "reason": "string", "suggested_day": "YYYY-MM-DD"}}
  ],
  "risks": [
    {{"description": "string", "severity": "low|medium|high"}}
  ]
}}"""

    def _format_goals(self, goals: list) -> str:
        """Format goals for the prompt."""
        if not goals:
            return "No active goals."
        lines: list[str] = []
        for g in goals:
            parts = [f"- {g.title}"]
            if g.description:
                parts.append(f"  Description: {g.description}")
            if g.deadline:
                parts.append(f"  Deadline: {g.deadline}")
            if g.status != "active":
                parts.append(f"  Status: {g.status}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _format_tasks(self, tasks: list) -> str:
        """Format tasks for the prompt."""
        if not tasks:
            return "No open tasks."
        lines: list[str] = []
        for t in tasks:
            parts = [f"- {t.title}"]
            if t.due_date:
                parts.append(f"  Due: {t.due_date}")
            if t.priority:
                parts.append(f"  Priority: {t.priority}")
            if t.state:
                parts.append(f"  State: {t.state}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _format_calendar(self, calendar: list) -> str:
        """Format calendar events for the prompt."""
        if not calendar:
            return "No calendar events."
        lines: list[str] = []
        for e in calendar:
            parts = [f"- {e.title}"]
            if e.start:
                parts.append(f"  Start: {e.start}")
            if e.end:
                parts.append(f"  End: {e.end}")
            if e.all_day:
                parts.append("  All day")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _format_signals(self, signals: PlanningSignals) -> str:
        """Format pre-computed signals for the prompt."""
        parts: list[str] = []
        if signals.overdue_tasks:
            parts.append(f"Overdue tasks: {', '.join(signals.overdue_tasks)}")
        if signals.due_soon_tasks:
            parts.append(f"Due soon: {', '.join(signals.due_soon_tasks)}")
        if signals.stalled_goals:
            parts.append(f"Stalled goals: {', '.join(signals.stalled_goals)}")
        if signals.behind_target_goals:
            parts.append(f"Behind target: {', '.join(signals.behind_target_goals)}")
        if signals.calendar_conflicts:
            parts.append(
                f"Calendar conflicts: {'; '.join(signals.calendar_conflicts)}"
            )
        if signals.competing_tasks:
            competing = ", ".join(
                f"{t} ({c})" for t, c in signals.competing_tasks.items()
            )
            parts.append(f"Competing tasks: {competing}")
        if not parts:
            return "No signals."
        return "\n".join(parts)

    # ── Response parsing ───────────────────────────────────────────────

    def _parse_response(self, response: str) -> WeeklyPlan:
        """Parse the LLM's response into a :class:`WeeklyPlan`.

        Args:
            response: The LLM's response as a string.

        Returns:
            A WeeklyPlan parsed from the response.

        Raises:
            ValueError: If the response is not valid JSON or missing
                required fields.
        """
        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM response is not valid JSON: {e}") from e

        if not isinstance(data, dict):
            raise ValueError(
                f"LLM response must be a JSON object, got {type(data).__name__}"
            )

        # Extract week_summary
        week_summary = data.get("week_summary")
        if not isinstance(week_summary, str) or not week_summary.strip():
            raise ValueError("Missing or invalid 'week_summary' field")

        # Extract priorities
        priorities_data = data.get("priorities", [])
        if not isinstance(priorities_data, list):
            raise ValueError("'priorities' must be a list")
        priorities = [self._parse_priority_entry(p) for p in priorities_data]

        # Extract planned_tasks
        planned_tasks_data = data.get("planned_tasks", [])
        if not isinstance(planned_tasks_data, list):
            raise ValueError("'planned_tasks' must be a list")
        planned_tasks = [self._parse_planned_task(t) for t in planned_tasks_data]

        # Extract risks
        risks_data = data.get("risks", [])
        if not isinstance(risks_data, list):
            raise ValueError("'risks' must be a list")
        risks = [self._parse_planning_risk(r) for r in risks_data]

        return WeeklyPlan(
            week_summary=week_summary,
            priorities=priorities,
            planned_tasks=planned_tasks,
            risks=risks,
        )

    def _parse_priority_entry(self, data: dict[str, Any]) -> PriorityEntry:
        """Parse a priority entry from JSON data."""
        goal_id = data.get("goal_id")
        if not isinstance(goal_id, str) or not goal_id.strip():
            raise ValueError("Priority entry missing or invalid 'goal_id'")

        reason = data.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Priority entry missing or invalid 'reason'")

        priority_str = data.get("priority")
        if not isinstance(priority_str, str):
            raise ValueError("Priority entry missing or invalid 'priority'")
        try:
            priority = Priority(priority_str.lower())
        except ValueError as e:
            raise ValueError(f"Invalid priority value: {priority_str!r}") from e

        return PriorityEntry(goal_id=goal_id, reason=reason, priority=priority)

    def _parse_planned_task(self, data: dict[str, Any]) -> PlannedTask:
        """Parse a planned task from JSON data."""
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("Planned task missing or invalid 'task_id'")

        goal_id = data.get("goal_id")
        if not isinstance(goal_id, str) or not goal_id.strip():
            raise ValueError("Planned task missing or invalid 'goal_id'")

        priority_str = data.get("priority")
        if not isinstance(priority_str, str):
            raise ValueError("Planned task missing or invalid 'priority'")
        try:
            priority = Priority(priority_str.lower())
        except ValueError as e:
            raise ValueError(f"Invalid priority value: {priority_str!r}") from e

        reason = data.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Planned task missing or invalid 'reason'")

        suggested_day_str = data.get("suggested_day")
        if not isinstance(suggested_day_str, str):
            raise ValueError("Planned task missing or invalid 'suggested_day'")
        try:
            suggested_day = date.fromisoformat(suggested_day_str)
        except ValueError as e:
            raise ValueError(
                f"Invalid suggested_day format: {suggested_day_str!r}"
            ) from e

        return PlannedTask(
            task_id=task_id,
            goal_id=goal_id,
            priority=priority,
            reason=reason,
            suggested_day=suggested_day,
        )

    def _parse_planning_risk(self, data: dict[str, Any]) -> PlanningRisk:
        """Parse a planning risk from JSON data."""
        description = data.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Planning risk missing or invalid 'description'")

        severity_str = data.get("severity")
        if not isinstance(severity_str, str):
            raise ValueError("Planning risk missing or invalid 'severity'")
        try:
            severity = RiskSeverity(severity_str.lower())
        except ValueError as e:
            raise ValueError(f"Invalid severity value: {severity_str!r}") from e

        return PlanningRisk(description=description, severity=severity)

    # ── Validation ─────────────────────────────────────────────────────

    def _validate_plan(self, plan: WeeklyPlan, context: PlanningContext) -> None:
        """Validate the parsed plan against the context.

        Args:
            plan: The parsed weekly plan.
            context: The planning context.

        Raises:
            ValueError: If the plan is invalid.
        """
        # Check that referenced goal IDs exist in context
        valid_goal_ids = {g.title for g in context.goals}
        for entry in plan.priorities:
            if entry.goal_id not in valid_goal_ids:
                raise ValueError(
                    f"Priority entry references unknown goal: {entry.goal_id!r}"
                )

        # Check that referenced task IDs exist in context
        valid_task_ids = {t.title for t in context.tasks}
        for task in plan.planned_tasks:
            if task.task_id not in valid_task_ids:
                raise ValueError(
                    f"Planned task references unknown task: {task.task_id!r}"
                )
            if task.goal_id not in valid_goal_ids:
                raise ValueError(
                    f"Planned task references unknown goal: {task.goal_id!r}"
                )

        # Check for duplicate task scheduling (same task on multiple days)
        task_days: dict[str, date] = {}
        for task in plan.planned_tasks:
            if task.task_id in task_days:
                raise ValueError(
                    f"Task {task.task_id!r} is scheduled for multiple days: "
                    f"{task_days[task.task_id]} and {task.suggested_day}"
                )
            task_days[task.task_id] = task.suggested_day
