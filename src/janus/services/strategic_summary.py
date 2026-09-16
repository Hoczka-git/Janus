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

The strategic summary service implements the aggregation logic from §2,
§3, and §5, while the change detector implements every criterion from §1:

1. Health-state transition (healthy ↔ watch ↔ stalled) or dominant signal
   score change >= 15 points.
2. Progress delta over the 14-day lookback crosses
   ``progress_slow_threshold`` (default 5%) in either direction.
3. A stalled-work signal activates or clears (goal_stalled, goal_overdue,
   milestone_slipped, no_recent_activity).
4. A measurement requirement becomes overdue or is satisfied.
5. Cross-domain link changes (new research artifact ↔ goal link, decision
   updated by a finding, follow-up linked to a goal milestone/project).
6. Goal status transition (active → completed/inactive).

Non-meaningful changes (excluded per spec):
- Individual task completion that does not affect progress delta.
- Attention-item score fluctuations under 15 points without state change.
- Metric snapshot append without health impact.

This module reuses existing signal computation from
``assess_goal_health()`` and aggregates its results into the strategic
summary models.
"""

import logging
from datetime import date, datetime

from janus._log import emit
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
from janus.services.weekly_review import create_weekly_review, _read_completed_task_titles

logger = logging.getLogger(__name__)

# Dominant-signal score delta that counts as meaningful (spec §1 criterion 1).
_DOMINANT_SIGNAL_SCORE_THRESHOLD = 15

# The number of days since a strategic action was surfaced after which a
# goal is considered "not recently attended to" (design §2).
STRATEGIC_ATTENTION_WINDOW_DAYS = 7


# ── Snapshot helpers ──────────────────────────────────────────────────────────


def _milestone_status_snapshot(goal: Goal) -> dict[str, str]:
    """Extract a {milestone_title: status} mapping from a Goal's milestones.

    Milestones are stored as list[dict] on the Goal model. This helper
    reads the ``title`` and ``status`` keys, defaulting status to "open"
    when absent. Used for milestone status change detection (§1.6).
    """
    result: dict[str, str] = {}
    for m in goal.milestones or []:
        title = m.get("title") if isinstance(m, dict) else getattr(m, "title", None)
        if title:
            status = (
                m.get("status", "open")
                if isinstance(m, dict)
                else getattr(m, "status", "open")
            )
            result[title] = status
    return result


def build_goal_state_snapshot(
    goal: Goal,
    today,
    open_task_titles: set[str],
    all_task_titles: set[str],
    metric_snapshots: list[MetricSnapshot] | None = None,
    completed_task_dates: dict[str, date] | None = None,
) -> GoalStateSnapshot:
    """Construct a ``GoalStateSnapshot`` from a Goal and its health assessment.

    Delegates all health computation to the existing
    ``assess_goal_health()`` function. The snapshot captures exactly the
    strategic-relevant fields needed for change detection.
    """
    assessment = assess_goal_health(
        goal,
        today,
        open_task_titles,
        all_task_titles,
        metric_snapshots=metric_snapshots,
        completed_task_dates=completed_task_dates,
    )

    if assessment is None:
        # Inactive goal — excluded from health assessment entirely.
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
            linked_research_artifacts=sorted(
                goal.research_artifact_titles or []
            ),
            linked_decision_numbers=sorted(
                goal.decision_numbers or []
            ),
            linked_followup_ids=sorted(
                goal.followup_ids or []
            ),
        )

    signals = frozenset(s.signal for s in assessment.signals)
    dominant = assessment.dominant_signal
    dominant_score = dominant.score if dominant is not None else 0
    dominant_name = dominant.signal if dominant is not None else None

    return GoalStateSnapshot(
        goal_title=goal.title,
        health_state=assessment.health_state,
        dominant_signal=dominant_name,
        dominant_signal_score=dominant_score,
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
        linked_research_artifacts=sorted(
            goal.research_artifact_titles or []
        ),
        linked_decision_numbers=sorted(
            goal.decision_numbers or []
        ),
        linked_followup_ids=sorted(
            goal.followup_ids or []
        ),
    )


def build_strategic_snapshot(
    goals: list[Goal],
    today,
    open_task_titles: set[str],
    all_task_titles: set[str],
) -> StrategicStateSnapshot:
    """Build a full ``StrategicStateSnapshot`` for all goals.

    Loads metric snapshots per-goal and delegates to
    :func:`build_goal_state_snapshot` for each goal.
    """
    from janus.integrations.metric_history import get_metric_snapshots

    now = datetime.now().astimezone()
    goal_snapshots: list[GoalStateSnapshot] = []

    for goal in goals:
        metric_snaps = (
            get_metric_snapshots(goal.title)
            if (
                goal.metric_name
                or goal.inactivity_window_days is not None
            )
            else []
        )

        snap = build_goal_state_snapshot(
            goal,
            today,
            open_task_titles,
            all_task_titles,
            metric_snapshots=metric_snaps,
            completed_task_dates=None,
        )
        goal_snapshots.append(snap)

    return StrategicStateSnapshot(
        generated_at=now,
        goals=goal_snapshots,
    )


# ── Meaningful change detection ───────────────────────────────────────────────


def detect_meaningful_changes(
    previous: StrategicStateSnapshot,
    current: StrategicStateSnapshot,
) -> list[MeaningfulChange]:
    """Detect meaningful changes between two strategic state snapshots.

    Implements the criteria from design spec §1.

    Changes are returned sorted by severity (descending), then by goal
    title for deterministic ordering.
    """
    now = datetime.now().astimezone()
    changes: list[MeaningfulChange] = []

    prev_by_title = {
        g.goal_title: g
        for g in previous.goals
    }

    current_titles = {
        g.goal_title
        for g in current.goals
    }

    for cur_goal in current.goals:
        title = cur_goal.goal_title
        prev_goal = prev_by_title.get(title)

        if prev_goal is None:
            _detect_new_goal_changes(cur_goal, now, changes)
            continue

        _detect_goal_changes(
            prev_goal,
            cur_goal,
            now,
            changes,
        )

    # Detect goals that disappeared from the current snapshot.
    for prev_goal in previous.goals:
        if prev_goal.goal_title not in current_titles:
            changes.append(
                MeaningfulChange(
                    change_type=CHANGE_GOAL_STATUS,
                    goal_title=prev_goal.goal_title,
                    description=(
                        f"Goal '{prev_goal.goal_title}' was removed from the "
                        f"strategic portfolio"
                    ),
                    severity=10,
                    details={
                        "previous_status": prev_goal.goal_status,
                        "current_status": "removed",
                    },
                    timestamp=now,
                )
            )

    changes.sort(
        key=lambda c: (-c.severity, c.goal_title)
    )
    return changes


def _detect_goal_changes(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect all meaningful changes for a single goal."""

    # §1.1: Health-state transition.
    if prev.health_state != cur.health_state:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_HEALTH_STATE,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' health state changed: "
                    f"{prev.health_state or 'none'} → "
                    f"{cur.health_state or 'none'}"
                ),
                severity=_health_severity(cur.health_state),
                details={
                    "previous_health_state": prev.health_state,
                    "current_health_state": cur.health_state,
                },
                timestamp=now,
            )
        )

    # §1.1: Dominant signal score change >= 15 points.
    score_delta = (
        cur.dominant_signal_score
        - prev.dominant_signal_score
    )
    prev_sig = prev.dominant_signal
    cur_sig = cur.dominant_signal

    if abs(score_delta) >= _DOMINANT_SIGNAL_SCORE_THRESHOLD:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_DOMINANT_SIGNAL_SCORE,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' dominant signal score changed "
                    f"by {score_delta:+d} points "
                    f"({prev_sig or 'none'}:{prev.dominant_signal_score} → "
                    f"{cur_sig or 'none'}:{cur.dominant_signal_score})"
                ),
                severity=5 + abs(score_delta) // 10,
                details={
                    "previous_signal": prev_sig,
                    "current_signal": cur_sig,
                    "previous_score": prev.dominant_signal_score,
                    "current_score": cur.dominant_signal_score,
                    "delta": score_delta,
                },
                timestamp=now,
            )
        )
    elif (
        prev_sig != cur_sig
        and prev_sig is not None
        and cur_sig is not None
    ):
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_DOMINANT_SIGNAL_SCORE,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' dominant signal changed: "
                    f"{prev_sig} → {cur_sig}"
                ),
                severity=5,
                details={
                    "previous_signal": prev_sig,
                    "current_signal": cur_sig,
                    "previous_score": prev.dominant_signal_score,
                    "current_score": cur.dominant_signal_score,
                    "delta": score_delta,
                },
                timestamp=now,
            )
        )

    # §1.2: Progress delta threshold crossing.
    _detect_progress_delta_change(
        prev,
        cur,
        now,
        changes,
    )

    # §1.3: Stalled-work signal activation / clearing.
    _detect_stalled_signal_change(
        prev,
        cur,
        now,
        changes,
    )

    # §1.4: Measurement requirement overdue / satisfied.
    _detect_measurement_change(
        prev,
        cur,
        now,
        changes,
    )

    # §1.5: Cross-domain link changes.
    _detect_cross_domain_link_change(
        prev,
        cur,
        now,
        changes,
    )

    # §1.6: Goal status transition.
    if prev.goal_status != cur.goal_status:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_GOAL_STATUS,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' status changed: "
                    f"{prev.goal_status} → {cur.goal_status}"
                ),
                severity=_goal_status_severity(cur.goal_status),
                details={
                    "previous_status": prev.goal_status,
                    "current_status": cur.goal_status,
                },
                timestamp=now,
            )
        )

    # §1.6: Milestone status changes.
    _detect_milestone_status_change(
        prev,
        cur,
        now,
        changes,
    )


