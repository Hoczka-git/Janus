"""Weekly review service — deterministic logic only.

Delegates goal progress computation to compute_goal_progress (central service).
Does not duplicate metric-vs-task priority logic.
"""

from pathlib import Path

from datetime import date, datetime, timezone

import logging
import re
import time

from janus._log import emit
from janus.models.weekly_review import GoalReview, WeeklyReview
from janus.integrations.markdown_goals import load_goals
from janus.integrations.markdown_tasks import load_tasks
from janus.services.goal_progress import compute_goal_progress
from janus.domain.planning import derive_next_action
from janus.services.project_progress import compute_all_project_progress

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TASKS_PATH = PROJECT_ROOT / "data" / "tasks.md"

logger = logging.getLogger(__name__)


def _read_completed_task_titles() -> list[str]:
    """Parse completed task titles directly from tasks.md file."""
    completed: list[str] = []
    if not TASKS_PATH.exists():
        return completed
    with TASKS_PATH.open() as f:
        for line in f:
            line = line.strip()
            if line.startswith("- [x]"):
                content = line[5:].strip()
                title = content.split(" | ", 1)[0].strip() if " | " in content else content
                completed.append(title)
    return completed


def _read_completed_task_dates() -> dict[str, date]:
    """Parse completion dates from completed task lines in tasks.md.

    Reads ``completed_at:`` and ``janus_evidence_completed_at:`` metadata
    fields from ``- [x]`` task lines. Returns a mapping of task title to
    completion date.

    The ``completed_at`` field is written by ``complete_task`` (format
    ``YYYY-MM-DD``). The ``janus_evidence_completed_at`` field is written by
    evidence propagation (format ``YYYY-MM-DDTHH:MM:SS+tz`` or
    ``YYYY-MM-DD``).

    Lines without a parseable completion date are skipped — the task title
    is still picked up by ``_read_completed_task_titles`` separately.
    """
    dates: dict[str, date] = {}
    if not TASKS_PATH.exists():
        return dates

    completed_at_re = re.compile(r"completed_at:\s*(\S+)")
    evidence_at_re = re.compile(r"janus_evidence_completed_at:\s*(\S+)")

    with TASKS_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line.startswith("- [x]"):
                continue
            content = line[5:].strip()
            # Title is everything before the first " | " separator
            if " | " in content:
                title, metadata = content.split(" | ", 1)
            else:
                title, metadata = content, ""
            title = title.strip()
            if not title:
                continue

            # Prefer the primary completed_at field; fall back to
            # janus_evidence_completed_at if the primary is absent.
            raw_date = None
            match = completed_at_re.search(metadata)
            if match:
                raw_date = match.group(1)
            else:
                match = evidence_at_re.search(metadata)
                if match:
                    raw_date = match.group(1)

            if raw_date is None:
                continue

            parsed = _parse_completion_date(raw_date)
            if parsed is not None:
                dates[title] = parsed

    return dates


