"""Tests for meaningful change detection (strategic_summary_service).

Covers the criteria from design/strategic_summary_spec.md §1:

1.1  Health-state transition (healthy<->watch<->stalled) or dominant-signal
     score change >= 15 points.
1.2  Progress-delta over 14-day lookback crosses the slow threshold (5%).
1.3  A stalled-work signal activates or clears.
1.4  A measurement requirement becomes overdue or is satisfied.
1.5  Cross-domain link changes (research artifact / decision / follow-up).
1.6  Goal status transition or milestone status change.

Plus the "non-meaningful" exclusions (§1, last paragraph):
- task completion without progress delta
- attention score fluctuation < 15 points without state change
- metric snapshot append without health impact

These tests exercise the pure detection logic directly by constructing
``GoalStateSnapshot`` / ``StrategicStateSnapshot`` instances, so they do
not depend on the file-based integrations.
"""

from datetime import date, datetime, timezone

import pytest

from janus.models.goal import Goal
from janus.models.strategic_summary import (
    CHANGE_CROSS_DOMAIN_LINK,
    CHANGE_DOMINANT_SIGNAL_SCORE,
    CHANGE_GOAL_STATUS,
    CHANGE_HEALTH_STATE,
    CHANGE_MEASUREMENT_DUE,
    CHANGE_MILESTONE_STATUS,
    CHANGE_PROGRESS_DELTA,
    CHANGE_STALLED_SIGNAL,
    GoalStateSnapshot,
    MeaningfulChange,
    StrategicStateSnapshot,
)
from janus.services.strategic_summary import (
    build_goal_state_snapshot,
    detect_meaningful_changes,
)

FIXED_TODAY = date(2026, 9, 6)
FIXED_NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


def _gs(**kw):
    """Build a GoalStateSnapshot with sensible defaults."""
    defaults = dict(
        goal_title="G",
        health_state="healthy",
        dominant_signal=None,
        dominant_signal_score=0,
        progress=0.0,
        progress_delta=0.0,
        measurement_overdue_count=0,
        signals=frozenset(),
        goal_status="active",
        milestone_statuses={},
        linked_research_artifacts=[],
        linked_decision_numbers=[],
        linked_followup_ids=[],
    )
    defaults.update(kw)
    return GoalStateSnapshot(**defaults)


def _snap(goals, generated_at=FIXED_NOW):
    return StrategicStateSnapshot(generated_at=generated_at, goals=goals)


# ===========================================================================
# §1.1 -- Health-state transitions
# ===========================================================================

class TestHealthStateTransition:
    def test_healthy_to_watch(self):
        prev = _snap([_gs(goal_title="G", health_state="healthy")])
        cur = _snap([_gs(
            goal_title="G", health_state="watch",
            dominant_signal="progress_slow", dominant_signal_score=40,
            signals=frozenset({"progress_slow"}),
        )])
        changes = detect_meaningful_changes(prev, cur)
        hs = [c for c in changes if c.change_type == CHANGE_HEALTH_STATE]
        assert len(hs) == 1
        assert hs[0].goal_title == "G"
        assert hs[0].details["previous_health_state"] == "healthy"
        assert hs[0].details["current_health_state"] == "watch"

    def test_watch_to_stalled(self):
        prev = _snap([_gs(
            goal_title="G", health_state="watch",
            dominant_signal="progress_slow", dominant_signal_score=40,
        )])
        cur = _snap([_gs(
            goal_title="G", health_state="stalled",
            dominant_signal="goal_stalled", dominant_signal_score=40,
        )])
        changes = detect_meaningful_changes(prev, cur)
        hs = [c for c in changes if c.change_type == CHANGE_HEALTH_STATE]
        assert len(hs) == 1
        assert hs[0].details["current_health_state"] == "stalled"

    def test_stalled_to_healthy(self):
        prev = _snap([_gs(
            goal_title="G", health_state="stalled",
            dominant_signal="goal_stalled", dominant_signal_score=40,
        )])
        cur = _snap([_gs(goal_title="G", health_state="healthy")])
        changes = detect_meaningful_changes(prev, cur)
        hs = [c for c in changes if c.change_type == CHANGE_HEALTH_STATE]
        assert len(hs) == 1
        assert hs[0].details["current_health_state"] == "healthy"

    def test_stalled_to_none_when_inactive(self):
        prev = _snap([_gs(
            goal_title="G", health_state="stalled",
            dominant_signal="goal_stalled", dominant_signal_score=40,
            goal_status="inactive",
        )])
        cur = _snap([_gs(goal_title="G", health_state=None, goal_status="inactive")])
        changes = detect_meaningful_changes(prev, cur)
        assert any(
            c.change_type == CHANGE_HEALTH_STATE
            and c.details["current_health_state"] is None
            for c in changes
        )


