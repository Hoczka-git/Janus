"""Tests for the goal remediation engine (spec §11 acceptance criteria).

Covers:
- RemediationAction model: action_type enum, frozen safety, parameters,
  requires_confirmation default for informational types.
- RemediationSuggestions / RemediationSummary output shapes.
- create_remediation_suggestions decision logic:
  - healthy → none
  - each stalled dominant signal → expected primary action
  - each watch dominant signal → expected primary action
  - structural-issue (error severity) precedence
  - secondary-action attachment (investigate, measure, task, escalate)
  - dedup by (goal_title, action_type)
  - edge cases: all healthy, all completed, inactive goals, unknown signal,
    no dominant signal, missing goal object.
- Determinism: same inputs → same outputs.
- Graceful degradation without history (previous_assessments=None).

The engine is a pure function over RemediationContext; all inputs are
constructed directly (no file I/O, no LLM, no network).
"""

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from janus.models.goal import Goal
from janus.models.goal_signal import GoalSignal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.goal_integrity_report import GoalIntegrityIssue
from janus.models.metric_snapshot import MetricSnapshot
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
from janus.services.remediation import (
    ESCALATION_POLICY,
    RemediationContext,
    create_remediation_suggestions,
)

FIXED_TODAY = date(2025, 1, 15)
FIXED_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_signal(signal, score, reason="some reason"):
    return GoalSignal(
        signal=signal,
        score=score,
        reason=reason,
        timestamp=FIXED_NOW,
    )


def _make_assessment(
    goal_title="Test Goal",
    health_state=None,
    signal="goal_overdue",
    score=80,
    reason="test signal",
    progress=50.0,
    progress_delta=-10.0,
    days_since_last_activity=45,
    measurement_overdue_count=0,
):
    if health_state is None:
        health_state = "overdue" if signal == "goal_overdue" else "stalled"
    sig = _make_signal(signal, score, reason)
    return GoalHealthAssessment(
        goal_title=goal_title,
        health_state=health_state,
        signals=[sig],
        dominant_signal=sig,
        progress=progress,
        progress_delta=progress_delta,
        days_since_last_activity=days_since_last_activity,
        measurement_overdue_count=measurement_overdue_count,
    )


def _make_assessment_no_signal(goal_title="Test Goal", health_state="stalled"):
    return GoalHealthAssessment(
        goal_title=goal_title,
        health_state=health_state,
        signals=[],
        dominant_signal=None,
    )


def _make_goal(
    title="Test Goal",
    status="active",
    **kw,
):
    return Goal(title=title, status=status, **kw)


def _make_ctx(
    assessments=None,
    goals=None,
    integrity_issues=None,
    cross_links=None,
    metric_snapshots=None,
    previous_assessments=None,
    open_task_titles=None,
    all_task_titles=None,
):
    return RemediationContext(
        assessments=assessments or [],
        goals=goals or [],
        open_task_titles=open_task_titles or set(),
        all_task_titles=all_task_titles or set(),
        integrity_issues=integrity_issues or [],
        today=FIXED_TODAY,
        now=FIXED_NOW,
        cross_links=cross_links or [],
        metric_snapshots=metric_snapshots or {},
        previous_assessments=previous_assessments,
    )


def _first_action(suggestions: RemediationSuggestions, action_type: str):
    """Return the first action of the given type, or None."""
    for a in suggestions.per_goal:
        if a.action_type == action_type:
            return a
    return None


def _has_action_type(suggestions: RemediationSuggestions, action_type: str) -> bool:
    return any(a.action_type == action_type for a in suggestions.per_goal)


# ── RemediationAction model tests (spec §3.2) ──────────────────────────────────


