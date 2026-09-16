"""Tests for the strategic summary service and CLI (spec §5, §6, §7).

Covers:
- ``create_strategic_summary()`` aggregation and JSON serialization (§6.1, §6.2)
- Portfolio health counts, including edge cases all-healthy / all-completed / all-inactive (§87–§88)
- Stalled-work detection uses existing + no_recent_activity signals, no new scores (§81)
- Neglected-goal exclusion of inactive/completed, severity ranking (§80)
- Cross-domain links surface research artifacts, decisions, follow-ups (§82)
- ``render_strategic_summary`` markdown output (§79)
"""

from datetime import date, datetime, timezone
from dataclasses import asdict

import pytest

from janus.models.goal import Goal
from janus.models.goal_signal import GoalSignal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.weekly_review import GoalReview, WeeklyReview
from janus.models.attention import AttentionItem
from janus.models.recommended_action import CrossDomainLink
from janus.models.strategic_summary import (
    PortfolioHealthCounts,
    StrategicSummary,
)
from janus.services.strategic_summary import (
    create_strategic_summary,
    _compute_portfolio_health_counts,
)

FIXED_TODAY = date(2026, 9, 6)
FIXED_NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


def _make_goal(title="Test goal", status="active", related_tasks=None, **kw):
    return Goal(title=title, status=status, related_tasks=related_tasks or [], **kw)


def _make_assessment(
    goal_title, health_state="healthy", dominant_signal=None,
    progress=None, progress_delta=None, days_since_last_activity=None,
    measurement_overdue_count=0, signals=None,
):
    return GoalHealthAssessment(
        goal_title=goal_title,
        health_state=health_state,
        signals=signals or [],
        dominant_signal=dominant_signal,
        progress=progress,
        progress_delta=progress_delta,
        days_since_last_activity=days_since_last_activity,
        measurement_overdue_count=measurement_overdue_count,
        evaluated_at=FIXED_NOW,
    )


def _sig(signal, score=40, reason="test reason"):
    return GoalSignal(signal=signal, score=score, reason=reason, timestamp=FIXED_NOW)


# ── PortfolioHealthCounts ────────────────────────────────────────────────────

class TestPortfolioHealthCounts:
    def test_defaults_zero(self):
        c = PortfolioHealthCounts()
        assert c.total_active == 0
        assert c.healthy == 0
        assert c.watch == 0
        assert c.stalled == 0
        assert c.completed == 0
        assert c.inactive == 0

    def test_serializes_to_dict(self):
        c = PortfolioHealthCounts(total_active=2, healthy=1, stalled=1, completed=1)
        d = c.to_dict()
        assert d["total_active"] == 2
        assert d["healthy"] == 1
        assert d["stalled"] == 1
        assert d["completed"] == 1


# ── _compute_portfolio_health_counts ─────────────────────────────────────────

class TestComputePortfolioHealthCounts:
    def test_counts_by_state(self):
        goals = [
            _make_goal(title="G1", status="active"),
            _make_goal(title="G2", status="active"),
            _make_goal(title="G3", status="active"),
            _make_goal(title="Done", status="completed"),
            _make_goal(title="Paused", status="inactive"),
        ]
        assessments = [
            _make_assessment("G1", health_state="healthy"),
            _make_assessment("G2", health_state="watch"),
            _make_assessment("G3", health_state="stalled", dominant_signal=_sig("goal_overdue", 100)),
        ]
        counts = _compute_portfolio_health_counts(goals, assessments)
        assert counts.total_active == 3
        assert counts.healthy == 1
        assert counts.watch == 1
        assert counts.stalled == 1
        assert counts.completed == 1
        assert counts.inactive == 1

    def test_all_completed(self):
        """All goals completed → empty active portfolio (spec §87)."""
        goals = [_make_goal(title="G1", status="completed")]
        counts = _compute_portfolio_health_counts(goals, [])
        assert counts.total_active == 0
        assert counts.completed == 1
        assert counts.stalled == 0
        assert counts.watch == 0

    def test_all_inactive_excluded_from_health(self):
        """Inactive goals excluded from health evaluation (spec §88)."""
        goals = [_make_goal(title="G1", status="inactive")]
        counts = _compute_portfolio_health_counts(goals, [])
        assert counts.total_active == 0
        assert counts.inactive == 1
        assert counts.healthy == 0