def _parse_completion_date(raw: str) -> date | None:
    """Parse a completion date string into a ``date`` object.

    Accepts both ``YYYY-MM-DD`` and full ISO datetime strings
    (``YYYY-MM-DDTHH:MM:SS+tz``). Returns ``None`` if the string
    cannot be parsed.
    """
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def create_weekly_review(trace_id: str | None = None) -> WeeklyReview:
    """Create a weekly review from current tasks and goals.

    Reads completion dates from ``tasks.md`` metadata (``completed_at:`` and
    ``janus_evidence_completed_at:`` fields on ``- [x]`` task lines) and
    passes them to the goal health assessment so that
    ``days_since_last_activity`` and task-based ``progress_delta`` are
    computed accurately (design §13.4 / §14.1).
    """
    start = time.monotonic()
    emit(logger, "briefing.generation.started",
         trace_id=trace_id, span_id="build_weekly",
         correlation_id=trace_id,
         briefing_type="weekly",
         message="Weekly review generation started")

    goals = load_goals(trace_id=trace_id)
    tasks = load_tasks(trace_id=trace_id)
    today = date.today()

    # Build lookup structures
    completed_titles = _read_completed_task_titles()
    completed_task_dates = _read_completed_task_dates()
    open_task_map = {t.title: t for t in tasks}
    all_open_titles = list(open_task_map.keys())

    # Load all task titles (open + completed) for stall detection
    from janus.services.attention import _load_all_task_titles
    from janus.integrations.metric_history import get_metric_snapshots
    all_task_titles = _load_all_task_titles(
        Path(__file__).resolve().parents[3] / "data" / "tasks.md"
    )

    goal_reviews: list[GoalReview] = []

    for goal in goals:
        if goal.status != "active":
            continue

        review = GoalReview(goal=goal)

        for related_title in goal.related_tasks:
            if related_title in completed_titles:
                review.completed_related_tasks.append(related_title)
            elif related_title in open_task_map:
                pass
            else:
                review.missing_related_tasks.append(related_title)

        # Delegate ALL progress computation to central service
        prog = compute_goal_progress(goal, completed_task_titles=completed_titles)
        review.progress = prog

        if prog is not None:
            if goal.metric_name:
                review.progress_detail = (
                    f"{goal.current_value} → {goal.target_value}, {goal.direction}"
                )
            else:
                completed_count = sum(
                    1 for rt in goal.related_tasks if rt in completed_titles
                )
                review.progress_detail = (
                    f"{completed_count}/{len(goal.related_tasks)} tasks completed"
                )
        else:
            review.progress_detail = "N/A"

        # Project progress (design §15): computed by dedicated service to
        # avoid duplicating Project traversal logic in the weekly review.
        review.projects = compute_all_project_progress(goal, set(completed_titles))

        # Suggested next step: use rules-based derive_next_action
        # Pass project-aware objects so goals with Projects use the
        # hierarchical traversal (P1-P7) while legacy goals use R1-R5.
        from janus.domain.planning import project_objs
        next_action = derive_next_action(
            goal, tasks, set(completed_titles), today,
            projects=project_objs(goal),
        )
        if next_action is not None:
            review.suggested_next_step = next_action.title
        else:
            # No next action. If all related tasks are completed and none
            # are missing, mark all_related_tasks_completed.
            if goal.related_tasks:
                if not review.missing_related_tasks \
                        and all(rt in completed_titles
                                for rt in goal.related_tasks):
                    review.all_related_tasks_completed = True

        # Compute health assessment (design §6.4.2).
        from janus.services.goal_health import assess_goal_health
        metric_snaps = get_metric_snapshots(goal.title) if goal.metric_name else []
        assessment = assess_goal_health(
            goal, today,
            open_task_titles={t.title for t in tasks},
            all_task_titles=all_task_titles,
            metric_snapshots=metric_snaps,
            completed_task_dates=completed_task_dates,
        )
        if assessment is not None:
            review.health_state = assessment.health_state
            review.progress_delta = assessment.progress_delta
            review.days_since_last_activity = assessment.days_since_last_activity

            # Derive remediation action from health diagnostics (R1).
            # Only populated for unhealthy goals; healthy goals get None.
            from janus.services.recommended_actions import derive_remediation_action
            remediation = derive_remediation_action(assessment, goal=goal, today=today)
            if remediation is not None:
                review.remediation_action = remediation.action

        goal_reviews.append(review)

    duration_ms = (time.monotonic() - start) * 1000
    emit(logger, "briefing.generation.finished",
         trace_id=trace_id, span_id="build_weekly",
         correlation_id=trace_id,
         briefing_type="weekly",
         duration_ms=duration_ms,
         completed_tasks=len(completed_titles),
         open_tasks=len(all_open_titles),
         goal_reviews=len(goal_reviews),
         message=f"Weekly review finished: {len(completed_titles)} completed, {len(all_open_titles)} open, {len(goal_reviews)} goal reviews")

    return WeeklyReview(
        completed_tasks=completed_titles,
        open_tasks=all_open_titles,
        goals=goal_reviews,
    )
