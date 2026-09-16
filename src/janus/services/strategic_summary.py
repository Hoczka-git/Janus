"""Strategic summary service for Janus — meaningful change detection.

Implements the data/logic layer defined in
``design/strategic_summary_spec.md`` §1: "Meaningful change".

A *meaningful change* is any event that alters the strategic picture.
This module provides :func:`detect_meaningful_changes`, which compares a
previous ``StrategicStateSnapshot`` against a current one and returns the
list of ``MeaningfulChange`` events that occurred.

The detector implements every criterion from spec §1:

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

The service reuses existing data structures:
- ``GoalHealthAssessment`` from ``services/goal_health.py``
- ``assess_goal_health()`` for computing current assessments
- ``GoalStateSnapshot`` / ``StrategicStateSnapshot`` / ``MeaningfulChange``
  from ``models/strategic_summary.py``
"""

import logging
from datetime import date, datetime

from janus._log import emit
from janus.models.goal import Goal
from janus.models.metric_snapshot import MetricSnapshot
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
    GoalStateSnapshot,
    MeaningfulChange,
    StrategicStateSnapshot,
)
from janus.services.goal_health import (
    INACTIVITY_WINDOW_DAYS,
    PROGRESS_LOOKBACK_DAYS,
    PROGRESS_SLOW_THRESHOLD,
    assess_goal_health,
)

logger = logging.getLogger(__name__)

# Dominant-signal score delta that counts as meaningful (spec §1 criterion 1).
_DOMINANT_SIGNAL_SCORE_THRESHOLD = 15


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
            status = m.get("status", "open") if isinstance(m, dict) else getattr(m, "status", "open")
            result[title] = status
    return result


