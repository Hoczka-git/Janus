"""Attention engine for Janus — deterministic scoring of what deserves attention."""

from datetime import date, datetime, timezone
from pathlib import Path

from janus.models.attention import AttentionItem
from janus.models.event import Event
from janus.models.goal import Goal
from janus.models.task import Task


def _load_all_task_titles(tasks_path: Path) -> set[str]:
    """Return set of all task titles (open and completed) from the markdown file."""
    if not tasks_path.exists():
        return set()

    titles: set[str] = set()
    with tasks_path.open() as f:
        for line in f:
            line = line.strip()
            if line.startswith("- [ ") or line.startswith("- [x]") or line.startswith("- [ ]"):
                content = line[5:].strip()
                title = content.split("|", 1)[0].strip()
                if title:
                    titles.add(title)
    return titles


def get_attention_items(
    events: list[Event],
    tasks: list[Task],
    goals: list[Goal],
    today: date,
    now: datetime | None = None,
) -> list[AttentionItem]:
    """Produce a deterministically sorted list of attention items.

    Events ───────┐
                 │

    Tasks ────────┼──> Attention Engine ──> Ranked Attention Items
                 │

    Goals ────────┘

    Args:
        now: current time for event filtering. Defaults to datetime.now().
    """
    if now is None:
        now = datetime.now().astimezone()

    items: list[AttentionItem] = []

    # ── Tasks ──────────────────────────────────────────────────────────────
    for task in tasks:
        score = 0
        reasons: list[str] = []

        if task.due_date is not None and task.due_date < today:
            score += 100
            days_overdue = (today - task.due_date).days
            if days_overdue == 1:
                reasons.append("Overdue by 1 day")
            else:
                reasons.append(f"Overdue by {days_overdue} days")

        elif task.due_date is not None and task.due_date == today:
            score += 80
            reasons.append("Due today")

        if task.priority >= 3:
            score += 50
            reasons.append("High priority task")

        # Priority 2 contributes only when task already qualifies
        if task.priority == 2 and score > 0:
            score += 20

        if score > 0:
            items.append(AttentionItem(
                title=task.title,
                reason="; ".join(reasons) if reasons else "Requires attention",
                score=score,
                category="overdue_task" if (task.due_date is not None and task.due_date < today)
                          else "due_today" if (task.due_date is not None and task.due_date == today)
                          else "high_priority_task",
            ))

    # ── Events ──────────────────────────────────────────────────────────────
    for event in events:
        if event.start is None:
            continue
        event_start_date = event.start.date()
        if event_start_date != today:
            continue
        event_start_dt = event.start
        if event_start_dt <= now:
            continue
        minutes = (event_start_dt - now).total_seconds() / 60
        items.append(AttentionItem(
            title=event.title,
            reason=f"Starts in {minutes:.0f} minutes",
            score=10,
            category="upcoming_event",
        ))

    # ── Goals: stagnation detection ─────────────────────────────────────────
    open_task_titles = {t.title for t in tasks}
    tasks_path = Path(__file__).resolve().parents[3] / "data" / "tasks.md"
    all_task_titles = _load_all_task_titles(tasks_path)

    for goal in goals:
        if goal.status != "active":
            continue
        if not goal.related_tasks:
            continue

        # Check if any related task is open anywhere.
        has_open_related = False
        all_existing_related: list[str] = []

        for rt in goal.related_tasks:
            if rt in open_task_titles:
                has_open_related = True
            if rt in all_task_titles or rt in open_task_titles:
                all_existing_related.append(rt)

        if has_open_related:
            continue  # not stalled

        if not all_existing_related:
            continue  # all missing references — don't mark as stalled

        # All existing related tasks are completed (none open).
        items.append(AttentionItem(
            title=goal.title,
            reason="All linked tasks are completed. Define the next milestone, add a new action, or mark the goal as complete.",
            score=40,
            category="goal_stalled",
        ))

    # ── Deterministic sort: highest score first, then category, then title ─
    items.sort(key=lambda i: (-i.score, i.category, i.title))
    return items
