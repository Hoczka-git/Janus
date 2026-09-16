"""Strategic summary service for Janus.

Aggregates goal-health assessments, weekly-review data, attention items,
task recommendations, and cross-domain knowledge links into a single
``StrategicSummary`` that identifies neglected goals and stalled work.

Implements the service layer defined in
``docs/design/strategic_summary_spec.md`` §5 and the identification logic
from §2 (neglected goals) and §3 (stalled work).

This is a pure addition — no existing surfaces are changed (design §5,
§83). All signal computation is delegated to the existing
``assess_goal_health()`` (goal_health.py) and ``assess_goal_stall()``
(attention.py); this module only aggregates their outputs.
"""

import logging
from datetime import date, datetime

from janus.models.goal import Goal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.weekly_review import GoalReview
from janus.models.strategic_summary import (
    CrossDomainLink,
    NeglectedGoal,
    PortfolioHealthCounts,
    RecommendedAction,
    StalledGoal,
    StrategicSummary,
)
from janus.services.goal_health import (
    assess_goal_health,
    INACTIVITY_WINDOW_DAYS,
)
from janus.services.weekly_review import create_weekly_review, _read_completed_task_titles

logger = logging.getLogger(__name__)

# ── Constants referenced by name, not hard-coded (design §94) ────────────────
# The number of days since a strategic action was surfaced after which a
# goal is considered "not recently attended to" (design §2).
STRATEGIC_ATTENTION_WINDOW_DAYS = 7


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_deadline(raw):
    """Parse an ISO date string into a date, or None."""
    if raw is None:
        return None
    from datetime import date as _date
    try:
        return _date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _has_upcoming_milestone_or_deadline(goal: Goal, today: date) -> bool:
    """Return True if the goal has an upcoming (future, non-terminal)
    milestone deadline or a future goal deadline (design §26).

    A goal with no upcoming milestones/deadlines is considered inert even if
    it has open related tasks that are not yet actionable toward a deadline.
    """
    goal_dl = _parse_deadline(goal.deadline)
    if goal_dl is not None and goal_dl > today:
        return True

    from janus.services.attention import _milestone_objs
    for m in _milestone_objs(goal):
        if m.status in ("completed", "skipped"):
            continue
        m_dl = _parse_deadline(m.deadline)
        if m_dl is not None and m_dl > today:
            return True
        # An open/in_progress milestone with no deadline still represents
        # a future checkpoint — upcoming work.
        if m.status in ("open", "in_progress") and m_dl is None:
            return True

    return False


def _collect_cross_domain_links(
    goal_titles: set[str],
    research_artifacts=None,
    decisions=None,
    followups=None,
) -> list[CrossDomainLink]:
    """Collect all cross-domain links for the given goal titles (design §4).

    Surveys:
    - research artifacts with ``linked_goal_titles`` matching a goal
    - decisions (ADRs) with ``goal_titles`` matching a goal
    - follow-ups with ``linked_goal_title`` matching a goal

    Deduplicates by (goal_title, category, title).
    """
    from janus.services.research_artifacts import load_all_artifacts
    from janus.services.decisions import load_decisions
    from janus.integrations.markdown_followups import load_followups

    if research_artifacts is None:
        research_artifacts = load_all_artifacts()
    if decisions is None:
        decisions = load_decisions()
    if followups is None:
        followups = load_followups()

    links: list[CrossDomainLink] = []
    seen: set[tuple[str, str, str]] = set()

    for art in research_artifacts:
        for gt in art.linked_goal_titles:
            if gt in goal_titles:
                key = (gt, "research_artifact", art.title)
                if key not in seen:
                    seen.add(key)
                    links.append(CrossDomainLink(
                        goal_title=gt,
                        category="research_artifact",
                        title=art.title,
                    ))

    for dec in decisions:
        for gt in dec.goal_titles:
            if gt in goal_titles:
                key = (gt, "decision", dec.title)
                if key not in seen:
                    seen.add(key)
                    links.append(CrossDomainLink(
                        goal_title=gt,
                        category="decision",
                        title=dec.title,
                    ))

    for fu in followups:
        if fu.linked_goal_title and fu.linked_goal_title in goal_titles:
            key = (fu.linked_goal_title, "follow_up", fu.title)
            if key not in seen:
                seen.add(key)
                links.append(CrossDomainLink(
                    goal_title=fu.linked_goal_title,
                    category="follow_up",
                    title=fu.title,
                ))

    return links


def _links_for_goal(
    goal_title: str,
    all_links: list[CrossDomainLink],
) -> list[CrossDomainLink]:
    """Return cross-domain links for a specific goal, deduplicated by type."""
    return [l for l in all_links if l.goal_title == goal_title]


