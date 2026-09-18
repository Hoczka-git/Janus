"""Strategic summary service for Janus.

Aggregates goal-health assessments, weekly-review data, attention items,
task recommendations, and cross-domain knowledge links into a single
``StrategicSummary`` that identifies neglected goals and stalled work.

Also provides strategic-state snapshot construction and meaningful-change
detection as specified in ``docs/design/strategic_summary_spec.md`` §1.

A *meaningful change* is any event that alters the strategic picture.
This module provides :func:`detect_meaningful_changes`, which compares a
previous ``StrategicStateSnapshot`` against a current one and returns the
list of ``MeaningfulChange`` events that occurred.

The strategic summary service reuses existing signal computation and
recommendation services rather than duplicating their domain logic.
"""

import logging
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from janus.models.goal import Goal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.weekly_review import GoalReview
from janus.models.strategic_summary import (
    CHANGE_CROSS_DOMAIN_LINK,
    CHANGE_DOMINANT_SIGNAL_SCORE,
    CHANGE_GOAL_STATUS,
    CHANGE_HEALTH_STATE,
    CHANGE_MEASUREMENT_DUE,
    CHANGE_MILESTONE_STATUS,
    CHANGE_PROGRESS_DELTA,
    CHANGE_STALLED_SIGNAL,
    _STALLED_SIGNALS,
    CrossDomainLink,
    GoalStateSnapshot,
    MeaningfulChange,
    NeglectedGoal,
    PortfolioHealthCounts,
    RecommendedAction,
    StalledGoal,
    StrategicStateSnapshot,
    StrategicSummary,
)
from janus.services.goal_health import (
    INACTIVITY_WINDOW_DAYS,
    PROGRESS_LOOKBACK_DAYS,
    PROGRESS_SLOW_THRESHOLD,
    assess_goal_health,
)
from janus.services.recommended_actions import (
    create_recommended_actions,
    identify_neglected_goals,
)
from janus.services.weekly_review import create_weekly_review

logger = logging.getLogger(__name__)

# Project root for data-file access.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Dominant-signal score delta that counts as meaningful.
_DOMINANT_SIGNAL_SCORE_THRESHOLD = 15

# Number of days after which a strategic action is considered stale.
STRATEGIC_ATTENTION_WINDOW_DAYS = 7


# ── Snapshot helpers ──────────────────────────────────────────────────────────


def _milestone_status_snapshot(goal: Goal) -> dict[str, str]:
    """Extract a {milestone_title: status} mapping from a Goal."""

    result: dict[str, str] = {}

    for milestone in goal.milestones or []:
        title = (
            milestone.get("title")
            if isinstance(milestone, dict)
            else getattr(milestone, "title", None)
        )

        if not title:
            continue

        status = (
            milestone.get("status", "open")
            if isinstance(milestone, dict)
            else getattr(milestone, "status", "open")
        )

        result[title] = status

    return result


def _goal_cross_domain_links(goal: Goal) -> tuple[list[str], list[str], list[str]]:
    """Extract cross-domain identifiers from a Goal."""

    research = sorted(goal.research_artifact_titles or [])
    decisions = sorted(goal.decision_numbers or [])
    followups = sorted(goal.followup_ids or [])

    return research, decisions, followups


def build_goal_state_snapshot(
    goal: Goal,
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    metric_snapshots: list[MetricSnapshot] | None = None,
    completed_task_dates: dict[str, date] | None = None,
) -> GoalStateSnapshot:
    """Construct a ``GoalStateSnapshot`` from a Goal and its health assessment.

    Health computation is delegated to ``assess_goal_health()``.
    """

    assessment = assess_goal_health(
        goal,
        today,
        open_task_titles=open_task_titles,
        all_task_titles=all_task_titles,
        metric_snapshots=metric_snapshots,
        completed_task_dates=completed_task_dates,
    )

    research, decisions, followups = _goal_cross_domain_links(goal)

    if assessment is None:
        return GoalStateSnapshot(
            goal_title=goal.title,
            health_state=None,
            dominant_signal=None,
            dominant_signal_score=0,
            progress=None,
            progress_delta=None,
            measurement_overdue_count=0,
            signals=frozenset(),
            goal_status=goal.status,
            milestone_statuses=_milestone_status_snapshot(goal),
            linked_research_artifacts=research,
            linked_decision_numbers=decisions,
            linked_followup_ids=followups,
        )

    signals = frozenset(
        signal.signal
        for signal in assessment.signals
    )

    dominant = assessment.dominant_signal

    return GoalStateSnapshot(
        goal_title=goal.title,
        health_state=assessment.health_state,
        dominant_signal=(
            dominant.signal
            if dominant is not None
            else None
        ),
        dominant_signal_score=(
            dominant.score
            if dominant is not None
            else 0
        ),
        progress=assessment.progress,
        progress_delta=assessment.progress_delta,
        measurement_overdue_count=(
            assessment.measurement_overdue_count
            if assessment.measurement_overdue_count is not None
            else 0
        ),
        signals=signals,
        goal_status=goal.status,
        milestone_statuses=_milestone_status_snapshot(goal),
        linked_research_artifacts=research,
        linked_decision_numbers=decisions,
        linked_followup_ids=followups,
    )