def _detect_new_goal_changes(
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect changes for a goal that is new in the current snapshot."""

    if cur.goal_status != "active":
        return

    if cur.health_state is None or cur.health_state == "healthy":
        if not cur.signals:
            return

    changes.append(
        MeaningfulChange(
            change_type=CHANGE_GOAL_STATUS,
            goal_title=cur.goal_title,
            description=(
                f"Goal '{cur.goal_title}' is newly active "
                f"(health: {cur.health_state or 'unknown'}, "
                f"signals: {sorted(cur.signals) or 'none'})"
            ),
            severity=_health_severity(cur.health_state) + 5,
            details={
                "previous_status": "new",
                "current_status": cur.goal_status,
                "current_health_state": cur.health_state,
                "current_signals": sorted(cur.signals),
            },
            timestamp=now,
        )
    )


def _detect_progress_delta_change(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect §1.2: progress delta crossing the slow threshold."""

    prev_delta = prev.progress_delta
    cur_delta = cur.progress_delta

    if prev_delta is None or cur_delta is None:
        if (
            cur_delta is not None
            and abs(cur_delta) >= PROGRESS_SLOW_THRESHOLD
        ):
            changes.append(
                MeaningfulChange(
                    change_type=CHANGE_PROGRESS_DELTA,
                    goal_title=cur.goal_title,
                    description=(
                        f"Goal '{cur.goal_title}' progress delta now "
                        f"measurable: {cur_delta:+.1f}% over "
                        f"{PROGRESS_LOOKBACK_DAYS} days "
                        f"(threshold: {PROGRESS_SLOW_THRESHOLD:.0f}%)"
                    ),
                    severity=3,
                    details={
                        "previous_delta": prev_delta,
                        "current_delta": cur_delta,
                        "threshold": PROGRESS_SLOW_THRESHOLD,
                    },
                    timestamp=now,
                )
            )
        return

    prev_crossed = (
        prev_delta < PROGRESS_SLOW_THRESHOLD
    )
    cur_crossed = (
        cur_delta < PROGRESS_SLOW_THRESHOLD
    )

    if prev_crossed != cur_crossed:
        direction = (
            "now exceeds"
            if not cur_crossed
            else "now below"
        )

        changes.append(
            MeaningfulChange(
                change_type=CHANGE_PROGRESS_DELTA,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' progress delta {direction} "
                    f"the slow-progress threshold: {cur_delta:+.1f}% "
                    f"(was {prev_delta:+.1f}%, threshold: "
                    f"{PROGRESS_SLOW_THRESHOLD:.0f}%)"
                ),
                severity=3,
                details={
                    "previous_delta": prev_delta,
                    "current_delta": cur_delta,
                    "threshold": PROGRESS_SLOW_THRESHOLD,
                },
                timestamp=now,
            )
        )