# ===========================================================================
# §1.1 -- Dominant signal score change >= 15 points
# ===========================================================================

class TestDominantSignalScoreChange:
    def test_score_increases_by_15(self):
        prev = _snap([_gs(
            goal_title="G", dominant_signal="progress_slow", dominant_signal_score=40,
        )])
        cur = _snap([_gs(
            goal_title="G", dominant_signal="goal_overdue", dominant_signal_score=55,
        )])
        changes = detect_meaningful_changes(prev, cur)
        sc = [c for c in changes if c.change_type == CHANGE_DOMINANT_SIGNAL_SCORE]
        assert len(sc) == 1
        assert sc[0].details["delta"] == 15

    def test_score_decreases_by_20(self):
        prev = _snap([_gs(
            goal_title="G", dominant_signal="goal_overdue", dominant_signal_score=100,
        )])
        cur = _snap([_gs(
            goal_title="G", dominant_signal="goal_stalled", dominant_signal_score=80,
        )])
        changes = detect_meaningful_changes(prev, cur)
        sc = [c for c in changes if c.change_type == CHANGE_DOMINANT_SIGNAL_SCORE]
        assert len(sc) == 1
        assert sc[0].details["delta"] == -20

    def test_score_change_under_15_not_meaningful(self):
        """Attention score fluctuation under 15 points without state change."""
        prev = _snap([_gs(
            goal_title="G", dominant_signal="progress_slow", dominant_signal_score=40,
        )])
        cur = _snap([_gs(
            goal_title="G", dominant_signal="progress_slow", dominant_signal_score=45,
        )])
        changes = detect_meaningful_changes(prev, cur)
        assert changes == []
        assert not any(c.change_type == CHANGE_DOMINANT_SIGNAL_SCORE for c in changes)


# ===========================================================================
# §1.1 -- Different dominant signal (even if score delta < 15)
# ===========================================================================

class TestDominantSignalChange:
    def test_different_signal_under_threshold(self):
        prev = _snap([_gs(
            goal_title="G", dominant_signal="progress_slow", dominant_signal_score=40,
        )])
        cur = _snap([_gs(
            goal_title="G", dominant_signal="measurement_due", dominant_signal_score=45,
        )])
        changes = detect_meaningful_changes(prev, cur)
        sc = [c for c in changes if c.change_type == CHANGE_DOMINANT_SIGNAL_SCORE]
        assert len(sc) == 1
        assert sc[0].details["previous_signal"] == "progress_slow"
        assert sc[0].details["current_signal"] == "measurement_due"


# ===========================================================================
# §1.2 -- Progress delta threshold crossing
# ===========================================================================

