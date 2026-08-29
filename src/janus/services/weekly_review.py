"""Weekly review service — deterministic logic only."""

from pathlib import Path

from janus.models.weekly_review import GoalReview, WeeklyReview
from janus.integrations.markdown_goals import load_goals
from janus.integrations.markdown_tasks import load_tasks


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TASKS_PATH = PROJECT_ROOT / "data" / "tasks.md"


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


def create_weekly_review() -> WeeklyReview:
    """Create a weekly review from current tasks and goals.

    Does not pretend to know historical completion timestamps.
    Reports current completed state only.
    """
    goals = load_goals()
    tasks = load_tasks()

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

        if review.completed_related_tasks:
            review.progress = True
        else:
            review.progress = False

        # Suggested next step: first open related task
        if goal.related_tasks:
            first_open: str | None = None
            for rt in goal.related_tasks:
                if rt in open_task_map:
                    first_open = rt
                    break
            if first_open:
                review.suggested_next_step = first_open
            else:
                # All related tasks either completed or missing
                if not review.missing_related_tasks and review.completed_related_tasks:
                    review.all_related_tasks_completed = True

        goal_reviews.append(review)

    return WeeklyReview(
        completed_tasks=completed_titles,
        open_tasks=all_open_titles,
        goals=goal_reviews,
    )
