"""Recommendation engine for strategic next actions (spec §4).

Surfaces ranked, actionable recommendations for neglected and stalled goals
by aggregating from multiple state-summary sources:

1. ``assess_goal_health()`` → health state + dominant signal
2. ``GoalReview.suggested_next_step`` (via ``next_action`` service)
3. ``recommendations`` service → task-level ranked recommendations
4. ``attention`` items → dominant attention category + reason
5. cross-domain links → research artifacts, decisions, follow-ups

The engine is pure addition — no existing surfaces are changed (spec §83).
All signal computation is delegated to the existing ``assess_goal_health()``
and ``assess_goal_stall()``; this module only assembles their outputs into
actionable recommendations.
"""

import logging
from datetime import date, datetime

from janus.models.goal import Goal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.weekly_review import GoalReview
from janus.models.attention import AttentionItem
from janus.models.recommended_action import (
    CrossDomainLink,
    RecommendedAction,
    RemediationAction,
    TaskRecommendation,
)
from janus.services.goal_health import INACTIVITY_WINDOW_DAYS

logger = logging.getLogger(__name__)

# Number of days since a strategic action was surfaced after which a goal
# is considered "not recently attended to" (spec section 2).
STRATEGIC_ATTENTION_WINDOW_DAYS = 7

# ── Remediation rules (R1) ────────────────────────────────────────────────────
#
# Maps each dominant signal to a concrete, actionable remediation action.
# These rules are tied to the specific health states and signals defined in
# docs/design/goal_health_progress_signals_stalled_detection_spec.md §4.2.
#
# The key is the signal identifier. The value is a remediation action template
# that may reference ``{reason}`` (the signal's own reason string) so the
# remediation is specific to the goal's diagnosis.
#
# Priority: higher = more urgent. Used for ranking when multiple goals need
# remediation.
_REMEDIATION_RULES: dict[str, tuple[str, int]] = {
    # --- Stalled signals (health_state = stalled) ---
    # Goal deadline has passed with no open related tasks.
    "goal_overdue": (
        "Deadline has passed. Either resume work immediately by adding an "
        "open related task, or mark the goal as completed/inactive if it is "
        "no longer relevant.",
        100,
    ),
    # The deadline is today — urgent action needed.
    "goal_deadline_today": (
        "Deadline is today. Add or complete a related task now to meet the "
        "deadline, or defer the deadline if it is no longer realistic.",
        90,
    ),
    # A milestone deadline has passed without completion.
    "milestone_slipped": (
        "Milestone deadline was missed. Re-scope the milestone, add the "
        "missing tasks, or reschedule the milestone deadline.",
        80,
    ),
    # All related tasks are completed but no next step is defined.
    "goal_stalled": (
        "All linked tasks are completed. Define the next milestone, add a "
        "new action, or mark the goal as complete.",
        40,
    ),
    # No recent activity — the goal may have been abandoned in practice.
    "no_recent_activity": (
        "No activity for an extended period. Either schedule a check-in, "
        "add a small starter task to make progress concrete, or mark the "
        "goal as inactive if paused intentionally.",
        35,
    ),

    # --- Watch signals (health_state = watch) ---
    # Progress is below the slow-progress threshold over the lookback window.
    "progress_slow": (
        "Progress is slow over the lookback window. Review the related "
        "tasks and break the next one into smaller steps, or record a "
        "metric update to confirm forward momentum.",
        40,
    ),
    # One or more measurement requirements are overdue.
    "measurement_due": (
        "Measurement requirements are overdue. Collect the missing metric "
        "data now, or review and adjust the measurement schedule.",
        45,
    ),
    # Deadline is approaching within the soon-window.
    "goal_deadline_soon": (
        "Deadline is approaching ({reason}). Ensure the next milestone or "
        "task is in progress, or reschedule the deadline if needed.",
        60,
    ),
    # Milestone deadline is approaching within the soon-window.
    "milestone_deadline_soon": (
        "Milestone deadline is approaching ({reason}). Confirm the "
        "milestone is on track — add or start the next task if needed.",
        55,
    ),
    # Goal is active but all tasks are done with no future plan (low severity).
    "goal_inactive": (
        "No upcoming milestones or deadlines. Add a future milestone or "
        "next action to define forward momentum.",
        30,
    ),
}