def _detect_stalled_signal_change(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect §1.3: stalled-work signal activation or clearing."""

    prev_stalled = (
        prev.signals & _STALLED_SIGNALS
    )
    cur_stalled = (
        cur.signals & _STALLED_SIGNALS
    )

    activated = cur_stalled - prev_stalled
    cleared = prev_stalled - cur_stalled

    for sig in sorted(activated):
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_STALLED_SIGNAL,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' stalled-work signal "
                    f"activated: {sig}"
                ),
                severity=8,
                details={
                    "signal": sig,
                    "action": "activated",
                    "previous_signals": sorted(prev_stalled),
                    "current_signals": sorted(cur_stalled),
                },
                timestamp=now,
            )
        )

    for sig in sorted(cleared):
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_STALLED_SIGNAL,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' stalled-work signal "
                    f"cleared: {sig}"
                ),
                severity=4,
                details={
                    "signal": sig,
                    "action": "cleared",
                    "previous_signals": sorted(prev_stalled),
                    "current_signals": sorted(cur_stalled),
                },
                timestamp=now,
            )
        )


def _detect_measurement_change(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect §1.4: measurement requirement overdue / satisfied."""

    prev_count = prev.measurement_overdue_count
    cur_count = cur.measurement_overdue_count

    if prev_count == 0 and cur_count > 0:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_MEASUREMENT_DUE,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' measurement requirements "
                    f"became overdue ({cur_count} now due)"
                ),
                severity=6,
                details={
                    "previous_overdue_count": prev_count,
                    "current_overdue_count": cur_count,
                    "action": "fired",
                },
                timestamp=now,
            )
        )
    elif prev_count > 0 and cur_count == 0:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_MEASUREMENT_DUE,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' measurement requirements "
                    f"satisfied (were {prev_count} overdue, now none)"
                ),
                severity=4,
                details={
                    "previous_overdue_count": prev_count,
                    "current_overdue_count": cur_count,
                    "action": "satisfied",
                },
                timestamp=now,
            )
        )