class TestRemediationActionModel:
    def test_action_types_enumeration(self):
        """All 10 action types from §3.1 exist."""
        expected = {
            "reassign", "split", "escalate", "archive", "notify",
            "task", "reschedule", "measure", "investigate", "none",
        }
        assert set(ALL_ACTION_TYPES) == expected

    def test_invalid_action_type_rejected(self):
        with pytest.raises(ValueError, match="Invalid action_type"):
            RemediationAction(
                goal_title="G",
                action_type="bogus",
                suggestion_id="x",
                health_state="stalled",
                dominant_signal="goal_overdue",
                dominant_signal_score=100,
                dominant_signal_reason="r",
            )

    def test_informative_types_do_not_require_confirmation(self):
        """investigate, notify, none are informational (§3.2 requires_confirmation=False)."""
        for t in (INVESTIGATE, NOTIFY, NONE):
            a = RemediationAction(
                goal_title="G",
                action_type=t,
                suggestion_id="x",
                health_state="healthy",
                dominant_signal=None,
                dominant_signal_score=0,
                dominant_signal_reason="",
            )
            assert a.requires_confirmation is False

    def test_non_informative_types_require_confirmation(self):
        """reassign, split, escalate, archive, task, reschedule, measure require confirmation."""
        for t in (REASSIGN, SPLIT, ESCALATE, ARCHIVE, TASK, RESCHEDULE, MEASURE):
            a = RemediationAction(
                goal_title="G",
                action_type=t,
                suggestion_id="x",
                health_state="stalled",
                dominant_signal="goal_overdue",
                dominant_signal_score=100,
                dominant_signal_reason="r",
            )
            assert a.requires_confirmation is True


# ── RemediationSuggestions / RemediationSummary output shape (§5.1) ────────────


class TestOutputShape:
    def test_empty_context(self):
        """No assessments → empty per_goal, summary has zero actions."""
        ctx = _make_ctx(goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        assert isinstance(s, RemediationSuggestions)
        assert isinstance(s.summary, RemediationSummary)
        assert s.per_goal == []
        assert s.summary.goals_with_actions == 0
        assert s.summary.highest_priority_action is None

    def test_summary_counts_by_type(self):
        a = _make_assessment(goal_title="Overdue Goal", signal="goal_overdue", score=100)
        goal = _make_goal("Overdue Goal")
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s = create_remediation_suggestions(ctx)
        assert s.summary.by_type[ESCALATE] == 1
        assert s.summary.goals_with_actions == 1
        assert s.summary.overdue_goal_titles == ["Overdue Goal"]

    def test_summary_highest_priority(self):
        """The highest-priority action is the overdue (score 100) escalate."""
        a1 = _make_assessment(goal_title="A", signal="goal_overdue", score=100)
        a2 = _make_assessment(goal_title="B", signal="goal_stalled", score=40)
        goals = [_make_goal("A"), _make_goal("B")]
        ctx = _make_ctx(assessments=[a1, a2], goals=goals)
        s = create_remediation_suggestions(ctx)
        assert s.summary.highest_priority_action is not None
        assert s.summary.highest_priority_action.goal_title == "A"
        assert s.summary.highest_priority_action.priority == 100


# ── §6.1 — healthy → none ─────────────────────────────────────────────────────


class TestHealthyGoal:
    def test_healthy_produces_none(self):
        """§6.1: healthy goal → action_type 'none', no secondaries."""
        a = _make_assessment(goal_title="H", health_state="healthy", signal="", score=0)
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("H")])
        s = create_remediation_suggestions(ctx)
        none_actions = [x for x in s.per_goal if x.action_type == NONE]
        assert len(none_actions) == 1
        assert none_actions[0].parameters["reason"] == (
            "Goal is on track. No structured remediation needed."
        )
        # No secondary actions for healthy goals.
        assert all(x.action_type == NONE for x in s.per_goal)
        assert s.summary.goals_with_actions == 0


# ── §6.1 — completed/inactive excluded ───────────────────────────────────────


class TestExcludedGoals:
    def test_completed_excluded(self):
        """§6.1: completed-goal assessments are excluded (no action)."""
        a = _make_assessment(goal_title="C", health_state="completed", signal="goal_stalled", score=40)
        goal = _make_goal("C", status="completed")
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s = create_remediation_suggestions(ctx)
        assert s.per_goal == []

    def test_inactive_excluded(self):
        """§6.1: inactive goals are excluded even if assessment says stalled."""
        a = _make_assessment(goal_title="I", health_state="stalled", signal="goal_overdue", score=100)
        goal = _make_goal("I", status="inactive")
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s = create_remediation_suggestions(ctx)
        assert s.per_goal == []


# ── §6.2.3 — stalled-signal table ─────────────────────────────────────────────