def build_strategic_snapshot(
    goals: list[Goal],
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    completed_task_dates: dict[str, date] | None = None,
) -> StrategicStateSnapshot:
    """Build a full ``StrategicStateSnapshot`` for all goals."""

    from janus.integrations.metric_history import get_metric_snapshots

    goal_snapshots: list[GoalStateSnapshot] = []

    for goal in goals:
        metric_snapshots = (
            get_metric_snapshots(goal.title)
            if (
                goal.metric_name
                or goal.inactivity_window_days is not None
            )
            else []
        )

        goal_snapshots.append(
            build_goal_state_snapshot(
                goal=goal,
                today=today,
                open_task_titles=open_task_titles,
                all_task_titles=all_task_titles,
                metric_snapshots=metric_snapshots,
                completed_task_dates=completed_task_dates,
            )
        )

    return StrategicStateSnapshot(
        generated_at=datetime.now().astimezone(),
        goals=goal_snapshots,
    )


# ── Meaningful change detection ──────────────────────────────────────────────


def detect_meaningful_changes(
    previous: StrategicStateSnapshot,
    current: StrategicStateSnapshot,
) -> list[MeaningfulChange]:
    """Detect meaningful changes between two strategic state snapshots."""

    now = datetime.now().astimezone()
    changes: list[MeaningfulChange] = []

    previous_by_title = {
        goal.goal_title: goal
        for goal in previous.goals
    }

    current_titles = {
        goal.goal_title
        for goal in current.goals
    }

    for current_goal in current.goals:
        previous_goal = previous_by_title.get(
            current_goal.goal_title
        )

        if previous_goal is None:
            _detect_new_goal_changes(
                current_goal,
                now,
                changes,
            )
            continue

        _detect_goal_changes(
            previous_goal,
            current_goal,
            now,
            changes,
        )

    for previous_goal in previous.goals:
        if previous_goal.goal_title not in current_titles:
            changes.append(
                MeaningfulChange(
                    change_type=CHANGE_GOAL_STATUS,
                    goal_title=previous_goal.goal_title,
                    description=(
                        f"Goal '{previous_goal.goal_title}' was removed "
                        "from the strategic portfolio"
                    ),
                    severity=10,
                    details={
                        "previous_status": previous_goal.goal_status,
                        "current_status": "removed",
                    },
                    timestamp=now,
                )
            )

    changes.sort(
        key=lambda change: (
            -change.severity,
            change.goal_title,
        )
    )

    return changes