class TestProgressDeltaChange:
    def test_delta_crosses_above_threshold(self):
        prev = _snap([_gs(goal_title="G", progress_delta=2.0)])  # below 5%
        cur = _snap([_gs(goal_title="G", progress_delta=6.0)])   # above 5%
        changes = detect_meaningful_changes(prev, cur)
        pdc = [c for c in changes if c.change_type == CHANGE_PROGRESS_DELTA]
        assert len(pdc) == 1
        assert pdc[0].details["current_delta"] == 6.0

    def test_delta_clears_threshold(self):
        prev = _snap([_gs(goal_title="G", progress_delta=8.0)])
        cur = _snap([_gs(goal_title="G", progress_delta=2.0)])
        changes = detect_meaningful_changes(prev, cur)
        pdc = [c for c in changes if c.change_type == CHANGE_PROGRESS_DELTA]
        assert len(pdc) == 1

    def test_delta_no_cross_no_change(self):
        prev = _snap([_gs(goal_title="G", progress_delta=2.0)])
        cur = _snap([_gs(goal_title="G", progress_delta=3.0)])
        changes = detect_meaningful_changes(prev, cur)
        assert not any(c.change_type == CHANGE_PROGRESS_DELTA for c in changes)

    def test_delta_from_none_to_significant(self):
        prev = _snap([_gs(goal_title="G", progress_delta=None)])
        cur = _snap([_gs(goal_title="G", progress_delta=6.0)])
        changes = detect_meaningful_changes(prev, cur)
        pdc = [c for c in changes if c.change_type == CHANGE_PROGRESS_DELTA]
        assert len(pdc) == 1

    def test_delta_from_none_to_insignificant(self):
        """Metric snapshot append without health impact -- non-meaningful."""
        prev = _snap([_gs(goal_title="G", progress_delta=None)])
        cur = _snap([_gs(goal_title="G", progress_delta=2.0)])
        changes = detect_meaningful_changes(prev, cur)
        assert not any(c.change_type == CHANGE_PROGRESS_DELTA for c in changes)


# ===========================================================================
# §1.3 -- Stalled-work signal activation / clearing
# ===========================================================================

class TestStalledSignalChange:
    def test_signal_activates(self):
        prev = _snap([_gs(goal_title="G", signals=frozenset())])
        cur = _snap([_gs(
            goal_title="G", signals=frozenset({"goal_stalled"}),
            health_state="stalled", dominant_signal="goal_stalled",
            dominant_signal_score=40,
        )])
        changes = detect_meaningful_changes(prev, cur)
        sc = [c for c in changes if c.change_type == CHANGE_STALLED_SIGNAL]
        assert len(sc) == 1
        assert sc[0].details["action"] == "activated"
        assert sc[0].details["signal"] == "goal_stalled"

    def test_signal_clears(self):
        prev = _snap([_gs(
            goal_title="G", signals=frozenset({"goal_overdue"}),
            health_state="stalled", dominant_signal="goal_overdue",
            dominant_signal_score=100,
        )])
        cur = _snap([_gs(goal_title="G", signals=frozenset())])
        changes = detect_meaningful_changes(prev, cur)
        sc = [c for c in changes if c.change_type == CHANGE_STALLED_SIGNAL]
        assert len(sc) == 1
        assert sc[0].details["action"] == "cleared"
        assert sc[0].details["signal"] == "goal_overdue"

    def test_non_stalled_signal_does_not_fire(self):
        """progress_slow is not a stalled-work signal."""
        prev = _snap([_gs(goal_title="G", signals=frozenset())])
        cur = _snap([_gs(
            goal_title="G", signals=frozenset({"progress_slow"}),
            health_state="watch", dominant_signal="progress_slow",
            dominant_signal_score=40,
        )])
        changes = detect_meaningful_changes(prev, cur)
        assert not any(c.change_type == CHANGE_STALLED_SIGNAL for c in changes)

    def test_no_recent_activity_signal(self):
        prev = _snap([_gs(goal_title="G", signals=frozenset())])
        cur = _snap([_gs(
            goal_title="G", signals=frozenset({"no_recent_activity"}),
            health_state="stalled", dominant_signal="no_recent_activity",
            dominant_signal_score=35,
        )])
        changes = detect_meaningful_changes(prev, cur)
        sc = [c for c in changes if c.change_type == CHANGE_STALLED_SIGNAL]
        assert len(sc) == 1
        assert sc[0].details["signal"] == "no_recent_activity"

    def test_multiple_signals_activate(self):
        prev = _snap([_gs(goal_title="G", signals=frozenset())])
        cur = _snap([_gs(
            goal_title="G",
            signals=frozenset({"goal_stalled", "no_recent_activity"}),
            health_state="stalled",
        )])
        changes = detect_meaningful_changes(prev, cur)
        sc = [c for c in changes if c.change_type == CHANGE_STALLED_SIGNAL]
        sigs = {c.details["signal"] for c in sc}
        assert sigs == {"goal_stalled", "no_recent_activity"}


# ===========================================================================
# §1.4 -- Measurement requirement overdue / satisfied
# ===========================================================================