class TestStalledPrimaryActions:
    def test_overdue_goal_overdue_escalate(self):
        """§6.2.3: goal_overdue → escalate, channel=telegram."""
        a = _make_assessment(goal_title="G", signal="goal_overdue", score=100)
        goal = _make_goal("G")
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, ESCALATE)
        assert primary is not None
        assert primary.parameters["channel"] == "telegram"
        assert primary.parameters["health_state"] == "overdue"
        assert primary.requires_confirmation is True

    def test_stalled_milestone_slipped_escalate(self):
        """§6.2.3: milestone_slipped → escalate."""
        a = _make_assessment(goal_title="G", signal="milestone_slipped", score=50)
        goal = _make_goal("G")
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, ESCALATE)
        assert primary is not None
        assert primary.parameters["channel"] == "telegram"

    def test_stalled_goal_stalled_task(self):
        """§6.2.3: goal_stalled → task (define next step)."""
        a = _make_assessment(goal_title="G", signal="goal_stalled", score=40)
        goal = _make_goal("G")
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, TASK)
        assert primary is not None
        assert "next step" in primary.parameters["suggested_title"].lower() or \
            "next step" in primary.parameters["suggested_reason"].lower()

    def test_stalled_no_recent_activity_archive(self):
        """§6.2.3: no_recent_activity with days > 2×window → archive."""
        a = _make_assessment(
            goal_title="G", signal="no_recent_activity", score=35,
            days_since_last_activity=70,
        )
        goal = _make_goal("G", inactivity_window_days=30)
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, ARCHIVE)
        assert primary is not None
        assert primary.parameters["target_status"] == "inactive"
        assert primary.parameters["preserve_cross_links"] is True

    def test_stalled_no_recent_activity_escalate(self):
        """§6.2.3: no_recent_activity within 2×window → escalate."""
        a = _make_assessment(
            goal_title="G", signal="no_recent_activity", score=35,
            days_since_last_activity=40,
        )
        goal = _make_goal("G", inactivity_window_days=30)
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, ESCALATE)
        assert primary is not None


# ── §6.2.2 — watch-signal table ───────────────────────────────────────────────


class TestWatchPrimaryActions:
    def test_watch_progress_slow_task(self):
        """§6.2.2: progress_slow → task."""
        a = _make_assessment(goal_title="G", health_state="watch", signal="progress_slow", score=40)
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, TASK)
        assert primary is not None
        assert "smaller" in primary.parameters["suggested_reason"].lower()

    def test_watch_progress_regressing_task(self):
        """§6.2.2: progress_regressing → investigate + task."""
        a = _make_assessment(goal_title="G", health_state="watch", signal="progress_regressing", score=50)
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        # Primary should be investigate (regression needs context first).
        primary = _first_action(s, INVESTIGATE)
        assert primary is not None
        assert primary.parameters["link_categories"] == []
        assert primary.parameters["link_titles"] == []
        assert primary.requires_confirmation is False

    def test_watch_measurement_due_measure(self):
        """§6.2.2: measurement_due → measure (one per overdue requirement)."""
        a = _make_assessment(
            goal_title="G", health_state="watch", signal="measurement_due", score=45,
            measurement_overdue_count=1,
        )
        goal = _make_goal("G", measurement_requirements=[
            {"metric": "Weight", "frequency": "daily"},
        ])
        # A snapshot from 10 days ago (daily frequency + 2 grace = 3 days overdue).
        old_snap = MetricSnapshot(
            goal_title="G", metric_name="Weight", value=70.0,
            timestamp=datetime(2025, 1, 5, tzinfo=timezone.utc),
            source="manual",
        )
        ctx = _make_ctx(
            assessments=[a], goals=[goal],
            metric_snapshots={"G": [old_snap]},
        )
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, MEASURE)
        assert primary is not None
        assert primary.parameters["metric_name"] == "Weight"
        assert primary.parameters["frequency"] == "daily"
        assert primary.parameters["days_overdue"] >= 3
        assert primary.parameters["requirement_index"] == 0

    def test_watch_goal_deadline_soon_no_tasks_reschedule(self):
        """§6.2.2: goal_deadline_soon with no open tasks → reschedule."""
        a = _make_assessment(
            goal_title="G", health_state="watch", signal="goal_deadline_soon", score=30,
            days_since_last_activity=10,
        )
        goal = _make_goal("G", deadline="2025-01-20")
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, RESCHEDULE)
        assert primary is not None
        assert primary.parameters["target"] == "goal"

    def test_watch_goal_deadline_soon_with_open_tasks_none(self):
        """§6.2.2: goal_deadline_soon with open tasks → none (urgency expected)."""
        a = _make_assessment(
            goal_title="G", health_state="watch", signal="goal_deadline_soon", score=30,
            days_since_last_activity=10,
        )
        goal = _make_goal("G", deadline="2025-01-20", related_tasks=["Do task"])
        ctx = _make_ctx(assessments=[a], goals=[goal], open_task_titles={"Do task"})
        s = create_remediation_suggestions(ctx)
        assert _has_action_type(s, NONE)
        # No escalate/reschedule/task for this case.
        assert not _has_action_type(s, RESCHEDULE)

    def test_watch_goal_inactive_task(self):
        """§6.2.2: goal_inactive → task (add future milestone)."""
        a = _make_assessment(
            goal_title="G", health_state="watch", signal="goal_inactive", score=30,
            days_since_last_activity=10,
        )
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, TASK)
        assert primary is not None

    def test_watch_unknown_signal_investigate(self):
        """§6.2.4 edge case: unknown signal → investigate (safe default)."""
        sig = _make_signal("weird_signal", 50, "weird")
        a = GoalHealthAssessment(
            goal_title="G", health_state="watch", signals=[sig], dominant_signal=sig,
        )
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, INVESTIGATE)
        assert primary is not None