def _detect_goal_changes(
    previous: GoalStateSnapshot,
    current: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect all meaningful changes for a single goal."""

    # §1.1 — health-state transition.
    if previous.health_state != current.health_state:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_HEALTH_STATE,
                goal_title=current.goal_title,
                description=(
                    f"Goal '{current.goal_title}' health state changed: "
                    f"{previous.health_state or 'none'} → "
                    f"{current.health_state or 'none'}"
                ),
                severity=_health_severity(
                    current.health_state
                ),
                details={
                    "previous_health_state": previous.health_state,
                    "current_health_state": current.health_state,
                },
                timestamp=now,
            )
        )

    # §1.1 — dominant signal score change.
    score_delta = (
        current.dominant_signal_score
        - previous.dominant_signal_score
    )

    previous_signal = previous.dominant_signal
    current_signal = current.dominant_signal

    if abs(score_delta) >= _DOMINANT_SIGNAL_SCORE_THRESHOLD:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_DOMINANT_SIGNAL_SCORE,
                goal_title=current.goal_title,
                description=(
                    f"Goal '{current.goal_title}' dominant signal score "
                    f"changed by {score_delta:+d} points "
                    f"({previous_signal or 'none'}:"
                    f"{previous.dominant_signal_score} → "
                    f"{current_signal or 'none'}:"
                    f"{current.dominant_signal_score})"
                ),
                severity=5 + abs(score_delta) // 10,
                details={
                    "previous_signal": previous_signal,
                    "current_signal": current_signal,
                    "previous_score": previous.dominant_signal_score,
                    "current_score": current.dominant_signal_score,
                    "delta": score_delta,
                },
                timestamp=now,
            )
        )
    elif (
        previous_signal != current_signal
        and previous_signal is not None
        and current_signal is not None
    ):
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_DOMINANT_SIGNAL_SCORE,
                goal_title=current.goal_title,
                description=(
                    f"Goal '{current.goal_title}' dominant signal changed: "
                    f"{previous_signal} → {current_signal}"
                ),
                severity=5,
                details={
                    "previous_signal": previous_signal,
                    "current_signal": current_signal,
                    "previous_score": previous.dominant_signal_score,
                    "current_score": current.dominant_signal_score,
                    "delta": score_delta,
                },
                timestamp=now,
            )
        )

    _detect_progress_delta_change(
        previous,
        current,
        now,
        changes,
    )

    _detect_stalled_signal_change(
        previous,
        current,
        now,
        changes,
    )

    _detect_measurement_change(
        previous,
        current,
        now,
        changes,
    )

    _detect_cross_domain_link_change(
        previous,
        current,
        now,
        changes,
    )

    # §1.6 — goal status transition.
    if previous.goal_status != current.goal_status:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_GOAL_STATUS,
                goal_title=current.goal_title,
                description=(
                    f"Goal '{current.goal_title}' status changed: "
                    f"{previous.goal_status} → "
                    f"{current.goal_status}"
                ),
                severity=_goal_status_severity(
                    current.goal_status
                ),
                details={
                    "previous_status": previous.goal_status,
                    "current_status": current.goal_status,
                },
                timestamp=now,
            )
        )

    # §1.6 — milestone status changes.
    _detect_milestone_status_change(
        previous,
        current,
        now,
        changes,
    )


def _detect_new_goal_changes(
    current: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect meaningful state for a newly active goal."""

    if current.goal_status != "active":
        return

    if (
        current.health_state is None
        or current.health_state == "healthy"
    ) and not current.signals:
        return

    changes.append(
        MeaningfulChange(
            change_type=CHANGE_GOAL_STATUS,
            goal_title=current.goal_title,
            description=(
                f"Goal '{current.goal_title}' is newly active "
                f"(health: {current.health_state or 'unknown'}, "
                f"signals: {sorted(current.signals) or 'none'})"
            ),
            severity=_health_severity(
                current.health_state
            ) + 5,
            details={
                "previous_status": "new",
                "current_status": current.goal_status,
                "current_health_state": current.health_state,
                "current_signals": sorted(current.signals),
            },
            timestamp=now,
        )
    )


def _detect_progress_delta_change(
    previous: GoalStateSnapshot,
    current: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect progress-delta threshold crossing."""

    previous_delta = previous.progress_delta
    current_delta = current.progress_delta

    if previous_delta is None or current_delta is None:
        if (
            current_delta is not None
            and abs(current_delta) >= PROGRESS_SLOW_THRESHOLD
        ):
            changes.append(
                MeaningfulChange(
                    change_type=CHANGE_PROGRESS_DELTA,
                    goal_title=current.goal_title,
                    description=(
                        f"Goal '{current.goal_title}' progress delta now "
                        f"measurable: {current_delta:+.1f}% over "
                        f"{PROGRESS_LOOKBACK_DAYS} days "
                        f"(threshold: "
                        f"{PROGRESS_SLOW_THRESHOLD:.0f}%)"
                    ),
                    severity=3,
                    details={
                        "previous_delta": previous_delta,
                        "current_delta": current_delta,
                        "threshold": PROGRESS_SLOW_THRESHOLD,
                    },
                    timestamp=now,
                )
            )
        return

    previous_slow = (
        previous_delta < PROGRESS_SLOW_THRESHOLD
    )
    current_slow = (
        current_delta < PROGRESS_SLOW_THRESHOLD
    )

    if previous_slow != current_slow:
        direction = (
            "now exceeds"
            if not current_slow
            else "now below"
        )

        changes.append(
            MeaningfulChange(
                change_type=CHANGE_PROGRESS_DELTA,
                goal_title=current.goal_title,
                description=(
                    f"Goal '{current.goal_title}' progress delta "
                    f"{direction} the slow-progress threshold: "
                    f"{current_delta:+.1f}% "
                    f"(was {previous_delta:+.1f}%, "
                    f"threshold: {PROGRESS_SLOW_THRESHOLD:.0f}%)"
                ),
                severity=3,
                details={
                    "previous_delta": previous_delta,
                    "current_delta": current_delta,
                    "threshold": PROGRESS_SLOW_THRESHOLD,
                },
                timestamp=now,
            )
        )


def _detect_stalled_signal_change(
    previous: GoalStateSnapshot,
    current: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect stalled-work signal activation or clearing."""

    previous_stalled = (
        previous.signals & _STALLED_SIGNALS
    )
    current_stalled = (
        current.signals & _STALLED_SIGNALS
    )

    activated = current_stalled - previous_stalled
    cleared = previous_stalled - current_stalled

    for signal in sorted(activated):
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_STALLED_SIGNAL,
                goal_title=current.goal_title,
                description=(
                    f"Goal '{current.goal_title}' stalled-work signal "
                    f"activated: {signal}"
                ),
                severity=8,
                details={
                    "signal": signal,
                    "action": "activated",
                    "previous_signals": sorted(previous_stalled),
                    "current_signals": sorted(current_stalled),
                },
                timestamp=now,
            )
        )

    for signal in sorted(cleared):
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_STALLED_SIGNAL,
                goal_title=current.goal_title,
                description=(
                    f"Goal '{current.goal_title}' stalled-work signal "
                    f"cleared: {signal}"
                ),
                severity=4,
                details={
                    "signal": signal,
                    "action": "cleared",
                    "previous_signals": sorted(previous_stalled),
                    "current_signals": sorted(current_stalled),
                },
                timestamp=now,
            )
        )