def _detect_cross_domain_link_change(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect §1.5: cross-domain link changes."""

    prev_artifacts = set(
        prev.linked_research_artifacts
    )
    cur_artifacts = set(
        cur.linked_research_artifacts
    )

    new_artifacts = (
        cur_artifacts - prev_artifacts
    )

    if new_artifacts:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_CROSS_DOMAIN_LINK,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' gained new cross-domain "
                    f"links: research artifacts added — "
                    f"{', '.join(sorted(new_artifacts))}"
                ),
                severity=3,
                details={
                    "link_type": "research_artifact",
                    "added": sorted(new_artifacts),
                    "removed": sorted(
                        prev_artifacts - cur_artifacts
                    ),
                },
                timestamp=now,
            )
        )

    prev_decisions = set(
        prev.linked_decision_numbers
    )
    cur_decisions = set(
        cur.linked_decision_numbers
    )

    new_decisions = (
        cur_decisions - prev_decisions
    )

    if new_decisions:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_CROSS_DOMAIN_LINK,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' gained new cross-domain "
                    f"links: decisions added — "
                    f"{', '.join(sorted(new_decisions))}"
                ),
                severity=3,
                details={
                    "link_type": "decision",
                    "added": sorted(new_decisions),
                    "removed": sorted(
                        prev_decisions - cur_decisions
                    ),
                },
                timestamp=now,
            )
        )

    prev_fups = set(
        prev.linked_followup_ids
    )
    cur_fups = set(
        cur.linked_followup_ids
    )

    new_fups = cur_fups - prev_fups

    if new_fups:
        changes.append(
            MeaningfulChange(
                change_type=CHANGE_CROSS_DOMAIN_LINK,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' gained new cross-domain "
                    f"links: follow-ups added — "
                    f"{', '.join(sorted(new_fups))}"
                ),
                severity=3,
                details={
                    "link_type": "followup",
                    "added": sorted(new_fups),
                    "removed": sorted(
                        prev_fups - cur_fups
                    ),
                },
                timestamp=now,
            )
        )


def _detect_milestone_status_change(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect §1.6: milestone status changes."""

    prev_ms = prev.milestone_statuses
    cur_ms = cur.milestone_statuses

    all_milestones = (
        set(prev_ms.keys()) | set(cur_ms.keys())
    )

    for ms_title in sorted(all_milestones):
        prev_status = prev_ms.get(ms_title)
        cur_status = cur_ms.get(ms_title)

        if prev_status != cur_status:
            changes.append(
                MeaningfulChange(
                    change_type=CHANGE_MILESTONE_STATUS,
                    goal_title=cur.goal_title,
                    description=(
                        f"Goal '{cur.goal_title}' milestone "
                        f"'{ms_title}' status changed: "
                        f"{prev_status or 'none'} → "
                        f"{cur_status or 'removed'}"
                    ),
                    severity=5,
                    details={
                        "milestone_title": ms_title,
                        "previous_status": prev_status,
                        "current_status": (
                            cur_status
                            if cur_status is not None
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


def _parse_deadline(raw):
    """Parse an ISO date string into a date, or None."""
    if raw is None:
        return None

    from datetime import date as _date

    try:
        return _date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _has_upcoming_milestone_or_deadline(
    goal: Goal,
    today: date,
) -> bool:
    """Return True if the goal has an upcoming milestone or deadline."""

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

        if (
            m.status in ("open", "in_progress")
            and m_dl is None
        ):
            return True

    return False


def _collect_cross_domain_links(
    goal_titles: set[str],
    research_artifacts=None,
    decisions=None,
    followups=None,
) -> list[CrossDomainLink]:
    """Collect all cross-domain links for the given goal titles."""

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
                key = (
                    gt,
                    "research_artifact",
                    art.title,
                )

                if key not in seen:
                    seen.add(key)
                    links.append(
                        CrossDomainLink(
                            goal_title=gt,
                            category="research_artifact",
                            title=art.title,
                        )
                    )

    for dec in decisions:
        for gt in dec.goal_titles:
            if gt in goal_titles:
                key = (
                    gt,
                    "decision",
                    dec.title,
                )

                if key not in seen:
                    seen.add(key)
                    links.append(
                        CrossDomainLink(
                            goal_title=gt,
                            category="decision",
                            title=dec.title,
                        )
                    )

    for fu in followups:
        if (
            fu.linked_goal_title
            and fu.linked_goal_title in goal_titles
        ):
            key = (
                fu.linked_goal_title,
                "follow_up",
                fu.title,
            )

            if key not in seen:
                seen.add(key)
                links.append(
                    CrossDomainLink(
                        goal_title=fu.linked_goal_title,
                        category="follow_up",
                        title=fu.title,
                    )
                )

    return links


def _links_for_goal(
    goal_title: str,
    all_links: list[CrossDomainLink],
) -> list[CrossDomainLink]:
    """Return cross-domain links for a specific goal."""
    return [
        link
        for link in all_links
        if link.goal_title == goal_title
    ]


def _build_portfolio_counts(
    assessments,
    goals,
):
    """Build PortfolioHealthCounts from assessments and goals."""
    counts = PortfolioHealthCounts()

    counts.total_active = sum(
        1
        for goal in goals
        if goal.status == "active"
    )

    for assessment in assessments:
        if assessment.health_state == "healthy":
            counts.healthy += 1
        elif assessment.health_state == "watch":
            counts.watch += 1
        elif assessment.health_state == "stalled":
            counts.stalled += 1
        elif assessment.health_state == "completed":
            counts.completed += 1

    counts.inactive = sum(
        1
        for goal in goals
        if goal.status == "inactive"
    )

    return counts


# ── Public API ───────────────────────────────────────────────────────────────


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
    """Create a strategic summary by aggregating existing signal services."""

    if now is None:
        now = datetime.now().astimezone()

    if today is None:
        today = now.date()

    # Load goals if not provided.
    if goals is None:
        from janus.integrations.markdown_goals import load_goals

        goals = load_goals()

    # Load task data if not provided.
    if (
        open_task_titles is None
        or all_task_titles is None
    ):
        from janus.integrations.markdown_tasks import load_tasks

        tasks = load_tasks()

        if open_task_titles is None:
            open_task_titles = {
                task.title
                for task in tasks
            }

        if all_task_titles is None:
            completed = _read_completed_task_titles()
            all_task_titles = (
                {task.title for task in tasks}
                | set(completed)
            )

    # Build attention items if not provided.
    if attention_items is None:
        from janus.services.attention import get_attention_items
        from janus.integrations.markdown_tasks import load_tasks

        _followups = (
            followups
            if followups is not None
            else None
        )

        attention_items = get_attention_items(
            events=[],
            tasks=load_tasks(),
            goals=goals,
            today=today,
            now=now,
            followups=_followups,
        )

    # Build recommendations if not provided.
    if recommendations is None:
        from janus.services.recommendations import recommend_tasks
        from janus.integrations.markdown_tasks import load_tasks

        _completed = _read_completed_task_titles()

        recommendations = recommend_tasks(
            goals=goals,
            tasks=load_tasks(),
            completed_task_titles=set(_completed),
            today=today,
        )

    # Build goal reviews if not provided.
    if goal_reviews is None:
        goal_reviews = create_weekly_review().goals

    # Collect cross-domain links.
    all_links = _collect_cross_domain_links(
        {goal.title for goal in goals},
        research_artifacts,
        decisions,
        followups,
    )

    # Assess each goal's health.
    assessments: list[GoalHealthAssessment] = []

    for goal in goals:
        snaps = None

        if metric_snapshots_by_goal is not None:
            snaps = metric_snapshots_by_goal.get(
                goal.title
            )

        assessment = assess_goal_health(
            goal,
            today,
            open_task_titles=open_task_titles,
            all_task_titles=all_task_titles,
            metric_snapshots=snaps,
            completed_task_dates=completed_task_dates,
        )

        if assessment is not None:
            assessments.append(assessment)

    # Build portfolio health counts.
    if portfolio_health_counts is None:
        portfolio_health_counts = _build_portfolio_counts(
            assessments,
            goals,
        )

    # Lookup: goal title → GoalReview.
    review_by_goal: dict[str, GoalReview] = {}

    for goal_review in goal_reviews:
        review_by_goal[goal_review.goal.title] = goal_review

    # Lookup: attention items by title.
    attention_by_title: dict[str, str] = {}

    for item in attention_items:
        attention_by_title[item.title] = item.reason

    # ── Stalled goals ────────────────────────────────────────────────────────

    stalled: list[StalledGoal] = []

    for assessment in assessments:
        if assessment.health_state != "stalled":
            continue

        dominant = assessment.dominant_signal

        stalled.append(
            StalledGoal(
                goal_title=assessment.goal_title,
                health_state=assessment.health_state,
                dominant_signal=(
                    dominant.signal
                    if dominant
                    else ""
                ),
                dominant_signal_score=(
                    dominant.score
                    if dominant
                    else 0
                ),
                dominant_signal_reason=(
                    dominant.reason
                    if dominant
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
        )

    stalled.sort(
        key=lambda item: item.dominant_signal_score,
        reverse=True,
    )

    # ── Neglected goals ─────────────────────────────────────────────────────

    neglected: list[NeglectedGoal] = []

    for assessment in assessments:
        if assessment.health_state not in (
            "watch",
            "stalled",
        ):
            continue

        goal = next(
            (
                goal
                for goal in goals
                if goal.title == assessment.goal_title
            ),
            None,
        )

        if goal is None:
            continue

        if goal.status in (
            "inactive",
            "completed",
        ):
            continue

        dominant = assessment.dominant_signal

        inactivity_window = (
            goal.inactivity_window_days
            or INACTIVITY_WINDOW_DAYS
        )

        days = assessment.days_since_last_activity

        days_exceeds = (
            days is not None
            and days > inactivity_window
        )

        has_measurement_overdue = (
            assessment.measurement_overdue_count > 0
        )

        open_related = any(
            related_task in open_task_titles
            for related_task in goal.related_tasks
        )

        has_upcoming = (
            _has_upcoming_milestone_or_deadline(
                goal,
                today,
            )
        )

        if (
            days_exceeds
            or has_measurement_overdue
            or (
                not open_related
                and not has_upcoming
            )
        ):
            neglected.append(
                NeglectedGoal(
                    goal_title=assessment.goal_title,
                    health_state=assessment.health_state,
                    dominant_signal=(
                        dominant.signal
                        if dominant
                        else ""
                    ),
                    dominant_signal_score=(
                        dominant.score
                        if dominant
                        else 0
                    ),
                    dominant_signal_reason=(
                        dominant.reason
                        if dominant
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
                    has_open_related_tasks=open_related,
                    has_upcoming_deadline=has_upcoming,
                )
            )

    neglected.sort(
        key=lambda item: (
            0
            if item.health_state == "stalled"
            else 1,
            -item.dominant_signal_score,
            -(item.days_since_last_activity or 0),
            item.goal_title,
        )
    )

    # ── Recommended actions ──────────────────────────────────────────────────

    neglected_titles = (
        {item.goal_title for item in neglected}
        | {item.goal_title for item in stalled}
    )

    recommendations_list: list[RecommendedAction] = []

    for assessment in assessments:
        if assessment.goal_title not in neglected_titles:
            continue

        dominant = assessment.dominant_signal
        goal_review = review_by_goal.get(
            assessment.goal_title
        )

        suggested = (
            goal_review.suggested_next_step
            if (
                goal_review
                and goal_review.suggested_next_step
            )
            else None
        )

        attention_reason = attention_by_title.get(
            assessment.goal_title
        )

        goal_links = _links_for_goal(
            assessment.goal_title,
            all_links,
        )

        recommendations_list.append(
            RecommendedAction(
                goal_title=assessment.goal_title,
                health_state=assessment.health_state,
                dominant_signal=(
                    dominant.signal
                    if dominant
                    else ""
                ),
                dominant_signal_score=(
                    dominant.score
                    if dominant
                    else 0
                ),
                dominant_signal_reason=(
                    dominant.reason
                    if dominant
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
                suggested_next_step=suggested,
                attention_reason=attention_reason,
                cross_links=goal_links,
            )
        )

    recommendations_list.sort(
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
        stalled_goals=stalled,
        neglected_goals=neglected,
        recommended_actions=recommendations_list,
        cross_domain_links=all_links,
    )


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

    # Stalled work list.
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
                delta_str = ""

                if stalled_goal.progress_delta is not None:
                    delta_str = (
                        f", delta "
                        f"{stalled_goal.progress_delta:+.1f}% "
                        f"over 14d"
                    )

                lines.append(
                    f"    Progress: "
                    f"{stalled_goal.progress:.1f}%"
                    f"{delta_str}"
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

    # Neglected goals list.
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
                delta_str = ""

                if neglected_goal.progress_delta is not None:
                    delta_str = (
                        f", delta "
                        f"{neglected_goal.progress_delta:+.1f}% "
                        f"over 14d"
                    )

                lines.append(
                    f"    Progress: "
                    f"{neglected_goal.progress:.1f}%"
                    f"{delta_str}"
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
                delta_str = ""

                if recommendation.progress_delta is not None:
                    delta_str = (
                        f", delta "
                        f"{recommendation.progress_delta:+.1f}% "
                        f"over 14d"
                    )

                lines.append(
                    f"   Progress: "
                    f"{recommendation.progress:.1f}%"
                    f"{delta_str}"
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
                link_strs = [
                    f"{link.category}: {link.title}"
                    for link in recommendation.cross_links
                ]

                lines.append(
                    f"   Cross-links: "
                    f"{'; '.join(link_strs)}"
                )

            lines.append("")
    else:
        lines.append("  No recommendations.")
        lines.append("")

    return "\n".join(lines)