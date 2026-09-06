"""Weekly review service — deterministic logic only.

Delegates goal progress computation to compute_goal_progress (central service).
Does not duplicate metric-vs-task priority logic.
"""

from pathlib import Path

from datetime import date

import logging
import time

from janus._log import emit
from janus.models.weekly_review import GoalReview, WeeklyReview
from janus.integrations.markdown_goals import load_goals
from janus.integrations.markdown_tasks import load_tasks
from janus.services.goal_progress import compute_goal_progress
from janus.services.next_action import derive_next_action

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


def create_weekly_review(trace_id: str | None = None) -> WeeklyReview:
    """Create a weekly review from current tasks and goals.

    Does not pretend to know historical completion timestamps.
    Reports current completed state only.
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
    open_task_map = {t.title: t for t in tasks}
    all_open_titles = list(open_task_map.keys())

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

        # Suggested next step: use rules-based derive_next_action
        next_action = derive_next_action(
            goal, tasks, set(completed_titles), today,
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