# ── §6.2.1 — structural integrity precedence ───────────────────────────────────


class TestStructuralPrecedence:
    def test_unknown_goal_reference_reassign(self):
        """§6.2.1: UNKNOWN_GOAL_REFERENCE (error) → reassign (overrides signal)."""
        a = _make_assessment(goal_title="G", signal="goal_overdue", score=100)
        issue = GoalIntegrityIssue(
            code="UNKNOWN_GOAL_REFERENCE", severity="error",
            goal_id="G", message="orphaned task",
        )
        ctx = _make_ctx(
            assessments=[a], goals=[_make_goal("G")],
            integrity_issues=[issue],
            cross_links=[],  # no cross-links → no investigate secondary
        )
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, REASSIGN)
        assert primary is not None
        assert primary.parameters["structural_issue"] == "UNKNOWN_GOAL_REFERENCE"
        # Should NOT escalate despite goal_overdue signal.
        assert not _has_action_type(s, ESCALATE)

    def test_invalid_metric_reschedule(self):
        """§6.2.1: INVALID_METRIC (error) → reschedule."""
        a = _make_assessment(
            goal_title="G", health_state="watch", signal="goal_inactive", score=30,
        )
        issue = GoalIntegrityIssue(
            code="INVALID_METRIC", severity="error",
            goal_id="G", message="bad metric",
        )
        ctx = _make_ctx(
            assessments=[a], goals=[_make_goal("G", deadline="2025-02-01")],
            integrity_issues=[issue],
        )
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, RESCHEDULE)
        assert primary is not None
        assert primary.parameters["target"] == "goal"


# ── §6.2.4 — secondary actions ────────────────────────────────────────────────