def _detect_measurement_change(
    previous: GoalStateSnapshot,
    current: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect measurement requirement overdue/satisfied transitions."""

    previous_count = previous.measurement_overdue_count
    current_count = current.measurement_overdue_count

    if previous_count == 0 and current_count > 0:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_MEASUREMENT_DUE,
                goal_title=current.goal_title,
                description=(
                    f"Goal '{current.goal_title}' measurement "
                    f"requirements became overdue "
                    f"({current_count} now due)"
                ),
                severity=6,
                details={
                    "previous_overdue_count": previous_count,
                    "current_overdue_count": current_count,
                    "action": "fired",
                },
                timestamp=now,
            )
        )

    elif previous_count > 0 and current_count == 0:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_MEASUREMENT_DUE,
                goal_title=current.goal_title,
                description=(
                    f"Goal '{current.goal_title}' measurement "
                    f"requirements satisfied "
                    f"(were {previous_count} overdue, now none)"
                ),
                severity=4,
                details={
                    "previous_overdue_count": previous_count,
                    "current_overdue_count": current_count,
                    "action": "satisfied",
                },
                timestamp=now,
            )
        )


def _detect_cross_domain_link_change(
    previous: GoalStateSnapshot,
    current: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect cross-domain link additions/removals."""

    _detect_link_set_change(
        previous.linked_research_artifacts,
        current.linked_research_artifacts,
        current.goal_title,
        "research_artifact",
        now,
        changes,
    )

    _detect_link_set_change(
        previous.linked_decision_numbers,
        current.linked_decision_numbers,
        current.goal_title,
        "decision",
        now,
        changes,
    )

    _detect_link_set_change(
        previous.linked_followup_ids,
        current.linked_followup_ids,
        current.goal_title,
        "followup",
        now,
        changes,
    )


def _detect_link_set_change(
    previous_links: list[str],
    current_links: list[str],
    goal_title: str,
    link_type: str,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect additions/removals for one cross-domain link type."""

    previous_set = set(previous_links)
    current_set = set(current_links)

    added = current_set - previous_set
    removed = previous_set - current_set

    if not added and not removed:
        return

    details = {
        "link_type": link_type,
        "added": sorted(added),
        "removed": sorted(removed),
    }

    if added:
        description = (
            f"Goal '{goal_title}' gained new cross-domain links: "
            f"{link_type} added — {', '.join(sorted(added))}"
        )
    else:
        description = (
            f"Goal '{goal_title}' lost cross-domain links: "
            f"{link_type} removed — {', '.join(sorted(removed))}"
        )

    changes.append(
        MeaningfulChange(
            change_type=CHANGE_CROSS_DOMAIN_LINK,
            goal_title=goal_title,
            description=description,
            severity=3,
            details=details,
            timestamp=now,
        )
    )


def _detect_milestone_status_change(
    previous: GoalStateSnapshot,
    current: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect milestone status changes."""

    all_milestones = (
        set(previous.milestone_statuses)
        | set(current.milestone_statuses)
    )

    for milestone_title in sorted(all_milestones):
        previous_status = previous.milestone_statuses.get(
            milestone_title
        )
        current_status = current.milestone_statuses.get(
            milestone_title
        )

        if previous_status == current_status:
            continue

        changes.append(
            MeaningfulChange(
                change_type=CHANGE_MILESTONE_STATUS,
                goal_title=current.goal_title,
                description=(
                    f"Goal '{current.goal_title}' milestone "
                    f"'{milestone_title}' status changed: "
                    f"{previous_status or 'none'} → "
                    f"{current_status or 'removed'}"
                ),
                severity=5,
                details={
                    "milestone_title": milestone_title,
                    "previous_status": previous_status,
                    "current_status": (
                        current_status
                        if current_status is not None
                        else "removed"
                    ),
                },
                timestamp=now,
            )
        )


# ── Severity helpers ─────────────────────────────────────────────────────────


_HEALTH_SEVERITY = {
    "stalled": 20,
    "watch": 15,
    "healthy": 5,
    "completed": 8,
    None: 0,
}


def _health_severity(
    health_state: str | None,
) -> int:
    """Map a health state to a base severity score."""

    return _HEALTH_SEVERITY.get(
        health_state,
        5,
    )


_GOAL_STATUS_SEVERITY = {
    "completed": 15,
    "inactive": 10,
    "active": 5,
}


def _goal_status_severity(
    status: str,
) -> int:
    """Map a goal status to a severity score."""

    return _GOAL_STATUS_SEVERITY.get(
        status,
        5,
    )


# ── Strategic summary helpers ────────────────────────────────────────────────


def _parse_deadline(raw) -> date | None:
    """Parse an ISO date string into a date."""

    if raw is None:
        return None

    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _has_upcoming_milestone_or_deadline(
    goal: Goal,
    today: date,
) -> bool:
    """Return True if the goal has an upcoming milestone or deadline."""

    goal_deadline = _parse_deadline(
        goal.deadline
    )

    if (
        goal_deadline is not None
        and goal_deadline > today
    ):
        return True

    from janus.services.attention import _milestone_objs

    for milestone in _milestone_objs(goal):
        if milestone.status in (
            "completed",
            "skipped",
        ):
            continue

        milestone_deadline = _parse_deadline(
            milestone.deadline
        )

        if (
            milestone_deadline is not None
            and milestone_deadline > today
        ):
            return True

        if (
            milestone.status in (
                "open",
                "in_progress",
            )
            and milestone_deadline is None
        ):
            return True

    return False


def _collect_cross_domain_links(
    goal_titles: set[str],
    research_artifacts=None,
    decisions=None,
    followups=None,
) -> list[CrossDomainLink]:
    """Collect cross-domain links for the given goals."""

    from janus.integrations.markdown_followups import load_followups
    from janus.services.decisions import load_decisions
    from janus.services.research_artifacts import load_all_artifacts

    if research_artifacts is None:
        research_artifacts = load_all_artifacts()

    if decisions is None:
        decisions = load_decisions()

    if followups is None:
        followups = load_followups()

    links: list[CrossDomainLink] = []
    seen: set[tuple[str, str, str]] = set()

    for artifact in research_artifacts:
        for goal_title in artifact.linked_goal_titles:
            if goal_title not in goal_titles:
                continue

            key = (
                goal_title,
                "research_artifact",
                artifact.title,
            )

            if key in seen:
                continue

            seen.add(key)
            links.append(
                CrossDomainLink(
                    goal_title=goal_title,
                    category="research_artifact",
                    title=artifact.title,
                )
            )

    for decision in decisions:
        for goal_title in decision.goal_titles:
            if goal_title not in goal_titles:
                continue

            key = (
                goal_title,
                "decision",
                decision.title,
            )

            if key in seen:
                continue

            seen.add(key)
            links.append(
                CrossDomainLink(
                    goal_title=goal_title,
                    category="decision",
                    title=decision.title,
                )
            )

    for followup in followups:
        goal_title = followup.linked_goal_title

        if (
            not goal_title
            or goal_title not in goal_titles
        ):
            continue

        key = (
            goal_title,
            "follow_up",
            followup.title,
        )

        if key in seen:
            continue

        seen.add(key)
        links.append(
            CrossDomainLink(
                goal_title=goal_title,
                category="follow_up",
                title=followup.title,
            )
        )

    return links


def _links_for_goal(
    goal_title: str,
    all_links: list[CrossDomainLink],
) -> list[CrossDomainLink]:
    """Return cross-domain links for one goal."""

    return [
        link
        for link in all_links
        if link.goal_title == goal_title
    ]


def _build_portfolio_counts(
    assessments: list[GoalHealthAssessment],
    goals: list[Goal],
) -> PortfolioHealthCounts:
    """Build portfolio health counts."""

    counts = PortfolioHealthCounts()

    counts.total_active = sum(
        1
        for goal in goals
        if goal.status == "active"
    )

    counts.completed = sum(
        1
        for goal in goals
        if goal.status == "completed"
    )

    counts.inactive = sum(
        1
        for goal in goals
        if goal.status == "inactive"
    )

    active_titles = {
        goal.title
        for goal in goals
        if goal.status == "active"
    }

    for assessment in assessments:
        if assessment.goal_title not in active_titles:
            continue

        if assessment.health_state == "healthy":
            counts.healthy += 1
        elif assessment.health_state == "watch":
            counts.watch += 1
        elif assessment.health_state == "stalled":
            counts.stalled += 1

    return counts


def _compute_portfolio_health_counts(
    goals: list[Goal],
    assessments: list[GoalHealthAssessment],
) -> PortfolioHealthCounts:
    """Compatibility wrapper for the original helper name."""

    return _build_portfolio_counts(
        assessments,
        goals,
    )


def _compute_assessments(
    goals: list[Goal],
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str] | None = None,
    completed_task_dates: dict[str, date] | None = None,
    metric_snapshots_by_goal: dict[str, list[MetricSnapshot]] | None = None,
) -> list[GoalHealthAssessment]:
    """Compute health assessments for all active goals."""

    if all_task_titles is None:
        all_task_titles = set()

    if not all_task_titles:
        try:
            from janus.integrations.markdown_tasks import load_tasks

            tasks = load_tasks()

            open_task_titles.update(
                task.title
                for task in tasks
            )

            all_task_titles.update(
                task.title
                for task in tasks
            )

            try:
                from janus.services.weekly_review import (
                    _read_completed_task_titles,
                )

                all_task_titles.update(
                    _read_completed_task_titles()
                )
            except FileNotFoundError:
                pass

        except FileNotFoundError:
            pass

    assessments: list[GoalHealthAssessment] = []

    for goal in goals:
        if goal.status != "active":
            continue

        metric_snapshots = None

        if metric_snapshots_by_goal is not None:
            metric_snapshots = metric_snapshots_by_goal.get(
                goal.title
            )

        assessment = assess_goal_health(
            goal,
            today,
            open_task_titles=open_task_titles,
            all_task_titles=all_task_titles,
            metric_snapshots=metric_snapshots,
            completed_task_dates=completed_task_dates,
        )

        if assessment is not None:
            assessments.append(assessment)

    return assessments


def _load_goal_reviews():
    """Load weekly reviews, returning [] when data is unavailable."""

    try:
        return create_weekly_review().goals
    except FileNotFoundError:
        return []


def _load_attention_items(
    goals,
    today,
    now,
    trace_id,
):
    """Load attention items."""

    try:
        from janus.integrations.markdown_tasks import load_tasks
        from janus.services.attention import get_attention_items

        return get_attention_items(
            events=[],
            tasks=load_tasks(trace_id=trace_id),
            goals=goals,
            today=today,
            now=now,
            trace_id=trace_id,
        )
    except FileNotFoundError:
        return []


def _load_task_recommendations(
    goals,
    today,
):
    """Load task-level recommendations."""

    try:
        from janus.integrations.markdown_tasks import load_tasks
        from janus.services.recommendations import recommend_tasks

        tasks = load_tasks()
        completed = set(
            _read_completed_task_titles()
        )

        return recommend_tasks(
            goals=goals,
            tasks=tasks,
            completed_task_titles=completed,
            today=today,
        )
    except FileNotFoundError:
        return []


# ── Public summary API ────────────────────────────────────────────────────────


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
    all_task_titles: set[str] | None = None,
    completed_task_dates: dict[str, date] | None = None,
    metric_snapshots_by_goal: dict[
        str,
        list[MetricSnapshot],
    ] | None = None,
    followups: list | None = None,
    research_artifacts: list | None = None,
    decisions: list | None = None,
    recommendations=None,
    portfolio_health_counts: PortfolioHealthCounts | None = None,
) -> StrategicSummary:
    """Create a structured strategic summary.

    The signature intentionally supports both the original summary-service
    API and the newer snapshot/change-detection API. Pre-computed values can
    be injected by callers and tests; otherwise existing Janus services are
    used to load and derive the required data.
    """

    if now is None:
        now = datetime.now().astimezone()

    if today is None:
        today = now.date()

    if goals is None:
        from janus.integrations.markdown_goals import load_goals

        goals = load_goals(
            trace_id=trace_id
        )

    if open_task_titles is None:
        open_task_titles = set()

    if all_task_titles is None:
        all_task_titles = set()

    # Load task state when necessary.
    if not open_task_titles or not all_task_titles:
        try:
            from janus.integrations.markdown_tasks import load_tasks

            tasks = load_tasks(
                trace_id=trace_id
            )

            open_task_titles.update(
                task.title
                for task in tasks
            )

            all_task_titles.update(
                task.title
                for task in tasks
            )

            try:
                completed = set(
                    _read_completed_task_titles()
                )
                all_task_titles.update(completed)
            except FileNotFoundError:
                pass

        except FileNotFoundError:
            pass

    # Health assessments.
    if assessments is None:
        assessments = _compute_assessments(
            goals=goals,
            today=today,
            open_task_titles=open_task_titles,
            all_task_titles=all_task_titles,
            completed_task_dates=completed_task_dates,
            metric_snapshots_by_goal=metric_snapshots_by_goal,
        )

    # Weekly reviews.
    if goal_reviews is None:
        goal_reviews = _load_goal_reviews()

    # Attention items.
    if attention_items is None:
        attention_items = _load_attention_items(
            goals,
            today,
            now,
            trace_id,
        )

    # Task recommendations.
    if recommendations is not None:
        task_recommendations = recommendations

    if task_recommendations is None:
        task_recommendations = _load_task_recommendations(
            goals,
            today,
        )

    # Cross-domain links.
    if cross_links is None:
        cross_links = _collect_cross_domain_links(
            {goal.title for goal in goals},
            research_artifacts=research_artifacts,
            decisions=decisions,
            followups=followups,
        )

    # Portfolio health.
    if portfolio_health_counts is None:
        portfolio_health_counts = _compute_portfolio_health_counts(
            goals,
            assessments,
        )

    # Restrict health-derived sections to active goals.
    active_titles = {
        goal.title
        for goal in goals
        if goal.status == "active"
    }

    active_assessments = [
        assessment
        for assessment in assessments
        if assessment.goal_title in active_titles
    ]

    # Stalled goals.
    stalled_assessments = [
        assessment
        for assessment in active_assessments
        if assessment.health_state == "stalled"
    ]

    stalled_assessments.sort(
        key=lambda assessment: (
            -(
                assessment.dominant_signal.score
                if assessment.dominant_signal
                else 0
            ),
            assessment.goal_title,
        )
    )

    stalled_goals = [
        StalledGoal(
            goal_title=assessment.goal_title,
            health_state=assessment.health_state,
            dominant_signal=(
                assessment.dominant_signal.signal
                if assessment.dominant_signal
                else ""
            ),
            dominant_signal_score=(
                assessment.dominant_signal.score
                if assessment.dominant_signal
                else 0
            ),
            dominant_signal_reason=(
                assessment.dominant_signal.reason
                if assessment.dominant_signal
                else ""
            ),
            progress=assessment.progress,
            progress_delta=assessment.progress_delta,
            days_since_last_activity=(
                assessment.days_since_last_activity
            ),
            measurement_overdue_count=(
                assessment.measurement_overdue_count
            ),
        )
        for assessment in stalled_assessments
    ]

    # Neglected goals.
    neglected_assessments = identify_neglected_goals(
        active_assessments,
        goals,
        open_task_titles,
        today,
    )

    neglected_goals = [
        NeglectedGoal(
            goal_title=assessment.goal_title,
            health_state=assessment.health_state,
            dominant_signal=(
                assessment.dominant_signal.signal
                if assessment.dominant_signal
                else ""
            ),
            dominant_signal_score=(
                assessment.dominant_signal.score
                if assessment.dominant_signal
                else 0
            ),
            dominant_signal_reason=(
                assessment.dominant_signal.reason
                if assessment.dominant_signal
                else ""
            ),
            progress=assessment.progress,
            days_since_last_activity=(
                assessment.days_since_last_activity
            ),
            measurement_overdue_count=(
                assessment.measurement_overdue_count
            ),
        )
        for assessment in neglected_assessments
    ]

    # Recommended actions.
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

    # Normalise ordering for deterministic output.
    neglected_goals.sort(
        key=lambda item: (
            0 if item.health_state == "stalled" else 1,
            -item.dominant_signal_score,
            -(item.days_since_last_activity or 0),
            item.goal_title,
        )
    )

    actions.sort(
        key=lambda item: (
            0
            if item.health_state == "stalled"
            else 1,
            -item.dominant_signal_score,
            -(item.days_since_last_activity or 0),
            item.goal_title,
        )
    )

    return StrategicSummary(
        generated_at=now,
        portfolio_health_counts=portfolio_health_counts,
        stalled_goals=stalled_goals,
        neglected_goals=neglected_goals,
        recommended_actions=actions,
        cross_domain_links=cross_links,
    )


