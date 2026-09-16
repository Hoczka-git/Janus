"""Strategic summary service for Janus (design spec §5, §67).

``create_strategic_summary()`` is the single entry point that aggregates the
existing, reusable state-summary services into a structured
``StrategicSummary`` model:

1. ``assess_goal_health()`` (services/goal_health.py) → health state +
   dominant signal per active goal (spec §4 source 1).
2. ``get_attention_items()`` (services/attention.py) → dominant attention
   category + reason per goal.
3. ``create_weekly_review()`` (services/weekly_review.py) →
   ``GoalReview.suggested_next_step`` (spec §4 source 2).
4. ``recommend_tasks()`` (services/recommendations.py) → task-level ranked
   recommendations (spec §4 source 3).
5. cross-domain links (research artifacts, decisions, follow-ups) surfaced
   via ``_collect_cross_domain_links`` (spec §4, §82).

This is pure addition — no existing surfaces change (spec §83). All signal
computation is delegated to the existing ``assess_goal_health()``; this
service only assembles the aggregated summary.
"""

import logging
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from janus.models.goal import Goal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.recommended_action import CrossDomainLink, RecommendedAction
from janus.models.strategic_summary import (
    PortfolioHealthCounts,
    StrategicSummary,
)
from janus.services.recommended_actions import (
    create_recommended_actions,
    identify_neglected_goals,
    _collect_cross_domain_links,
)

logger = logging.getLogger(__name__)