def _build_portfolio_counts(assessments, goals):
    """Build PortfolioHealthCounts from assessments and goals."""
    counts = PortfolioHealthCounts()
    counts.total_active = sum(1 for g in goals if g.status == "active")
    for a in assessments:
        if a.health_state == "healthy":
            counts.healthy += 1
        elif a.health_state == "watch":
            counts.watch += 1
        elif a.health_state == "stalled":
            counts.stalled += 1
        elif a.health_state == "completed":
            counts.completed += 1
    counts.inactive = sum(1 for g in goals if g.status == "inactive")
    return counts


# ── Public API ──────────────────────────────────────────────────────────────


def create_strategic_summary(
    goals: list[Goal] | None = None,
    today: date | None = None,
    now: datetime | None = None,
    open_task_titles: set[str] | None = None,
    all_task_titles: set[str] | None = None,
    completed_task_dates: dict | None = None,
    metric_snapshots_by_goal: dict | None = None,
    followups: list | None = None,
    research_artifacts: list | None = None,
    decisions: list | None = None,
    attention_items=None,
    recommendations=None,
    portfolio_health_counts: PortfolioHealthCounts | None = None,
    goal_reviews=None,
) -> StrategicSummary:
    """Create a strategic summary by aggregating existing signal services.

    Delegates all health/signal computation to ``assess_goal_health()``
    (goal_health.py) and reuses ``GoalReview`` from the weekly review
    for recommended-action computation (design §2, §28).

    Args:
        goals: Goals to assess. Defaults to loading all goals.
        today: Current date. Defaults to ``date.today()``.
        now: Current datetime. Defaults to ``datetime.now().astimezone()``.
        open_task_titles: Set of open task titles for stall assessment.
        all_task_titles: Set of all task titles (open + completed).
        completed_task_dates: Mapping task title -> completion date.
        metric_snapshots_by_goal: Per-goal metric snapshots (for time-based
            signals). When None, assessed via ``assess_goal_health``.
        followups: Pre-loaded follow-ups (for cross-domain links).
        research_artifacts: Pre-loaded research artifacts.
        decisions: Pre-loaded decisions.
        attention_items: Pre-computed attention items.
        recommendations: Pre-computed recommendations.
        portfolio_health_counts: Pre-computed health counts.
        goal_reviews: Pre-computed weekly reviews (for suggested-next-step).

    Returns:
        A ``StrategicSummary`` with stalled goals, neglected goals, and
        recommended actions (design §5 acceptance criteria).
    """
    if now is None:
        now = datetime.now().astimezone()
    if today is None:
        today = now.date()

    # Load goals if not provided.
    if goals is None:
        from janus.integrations.markdown_goals import load_goals
        goals = load_goals()

    # Load task data if not provided (needed for assess_goal_health).
    if open_task_titles is None or all_task_titles is None:
        from janus.integrations.markdown_tasks import load_tasks
        tasks = load_tasks()
        if open_task_titles is None:
            open_task_titles = {t.title for t in tasks}
        if all_task_titles is None:
            completed = _read_completed_task_titles()
            all_task_titles = {t.title for t in tasks} | set(completed)

    # Build attention items if not provided.
    if attention_items is None:
        from janus.services.attention import get_attention_items
        _followups = followups if followups is not None else None
        attention_items = get_attention_items(
            events=[],
            tasks=__import__("janus.integrations.markdown_tasks", fromlist=["load_tasks"]).load_tasks(),
            goals=goals,
            today=today,
            now=now,
            followups=_followups,
        )

    # Build recommendations if not provided.
    if recommendations is None:
        from janus.services.recommendations import recommend_tasks
        _completed = _read_completed_task_titles()
        recommendations = recommend_tasks(
            goals=goals,
            tasks=__import__("janus.integrations.markdown_tasks", fromlist=["load_tasks"]).load_tasks(),
            completed_task_titles=set(_completed),
            today=today,
        )

    # Build goal reviews if not provided (for suggested_next_step).
    if goal_reviews is None:
        goal_reviews = create_weekly_review().goals

    # Collect cross-domain links.
    all_links = _collect_cross_domain_links(
        {g.title for g in goals}, research_artifacts, decisions, followups,
    )

    # Assess each goal's health.
    assessments: list[GoalHealthAssessment] = []
    for goal in goals:
        _snaps = None
        if metric_snapshots_by_goal is not None:
            _snaps = metric_snapshots_by_goal.get(goal.title)
        a = assess_goal_health(
            goal, today,
            open_task_titles=open_task_titles,
            all_task_titles=all_task_titles,
            metric_snapshots=_snaps,
            completed_task_dates=completed_task_dates,
        )
        if a is not None:
            assessments.append(a)

    # Build portfolio health counts.
    if portfolio_health_counts is None:
        portfolio_health_counts = _build_portfolio_counts(assessments, goals)

    # Lookup: goal title → GoalReview (for suggested_next_step).
    review_by_goal: dict[str, GoalReview] = {}
    for gr in goal_reviews:
        review_by_goal[gr.goal.title] = gr

    # Lookup: attention items by goal title.
    attention_by_title: dict[str, str] = {}
    for item in attention_items:
        attention_by_title[item.title] = item.reason

    # ── Stalled goals (health_state == stalled), sorted by score desc ──
    # (design §3, §39)
    stalled: list[StalledGoal] = []
    for a in assessments:
        if a.health_state != "stalled":
            continue
        dom = a.dominant_signal
        stalled.append(StalledGoal(
            goal_title=a.goal_title,
            health_state=a.health_state,
            dominant_signal=dom.signal if dom else "",
            dominant_signal_score=dom.score if dom else 0,
            dominant_signal_reason=dom.reason if dom else "",
            progress=a.progress,
            progress_delta=a.progress_delta,
            days_since_last_activity=a.days_since_last_activity,
            measurement_overdue_count=a.measurement_overdue_count,
        ))
    stalled.sort(key=lambda s: s.dominant_signal_score, reverse=True)

    # ── Neglected goals (design §2, §26) ──
    neglected: list[NeglectedGoal] = []
    for a in assessments:
        # Only watch or stalled goals are candidates.
        if a.health_state not in ("watch", "stalled"):
            continue
        goal = next((g for g in goals if g.title == a.goal_title), None)
        if goal is None:
            continue
        # Suppress inactive and completed (already excluded by assess_goal_health
        # returning None, but guard for safety — design §26).
        if goal.status in ("inactive", "completed"):
            continue

        dom = a.dominant_signal
        # Threshold conditions (design §26):
        #   days_since_last_activity > inactivity_window_days (default 30)
        #   OR measurement_overdue_count > 0
        #   OR no open related tasks with upcoming milestone/deadline
        inactivity_window = goal.inactivity_window_days or INACTIVITY_WINDOW_DAYS
        days = a.days_since_last_activity
        days_exceeds = days is not None and days > inactivity_window
        has_measurement_overdue = a.measurement_overdue_count > 0
        open_related = any(rt in open_task_titles for rt in goal.related_tasks)
        has_upcoming = _has_upcoming_milestone_or_deadline(goal, today)

        if (
            days_exceeds
            or has_measurement_overdue
            or (not open_related and not has_upcoming)
        ):
            neglected.append(NeglectedGoal(
                goal_title=a.goal_title,
                health_state=a.health_state,
                dominant_signal=dom.signal if dom else "",
                dominant_signal_score=dom.score if dom else 0,
                dominant_signal_reason=dom.reason if dom else "",
                progress=a.progress,
                progress_delta=a.progress_delta,
                days_since_last_activity=a.days_since_last_activity,
                measurement_overdue_count=a.measurement_overdue_count,
                has_open_related_tasks=open_related,
                has_upcoming_deadline=has_upcoming,
            ))

    # Severity ranking: stalled > watch; within each, by dominant score desc,
    # then days_since_last_activity desc (design §25, §61).
    neglected.sort(
        key=lambda n: (
            0 if n.health_state == "stalled" else 1,
            -n.dominant_signal_score,
            -(n.days_since_last_activity or 0),
            n.goal_title,
        )
    )

    # ── Recommended actions (design §4, §43-§61) ──
    neglected_titles = (
        {n.goal_title for n in neglected}
        | {s.goal_title for s in stalled}
    )
    recommendations_list: list[RecommendedAction] = []

    for a in assessments:
        if a.goal_title not in neglected_titles:
            continue
        dom = a.dominant_signal
        gr = review_by_goal.get(a.goal_title)
        suggested = gr.suggested_next_step if gr and gr.suggested_next_step else None
        attention_reason = attention_by_title.get(a.goal_title)

        goal_links = _links_for_goal(a.goal_title, all_links)

        recommendations_list.append(RecommendedAction(
            goal_title=a.goal_title,
            health_state=a.health_state,
            dominant_signal=dom.signal if dom else "",
            dominant_signal_score=dom.score if dom else 0,
            dominant_signal_reason=dom.reason if dom else "",
            progress=a.progress,
            progress_delta=a.progress_delta,
            days_since_last_activity=a.days_since_last_activity,
            measurement_overdue_count=a.measurement_overdue_count,
            suggested_next_step=suggested,
            attention_reason=attention_reason,
            cross_links=goal_links,
        ))

    # Rank: stalled by dominant score desc, then watch, then by
    # days_since_last_activity desc (design §61).
    recommendations_list.sort(
        key=lambda r: (
            0 if r.health_state == "stalled" else 1,
            -r.dominant_signal_score,
            -(r.days_since_last_activity or 0),
            r.goal_title,
        )
    )

    return StrategicSummary(
        generated_at=now,
        portfolio_health_counts=portfolio_health_counts,
        stalled_goals=stalled,
        neglected_goals=neglected,
        recommended_actions=recommendations_list,
        cross_domain_links=all_links,
    )