# ── create_strategic_summary ─────────────────────────────────────────────────

class TestCreateStrategicSummary:
    def test_aggregates_assessments_and_links(self):
        """Summary aggregates health assessments, neglected, and recommendations."""
        goals = [_make_goal(title="G", related_tasks=["Task A"])]
        dom = _sig("goal_stalled", 40, "All tasks done")
        assessments = [_make_assessment(
            "G", health_state="stalled", dominant_signal=dom,
            progress=0.0, progress_delta=0.0,
            days_since_last_activity=5,
        )]
        links = [CrossDomainLink(goal_title="G", category="decision", title="ADR-001")]
        summary = create_strategic_summary(
            goals=goals, assessments=assessments,
            cross_links=links,
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert summary.generated_at == FIXED_NOW
        assert summary.portfolio_health_counts.stalled == 1
        assert summary.portfolio_health_counts.watch == 0
        # Stalled goal surfaced in stalled_goals
        assert len(summary.stalled_goals) == 1
        assert summary.stalled_goals[0]["goal_title"] == "G"
        assert summary.stalled_goals[0]["health_state"] == "stalled"
        # Cross-domain links surfaced (spec §82)
        assert len(summary.cross_domain_links) == 1
        assert summary.cross_domain_links[0]["category"] == "decision"
        assert summary.cross_domain_links[0]["title"] == "ADR-001"

    def test_all_healthy_returns_empty_stalled_and_recommendations(self):
        """All goals healthy → no stalled, no recommendations (spec §6.2, §87)."""
        goals = [
            _make_goal(title="G1", related_tasks=["A"]),
            _make_goal(title="G2", related_tasks=["B"]),
        ]
        assessments = [
            _make_assessment("G1", health_state="healthy"),
            _make_assessment("G2", health_state="healthy"),
        ]
        summary = create_strategic_summary(
            goals=goals, assessments=assessments,
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []
        assert summary.portfolio_health_counts.healthy == 2

    def test_all_completed_empty_portfolio(self):
        """All completed → zero active, no stalled/neglected (spec §87)."""
        goals = [_make_goal(title="G1", status="completed")]
        summary = create_strategic_summary(
            goals=goals, assessments=[],
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert summary.portfolio_health_counts.total_active == 0
        assert summary.portfolio_health_counts.completed == 1
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []

    def test_all_inactive_empty_portfolio(self):
        """All inactive → excluded, zero active, no recommendations (spec §88)."""
        goals = [_make_goal(title="G1", status="inactive")]
        summary = create_strategic_summary(
            goals=goals, assessments=[],
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert summary.portfolio_health_counts.total_active == 0
        assert summary.portfolio_health_counts.inactive == 1
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []

    def test_stalled_goal_produces_recommendation(self):
        """A stalled goal produces a recommended action (spec §6.2, §78)."""
        goals = [_make_goal(title="G", related_tasks=["Task A"])]
        assessments = [_make_assessment(
            "G", health_state="stalled",
            dominant_signal=_sig("goal_overdue", 100, "passed deadline"),
            progress=0.0, progress_delta=0.0,
            days_since_last_activity=5,
        )]
        summary = create_strategic_summary(
            goals=goals, assessments=assessments,
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert len(summary.recommended_actions) == 1
        assert summary.recommended_actions[0]["goal_title"] == "G"
        assert summary.recommended_actions[0]["health_state"] == "stalled"

    def test_neglected_goals_exclude_inactive_and_completed(self):
        """Neglected logic excludes inactive/completed (spec §80)."""
        goals = [
            _make_goal(title="Paused", status="inactive"),
            _make_goal(title="Done", status="completed"),
        ]
        # Even though assessments claim stalled/watch, the goal status must
        # override exclusion.
        assessments = [
            _make_assessment("Paused", health_state="watch",
                             dominant_signal=_sig("progress_slow", 40)),
            _make_assessment("Done", health_state="stalled",
                             dominant_signal=_sig("goal_overdue", 100)),
        ]
        summary = create_strategic_summary(
            goals=goals, assessments=assessments,
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        # Inactive/completed excluded from health eval → no stalled/neglected
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []

    def test_cross_domain_links_surface_artifacts_decisions_followups(self):
        """Cross-domain links surface research artifacts, decisions, follow-ups (§82)."""
        goals = [_make_goal(title="G")]
        links = [
            CrossDomainLink(goal_title="G", category="research_artifact", title="Note A"),
            CrossDomainLink(goal_title="G", category="decision", title="ADR-001"),
            CrossDomainLink(goal_title="G", category="follow_up", title="Follow-up 1"),
        ]
        summary = create_strategic_summary(
            goals=goals, assessments=[],
            cross_links=links,
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert len(summary.cross_domain_links) == 3
        categories = {l["category"] for l in summary.cross_domain_links}
        assert categories == {"research_artifact", "decision", "follow_up"}

    def test_serializes_to_dict(self):
        """StrategicSummary serializes to JSON-friendly dict (spec §73)."""
        summary = create_strategic_summary(
            goals=[], assessments=[],
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        d = summary.to_dict()
        assert "generated_at" in d
        assert "portfolio_health_counts" in d
        assert "stalled_goals" in d
        assert "neglected_goals" in d
        assert "recommended_actions" in d
        assert "cross_domain_links" in d
        assert d["stalled_goals"] == []

    def test_stalled_sorted_by_score_desc(self):
        """Stalled goals sorted by dominant signal score descending (spec §3.9)."""
        goals = [_make_goal(title="G1"), _make_goal(title="G2")]
        assessments = [
            _make_assessment("G1", health_state="stalled",
                             dominant_signal=_sig("goal_stalled", 40)),
            _make_assessment("G2", health_state="stalled",
                             dominant_signal=_sig("goal_overdue", 100)),
        ]
        summary = create_strategic_summary(
            goals=goals, assessments=assessments,
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        # score 100 (G2) before 40 (G1)
        assert summary.stalled_goals[0]["goal_title"] == "G2"
        assert summary.stalled_goals[1]["goal_title"] == "G1"


# ── render_strategic_summary ─────────────────────────────────────────────────

class TestRenderStrategicSummary:
    def _render(self, summary):
        from janus.strategic_cli import render_strategic_summary
        return render_strategic_summary(summary)

    def test_renders_header_and_sections(self):
        summary = create_strategic_summary(
            goals=[], assessments=[],
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        output = self._render(summary)
        assert "JANUS — STATUS" in output
        assert "PORTFOLIO HEALTH" in output
        assert "STALLED WORK" in output
        assert "NEGLECTED GOALS" in output
        assert "RECOMMENDED NEXT ACTIONS" in output

    def test_empty_portfolio_renders_empty_lists(self):
        summary = create_strategic_summary(
            goals=[], assessments=[],
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        output = self._render(summary)
        assert "No stalled goals." in output
        assert "No neglected goals." in output
        assert "No recommendations." in output

    def test_renders_stalled_and_recommendations(self):
        goals = [_make_goal(title="G", related_tasks=[])]
        assessments = [_make_assessment(
            "G", health_state="stalled",
            dominant_signal=_sig("goal_overdue", 100, "deadline passed"),
            progress=0.0, progress_delta=-1.0,
            days_since_last_activity=40,
            measurement_overdue_count=1,
        )]
        summary = create_strategic_summary(
            goals=goals, assessments=assessments,
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        output = self._render(summary)
        assert "G [stalled, score=100]" in output
        assert "Reason: deadline passed" in output
        assert "Progress: 0.0%" in output
        assert "Measurements overdue: 1" in output

    def test_does_not_render_stalled_for_completed(self):
        """Completed goals never appear in stalled/neglected (edge case §87)."""
        goals = [_make_goal(title="G", status="completed")]
        summary = create_strategic_summary(
            goals=goals, assessments=[],
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        output = self._render(summary)
        assert "No stalled goals." in output
        assert "No neglected goals." in output