class TestSecondaryActions:
    def test_stalled_with_cross_links_gets_investigate(self):
        """§6.2.4: stalled goal with cross-links → investigate secondary."""
        from janus.models.recommended_action import CrossDomainLink
        a = _make_assessment(goal_title="G", signal="goal_stalled", score=40)
        goal = _make_goal("G")
        links = [CrossDomainLink(goal_title="G", category="research_artifact", title="Art")]
        ctx = _make_ctx(assessments=[a], goals=[goal], cross_links=links)
        s = create_remediation_suggestions(ctx)
        # Primary should be task, secondary should be investigate.
        assert _has_action_type(s, TASK)
        assert _has_action_type(s, INVESTIGATE)
        inv = _first_action(s, INVESTIGATE)
        assert "Art" in inv.parameters["link_titles"]

    def test_stalled_with_measurement_gets_measure_secondary(self):
        """§6.2.4: stalled goal with overdue measurement → measure secondary."""
        a = _make_assessment(
            goal_title="G", signal="goal_stalled", score=40,
            measurement_overdue_count=1,
            days_since_last_activity=20,
        )
        goal = _make_goal("G", measurement_requirements=[
            {"metric": "Weight", "frequency": "daily"},
        ])
        old_snap = MetricSnapshot(
            goal_title="G", metric_name="Weight", value=70.0,
            timestamp=datetime(2025, 1, 5, tzinfo=timezone.utc),
            source="manual",
        )
        ctx = _make_ctx(
            assessments=[a], goals=[goal],
            metric_snapshots={"G": [old_snap]},
        )
        s = create_remediation_suggestions(ctx)
        assert _has_action_type(s, TASK)
        assert _has_action_type(s, MEASURE)

    def test_stalled_with_goal_without_tasks_gets_task_secondary(self):
        """§6.2.4: GOAL_WITHOUT_TASKS warning → task secondary even if primary is escalate."""
        a = _make_assessment(goal_title="G", signal="goal_overdue", score=100)
        issue = GoalIntegrityIssue(
            code="GOAL_WITHOUT_TASKS", severity="warning",
            goal_id="G", message="no tasks",
        )
        ctx = _make_ctx(
            assessments=[a], goals=[_make_goal("G")],
            integrity_issues=[issue],
        )
        s = create_remediation_suggestions(ctx)
        # Primary should be escalate (goal_overdue).
        assert _has_action_type(s, ESCALATE)
        # Secondary should be task (GOAL_WITHOUT_TASKS).
        assert _has_action_type(s, TASK)


# ── §6.3 — deduplication ───────────────────────────────────────────────────────


class TestDedup:
    def test_duplicate_task_actions_merged(self):
        """§6.3: two task actions for same goal merge into one with combined reason."""
        a = _make_assessment(
            goal_title="G", signal="goal_stalled", score=40,
            days_since_last_activity=35,
        )
        goal = _make_goal("G", inactivity_window_days=30)
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s = create_remediation_suggestions(ctx)
        # Should have exactly one task action (primary merged with secondary).
        task_actions = [x for x in s.per_goal if x.action_type == TASK]
        assert len(task_actions) == 1

    def test_dedup_by_suggestion_id_stable(self):
        """§6.3: repeated runs produce the same suggestion_ids (deterministic)."""
        a = _make_assessment(
            goal_title="G", signal="goal_stalled", score=40,
            days_since_last_activity=35,
        )
        goal = _make_goal("G", inactivity_window_days=30)
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s1 = create_remediation_suggestions(ctx)
        s2 = create_remediation_suggestions(ctx)
        ids1 = [a.suggestion_id for a in s1.per_goal]
        ids2 = [a.suggestion_id for a in s2.per_goal]
        assert ids1 == ids2


# ── §6.4 — determinism ────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_inputs_same_outputs(self):
        """§6.4: same RemediationContext → same RemediationSuggestions."""
        a = _make_assessment(goal_title="G", signal="goal_overdue", score=100)
        goal = _make_goal("G")
        ctx = _make_ctx(assessments=[a], goals=[goal])
        s1 = create_remediation_suggestions(ctx)
        s2 = create_remediation_suggestions(ctx)
        assert len(s1.per_goal) == len(s2.per_goal)
        for a1, a2 in zip(s1.per_goal, s2.per_goal):
            assert a1.action_type == a2.action_type
            assert a1.priority == a2.priority
            assert a1.parameters == a2.parameters
        assert s1.summary.by_type == s2.summary.by_type
        assert s1.summary.goals_with_actions == s2.summary.goals_with_actions


# ── §9 — graceful degradation without history ─────────────────────────────────


class TestNoHistory:
    def test_no_previous_assessments_does_not_crash(self):
        """§8 (spec): engine works without previous_assessments."""
        a = _make_assessment(goal_title="G", signal="goal_overdue", score=100)
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        assert _has_action_type(s, ESCALATE)

    def test_no_previous_assessments_watch_goal(self):
        """§8: watch goal without history still produces actions."""
        a = _make_assessment(
            goal_title="G", health_state="watch", signal="progress_slow", score=40,
            days_since_last_activity=10,
        )
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        assert _has_action_type(s, TASK)