def render_strategic_summary(summary: StrategicSummary) -> str:
    """Render a ``StrategicSummary`` as human-readable markdown (design §73).

    Output: health-state summary table + stalled-work list + neglected list +
    per-item recommendations including cross-links (design §79).
    """
    lines: list[str] = []
    counts = summary.portfolio_health_counts

    lines.append("JANUS — STRATEGIC SUMMARY")
    lines.append("=" * 60)
    lines.append("")
    lines.append("PORTFOLIO HEALTH")
    lines.append(
        f"  Active: {counts.total_active}  "
        f"Healthy: {counts.healthy}  "
        f"Watch: {counts.watch}  "
        f"Stalled: {counts.stalled}"
    )
    if counts.completed or counts.inactive:
        lines.append(f"  Completed: {counts.completed}  Inactive: {counts.inactive}")
    lines.append("")

    # Stalled work list (design §39)
    lines.append("STALLED WORK")
    if summary.stalled_goals:
        for sg in summary.stalled_goals:
            lines.append(
                f"  [{sg.dominant_signal} score={sg.dominant_signal_score}] "
                f"{sg.goal_title}"
            )
            lines.append(f"    Reason: {sg.dominant_signal_reason}")
            if sg.progress is not None:
                delta_str = ""
                if sg.progress_delta is not None:
                    delta_str = f", delta {sg.progress_delta:+.1f}% over 14d"
                lines.append(f"    Progress: {sg.progress:.1f}%{delta_str}")
            if sg.days_since_last_activity is not None:
                lines.append(
                    f"    Activity: {sg.days_since_last_activity}d since last metric/task"
                )
            lines.append(f"    Measurements overdue: {sg.measurement_overdue_count}")
    else:
        lines.append("  No stalled goals.")
    lines.append("")

    # Neglected goals list
    lines.append("NEGLECTED GOALS")
    if summary.neglected_goals:
        for ng in summary.neglected_goals:
            lines.append(
                f"  [{ng.health_state}, score={ng.dominant_signal_score}] "
                f"{ng.goal_title}"
            )
            lines.append(f"    Reason: {ng.dominant_signal_reason}")
            if ng.progress is not None:
                delta_str = ""
                if ng.progress_delta is not None:
                    delta_str = f", delta {ng.progress_delta:+.1f}% over 14d"
                lines.append(f"    Progress: {ng.progress:.1f}%{delta_str}")
            else:
                lines.append("    Progress: N/A")
            if ng.days_since_last_activity is not None:
                lines.append(
                    f"    Activity: {ng.days_since_last_activity}d since last metric/task"
                )
            else:
                lines.append("    Activity: no data")
            lines.append(f"    Measurements overdue: {ng.measurement_overdue_count}")
    else:
        lines.append("  No neglected goals.")
    lines.append("")

    # Recommended actions (design §4, §51-§59)
    lines.append("RECOMMENDED ACTIONS")
    if summary.recommended_actions:
        for i, ra in enumerate(summary.recommended_actions, 1):
            lines.append(
                f"{i}. {ra.goal_title} [{ra.health_state}, score={ra.dominant_signal_score}]"
            )
            lines.append(f"   Reason: {ra.dominant_signal_reason}")
            if ra.progress is not None:
                delta_str = ""
                if ra.progress_delta is not None:
                    delta_str = f", delta {ra.progress_delta:+.1f}% over 14d"
                lines.append(f"   Progress: {ra.progress:.1f}%{delta_str}")
            else:
                lines.append("   Progress: N/A")
            if ra.days_since_last_activity is not None:
                lines.append(
                    f"   Activity: {ra.days_since_last_activity}d since last metric/task"
                )
            else:
                lines.append("   Activity: no data")
            lines.append(f"   Measurements overdue: {ra.measurement_overdue_count}")
            action = ra.suggested_next_step or ra.attention_reason
            if action:
                lines.append(f"   Suggested action: {action}")
            if ra.cross_links:
                link_strs = [f"{l.category}: {l.title}" for l in ra.cross_links]
                lines.append(f"   Cross-links: {'; '.join(link_strs)}")
            lines.append("")
    else:
        lines.append("  No recommendations.")
        lines.append("")

    return "\n".join(lines)
