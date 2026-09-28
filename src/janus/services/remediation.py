"""Goal remediation engine for Janus (spec §6 decision pipeline, §7 config).

A deterministic, read-only service that consumes goal-health diagnostics
(``assess_goal_health``) and structural-audit results
(``audit_goal_integrity``) and produces **structured** remediation action
suggestions — one or more :class:`RemediationAction` per active goal —
with a typed ``action_type``, typed ``parameters``, preconditions, priority,
and a ``requires_confirmation`` flag.

This engine is **additive**: it does not modify the existing advisory
remediation layer in ``services/recommended_actions.py``. The advisory layer
produces human-readable text; this engine produces structured operations
alongside it (spec §5.3 / §2.2).

The engine is a pure function over an explicit :class:`RemediationContext`
(spec §4.1): no hidden state, no network, no LLM.

Design reference: ``docs/design/goal_remediation_engine_spec.md``.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from janus.models.goal import Goal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.goal_integrity_report import GoalIntegrityIssue
from janus.models.recommended_action import (
    CrossDomainLink,
    TaskRecommendation,
)
from janus.models.remediation import (
    ARCHIVE,
    ESCALATE,
    INVESTIGATE,
    MEASURE,
    NONE,
    NOTIFY,
    REASSIGN,
    RESCHEDULE,
    SPLIT,
    TASK,
    ALL_ACTION_TYPES,
    RemediationAction,
    RemediationSuggestions,
    RemediationSummary,
)
from janus.services.goal_health import (
    DEADLINE_SOON_WINDOW_DAYS,
    INACTIVITY_WINDOW_DAYS,
    PROGRESS_LOOKBACK_DAYS,
    PROGRESS_SLOW_THRESHOLD,
)

logger = logging.getLogger(__name__)

# Days after which a measurement snapshot is considered late (spec §7.1).
# Re-exported here from goal_health for a single source of truth.
MEASUREMENT_DUE_GRACE_DAYS = 2

# ── Configuration: escalation policy (spec §7.2) ─────────────────────────────
# Maps (health_state, min_dominant_signal_score, max_dominant_signal_score)
# → preferred escalation channel. The engine *suggests* the channel; a
# downstream policy gate decides whether to honor it.
ESCALATION_POLICY: dict[tuple[str, int, int], str] = {
    # goal_overdue (100) → high-visibility immediate channel.
    ("stalled", 100, 100): "telegram",
    # milestone_slipped (50–99) → same visibility tier.
    ("stalled", 50, 99): "telegram",
    # Lower-severity stalls (goal_stalled 40 / no_recent_activity 35) →
    # weekly review surface.
    ("stalled", 30, 49): "weekly_review",
    # Watch: measurement_due (45) / deadline_soon — weekly review.
    ("watch", 45, 99): "weekly_review",
    # Watch: low-severity (goal_inactive 30) — strategic summary pin.
    ("watch", 0, 44): "strategic_summary",
}

# Error-severity integrity issue codes (spec §6.2.1) that take structural
# precedence over health-signal-based action selection.
_STRUCTURE_ERROR_CODES = frozenset({
    "UNKNOWN_GOAL_REFERENCE",
    "INVALID_METRIC",
})


@dataclass
class RemediationContext:
    """All inputs required to produce structured remediation suggestions.

    Mirrors spec §4.1. The engine is a pure function over this context.
    """

    # ── Diagnostics (from existing services) ─────────────────────────────
    assessments: list[GoalHealthAssessment]
    goals: list[Goal]
    open_task_titles: set[str]
    all_task_titles: set[str]

    # ── Structural audit (from existing audit service) ─────────────────────
    integrity_issues: list[GoalIntegrityIssue]

    # ── Time / cadence ───────────────────────────────────────────────────────
    today: date
    now: datetime | None = None

    # ── Optional: history (- unlocks escalation persistence) ────────────────
    previous_assessments: dict[str, GoalHealthAssessment] | None = None

    # ── Supporting inputs (for action parameter construction, spec §4.2) ──────
    cross_links: list[CrossDomainLink] = field(default_factory=list)
    task_recommendations: dict[str, list[TaskRecommendation]] = field(
        default_factory=dict
    )
    metric_snapshots: dict[str, list[Any]] = field(default_factory=dict)


# ── Suggestion-id helpers ─────────────────────────────────────────────────────


def _suggestion_id(goal_title: str, action_type: str, parameters: dict[str, Any]) -> str:
    """Stable id for dedup / audit (spec §3.2).

    Composed of ``goal_title + action_type + hashed parameter key``.
    """
    # Build a stable, hashable representation of the parameter *values* that
    # identify the action kind (not free-form text reasons, which may vary).
    key_parts: list[str] = []
    if action_type == MEASURE:
        key_parts.append(str(parameters.get("requirement_index", "")))
        key_parts.append(str(parameters.get("metric_name", "")))
    elif action_type == RESCHEDULE:
        key_parts.append(str(parameters.get("target", "")))
        key_parts.append(str(parameters.get("current_deadline", "")))
    elif action_type == NOTIFY:
        key_parts.append(str(parameters.get("event", "")))
        key_parts.append(str(parameters.get("channel", "")))
    # For most types the (goal, type) pairing is already unique per goal.
    key_text = "|".join([goal_title, action_type, *key_parts])
    digest = hashlib.sha256(key_text.encode("utf-8")).hexdigest()[:12]
    return f"{goal_title}/{action_type}/{digest}"


def _dominant(a: GoalHealthAssessment) -> Any:
    """Convenience accessor for the dominant signal (possibly None)."""
    return a.dominant_signal


def _dominant_score(a: GoalHealthAssessment) -> int:
    d = _dominant(a)
    return d.score if d is not None else 0


def _dominant_signal_name(a: GoalHealthAssessment) -> str:
    d = _dominant(a)
    return d.signal if d is not None else ""


def _dominant_reason(a: GoalHealthAssessment) -> str:
    d = _dominant(a)
    return d.reason if d is not None else ""


def _issues_for_goal(
    integrity_issues: list[GoalIntegrityIssue], goal_title: str,
) -> list[str]:
    """Return the list of integrity-issue codes affecting *goal_title*."""
    return [
        i.code for i in integrity_issues if i.goal_id == goal_title
    ]


def _error_severity_issues(
    integrity_issues: list[GoalIntegrityIssue], goal_title: str,
) -> list[GoalIntegrityIssue]:
    """Return error-severity integrity issues for *goal_title* (spec §6.2.1)."""
    return [
        i
        for i in integrity_issues
        if i.goal_id == goal_title
        and i.severity == "error"
        and i.code in _STRUCTURE_ERROR_CODES
    ]


def _escalation_channel(
    health_state: str, dominant_score: int,
) -> str:
    """Resolve the preferred escalation channel from ESCALATION_POLICY (§7.2)."""
    for (hs, lo, hi), channel in ESCALATION_POLICY.items():
        if hs == health_state and lo <= dominant_score <= hi:
            return channel
    return "weekly_review"


def _inactivity_window(goal: Goal) -> int:
    """Per-goal inactivity window with system default fallback (§7.3)."""
    return goal.inactivity_window_days or INACTIVITY_WINDOW_DAYS


def _build_measure_action(
    goal: Goal, assessment: GoalHealthAssessment, now: datetime,
    ctx: RemediationContext,
) -> RemediationAction | None:
    """Build a single ``measure`` action for the first overdue requirement."""
    snaps = ctx.metric_snapshots.get(goal.title, [])
    from janus.services.goal_health import _FREQUENCY_INTERVAL_DAYS

    if not goal.measurement_requirements:
        return None
    most_overdue: tuple[int, dict, int] | None = None
    for idx, req in enumerate(goal.measurement_requirements):
        metric = req.get("metric")
        if not metric:
            continue
        frequency = req.get("frequency", "daily")
        interval_days = req.get("interval_days")
        if frequency == "custom" and interval_days is None:
            continue
        if frequency not in _FREQUENCY_INTERVAL_DAYS and frequency != "custom":
            continue
        interval = (
            interval_days if frequency == "custom"
            else _FREQUENCY_INTERVAL_DAYS[frequency]
        )
        assert interval is not None
        due_after = interval + MEASUREMENT_DUE_GRACE_DAYS
        relevant = [s for s in snaps if s.metric_name == metric]
        if not relevant:
            days_overdue = due_after  # not yet collected
        else:
            most_recent = max(relevant, key=lambda s: s.timestamp)
            days_overdue = (now - most_recent.timestamp).days
        if days_overdue >= due_after:
            if most_overdue is None or days_overdue > most_overdue[2]:
                most_overdue = (idx, req, days_overdue)

    if most_overdue is None:
        return None

    idx, req, days_overdue = most_overdue
    params = {
        "metric_name": req.get("metric"),
        "frequency": req.get("frequency", "daily"),
        "days_overdue": days_overdue,
        "requirement_index": idx,
    }
    last_snapshot_date = None
    relevant = [s for s in snaps if s.metric_name == req.get("metric")]
    if relevant:
        last_snapshot_date = max(
            s.timestamp for s in relevant
        ).date().isoformat()
    if last_snapshot_date:
        params["last_snapshot_date"] = last_snapshot_date

    return _make_action(
        goal_title=goal.title,
        action_type=MEASURE,
        parameters=params,
        assessment=assessment,
        priority=_rule_priority(assessment),
    )


def _rule_priority(assessment: GoalHealthAssessment) -> int:
    """Base priority from the dominant-signal advisory rule table.

    Reuses the existing ``_REMEDIATION_RULES`` priorities (spec §3.3).
    """
    from janus.services.recommended_actions import (
        _REMEDIATION_RULES,
        _HEALTH_STATE_DEFAULT_PRIORITY,
    )

    d = _dominant(assessment)
    signal_key = d.signal if d else ""
    if not signal_key:
        signal_key = assessment.health_state
    rule = _REMEDIATION_RULES.get(signal_key)
    if rule is not None:
        _text, priority = rule
        return priority
    return _HEALTH_STATE_DEFAULT_PRIORITY.get(assessment.health_state, 20)


def _make_action(
    goal_title: str,
    action_type: str,
    parameters: dict[str, Any],
    assessment: GoalHealthAssessment,
    priority: int,
    structural_issues: list[str] | None = None,
) -> RemediationAction:
    """Construct a ``RemediationAction`` with diagnosis fields populated."""
    structural_issues = structural_issues or []
    params = dict(parameters)
    return RemediationAction(
        goal_title=goal_title,
        action_type=action_type,
        suggestion_id=_suggestion_id(goal_title, action_type, params),
        health_state=assessment.health_state,
        dominant_signal=_dominant_signal_name(assessment),
        dominant_signal_score=_dominant_score(assessment),
        dominant_signal_reason=_dominant_reason(assessment),
        structural_issues=list(structural_issues),
        parameters=params,
        priority=priority,
    )


# ── Per-goal primary action selection (spec §6) ──────────────────────────────


def _select_primary_action(
    goal: Goal,
    assessment: GoalHealthAssessment,
    integrity_issues: list[GoalIntegrityIssue],
    ctx: RemediationContext,
) -> RemediationAction | None:
    """Select the primary (or only) action for a goal (spec §6.1–6.2)."""
    # §6.1 — healthy → none.
    if assessment.health_state == "healthy":
        return _make_action(
            goal_title=goal.title,
            action_type=NONE,
            parameters={"reason": "Goal is on track. No structured remediation needed."},
            assessment=assessment,
            priority=0,
        )

    # §6.1 / §6.2.1 — excluded states produce no action.
    if assessment.health_state in ("completed",):
        return None

    err_issues = _error_severity_issues(integrity_issues, goal.title)

    # §6.2.1 — structural integrity error takes precedence.
    if err_issues:
        codes = [e.code for e in err_issues]
        for issue in err_issues:
            if issue.code == "UNKNOWN_GOAL_REFERENCE":
                reason = (
                    "Orphaned task references goal; reassign the task "
                    "to an existing goal or remove the stale reference."
                )
                # Reattach the referenced task to a goal if it is a known
                # orphan with no goal link.
                structural = codes
                primary = _make_action(
                    goal_title=goal.title,
                    action_type=REASSIGN,
                    parameters={
                        "reason": reason,
                        "structural_issue": issue.code,
                    },
                    assessment=assessment,
                    priority=_rule_priority(assessment) + 5,
                    structural_issues=structural,
                )
                return primary
            # INVALID_METRIC → reschedule with a review rationale.
            return _make_action(
                goal_title=goal.title,
                action_type=RESCHEDULE,
                parameters={
                    "target": "goal",
                    "current_deadline": goal.deadline or "",
                    "reason": (
                        "Metric configuration is invalid — review and "
                        "fix the metric before measuring."
                    ),
                },
                assessment=assessment,
                priority=_rule_priority(assessment) + 5,
                structural_issues=codes,
            )

    dominant = _dominant_signal_name(assessment)
    score = _dominant_score(assessment)
    state = assessment.health_state

    primary: RemediationAction | None = None

    if state == "watch":
        # §6.2.2 — watch-signal table.
        if dominant == "progress_slow":
            primary = _make_action(
                goal_title=goal.title,
                action_type=TASK,
                parameters={
                    "suggested_reason": (
                        "Progress is slow; add a smaller concrete next step."
                    ),
                    "suggested_title": _next_task_title(goal, assessment),
                },
                assessment=assessment,
                priority=_rule_priority(assessment),
            )
        elif dominant == "progress_regressing":
            primary = _make_action(
                goal_title=goal.title,
                action_type=INVESTIGATE,
                parameters=_investigate_params(goal, ctx),
                assessment=assessment,
                priority=_rule_priority(assessment),
            )
        elif dominant == "measurement_due":
            primary = _build_measure_action(goal, assessment, ctx.now or datetime.now().astimezone(), ctx)
        elif dominant in ("goal_deadline_soon", "milestone_deadline_soon"):
            # §6.2.2: if no open tasks → reschedule; else healthy (but we
            # only reach here for watch, meaning progress is slow — reschedule).
            if not any(rt in ctx.open_task_titles for rt in goal.related_tasks):
                primary = _make_action(
                    goal_title=goal.title,
                    action_type=RESCHEDULE,
                    parameters={
                        "target": "goal" if dominant == "goal_deadline_soon" else "milestone",
                        "current_deadline": goal.deadline or "",
                        "reason": "Deadline is approaching with no open tasks to meet it.",
                    },
                    assessment=assessment,
                    priority=_rule_priority(assessment),
                )
            else:
                primary = _make_action(
                    goal_title=goal.title,
                    action_type=NONE,
                    parameters={"reason": "Open tasks in progress — deadline urgency is expected."},
                    assessment=assessment,
                    priority=0,
                )
        elif dominant == "goal_inactive":
            primary = _make_action(
                goal_title=goal.title,
                action_type=TASK,
                parameters={
                    "suggested_reason": "No forward plan defined; add a future milestone or next action.",
                    "suggested_title": _next_task_title(goal, assessment),
                },
                assessment=assessment,
                priority=_rule_priority(assessment),
            )
        else:
            # §6.2.2 — default for watch goals that don't match a specific rule.
            primary = _make_action(
                goal_title=goal.title,
                action_type=INVESTIGATE,
                parameters=_investigate_params(goal, ctx),
                assessment=assessment,
                priority=_rule_priority(assessment),
            )

        # §6.2.2 escalation override for neglected watch goals whose dominant
        # signal score ≥ 45. Does not override informational primaries
        # (investigate) — those already surface context for operator decision.
        if (
            primary
            and primary.action_type not in (INVESTIGATE, NOTIFY, NONE)
            and score >= 45
            and _is_neglected(goal, assessment, ctx)
        ):
            primary = _make_action(
                goal_title=goal.title,
                action_type=ESCALATE,
                parameters={
                    "channel": _escalation_channel(state, score),
                    "reason": (
                        "Watch goal has crossed the neglected threshold "
                        "with a high-severity signal."
                    ),
                    "health_state": state,
                    "dominant_signal": dominant,
                },
                assessment=assessment,
                priority=_rule_priority(assessment),
            )

    elif state == "stalled":
        # §6.2.3 — stalled-signal table.
        if dominant == "goal_overdue":
            primary = _make_action(
                goal_title=goal.title,
                action_type=ESCALATE,
                parameters={
                    "channel": _escalation_channel(state, score),
                    "reason": "Deadline has passed with no open tasks.",
                    "health_state": state,
                    "dominant_signal": dominant,
                },
                assessment=assessment,
                priority=_rule_priority(assessment),
            )
        elif dominant == "milestone_slipped":
            primary = _make_action(
                goal_title=goal.title,
                action_type=ESCALATE,
                parameters={
                    "channel": _escalation_channel(state, score),
                    "reason": "Milestone deadline was missed.",
                    "health_state": state,
                    "dominant_signal": dominant,
                },
                assessment=assessment,
                priority=_rule_priority(assessment),
            )
        elif dominant == "goal_stalled":
            primary = _make_action(
                goal_title=goal.title,
                action_type=TASK,
                parameters={
                    "suggested_reason": "All linked tasks are completed; define the next step.",
                    "suggested_title": _next_task_title(goal, assessment),
                },
                assessment=assessment,
                priority=_rule_priority(assessment),
            )
        elif dominant == "no_recent_activity":
            days = assessment.days_since_last_activity
            window = _inactivity_window(goal)
            if days is not None and days > 2 * window:
                primary = _make_action(
                    goal_title=goal.title,
                    action_type=ARCHIVE,
                    parameters={
                        "rationale": (
                            f"No activity for {days} days (>{2 * window} "
                            f"window) — appears abandoned."
                        ),
                        "target_status": "inactive",
                        "preserve_cross_links": True,
                    },
                    assessment=assessment,
                    priority=_rule_priority(assessment),
                )
            else:
                primary = _make_action(
                    goal_title=goal.title,
                    action_type=ESCALATE,
                    parameters={
                        "channel": _escalation_channel(state, score),
                        "reason": "Prolonged inactivity — escalate and offer a starter task.",
                        "health_state": state,
                        "dominant_signal": dominant,
                    },
                    assessment=assessment,
                    priority=_rule_priority(assessment),
                )
        else:
            # §6.2.4 edge case: stalled but no dominant signal.
            primary = _make_action(
                goal_title=goal.title,
                action_type=INVESTIGATE,
                parameters=_investigate_params(goal, ctx),
                assessment=assessment,
                priority=_rule_priority(assessment),
            )

    if primary is None:
        # No dominant signal but in an unhealthy state — degrade safely.
        primary = _make_action(
            goal_title=goal.title,
            action_type=INVESTIGATE,
            parameters=_investigate_params(goal, ctx),
            assessment=assessment,
            priority=_rule_priority(assessment),
        )

    return primary


def _next_task_title(goal: Goal, assessment: GoalHealthAssessment) -> str:
    """Pick a concrete next-task title from recommendations, or a fallback."""
    dominant = _dominant_signal_name(assessment)
    if dominant in ("goal_stalled", "goal_inactive"):
        return f"Define next step for {goal.title}"
    if dominant == "progress_slow":
        return f"Break down next task for {goal.title}"
    if dominant == "progress_regressing":
        return f"Re-establish baseline for {goal.title}"
    return f"Define next step for {goal.title}"


def _investigate_params(goal: Goal, ctx: RemediationContext) -> dict[str, Any]:
    """Build parameter bag for an ``investigate`` action (spec §5.2)."""
    links = [l for l in ctx.cross_links if l.goal_title == goal.title]
    cats = sorted({l.category for l in links})
    titles = [l.title for l in links]
    return {
        "link_categories": cats,
        "link_titles": titles,
        "reason": (
            "No specific signal triggered a concrete action; "
            "surface cross-domain context for operator decision."
        ),
    }


def _is_neglected(
    goal: Goal, assessment: GoalHealthAssessment, ctx: RemediationContext,
) -> bool:
    """Whether a watch goal crosses the neglected threshold (§6.2.2).

    Reuses the existing ``identify_neglected_goals`` semantics.
    """
    from janus.services.recommended_actions import identify_neglected_goals

    if goal.status in ("inactive", "completed"):
        return False
    results = identify_neglected_goals(
        [assessment], [goal], ctx.open_task_titles, ctx.today,
    )
    return any(a.goal_title == goal.title for a in results)


# ── Secondary actions (spec §6.2.4) ──────────────────────────────────────────


def _attach_secondaries(
    goal: Goal,
    primary: RemediationAction | None,
    assessment: GoalHealthAssessment,
    integrity_issues: list[GoalIntegrityIssue],
    ctx: RemediationContext,
    now: datetime,
) -> list[RemediationAction]:
    """Return secondary actions to attach to a goal (spec §6.2.4)."""
    secondaries: list[RemediationAction] = []
    dominant_code = primary.action_type if primary else ""

    # Condition 1: cross-domain links AND primary is not already investigate.
    links = [l for l in ctx.cross_links if l.goal_title == goal.title]
    if links and dominant_code != INVESTIGATE:
        secondaries.append(_make_action(
            goal_title=goal.title,
            action_type=INVESTIGATE,
            parameters=_investigate_params(goal, ctx),
            assessment=assessment,
            priority=_rule_priority(assessment),
        ))

    # Condition 2: measurement_overdue_count > 0 AND primary is not measure.
    if (
        assessment.measurement_overdue_count > 0
        and dominant_code != MEASURE
    ):
        measure_action = _build_measure_action(goal, assessment, now, ctx)
        if measure_action is not None:
            secondaries.append(measure_action)

    # Condition 3: days_since_last_activity > window AND primary not archive/escalate.
    days = assessment.days_since_last_activity
    window = _inactivity_window(goal)
    if (
        days is not None
        and days > window
        and dominant_code not in (ARCHIVE, ESCALATE)
    ):
        secondaries.append(_make_action(
            goal_title=goal.title,
            action_type=TASK,
            parameters={
                "suggested_reason": (
                    f"No activity for {days} days; add a small starter task."
                ),
                "suggested_title": _next_task_title(goal, assessment),
            },
            assessment=assessment,
            priority=_rule_priority(assessment),
        ))

    # Condition 4: GOAL_WITHOUT_TASKS → task as secondary.
    codes = _issues_for_goal(integrity_issues, goal.title)
    if "GOAL_WITHOUT_TASKS" in codes and dominant_code != TASK:
        secondaries.append(_make_action(
            goal_title=goal.title,
            action_type=TASK,
            parameters={
                "suggested_reason": "Goal has no related tasks; create a next task.",
                "suggested_title": _next_task_title(goal, assessment),
            },
            assessment=assessment,
            priority=_rule_priority(assessment),
        ))

    return secondaries


# ── Deduplication (spec §6.3) ─────────────────────────────────────────────────


def _dedup_actions(actions: list[RemediationAction]) -> list[RemediationAction]:
    """Dedup by ``suggestion_id`` (spec §6.3).

    Two actions with the same (goal_title, action_type) and identical
    parameter-key are merged: their ``structural_issues`` and ``parameters``
    are combined. ``task`` actions merge their reasons.
    """
    seen: dict[str, RemediationAction] = {}
    order: list[str] = []
    for action in actions:
        sid = action.suggestion_id
        # Normalize the suggestion id key: for merge purposes, treat
        # actions differing only in free-text reason as mergeable.
        merge_key = f"{action.goal_title}|{action.action_type}"
        if merge_key in seen:
            existing = seen[merge_key]
            # Merge structural issues (dedup, preserve order).
            merged_issues = list(existing.structural_issues)
            for issue in action.structural_issues:
                if issue not in merged_issues:
                    merged_issues.append(issue)
            # Merge parameters: combine text-like fields.
            merged_params = dict(existing.parameters)
            if action.action_type == TASK:
                reasons = [
                    r for r in (merged_params.get("suggested_reason", ""),
                                action.parameters.get("suggested_reason", ""))
                    if r
                ]
                merged_params["suggested_reason"] = " / ".join(reasons)
            merged = _make_action(
                goal_title=existing.goal_title,
                action_type=existing.action_type,
                parameters=merged_params,
                assessment=_assessment_from(existing, action),
                priority=max(existing.priority, action.priority),
                structural_issues=merged_issues,
            )
            # RemediationAction is frozen; use object.__setattr__ to set
            # the stable suggestion_id after construction (spec §6.3 dedup).
            object.__setattr__(merged, "suggestion_id", sid)
            seen[merge_key] = merged
        else:
            seen[merge_key] = action
            order.append(merge_key)
    return [seen[k] for k in order]


def _assessment_from(a: RemediationAction, b: RemediationAction) -> GoalHealthAssessment:
    """Reconstruct a minimal GoalHealthAssessment carrying merged diagnosis.

    ``_make_action`` only needs health_state, dominant signal fields, which
    are preserved from the primary action.
    """
    from janus.models.goal_signal import GoalSignal

    signal = None
    if a.dominant_signal:
        signal = GoalSignal(
            signal=a.dominant_signal,
            score=a.dominant_signal_score,
            reason=a.dominant_signal_reason,
            timestamp=datetime.now(),
        )
    return GoalHealthAssessment(
        goal_title=a.goal_title,
        health_state=a.health_state,
        signals=[signal] if signal else [],
        dominant_signal=signal,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def create_remediation_suggestions(
    ctx: RemediationContext,
) -> RemediationSuggestions:
    """Produce structured remediation suggestions from a diagnostics context.

    Implements spec §6 (decision pipeline): per-goal classification →
    action-type selection → parameter construction → priority + dedup.

    The engine is deterministic given its inputs (spec §6.4) and read-only:
    it does not modify goals, tasks, metrics, or send notifications.

    Args:
        ctx: A fully-populated :class:`RemediationContext` (spec §4.1).
            Assessments and integrity issues must be pre-computed by the
            caller so the engine stays pure and testable.

    Returns:
        A :class:`RemediationSuggestions` containing all per-goal actions.
    """
    now = ctx.now or datetime.now().astimezone()
    generated_at = now

    goals_by_title = {g.title: g for g in ctx.goals}
    assessments_by_title = {a.goal_title: a for a in ctx.assessments}

    # Index structural issues per goal.
    issues_by_goal: dict[str, list[GoalIntegrityIssue]] = {}
    for issue in ctx.integrity_issues:
        if issue.goal_id:
            issues_by_goal.setdefault(issue.goal_id, []).append(issue)

    per_goal: list[RemediationAction] = []

    for assessment in ctx.assessments:
        goal = goals_by_title.get(assessment.goal_title)
        if goal is None:
            # Assessment without a goal object — skip (no goal to act on).
            continue

        goal_issues = issues_by_goal.get(goal.title, [])

        # §6.1 — completed/inactive goals are excluded.
        if assessment.health_state in ("completed",):
            continue
        if goal.status == "inactive":
            continue

        primary = _select_primary_action(
            goal, assessment, goal_issues, ctx,
        )
        if primary is not None:
            per_goal.append(primary)
        # §6.1: healthy goals produce only a `none` action — skip secondaries.
        if assessment.health_state == "healthy":
            continue
        secondaries = _attach_secondaries(
            goal, primary, assessment, goal_issues, ctx, now,
        )
        per_goal.extend(secondaries)

    deduped = _dedup_actions(per_goal)

    summary = _build_summary(deduped, assessments_by_title, generated_at)
    return RemediationSuggestions(
        generated_at=generated_at,
        per_goal=deduped,
        summary=summary,
    )


def _build_summary(
    actions: list[RemediationAction],
    assessments_by_title: dict[str, GoalHealthAssessment],
    generated_at: datetime,
) -> RemediationSummary:
    """Build the aggregate ``RemediationSummary`` (spec §5.1)."""
    by_type: dict[str, int] = {}
    by_health_state: dict[str, int] = {}
    goals_with_actions: set[str] = set()
    stalled_titles: list[str] = []

    for action in actions:
        by_type[action.action_type] = by_type.get(action.action_type, 0) + 1
        by_health_state[action.health_state] = (
            by_health_state.get(action.health_state, 0) + 1
        )
        goals_with_actions.add(action.goal_title)
        if action.health_state == "stalled":
            stalled_titles.append(action.goal_title)

    needs_confirmation_count = sum(
        1 for a in actions if a.requires_confirmation
    )

    highest_priority_action = None
    if actions:
        highest_priority_action = max(
            actions, key=lambda a: (a.priority, a.action_type)
        )

    # Include healthy goals that produced a `none` action in the count of
    # goals evaluated, but only count goals with real actions in
    # goals_with_actions.
    real_actions = [a for a in actions if a.action_type != NONE]
    goals_with_real_actions = {a.goal_title for a in real_actions}

    return RemediationSummary(
        goals_with_actions=len(goals_with_real_actions),
        by_type=by_type,
        by_health_state=by_health_state,
        stalled_goal_titles=sorted(set(stalled_titles)),
        needs_confirmation_count=needs_confirmation_count,
        highest_priority_action=highest_priority_action,
    )