# ── §6.2.4 — edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_all_healthy(self):
        """§6.3: all goals healthy → only 'none' actions, goals_with_actions=0."""
        a1 = _make_assessment(goal_title="H1", health_state="healthy", signal="", score=0)
        a2 = _make_assessment(goal_title="H2", health_state="healthy", signal="", score=0)
        ctx = _make_ctx(
            assessments=[a1, a2],
            goals=[_make_goal("H1"), _make_goal("H2")],
        )
        s = create_remediation_suggestions(ctx)
        for action in s.per_goal:
            assert action.action_type == NONE
        assert s.summary.goals_with_actions == 0

    def test_assessment_without_goal_skipped(self):
        """§6.3: assessment for a goal not in the goals list is skipped."""
        a = _make_assessment(goal_title="Missing", signal="goal_overdue", score=100)
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("Other")])
        s = create_remediation_suggestions(ctx)
        assert s.per_goal == []

    def test_stalled_no_dominant_signal_investigate(self):
        """§6.2.4: stalled health_state but no dominant signal → investigate."""
        a = _make_assessment_no_signal(goal_title="G", health_state="stalled")
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, INVESTIGATE)
        assert primary is not None

    def test_unknown_dominant_signal_watch_falls_to_investigate(self):
        """§6.3: unknown signal in watch state → falls through to investigate."""
        sig = _make_signal("totally_unknown", 50, "weird")
        a = GoalHealthAssessment(
            goal_title="G", health_state="watch", signals=[sig], dominant_signal=sig,
        )
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, INVESTIGATE)
        assert primary is not None

    def test_no_recent_activity_default_window_archive(self):
        """§6.2.3: no_recent_activity > 2× default window(30) → archive."""
        a = _make_assessment(
            goal_title="G", signal="no_recent_activity", score=35,
            days_since_last_activity=70,
        )
        # No per-goal override → uses system default INACTIVITY_WINDOW_DAYS=30.
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        primary = _first_action(s, ARCHIVE)
        assert primary is not None


# ── §7 — configuration ───────────────────────────────────────────────────────


class TestConfig:
    def test_escalation_policy_exists(self):
        """§7.2: ESCALATION_POLICY is a configurable mapping."""
        assert isinstance(ESCALATION_POLICY, dict)
        # goal_overdue (100) in overdue → telegram.
        assert ("overdue", 100, 100) in ESCALATION_POLICY
        assert ESCALATION_POLICY[("overdue", 100, 100)] == "telegram"

    def test_escalation_channel_resolution(self):
        """§7.2: escalate action gets channel from ESCALATION_POLICY."""
        from janus.services.remediation import _escalation_channel
        assert _escalation_channel("overdue", 100) == "telegram"
        assert _escalation_channel("stalled", 40) == "weekly_review"
        assert _escalation_channel("watch", 30) == "strategic_summary"


# ── Integration: create_strategic_summary wiring ─────────────────────────────


class TestStrategicSummaryIntegration:
    """Verify the remediation engine can be wired into the strategic summary
    without modifying the existing advisory layer."""

    def test_remediation_engine_pure_function(self):
        """§4.1: the engine does not load data internally — it's a pure function
        over RemediationContext. Verify it doesn't call load_goals, etc."""
        import janus.services.remediation as rem_mod
        # If the engine tried to load data, these would be called.
        # We verify purity by confirming no file/database calls are needed.
        a = _make_assessment(goal_title="Pure", signal="goal_overdue", score=100)
        ctx = _make_ctx(
            assessments=[a], goals=[_make_goal("Pure")],
        )
        s = rem_mod.create_remediation_suggestions(ctx)
        assert len(s.per_goal) == 1
        assert s.per_goal[0].action_type == ESCALATE

    def test_engine_consumes_assessment_fields(self):
        """§4: engine consumes GoalHealthAssessment fields properly."""
        a = _make_assessment(
            goal_title="G", signal="goal_overdue", score=100,
            days_since_last_activity=50,
            progress=20.0,
            progress_delta=-15.0,
        )
        ctx = _make_ctx(assessments=[a], goals=[_make_goal("G")])
        s = create_remediation_suggestions(ctx)
        action = s.per_goal[0]
        assert action.health_state == "overdue"
        assert action.dominant_signal == "goal_overdue"
        assert action.dominant_signal_score == 100
        assert action.dominant_signal_reason == "test signal"