# Project root for data-file access (three levels up from services/).
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def create_strategic_summary(
    goals: list[Goal] | None = None,
    assessments: list[GoalHealthAssessment] | None = None,
    goal_reviews=None,
    attention_items=None,
    task_recommendations=None,
    cross_links: list[CrossDomainLink] | None = None,
    open_task_titles: set[str] | None = None,
    *,
    today: date | None = None,
    now: datetime | None = None,
    trace_id: str | None = None,
) -> StrategicSummary:
    """Build a structured ``StrategicSummary`` for the goal portfolio (spec §5).

    The summary aggregates health assessments, attention items, weekly
    reviews, task recommendations, and cross-domain links into a single
    ranked, actionable portrait of portfolio health.

    Args:
        goals: The full Goal list. If ``None``, loaded from markdown (for
            the default CLI/CLI-less call path).
        assessments: Pre-computed goal health assessments. If ``None``,
            computed via ``assess_goal_health()`` for each active goal.
        goal_reviews: Pre-computed weekly reviews (for
            ``suggested_next_step``). If ``None``, loaded via
            ``create_weekly_review()``.
        attention_items: Pre-computed attention items. If ``None``, loaded
            via ``get_attention_items()``.
        task_recommendations: Pre-computed task recommendations. If ``None``,
            loaded via ``recommend_tasks()``.
        cross_links: Pre-collected cross-domain links for the relevant goals.
            If ``None``, collected via ``_collect_cross_domain_links()``.
        open_task_titles: Set of open task titles. When assessments are
            provided directly, the caller may pass this so the neglected-goal
            logic has the active-task set without a filesystem load.
        today: Current date for deadline/activity calculations. Defaults to
            ``date.today()``.
        now: Current datetime for ``generated_at``. Defaults to now.
        trace_id: Trace identifier propagated for observability events.

    Returns:
        A ``StrategicSummary`` with portfolio health counts, stalled goals,
        neglected goals, ranked recommended actions, and cross-domain links.
    """
    if today is None:
        today = date.today()
    if now is None:
        now = datetime.now().astimezone()

    # ── Load data sources (reuse existing integrations — spec §5 reusepoints) ──
    if goals is None:
        from janus.integrations.markdown_goals import load_goals
        goals = load_goals(trace_id=trace_id)

    if open_task_titles is None:
        open_task_titles = set()
    if assessments is None:
        assessments = _compute_assessments(goals, today, open_task_titles)
    elif not open_task_titles:
        # Assessments were injected but no open-task set was provided; try
        # the filesystem, but fall back to empty (no crash on missing data).
        try:
            from janus.integrations.markdown_tasks import load_tasks
            open_task_titles = {t.title for t in load_tasks(trace_id=trace_id)}
        except FileNotFoundError:
            pass

    if goal_reviews is None:
        goal_reviews = _load_goal_reviews()
    if attention_items is None:
        attention_items = _load_attention_items(goals, today, now, trace_id)
    if task_recommendations is None:
        task_recommendations = _load_task_recommendations(goals, today)

    # Cross-domain links (spec §4 source 5, §82).
    all_goal_titles = {g.title for g in goals}
    if cross_links is None:
        cross_links = _collect_cross_domain_links(all_goal_titles)
    link_by_goal: dict[str, list[CrossDomainLink]] = {}
    for link in cross_links:
        link_by_goal.setdefault(link.goal_title, []).append(link)

    # ── Portfolio health counts (spec §5.1, §6.7) ──
    counts = _compute_portfolio_health_counts(goals, assessments)

    # Restrict to assessments whose goal is active (inactive/completed goals
    # are excluded from health evaluation per spec §80, §88). This guards
    # against callers injecting assessments for non-active goals.
    active_titles = {g.title for g in goals if g.status == "active"}
    active_assessments = [a for a in assessments if a.goal_title in active_titles]

    # ── Stalled goals (spec §3.9): health_state == stalled, score desc ──
    stalled = [a for a in active_assessments if a.health_state == "stalled"]
    stalled.sort(
        key=lambda a: (-(a.dominant_signal.score if a.dominant_signal else 0), a.goal_title)
    )

    # ── Neglected goals (spec §2, §26) ──
    neglected = identify_neglected_goals(active_assessments, goals, open_task_titles, today)

    # ── Recommended next actions (spec §4, §61) ──
    actions = create_recommended_actions(
        active_assessments,
        goals,
        goal_reviews=goal_reviews,
        attention_items=attention_items,
        recommendations=task_recommendations,
        cross_links=cross_links,
        open_task_titles=open_task_titles,
        today=today,
        now=now,
    )

    return StrategicSummary(
        generated_at=now,
        portfolio_health_counts=counts,
        stalled_goals=[a.to_dict() for a in stalled] if stalled else [],
        neglected_goals=[a.to_dict() for a in neglected] if neglected else [],
        recommended_actions=[a.to_dict() for a in actions] if actions else [],
        cross_domain_links=[asdict(l) for l in cross_links] if cross_links else [],
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _compute_portfolio_health_counts(
    goals: list[Goal],
    assessments: list[GoalHealthAssessment],
) -> PortfolioHealthCounts:
    """Compute portfolio-wide health counts (spec §5.1, §6.7)."""
    counts = PortfolioHealthCounts()
    counts.total_active = sum(1 for g in goals if g.status == "active")
    counts.completed = sum(1 for g in goals if g.status == "completed")
    counts.inactive = sum(1 for g in goals if g.status == "inactive")
    # Index assessments by goal title for quick lookup of active-goal health.
    assessment_by_goal = {a.goal_title: a for a in assessments}
    for g in goals:
        if g.status != "active":
            continue
        a = assessment_by_goal.get(g.title)
        if a is None:
            continue
        if a.health_state == "healthy":
            counts.healthy += 1
        elif a.health_state == "watch":
            counts.watch += 1
        elif a.health_state == "stalled":
            counts.stalled += 1
    return counts


def _compute_assessments(
    goals: list[Goal],
    today: date,
    open_task_titles: set[str],
) -> list[GoalHealthAssessment]:
    """Compute health assessments for all active goals via assess_goal_health."""
    from janus.services.goal_health import assess_goal_health
    from janus.services.attention import _load_all_task_titles

    try:
        from janus.integrations.markdown_tasks import load_tasks
        tasks = load_tasks()
    except FileNotFoundError:
        return []
    open_task_titles.update({t.title for t in tasks})
    tasks_path = PROJECT_ROOT / "data" / "tasks.md"
    all_task_titles = _load_all_task_titles(tasks_path)

    assessments: list[GoalHealthAssessment] = []
    for goal in goals:
        if goal.status != "active":
            continue
        a = assess_goal_health(
            goal, today,
            open_task_titles=open_task_titles,
            all_task_titles=all_task_titles,
        )
        if a is not None:
            assessments.append(a)
    return assessments


def _load_goal_reviews():
    """Load weekly reviews and return GoalReview objects (spec §4 source 2).

    Returns an empty list when no goals/tasks data exists on disk so the
    service remains usable in test contexts without data files.
    """
    try:
        from janus.services.weekly_review import create_weekly_review
        return create_weekly_review().goals
    except FileNotFoundError:
        return []


def _load_attention_items(goals, today, now, trace_id):
    """Load attention items (spec §4 source 1).

    Returns an empty list when no goals/tasks data exists on disk.
    """
    try:
        from janus.integrations.markdown_tasks import load_tasks
        from janus.services.attention import get_attention_items
        events: list = []
        tasks = load_tasks(trace_id=trace_id)
        return get_attention_items(
            events=events, tasks=tasks, goals=goals, today=today, now=now,
            trace_id=trace_id,
        )
    except FileNotFoundError:
        return []


def _load_task_recommendations(goals, today):
    """Load task-level recommendations (spec §4 source 3).

    Returns an empty list when no goals/tasks data exists on disk.
    """
    try:
        from janus.integrations.markdown_tasks import load_tasks
        from janus.services.recommendations import recommend_tasks
        from janus.services.weekly_review import _read_completed_task_titles
        tasks = load_tasks()
        completed = set(_read_completed_task_titles())
        return recommend_tasks(
            goals=goals, tasks=tasks,
            completed_task_titles=completed, today=today,
        )
    except FileNotFoundError:
        return []