class TestMeasurementChange:
    def test_measurement_becomes_overdue(self):
        prev = _snap([_gs(goal_title="G", measurement_overdue_count=0)])
        cur = _snap([_gs(goal_title="G", measurement_overdue_count=2)])
        changes = detect_meaningful_changes(prev, cur)
        mc = [c for c in changes if c.change_type == CHANGE_MEASUREMENT_DUE]
        assert len(mc) == 1
        assert mc[0].details["action"] == "fired"
        assert mc[0].details["current_overdue_count"] == 2

    def test_measurement_satisfied(self):
        prev = _snap([_gs(goal_title="G", measurement_overdue_count=3)])
        cur = _snap([_gs(goal_title="G", measurement_overdue_count=0)])
        changes = detect_meaningful_changes(prev, cur)
        mc = [c for c in changes if c.change_type == CHANGE_MEASUREMENT_DUE]
        assert len(mc) == 1
        assert mc[0].details["action"] == "satisfied"

    def test_measurement_count_unchanged_no_change(self):
        prev = _snap([_gs(goal_title="G", measurement_overdue_count=1)])
        cur = _snap([_gs(goal_title="G", measurement_overdue_count=1)])
        changes = detect_meaningful_changes(prev, cur)
        assert not any(c.change_type == CHANGE_MEASUREMENT_DUE for c in changes)


# ===========================================================================
# §1.5 -- Cross-domain link changes
# ===========================================================================

class TestCrossDomainLinkChange:
    def test_new_research_artifact_link(self):
        prev = _snap([_gs(goal_title="G", linked_research_artifacts=["A"])])
        cur = _snap([_gs(goal_title="G", linked_research_artifacts=["A", "B"])])
        changes = detect_meaningful_changes(prev, cur)
        links = [c for c in changes if c.change_type == CHANGE_CROSS_DOMAIN_LINK]
        assert len(links) == 1
        assert links[0].details["link_type"] == "research_artifact"
        assert "B" in links[0].details["added"]

    def test_new_decision_link(self):
        prev = _snap([_gs(goal_title="G", linked_decision_numbers=["ADR-001"])])
        cur = _snap([_gs(goal_title="G", linked_decision_numbers=["ADR-001", "ADR-002"])])
        changes = detect_meaningful_changes(prev, cur)
        dec = [
            c for c in changes
            if c.change_type == CHANGE_CROSS_DOMAIN_LINK
            and c.details["link_type"] == "decision"
        ]
        assert len(dec) == 1
        assert "ADR-002" in dec[0].details["added"]

    def test_new_followup_link(self):
        prev = _snap([_gs(goal_title="G", linked_followup_ids=["fu-1"])])
        cur = _snap([_gs(goal_title="G", linked_followup_ids=["fu-1", "fu-2"])])
        changes = detect_meaningful_changes(prev, cur)
        fups = [
            c for c in changes
            if c.change_type == CHANGE_CROSS_DOMAIN_LINK
            and c.details["link_type"] == "followup"
        ]
        assert len(fups) == 1
        assert "fu-2" in fups[0].details["added"]

    def test_no_link_change(self):
        prev = _snap([_gs(goal_title="G", linked_research_artifacts=["A", "B"])])
        cur = _snap([_gs(goal_title="G", linked_research_artifacts=["B", "A"])])
        changes = detect_meaningful_changes(prev, cur)
        assert not any(c.change_type == CHANGE_CROSS_DOMAIN_LINK for c in changes)
        assert changes == []

    def test_multiple_link_types_added(self):
        prev = _snap([_gs(goal_title="G")])
        cur = _snap([_gs(
            goal_title="G",
            linked_research_artifacts=["RA"],
            linked_decision_numbers=["ADR-1"],
            linked_followup_ids=["fu-1"],
        )])
        changes = detect_meaningful_changes(prev, cur)
        links = [c for c in changes if c.change_type == CHANGE_CROSS_DOMAIN_LINK]
        assert len(links) == 3
        types = {l.details["link_type"] for l in links}
        assert types == {"research_artifact", "decision", "followup"}


# ===========================================================================
# §1.6 -- Goal status / milestone transitions
# ===========================================================================

