"""Goal-aware task recommendations.

Provides ranked, filterable task recommendations based on the
Goal → Milestone → Project → Task hierarchy.

Recommends tasks considering:
- Goal priority and status
- Milestone urgency (deadlines, status)
- Project status and progress
- Task priority and due dates
- Explicit Project assignments (I6 precedence over dynamic derivation)

Integration with the execution planning flow:
- Uses ``derive_next_action`` for the primary next-action determination
- Enriches with context-aware scoring for recommendation ranking
- Supports filtering by goal, milestone, project, and task attributes
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from janus.models.goal import Goal
from janus.models.project import Project
from janus.models.task import Task
from janus.services.next_action import (
    NextAction,
    _project_objs,
    derive_next_action,
)


@dataclass
class Recommendation:
    """A goal-aware task recommendation.

    Fields:
        title: The recommended item's title.
        kind: What kind of item is recommended — ``task``,
              ``project``, or ``milestone``.
        goal_title: The goal this recommendation belongs to.
        score: Recommendation score (higher = more urgent/important).
        reason: Human-readable explanation of why this was recommended.
        project_title: The Project context, if applicable.
        milestone_title: The Milestone context, if applicable.
        due_date: Task due date, if available.
        priority: Task priority, if available.
    """

    title: str
    kind: Literal["task", "project", "milestone"]
    goal_title: str
    score: int = 0
    reason: str = ""
    project_title: str | None = None
    milestone_title: str | None = None
    due_date: str | None = None
    priority: int | None = None


# ── Scoring helpers ────────────────────────────────────────────

def _task_base_score(task: Task, today: date) -> int:
    """Compute a base urgency score for a task."""
    score = 0
    if task.due_date is not None:
        try:
            due = date.fromisoformat(task.due_date) if isinstance(task.due_date, str) else task.due_date
            delta = (due - today).days
            if delta < 0:
                score += 100  # overdue
            elif delta == 0:
                score += 80  # due today
            elif delta <= 3:
                score += 60  # due soon
            elif delta <= 7:
                score += 40  # due this week
            else:
                score += 20  # due later
        except (ValueError, TypeError):
            pass
    if task.priority >= 3:
        score += 30
    elif task.priority >= 2:
        score += 15
    return score


def _project_progress_score(project: Project, completed_titles: set[str]) -> float:
    """Score a project based on completion progress (0..1, higher = more complete)."""
    if not project.related_tasks:
        return 0.0
    completed = sum(1 for t in project.related_tasks if t in completed_titles)
    return completed / len(project.related_tasks)


def _milestone_urgency_score(milestone_dict: dict, today: date) -> int:
    """Compute urgency score for a milestone based on deadline."""
    score = 0
    deadline = milestone_dict.get("deadline")
    if deadline:
        try:
            d = date.fromisoformat(deadline) if isinstance(deadline, str) else deadline
            delta = (d - today).days
            if delta < 0:
                score += 50  # overdue
            elif delta == 0:
                score += 40  # due today
            elif delta <= 3:
                score += 30  # due soon
            elif delta <= 7:
                score += 20  # due this week
        except (ValueError, TypeError):
            pass
    return score


# ── Recommendation builders ────────────────────────────────────

def _recommendation_from_next_action(
    action: NextAction,
    goal: Goal,
    tasks: list[Task],
    completed_titles: set[str],
    projects: list[Project],
) -> Recommendation:
    """Convert a NextAction into a Recommendation with enriched context."""
    task_map = {t.title: t for t in tasks}
    score = 0
    due_date = None
    priority = None

    if action.kind == "task" and action.title in task_map:
        t = task_map[action.title]
        score = _task_base_score(t, date.today())
        due_date = t.due_date
        priority = t.priority
    elif action.kind == "project":
        for p in projects:
            if p.title == action.title:
                progress = _project_progress_score(p, completed_titles)
                score = 50 + int((1 - progress) * 50)  # 50-100 based on incomplete work
                break
    elif action.kind == "milestone":
        for m in goal.milestones:
            if m.get("title") == action.title:
                ms_dict = {
                    "title": m.get("title", ""),
                    "goal_title": m.get("goal_title", ""),
                    "description": m.get("description", ""),
                    "deadline": m.get("deadline"),
                    "status": m.get("status", ""),
                    "order": m.get("order", 0),
                }
                score = _milestone_urgency_score(ms_dict, date.today()) + 30
                break
        else:
            score = 30

    # Determine project context
    project_title = None
    milestone_title = None
    for p in projects:
        if p.title == action.title:
            project_title = p.title
            milestone_title = p.milestone_title
            break
        for rt in p.related_tasks:
            if rt == action.title:
                project_title = p.title
                milestone_title = p.milestone_title
                break
        if project_title:
            break

    # Extract milestone from reason or goal structure
    if not milestone_title and action.reason:
        for m in goal.milestones:
            if m.get("title") in action.reason:
                milestone_title = m.get("title")
                break
    # Fallback: use action title as milestone title for milestone-kind actions
    if not milestone_title and action.kind == "milestone":
        milestone_title = action.title

    return Recommendation(
        title=action.title,
        kind=action.kind,
        goal_title=action.goal_title,
        score=score,
        reason=action.reason,
        project_title=project_title,
        milestone_title=milestone_title,
        due_date=due_date,
        priority=priority,
    )


# ── Public API ───────────────────────────────────────────────

def recommend_tasks(
    goals: list[Goal],
    tasks: list[Task],
    completed_task_titles: set[str] | None = None,
    today: date | None = None,
    goal_filter: str | None = None,
    milestone_filter: str | None = None,
    project_filter: str | None = None,
    kind_filter: Literal["task", "project", "milestone"] | None = None,
    min_score: int = 0,
    max_results: int = 10,
) -> list[Recommendation]:
    """Generate goal-aware task recommendations.

    Args:
        goals: List of active goals to consider.
        tasks: List of open (not completed) tasks.
        completed_task_titles: Set of completed task titles.
        today: Current date for deadline calculations. Defaults to date.today().
        goal_filter: Only recommend tasks for this goal title.
        milestone_filter: Only recommend tasks in this milestone.
        project_filter: Only recommend tasks in this project.
        kind_filter: Only recommend items of this kind (task/project/milestone).
        min_score: Minimum recommendation score to include.
        max_results: Maximum number of recommendations to return.

    Returns:
        Ranked list of recommendations sorted by score descending.
    """
    if completed_task_titles is None:
        completed_task_titles = set()
    if today is None:
        today = date.today()

    task_map = {t.title: t for t in tasks}
    open_task_titles = {t.title for t in tasks}
    recommendations: list[Recommendation] = []

    for goal in goals:
        if goal.status != "active":
            continue
        if goal_filter and goal.title != goal_filter:
            continue

        # Convert Project objects to dicts for _project_objs compatibility
        # (and ensure milestones have goal_title) BEFORE calling _project_objs
        if goal.projects:
            for i, p in enumerate(goal.projects):
                if isinstance(p, Project):
                    goal.projects[i] = {
                        "title": p.title,
                        "milestone_title": p.milestone_title,
                        "description": p.description,
                        "deadline": p.deadline,
                        "status": p.status,
                        "order": p.order,
                        "related_tasks": list(p.related_tasks),
                    }
        if goal.milestones:
            for i, m_dict in enumerate(goal.milestones):
                if isinstance(m_dict, dict) and "goal_title" not in m_dict:
                    goal.milestones[i] = dict(m_dict, goal_title=goal.title)

        projects = _project_objs(goal)
        milestone_objs = _milestone_objs(goal)

        # Derive next action using hierarchical traversal
        action = derive_next_action(
            goal,
            tasks,
            completed_task_titles,
            today,
            projects=projects if projects else None,
        )

        if action is None:
            # No next action — check if milestone or project is the next actionable item
            _add_milestone_recommendations(
                goal, milestone_objs, recommendations, today,
                milestone_filter, kind_filter, min_score,
            )
            _add_project_recommendations(
                goal, projects, completed_task_titles, recommendations,
                project_filter, kind_filter, min_score,
            )
            continue

        # Check filters
        if kind_filter and action.kind != kind_filter:
            continue
        if milestone_filter and action.kind == "task":
            # Check if task belongs to the filtered milestone
            if not _task_in_milestone(action.title, milestone_filter, goal, tasks):
                continue
        if project_filter and action.kind in ("task", "project"):
            if not _item_in_project(action.title, project_filter, projects):
                continue

        rec = _recommendation_from_next_action(
            action, goal, tasks, completed_task_titles, projects,
        )
        if rec.score >= min_score:
            recommendations.append(rec)

    # Sort by score descending, then by kind priority (task > project > milestone)
    kind_order = {"task": 0, "project": 1, "milestone": 2}
    recommendations.sort(key=lambda r: (-r.score, kind_order.get(r.kind, 3)))

    return recommendations[:max_results]


def recommend_for_goal(
    goal: Goal,
    tasks: list[Task],
    completed_task_titles: set[str] | None = None,
    today: date | None = None,
    **filters,
) -> list[Recommendation]:
    """Generate recommendations for a single goal.

    Convenience wrapper around ``recommend_tasks`` scoped to one goal.
    """
    return recommend_tasks(
        goals=[goal],
        tasks=tasks,
        completed_task_titles=completed_task_titles,
        today=today,
        goal_filter=goal.title,
        **filters,
    )


def recommend_next_actions(
    goals: list[Goal],
    tasks: list[Task],
    completed_task_titles: set[str] | None = None,
    today: date | None = None,
) -> list[Recommendation]:
    """Generate recommendations focused on next actions only (kind=task).

    Returns the most urgent actionable tasks across all active goals.
    """
    return recommend_tasks(
        goals=goals,
        tasks=tasks,
        completed_task_titles=completed_task_titles,
        today=today,
        kind_filter="task",
        max_results=5,
    )


# ── Helpers ────────────────────────────────────────────────────

def _milestone_objs(goal: Goal):
    """Construct ordered Milestone objects from goal.milestones dicts."""
    from janus.services.next_action import _milestone_objs as _original
    # Ensure milestones have goal_title before passing to original
    if goal.milestones:
        for i, m_dict in enumerate(goal.milestones):
            if isinstance(m_dict, dict) and "goal_title" not in m_dict:
                goal.milestones[i] = dict(m_dict, goal_title=goal.title)
    return _original(goal)


def _task_in_milestone(
    task_title: str,
    milestone_title: str,
    goal: Goal,
    tasks: list[Task],
) -> bool:
    """Check if a task belongs to a milestone via dynamic derivation or project assignment."""
    from janus.services.next_action import (
        _milestone_objs as mo,
        derive_milestone_task_set,
        _assigned_project_tasks,
    )
    milestone_objs = mo(goal)
    open_titles = {t.title for t in tasks}

    for m in milestone_objs:
        if m.title != milestone_title:
            continue
        ms_tasks = derive_milestone_task_set(milestone_objs, goal, open_titles)
        if task_title in ms_tasks:
            return True

    # Check project assignments
    projects = _project_objs(goal)
    assigned = _assigned_project_tasks(projects)
    if task_title in assigned:
        for p in projects:
            if p.title == milestone_title or p.milestone_title == milestone_title:
                if task_title in p.related_tasks:
                    return True

    return False


def _item_in_project(
    item_title: str,
    project_title: str,
    projects: list[Project],
) -> bool:
    """Check if a task or project matches the project filter."""
    for p in projects:
        if p.title == project_title:
            if item_title == project_title or item_title in p.related_tasks:
                return True
    return False


def _add_milestone_recommendations(
    goal: Goal,
    milestone_objs: list,
    recommendations: list[Recommendation],
    today: date,
    milestone_filter: str | None,
    kind_filter: str | None,
    min_score: int,
) -> None:
    """Add milestone-level recommendations when no task action is available."""
    if kind_filter and kind_filter != "milestone":
        return
    for m in milestone_objs:
        if m.status in ("completed", "skipped"):
            continue
        if milestone_filter and m.title != milestone_filter:
            continue
        ms_dict = {
            "title": m.title,
            "goal_title": m.goal_title,
            "description": m.description,
            "deadline": m.deadline,
            "status": m.status,
            "order": m.order,
        }
        score = _milestone_urgency_score(ms_dict, today) + 30
        if score >= min_score:
            recommendations.append(Recommendation(
                title=m.title,
                kind="milestone",
                goal_title=goal.title,
                score=score,
                reason=f"Next milestone: {m.title}",
                milestone_title=m.title,
            ))


def _add_project_recommendations(
    goal: Goal,
    projects: list[Project],
    completed_titles: set[str],
    recommendations: list[Recommendation],
    project_filter: str | None,
    kind_filter: str | None,
    min_score: int,
) -> None:
    """Add project-level recommendations for projects without open tasks."""
    if kind_filter and kind_filter != "project":
        return
    for p in projects:
        if p.status in ("completed", "skipped"):
            continue
        if project_filter and p.title != project_filter:
            continue
        progress = _project_progress_score(p, completed_titles)
        score = 50 + int((1 - progress) * 50)
        if score >= min_score:
            recommendations.append(Recommendation(
                title=p.title,
                kind="project",
                goal_title=goal.title,
                score=score,
                reason=f"Project '{p.title}' has incomplete tasks",
                project_title=p.title,
                milestone_title=p.milestone_title,
            ))