# ── Rendering ─────────────────────────────────────────────────────────────────


def render_strategic_summary(
    summary: StrategicSummary,
) -> str:
    """Render a ``StrategicSummary`` as human-readable markdown."""

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
        lines.append(
            f"  Completed: {counts.completed}  "
            f"Inactive: {counts.inactive}"
        )

    lines.append("")

    # Stalled work.
    lines.append("STALLED WORK")

    if summary.stalled_goals:
        for stalled_goal in summary.stalled_goals:
            lines.append(
                f"  [{stalled_goal.dominant_signal} "
                f"score={stalled_goal.dominant_signal_score}] "
                f"{stalled_goal.goal_title}"
            )

            lines.append(
                f"    Reason: "
                f"{stalled_goal.dominant_signal_reason}"
            )

            if stalled_goal.progress is not None:
                delta = ""

                if stalled_goal.progress_delta is not None:
                    delta = (
                        f", delta "
                        f"{stalled_goal.progress_delta:+.1f}% "
                        f"over 14d"
                    )

                lines.append(
                    f"    Progress: "
                    f"{stalled_goal.progress:.1f}%"
                    f"{delta}"
                )

            if (
                stalled_goal.days_since_last_activity
                is not None
            ):
                lines.append(
                    f"    Activity: "
                    f"{stalled_goal.days_since_last_activity}d "
                    f"since last metric/task"
                )

            lines.append(
                f"    Measurements overdue: "
                f"{stalled_goal.measurement_overdue_count}"
            )
    else:
        lines.append("  No stalled goals.")

    lines.append("")

    # Neglected goals.
    lines.append("NEGLECTED GOALS")

    if summary.neglected_goals:
        for neglected_goal in summary.neglected_goals:
            lines.append(
                f"  [{neglected_goal.health_state}, "
                f"score={neglected_goal.dominant_signal_score}] "
                f"{neglected_goal.goal_title}"
            )

            lines.append(
                f"    Reason: "
                f"{neglected_goal.dominant_signal_reason}"
            )

            if neglected_goal.progress is not None:
                delta = ""

                if neglected_goal.progress_delta is not None:
                    delta = (
                        f", delta "
                        f"{neglected_goal.progress_delta:+.1f}% "
                        f"over 14d"
                    )

                lines.append(
                    f"    Progress: "
                    f"{neglected_goal.progress:.1f}%"
                    f"{delta}"
                )
            else:
                lines.append("    Progress: N/A")

            if (
                neglected_goal.days_since_last_activity
                is not None
            ):
                lines.append(
                    f"    Activity: "
                    f"{neglected_goal.days_since_last_activity}d "
                    f"since last metric/task"
                )
            else:
                lines.append("    Activity: no data")

            lines.append(
                f"    Measurements overdue: "
                f"{neglected_goal.measurement_overdue_count}"
            )
    else:
        lines.append("  No neglected goals.")

    lines.append("")

    # Recommended actions.
    lines.append("RECOMMENDED ACTIONS")

    if summary.recommended_actions:
        for index, recommendation in enumerate(
            summary.recommended_actions,
            1,
        ):
            lines.append(
                f"{index}. {recommendation.goal_title} "
                f"[{recommendation.health_state}, "
                f"score={recommendation.dominant_signal_score}]"
            )

            lines.append(
                f"   Reason: "
                f"{recommendation.dominant_signal_reason}"
            )

            if recommendation.progress is not None:
                delta = ""

                if recommendation.progress_delta is not None:
                    delta = (
                        f", delta "
                        f"{recommendation.progress_delta:+.1f}% "
                        f"over 14d"
                    )

                lines.append(
                    f"   Progress: "
                    f"{recommendation.progress:.1f}%"
                    f"{delta}"
                )
            else:
                lines.append("   Progress: N/A")

            if (
                recommendation.days_since_last_activity
                is not None
            ):
                lines.append(
                    f"   Activity: "
                    f"{recommendation.days_since_last_activity}d "
                    f"since last metric/task"
                )
            else:
                lines.append("   Activity: no data")

            lines.append(
                f"   Measurements overdue: "
                f"{recommendation.measurement_overdue_count}"
            )

            action = (
                recommendation.suggested_next_step
                or recommendation.attention_reason
            )

            if action:
                lines.append(
                    f"   Suggested action: {action}"
                )

            if recommendation.cross_links:
                link_strings = [
                    f"{link.category}: {link.title}"
                    for link in recommendation.cross_links
                ]

                lines.append(
                    f"   Cross-links: "
                    f"{'; '.join(link_strings)}"
                )

            lines.append("")
    else:
        lines.append("  No recommendations.")
        lines.append("")

    return "\n".join(lines)