class TestGoalAndMilestoneStatusChange:
    def test_goal_active_to_completed(self):
        prev = _snap([_gs(goal_title="G", goal_status="active")])
        cur = _snap([_gs(
            goal_title="G", goal_status="completed", health_state="completed",
        )])
        changes = detect_meaningful_changes(prev, cur)
        gs = [c for c in changes if c.change_type == CHANGE_GOAL_STATUS]
        assert len(gs) == 1
        assert gs[0].details["previous_status"] == "active"
        assert gs[0].details["current_status"] == "completed"

    def test_goal_active_to_inactive(self):
        prev = _snap([_gs(
            goal_title="G", goal_status="active", health_state="healthy",
        )])
        cur = _snap([_gs(
            goal_title="G", goal_status="inactive", health_state=None,
        )])
        changes = detect_meaningful_changes(prev, cur)
        gs = [c for c in changes if c.change_type == CHANGE_GOAL_STATUS]
        assert len(gs) == 1
        assert gs[0].details["current_status"] == "inactive"

    def test_milestone_status_change(self):
        prev = _snap([_gs(goal_title="G", milestone_statuses={"M1": "open"})])
        cur = _snap([_gs(goal_title="G", milestone_statuses={"M1": "completed"})])
        changes = detect_meaningful_changes(prev, cur)
        ms = [c for c in changes if c.change_type == CHANGE_MILESTONE_STATUS]
        assert len(ms) == 1
        assert ms[0].details["milestone_title"] == "M1"
        assert ms[0].details["previous_status"] == "open"
        assert ms[0].details["current_status"] == "completed"

    def test_milestone_removed(self):
        prev = _snap([_gs(
            goal_title="G", milestone_statuses={"M1": "open", "M2": "open"},
        )])
        cur = _snap([_gs(goal_title="G", milestone_statuses={"M2": "open"})])
        changes = detect_meaningful_changes(prev, cur)
        ms = [c for c in changes if c.change_type == CHANGE_MILESTONE_STATUS]
        assert len(ms) == 1
        assert ms[0].details["current_status"] == "removed"


# ===========================================================================
# New / removed goals
# ===========================================================================

class TestNewAndRemovedGoals:
    def test_new_active_nonhealthy_goal_is_meaningful(self):
        prev = _snap([])
        cur = _snap([_gs(
            goal_title="NewG", health_state="stalled",
            dominant_signal="goal_stalled", dominant_signal_score=40,
        )])
        changes = detect_meaningful_changes(prev, cur)
        assert len(changes) == 1
        assert changes[0].change_type == CHANGE_GOAL_STATUS
        assert changes[0].details["previous_status"] == "new"

    def test_new_healthy_goal_with_signals_is_meaningful(self):
        prev = _snap([])
        cur = _snap([_gs(
            goal_title="NewG", health_state="healthy",
            signals=frozenset({"progress_slow"}),
            dominant_signal="progress_slow", dominant_signal_score=40,
        )])
        changes = detect_meaningful_changes(prev, cur)
        assert len(changes) >= 1
        assert changes[0].change_type == CHANGE_GOAL_STATUS

    def test_new_healthy_goal_no_signals_not_meaningful(self):
        prev = _snap([])
        cur = _snap([_gs(goal_title="NewG", health_state="healthy")])
        changes = detect_meaningful_changes(prev, cur)
        assert changes == []

    def test_removed_goal(self):
        prev = _snap([_gs(goal_title="Gone", health_state="healthy")])
        cur = _snap([])
        changes = detect_meaningful_changes(prev, cur)
        gs = [c for c in changes if c.change_type == CHANGE_GOAL_STATUS]
        assert len(gs) == 1
        assert gs[0].details["current_status"] == "removed"


# ===========================================================================
# Non-meaningful changes (excluded)
# ===========================================================================

class TestNonMeaningfulExcluded:
    def test_identical_snapshots_no_changes(self):
        snap = _snap([_gs(goal_title="G", health_state="healthy")])
        assert detect_meaningful_changes(snap, snap) == []

    def test_attention_score_fluctuation_under_15(self):
        """Dominant signal score fluctuation < 15 with no state change."""
        prev = _snap([_gs(
            goal_title="G", dominant_signal="progress_slow",
            dominant_signal_score=40, health_state="watch",
        )])
        cur = _snap([_gs(
            goal_title="G", dominant_signal="progress_slow",
            dominant_signal_score=44, health_state="watch",
        )])
        assert detect_meaningful_changes(prev, cur) == []