# Priority override per health state for signals not in the rule table.
# Default priority when a signal maps to a state but has no explicit rule.
_HEALTH_STATE_DEFAULT_PRIORITY = {
    "stalled": 40,
    "watch": 30,
    "healthy": 10,
    "completed": 0,
}


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
    """Return True if the goal has an upcoming future milestone/deadline.

    Per spec §26: a goal with no upcoming milestones/deadlines is inert even
    if it has open related tasks not yet actionable toward a deadline.
    """
    goal_dl = _parse_deadline(goal.deadline)
    if goal_dl is not None and goal_dl > today:
        return True
    from janus.domain.planning import milestone_objs as _milestone_objs
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
    """Collect all cross-domain links for the given goal titles (spec §4, §82).

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


def _assessment_by_goal(
    assessments: list[GoalHealthAssessment],
) -> dict[str, GoalHealthAssessment]:
    """Index assessments by goal title."""
    return {a.goal_title: a for a in assessments}


def _review_by_goal(
    goal_reviews: list[GoalReview],
) -> dict[str, GoalReview]:
    """Index GoalReview objects by goal title."""
    return {gr.goal.title: gr for gr in goal_reviews}


def _attention_by_goal(
    attention_items: list[AttentionItem],
) -> dict[str, str]:
    """Index attention items by title, returning the reason per goal."""
    return {item.title: item.reason for item in attention_items}


def _task_recommendations_by_goal(
    recommendations,
) -> dict[str, list[TaskRecommendation]]:
    """Index task-level recommendations by goal title.

    ``recommendations`` may be a list of ``Recommendation`` objects from
    ``services/recommendations.py`` (which has ``goal_title`` and ``kind``).
    Only ``task``-kind recommendations are included (spec §4 source 3 —
    task-level recommendations).
    """
    result: dict[str, list[TaskRecommendation]] = {}
    if not recommendations:
        return result
    for rec in recommendations:
        if getattr(rec, "kind", None) != "task":
            continue
        gt = getattr(rec, "goal_title", "")
        if not gt:
            continue
        result.setdefault(gt, []).append(TaskRecommendation(
            title=rec.title,
            score=getattr(rec, "score", 0),
            reason=getattr(rec, "reason", ""),
            due_date=getattr(rec, "due_date", None),
            priority=getattr(rec, "priority", None),
        ))
    # Sort each goal's task recommendations by score descending.
    for gt in result:
        result[gt].sort(key=lambda t: t.score, reverse=True)
    return result


def derive_remediation_action(
    assessment: GoalHealthAssessment,
    goal: Goal | None = None,
    today: date | None = None,
) -> RemediationAction | None:
    """Derive a concrete, actionable remediation step for a goal from its health signals.

    Consumes an enriched ``GoalHealthAssessment`` (produced by
    ``assess_goal_health()``) and maps the goal's health state and dominant
    signal to a specific remediation action via the rule table (R1).

    The remediation is tied to the specific diagnosed health issue — not a
    generic suggestion — so it is directly actionable and structured for
    downstream consumption (e.g. the weekly review integration populates
    ``GoalReview.remediation_action`` from this).

    Args:
        assessment: The pre-computed health assessment for the goal.
        goal: Optional ``Goal`` object. If provided, its title is used in the
            remediation action (preferred over the assessment's ``goal_title``
            for display consistency).
        today: Current date for context. Defaults to today.

    Returns:
        A ``RemediationAction`` with a concrete, specific recommendation, or
        ``None`` if the goal is healthy (no remediation needed).
    """
    if today is None:
        today = date.today()

    health_state = assessment.health_state

    # Healthy goals need no remediation (spec §4.18.2).
    if health_state == "healthy":
        return None

    goal_title = goal.title if goal is not None else assessment.goal_title

    # Determine the dominant signal to key off of.
    dominant = assessment.dominant_signal
    signal_key = dominant.signal if dominant else ""

    # Fallback: if there is no dominant signal but the goal is unhealthy,
    # use the health state as the key for a generic remediation.
    if not signal_key:
        signal_key = health_state

    rule = _REMEDIATION_RULES.get(signal_key)
    if rule is not None:
        action_text, priority = rule
        # Substitute the signal reason if the template references {reason}.
        reason = dominant.reason if dominant else ""
        if "{reason}" in action_text and reason:
            action_text = action_text.format(reason=reason)
        elif "{reason}" in action_text:
            action_text = action_text.replace("{reason}", "see goal health report")
    else:
        # No specific rule for this signal — use the health state default.
        if health_state == "stalled":
            action_text = (
                "Goal is stalled. Review related tasks and milestones to "
                "restart progress, or mark as inactive if abandoned."
            )
        elif health_state == "watch":
            action_text = (
                "Goal is at risk. Monitor closely and add an action to "
                "improve momentum."
            )
        else:
            action_text = "Review goal and take corrective action."
        priority = _HEALTH_STATE_DEFAULT_PRIORITY.get(health_state, 20)

    return RemediationAction(
        goal_title=goal_title,
        health_state=health_state,
        signal=signal_key,
        action=action_text,
        priority=priority,
    )


def derive_remediation_for_reviews(
    assessments: list[GoalHealthAssessment],
    goals: list[Goal],
    today: date | None = None,
) -> dict[str, RemediationAction | None]:
    """Derive remediation actions for all goals, keyed by goal title.

    Convenience wrapper for ``derive_remediation_action`` that processes a
    list of assessments and goals (as used by the weekly review integration).

    Args:
        assessments: Pre-computed health assessments.
        goals: The full Goal list (for title lookups and context).
        today: Current date. Defaults to today.

    Returns:
        Dict mapping goal title to ``RemediationAction`` (or ``None`` if
        healthy). Every active goal in ``assessments`` gets an entry.
    """
    if today is None:
        today = date.today()

    goal_by_title = {g.title: g for g in goals}
    result: dict[str, RemediationAction | None] = {}
    for a in assessments:
        goal = goal_by_title.get(a.goal_title)
        result[a.goal_title] = derive_remediation_action(a, goal, today)
    return result


# ── Neglected-goal identification (spec §2, §26) ─────────────────────────────

def identify_neglected_goals(
    assessments: list[GoalHealthAssessment],
    goals: list[Goal],
    open_task_titles: set[str],
    today: date,
) -> list[GoalHealthAssessment]:
    """Identify neglected goals — at-risk goals with insufficient attention.

    A goal is neglected when (spec §26):
    - ``health_state`` is ``watch`` or ``stalled`` (!= ``healthy``), AND
    - at least one of:
      - ``days_since_last_activity`` > ``inactivity_window_days`` (default 30)
      - ``measurement_overdue_count`` > 0
      - no open related tasks AND no upcoming milestone/deadline

    Inactive and completed goals are excluded (spec §26).
    """
    neglected: list[GoalHealthAssessment] = []
    for a in assessments:
        if a.health_state not in ("watch", "stalled"):
            continue
        goal = next((g for g in goals if g.title == a.goal_title), None)
        if goal is None:
            continue
        if goal.status in ("inactive", "completed"):
            continue

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
            neglected.append(a)
    return neglected


# ── Public API ────────────────────────────────────────────────────────────────

def create_recommended_actions(
    assessments: list[GoalHealthAssessment],
    goals: list[Goal],
    goal_reviews: list[GoalReview] | None = None,
    attention_items: list[AttentionItem] | None = None,
    recommendations=None,
    cross_links: list[CrossDomainLink] | None = None,
    open_task_titles: set[str] | None = None,
    today: date | None = None,
    now: datetime | None = None,
) -> list[RecommendedAction]:
    """Create ranked recommended next actions for neglected and stalled goals.

    Implements spec §4: each strategic summary includes a ranked recommendation
    list, one per neglected/stalled goal, computed from:
    - ``assess_goal_health()`` → dominant attention category + reason
    - ``GoalReview.suggested_next_step`` (reuse existing computation)
    - ``recommendations`` service → task-level recommendations
    - ``next_action`` service → sequencing (already in suggested_next_step)
    - cross-domain links (research artifacts, decisions, follow-ups)

    Args:
        assessments: Pre-computed goal health assessments (from
            ``assess_goal_health()``). Must cover the active goals.
        goals: The full Goal list (used for neglected-goal threshold logic).
        goal_reviews: Pre-computed weekly reviews (for ``suggested_next_step``).
        attention_items: Pre-computed attention items (for dominant attention
            category + reason).
        recommendations: Pre-computed task recommendations from
            ``recommend_tasks()`` / ``recommend_next_actions()``.
        cross_links: Pre-collected cross-domain links for the relevant goals.
        open_task_titles: Set of open task titles (for neglected-goal logic).
        today: Current date for deadline calculations. Defaults to today.
        now: Current datetime for ``generated_at``. Defaults to now.

    Returns:
        Ranked list of ``RecommendedAction``, one per neglected/stalled goal,
        sorted by: stalled (score desc) > watch (score desc) >
        ``days_since_last_activity`` desc, then goal title (spec §61).

    Design §4 spec format per item:
        {goal_title} [{health_state}, score={dominant_signal_score}]
          Reason: {dominant_signal_reason}
          Progress: {current_progress}% (delta {progress_delta}% over 14d)
          Activity: {days_since_last_activity}d since last metric/task
          Measurements overdue: {measurement_overdue_count}
          Suggested action: {suggested_next_step or attention_item.reason}
          Cross-links: {research_artifact, decision, follow_up}
    """
    if today is None:
        today = date.today()
    if now is None:
        now = datetime.now().astimezone()
    if goal_reviews is None:
        goal_reviews = []
    if attention_items is None:
        attention_items = []
    if cross_links is None:
        cross_links = []
    if open_task_titles is None:
        open_task_titles = set()

    # Index supporting data by goal title for O(1) lookup.
    review_by_goal = _review_by_goal(goal_reviews)
    attention_by_title = _attention_by_goal(attention_items)
    task_recs_by_goal = _task_recommendations_by_goal(recommendations)

    # Determine the set of goals to produce recommendations for:
    # stalled goals (health_state == stalled) are always included;
    # watch goals are included only if they pass the neglected threshold.
    stalled_titles = {
        a.goal_title for a in assessments if a.health_state == "stalled"
    }
    neglected = identify_neglected_goals(
        assessments, goals, open_task_titles, today,
    )
    neglected_titles = {n.goal_title for n in neglected}
    target_titles = stalled_titles | neglected_titles

    actions: list[RecommendedAction] = []
    for a in assessments:
        if a.goal_title not in target_titles:
            continue
        dom = a.dominant_signal
        gr = review_by_goal.get(a.goal_title)
        suggested = gr.suggested_next_step if gr and gr.suggested_next_step else None
        attention_reason = attention_by_title.get(a.goal_title)
        goal_links = _links_for_goal(a.goal_title, cross_links)
        task_recs = task_recs_by_goal.get(a.goal_title, [])

        # Derive concrete remediation action tied to the health state/signals.
        g = next((gg for gg in goals if gg.title == a.goal_title), None)
        remediation = derive_remediation_action(a, goal=g, today=today)
        remediation_action = remediation.action if remediation else None

        actions.append(RecommendedAction(
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
            remediation_action=remediation_action,
            attention_reason=attention_reason,
            task_recommendations=task_recs,
            cross_links=goal_links,
            generated_at=now,
        ))

    # Rank: stalled by dominant score desc, then watch, then by
    # days_since_last_activity desc (spec §61).
    actions.sort(
        key=lambda r: (
            0 if r.health_state == "stalled" else 1,
            -r.dominant_signal_score,
            -(r.days_since_last_activity or 0),
            r.goal_title,
        )
    )
    return actions


def render_recommended_actions(
    actions: list[RecommendedAction],
) -> str:
    """Render recommended actions as markdown (spec §4.10, §73).

    Format per item:
        {goal_title} [{health_state}, score={dominant_signal_score}]
          Reason: {dominant_signal_reason}
          Progress: {current_progress}% (delta {progress_delta}% over 14d)
          Activity: {days_since_last_activity}d since last metric/task
          Measurements overdue: {measurement_overdue_count}
          Suggested action: {suggested_next_step or attention_item.reason}
          Cross-links: {research_artifact_title, decision_title, follow_up_title}
    """
    lines: list[str] = []
    if not actions:
        lines.append("  No recommendations.")
        return "\n".join(lines)

    for i, ra in enumerate(actions, 1):
        lines.append(
            f"{i}. {ra.goal_title} [{ra.health_state}, "
            f"score={ra.dominant_signal_score}]"
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
                f"   Activity: {ra.days_since_last_activity}d since last "
                f"metric/task"
            )
        else:
            lines.append("   Activity: no data")
        lines.append(f"   Measurements overdue: {ra.measurement_overdue_count}")
        action = ra.suggested_action
        if action:
            lines.append(f"   Suggested action: {action}")
        if ra.remediation_action:
            lines.append(f"   Remediation: {ra.remediation_action}")
        if ra.task_recommendations:
            for tr in ra.task_recommendations:
                lines.append(f"   Task: {tr.title} (score={tr.score})")
        if ra.cross_links:
            link_strs = [f"{l.category}: {l.title}" for l in ra.cross_links]
            lines.append(f"   Cross-links: {'; '.join(link_strs)}")
        lines.append("")
    return "\n".join(lines)