# ── Snapshot construction ────────────────────────────────────────────────────


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
    ``assess_goal_health()`` function (spec: "reuse assess_goal_health from
    existing attention.py + goal_progress.py"). The snapshot captures exactly
    the strategic-relevant fields needed for change detection — nothing more.

    Args:
        goal: The Goal to snapshot.
        today: Current date.
        open_task_titles: Set of currently-open task titles.
        all_task_titles: Set of all task titles (open + completed).
        metric_snapshots: Optional pre-loaded metric snapshots for the goal.
        completed_task_dates: Optional mapping of task title → completion date.

    Returns:
        A ``GoalStateSnapshot`` capturing the goal's strategic state.
    """
    assessment = assess_goal_health(
        goal, today, open_task_titles, all_task_titles,
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
            linked_research_artifacts=sorted(goal.research_artifact_titles or []),
            linked_decision_numbers=sorted(goal.decision_numbers or []),
            linked_followup_ids=sorted(goal.followup_ids or []),
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
        measurement_overdue_count=assessment.measurement_overdue_count if assessment.measurement_overdue_count is not None else 0,
        signals=signals,
        goal_status=goal.status,
        milestone_statuses=_milestone_status_snapshot(goal),
        linked_research_artifacts=sorted(goal.research_artifact_titles or []),
        linked_decision_numbers=sorted(goal.decision_numbers or []),
        linked_followup_ids=sorted(goal.followup_ids or []),
    )


def build_strategic_snapshot(
    goals: list[Goal],
    today,
    open_task_titles: set[str],
    all_task_titles: set[str],
) -> StrategicStateSnapshot:
    """Build a full ``StrategicStateSnapshot`` for all goals.

    Loads metric snapshots per-goal (only when the goal has metric config
    or an inactivity window override), then delegates to
    :func:`build_goal_state_snapshot` for each goal.
    """
    from janus.integrations.metric_history import get_metric_snapshots

    now = datetime.now().astimezone()
    goal_snapshots: list[GoalStateSnapshot] = []

    for goal in goals:
        metric_snaps = get_metric_snapshots(goal.title) if (
            goal.metric_name or goal.inactivity_window_days is not None
        ) else []
        snap = build_goal_state_snapshot(
            goal, today, open_task_titles, all_task_titles,
            metric_snapshots=metric_snaps,
            completed_task_dates=None,
        )
        goal_snapshots.append(snap)

    return StrategicStateSnapshot(
        generated_at=now,
        goals=goal_snapshots,
    )


# ── Change detection ─────────────────────────────────────────────────────────


def detect_meaningful_changes(
    previous: StrategicStateSnapshot,
    current: StrategicStateSnapshot,
) -> list[MeaningfulChange]:
    """Detect meaningful changes between two strategic state snapshots.

    Implements the criteria from design spec §1. Each detected change
    becomes a :class:`MeaningfulChange` with a type, goal title,
    human-readable description, severity, and machine-readable details.

    Changes are returned sorted by severity (descending), then by goal
    title for deterministic ordering.

    Args:
        previous: The earlier ``StrategicStateSnapshot``.
        current:  The later ``StrategicStateSnapshot``.

    Returns:
        A list of ``MeaningfulChange`` events. Empty if nothing meaningful
        changed.
    """
    now = datetime.now().astimezone()
    changes: list[MeaningfulChange] = []

    # Index previous goals by title for fast lookup.
    prev_by_title = {
        g.goal_title: g for g in previous.goals
    }

    for cur_goal in current.goals:
        title = cur_goal.goal_title
        prev_goal = prev_by_title.get(title)

        # New goal appearing in the current snapshot — every field is
        # a "change" but we surface it as a goal_status_transition from
        # "new" (only if it has signals or non-healthy state).
        if prev_goal is None:
            _detect_new_goal_changes(cur_goal, now, changes)
            continue

        if prev_goal is not None:
            _detect_goal_changes(prev_goal, cur_goal, now, changes)

    # Detect goals that disappeared (were removed from current snapshot).
    for prev_goal in previous.goals:
        if prev_goal.goal_title not in {g.goal_title for g in current.goals}:
            changes.append(MeaningfulChange(
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
            ))

    # Sort by severity descending, then goal title for determinism.
    changes.sort(key=lambda c: (-c.severity, c.goal_title))
    return changes


def _detect_goal_changes(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect all meaningful changes for a single goal between two snapshots.

    Appends to *changes* in-place.
    """
    # ── §1.1: Health-state transition ────────────────────────────────────────
    if prev.health_state != cur.health_state:
        changes.append(MeaningfulChange(
            change_type=CHANGE_HEALTH_STATE,
            goal_title=cur.goal_title,
            description=(
                f"Goal '{cur.goal_title}' health state changed: "
                f"{prev.health_state or 'none'} → {cur.health_state or 'none'}"
            ),
            severity=_health_severity(cur.health_state),
            details={
                "previous_health_state": prev.health_state,
                "current_health_state": cur.health_state,
            },
            timestamp=now,
        ))

    # ── §1.1: Dominant signal score change >= 15 points ──────────────────────
    score_delta = cur.dominant_signal_score - prev.dominant_signal_score
    prev_sig = prev.dominant_signal
    cur_sig = cur.dominant_signal
    if abs(score_delta) >= _DOMINANT_SIGNAL_SCORE_THRESHOLD:
        changes.append(MeaningfulChange(
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
        ))
    elif (
        prev_sig != cur_sig
        and prev_sig is not None
        and cur_sig is not None
        and prev_sig != cur_sig
    ):
        # Different dominant signal even if score delta < 15 — still
        # meaningful because the *reason* for the score changed.
        changes.append(MeaningfulChange(
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
        ))

    # ── §1.2: Progress delta threshold crossing ─────────────────────────────
    _detect_progress_delta_change(prev, cur, now, changes)

    # ── §1.3: Stalled-work signal activation / clearing ──────────────────────
    _detect_stalled_signal_change(prev, cur, now, changes)

    # ── §1.4: Measurement requirement overdue / satisfied ────────────────────
    _detect_measurement_change(prev, cur, now, changes)

    # ── §1.5: Cross-domain link changes ───────────────────────────────────────
    _detect_cross_domain_link_change(prev, cur, now, changes)

    # ── §1.6: Goal status transition ─────────────────────────────────────────
    if prev.goal_status != cur.goal_status:
        changes.append(MeaningfulChange(
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
        ))

    # ── §1.6: Milestone status changes ────────────────────────────────────────
    _detect_milestone_status_change(prev, cur, now, changes)


def _detect_new_goal_changes(
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect changes for a goal that is new in the current snapshot.

    A new goal is meaningful only if it is active and non-healthy, or
    has any signals fired. A brand-new healthy goal is not a strategic
    change (it has no strategic impact yet).
    """
    if cur.goal_status != "active":
        return
    if cur.health_state is None or cur.health_state == "healthy":
        if not cur.signals:
            return
    changes.append(MeaningfulChange(
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
    ))


def _detect_progress_delta_change(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect §1.2: progress delta crossing the slow threshold."""
    prev_delta = prev.progress_delta
    cur_delta = cur.progress_delta

    # Determine if the threshold crossing happened.
    # Fires when delta crosses PROGRESS_SLOW_THRESHOLD (5%) in either
    # direction — i.e., transitions from below-threshold to above, or
    # above to below (clearing).
    if prev_delta is None or cur_delta is None:
        # If we go from no-data to having data, that's a meaningful event
        # only if the delta itself is significant.
        if cur_delta is not None and abs(cur_delta) >= PROGRESS_SLOW_THRESHOLD:
            changes.append(MeaningfulChange(
                change_type=CHANGE_PROGRESS_DELTA,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' progress delta now measurable: "
                    f"{cur_delta:+.1f}% over {PROGRESS_LOOKBACK_DAYS} days "
                    f"(threshold: {PROGRESS_SLOW_THRESHOLD:.0f}%)"
                ),
                severity=3,
                details={
                    "previous_delta": prev_delta,
                    "current_delta": cur_delta,
                    "threshold": PROGRESS_SLOW_THRESHOLD,
                },
                timestamp=now,
            ))
        return

    prev_crossed = prev_delta < PROGRESS_SLOW_THRESHOLD
    cur_crossed = cur_delta < PROGRESS_SLOW_THRESHOLD

    if prev_crossed != cur_crossed:
        direction = "now exceeds" if not cur_crossed else "now below"
        changes.append(MeaningfulChange(
            change_type=CHANGE_PROGRESS_DELTA,
            goal_title=cur.goal_title,
            description=(
                f"Goal '{cur.goal_title}' progress delta {direction} the "
                f"slow-progress threshold: {cur_delta:+.1f}% "
                f"(was {prev_delta:+.1f}%, threshold: {PROGRESS_SLOW_THRESHOLD:.0f}%)"
            ),
            severity=3,
            details={
                "previous_delta": prev_delta,
                "current_delta": cur_delta,
                "threshold": PROGRESS_SLOW_THRESHOLD,
            },
            timestamp=now,
        ))


def _detect_stalled_signal_change(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect §1.3: a stalled-work signal activates or clears.

    Uses frozenset set operations on the signal identifiers.
    A signal activates when it is in ``cur.signals`` but not ``prev.signals``.
    A signal clears when it is in ``prev.signals`` but not ``cur.signals``.
    Only signals in ``_STALLED_SIGNALS`` are considered (spec §1.3).
    """
    prev_stalled = prev.signals & _STALLED_SIGNALS
    cur_stalled = cur.signals & _STALLED_SIGNALS

    activated = cur_stalled - prev_stalled
    cleared = prev_stalled - cur_stalled

    for sig in sorted(activated):
        changes.append(MeaningfulChange(
            change_type=CHANGE_STALLED_SIGNAL,
            goal_title=cur.goal_title,
            description=(
                f"Goal '{cur.goal_title}' stalled-work signal activated: "
                f"{sig}"
            ),
            severity=8,
            details={
                "signal": sig,
                "action": "activated",
                "previous_signals": sorted(prev_stalled),
                "current_signals": sorted(cur_stalled),
            },
            timestamp=now,
        ))

    for sig in sorted(cleared):
        changes.append(MeaningfulChange(
            change_type=CHANGE_STALLED_SIGNAL,
            goal_title=cur.goal_title,
            description=(
                f"Goal '{cur.goal_title}' stalled-work signal cleared: "
                f"{sig}"
            ),
            severity=4,
            details={
                "signal": sig,
                "action": "cleared",
                "previous_signals": sorted(prev_stalled),
                "current_signals": sorted(cur_stalled),
            },
            timestamp=now,
        ))


def _detect_measurement_change(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect §1.4: measurement requirement becomes overdue or satisfied."""
    prev_count = prev.measurement_overdue_count
    cur_count = cur.measurement_overdue_count

    if prev_count == 0 and cur_count > 0:
        changes.append(MeaningfulChange(
            change_type=CHANGE_MEASUREMENT_DUE,
            goal_title=cur.goal_title,
            description=(
                f"Goal '{cur.goal_title}' measurement requirements became "
                f"overdue ({cur_count} now due)"
            ),
            severity=6,
            details={
                "previous_overdue_count": prev_count,
                "current_overdue_count": cur_count,
                "action": "fired",
            },
            timestamp=now,
        ))
    elif prev_count > 0 and cur_count == 0:
        changes.append(MeaningfulChange(
            change_type=CHANGE_MEASUREMENT_DUE,
            goal_title=cur.goal_title,
            description=(
                f"Goal '{cur.goal_title}' measurement requirements satisfied "
                f"(were {prev_count} overdue, now none)"
            ),
            severity=4,
            details={
                "previous_overdue_count": prev_count,
                "current_overdue_count": cur_count,
                "action": "satisfied",
            },
            timestamp=now,
        ))


def _detect_cross_domain_link_change(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect §1.5: cross-domain link changes.

    Compares the sorted lists of linked research artifacts, decision
    numbers, and follow-up IDs between the two snapshots.
    """
    prev_artifacts = set(prev.linked_research_artifacts)
    cur_artifacts = set(cur.linked_research_artifacts)
    new_artifacts = cur_artifacts - prev_artifacts
    if new_artifacts:
        changes.append(MeaningfulChange(
            change_type=CHANGE_CROSS_DOMAIN_LINK,
            goal_title=cur.goal_title,
            description=(
                f"Goal '{cur.goal_title}' gained new cross-domain links: "
                f"research artifacts added — {', '.join(sorted(new_artifacts))}"
            ),
            severity=3,
            details={
                "link_type": "research_artifact",
                "added": sorted(new_artifacts),
                "removed": sorted(prev_artifacts - cur_artifacts),
            },
            timestamp=now,
        ))

    prev_decisions = set(prev.linked_decision_numbers)
    cur_decisions = set(cur.linked_decision_numbers)
    new_decisions = cur_decisions - prev_decisions
    if new_decisions:
        changes.append(MeaningfulChange(
            change_type=CHANGE_CROSS_DOMAIN_LINK,
            goal_title=cur.goal_title,
            description=(
                f"Goal '{cur.goal_title}' gained new cross-domain links: "
                f"decisions added — {', '.join(sorted(new_decisions))}"
            ),
            severity=3,
            details={
                "link_type": "decision",
                "added": sorted(new_decisions),
                "removed": sorted(prev_decisions - cur_decisions),
            },
            timestamp=now,
        ))

    prev_fups = set(prev.linked_followup_ids)
    cur_fups = set(cur.linked_followup_ids)
    new_fups = cur_fups - prev_fups
    if new_fups:
        changes.append(MeaningfulChange(
            change_type=CHANGE_CROSS_DOMAIN_LINK,
            goal_title=cur.goal_title,
            description=(
                f"Goal '{cur.goal_title}' gained new cross-domain links: "
                f"follow-ups added — {', '.join(sorted(new_fups))}"
            ),
            severity=3,
            details={
                "link_type": "followup",
                "added": sorted(new_fups),
                "removed": sorted(prev_fups - cur_fups),
            },
            timestamp=now,
        ))


def _detect_milestone_status_change(
    prev: GoalStateSnapshot,
    cur: GoalStateSnapshot,
    now: datetime,
    changes: list[MeaningfulChange],
) -> None:
    """Detect §1.6: milestone status changes (open → completed | slipped)."""
    prev_ms = prev.milestone_statuses
    cur_ms = cur.milestone_statuses

    all_milestones = set(prev_ms.keys()) | set(cur_ms.keys())
    for ms_title in sorted(all_milestones):
        prev_status = prev_ms.get(ms_title)
        cur_status = cur_ms.get(ms_title)
        if prev_status != cur_status:
            changes.append(MeaningfulChange(
                change_type=CHANGE_MILESTONE_STATUS,
                goal_title=cur.goal_title,
                description=(
                    f"Goal '{cur.goal_title}' milestone '{ms_title}' "
                    f"status changed: {prev_status or 'none'} → "
                    f"{cur_status or 'removed'}"
                ),
                severity=5,
                details={
                    "milestone_title": ms_title,
                    "previous_status": prev_status,
                    "current_status": cur_status if cur_status is not None else "removed",
                },
                timestamp=now,
            ))


# ── Severity helpers ──────────────────────────────────────────────────────────

# Maps health state to a base severity for sorting.
_HEALTH_SEVERITY = {
    "stalled": 20,
    "watch": 15,
    "healthy": 5,
    "completed": 8,
    None: 0,
}


def _health_severity(health_state: str | None) -> int:
    """Map a health state to a base severity score for sorting."""
    return _HEALTH_SEVERITY.get(health_state, 5)


# Maps goal status to a severity for status-transition changes.
_GOAL_STATUS_SEVERITY = {
    "completed": 15,
    "inactive": 10,
    "active": 5,
}


def _goal_status_severity(status: str) -> int:
    """Map a goal status to a severity score for sorting."""
    return _GOAL_STATUS_SEVERITY.get(status, 5)