# ===========================================================================
# Sorting & determinism
# ===========================================================================

class TestChangeOrdering:
    def test_sorted_by_severity_desc_then_title(self):
        prev = _snap([
            _gs(goal_title="A", health_state="healthy"),
            _gs(goal_title="B", health_state="healthy"),
        ])
        cur = _snap([
            _gs(
                goal_title="A", health_state="stalled",
                dominant_signal="goal_stalled", dominant_signal_score=40,
            ),
            _gs(
                goal_title="B", health_state="watch",
                dominant_signal="progress_slow", dominant_signal_score=40,
            ),
        ])
        changes = detect_meaningful_changes(prev, cur)
        # A has higher health severity (stalled=20 > watch=15).
        assert changes[0].goal_title == "A"
        assert changes[1].goal_title == "B"

    def test_multiple_changes_single_goal(self):
        prev = _snap([_gs(
            goal_title="G", health_state="healthy",
            dominant_signal="goal_deadline_soon", dominant_signal_score=60,
            signals=frozenset({"goal_deadline_soon"}),
        )])
        cur = _snap([_gs(
            goal_title="G", health_state="stalled",
            dominant_signal="goal_overdue", dominant_signal_score=100,
            signals=frozenset({"goal_overdue"}),
        )])
        changes = detect_meaningful_changes(prev, cur)
        types = {c.change_type for c in changes}
        # health state, score change (>=15), stalled signal activate.
        # goal_status itself didn't change -- still active -- so no
        # CHANGE_GOAL_STATUS here.
        assert CHANGE_HEALTH_STATE in types
        assert CHANGE_DOMINANT_SIGNAL_SCORE in types
        assert CHANGE_STALLED_SIGNAL in types


# ===========================================================================
# Integration: build_goal_state_snapshot via assess_goal_health
# ===========================================================================

class TestIntegrationBuildSnapshot:
    def test_build_snapshot_healthy_goal(self):
        """An active goal with open related tasks and a future deadline is healthy."""
        goal = Goal(
            title="Live Goal", status="active",
            deadline="2026-09-20", related_tasks=["Task A"],
        )
        snap = build_goal_state_snapshot(
            goal, FIXED_TODAY,
            open_task_titles={"Task A"},
            all_task_titles={"Task A"},
        )
        assert snap.goal_title == "Live Goal"
        assert snap.health_state == "healthy"
        assert snap.goal_status == "active"

    def test_detect_overdue_via_snapshot_builder(self):
        """Detect a real health transition via the full snapshot builder + detector."""
        goal = Goal(
            title="Overdue", status="active",
            deadline="2026-08-30", related_tasks=["Task A"],
        )
        prev_snap = build_goal_state_snapshot(
            goal, date(2026, 8, 20),
            open_task_titles={"Task A"}, all_task_titles={"Task A"},
        )
        cur_snap = build_goal_state_snapshot(
            goal, FIXED_TODAY,
            open_task_titles=set(), all_task_titles={"Task A"},
        )
        changes = detect_meaningful_changes(
            StrategicStateSnapshot(generated_at=FIXED_NOW, goals=[prev_snap]),
            StrategicStateSnapshot(generated_at=FIXED_NOW, goals=[cur_snap]),
        )
        assert any(c.change_type == CHANGE_HEALTH_STATE for c in changes)
        assert any(c.change_type == CHANGE_STALLED_SIGNAL for c in changes)


# ===========================================================================
# Model validation
# ===========================================================================

class TestMeaningfulChangeValidation:
    def test_invalid_change_type_raises(self):
        with pytest.raises(ValueError, match="Invalid change_type"):
            MeaningfulChange(
                change_type="bogus",
                goal_title="G",
                description="x",
            )

    def test_valid_change_type_accepted(self):
        mc = MeaningfulChange(
            change_type="health_state_transition",
            goal_title="G",
            description="changed",
        )
        assert mc.change_type == "health_state_transition"
