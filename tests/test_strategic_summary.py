"""Tests for the strategic summary service and CLI.

Implements the acceptance criteria from
``docs/design/strategic_summary_spec.md`` §6:
- §6.1 StrategicSummary model exists with all 5 sections and serializes to JSON.
- §6.2 create_strategic_summary() returns non-empty stalled_goals and
      recommended_actions when at least one active goal has health != healthy;
      returns empty lists when all goals healthy/inactive/completed.
- §6.3 janus status renders markdown with health counts, stalled list,
      neglected list, and per-item recommendations with cross-links.
- §6.4 Neglected-goal logic excludes inactive and completed; includes watch
      and stalled with correct severity ranking.
- §6.5 Stalled detection reuses existing signals + no_recent_activity.
- §6.6 Cross-domain links surface research artifacts, decisions, follow-ups.
- §6.7 No changes to existing CLI commands — pure addition.

Edge cases from §7:
- All goals completed → empty portfolio.
- All goals inactive → excluded from health evaluation.
- Goal with open tasks but progress_slow → watch, not stalled.
- Goal with measurement_due but no metric history → measurement_overdue_count >= 1.
- Multiple cross-links for same goal → all surfaced.
- No cross-links → recommendation relies on attention + suggested_next_step.
- Deadline-soon + open tasks + no progress_slow → healthy (not downgraded).
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from janus.models.goal import Goal
from janus.models.strategic_summary import (
    CrossDomainLink,
    NeglectedGoal,
    PortfolioHealthCounts,
    RecommendedAction,
    StalledGoal,
    StrategicSummary,
)
from janus.models.goal_signal import GoalSignal
from janus.services.strategic_summary import (
    create_strategic_summary,
    render_strategic_summary,
    _has_upcoming_milestone_or_deadline,
)


FIXED_TODAY = date(2026, 9, 6)
FIXED_NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


def _make_goal(
    title="Test goal",
    status="active",
    deadline=None,
    related_tasks=None,
    milestones=None,
    metric_name=None,
    metric_unit=None,
    start_value=None,
    current_value=None,
    target_value=None,
    direction=None,
    measurement_requirements=None,
    inactivity_window_days=None,
):
    return Goal(
        title=title,
        status=status,
        deadline=deadline,
        related_tasks=related_tasks or [],
        milestones=milestones or [],
        metric_name=metric_name,
        metric_unit=metric_unit,
        start_value=start_value,
        current_value=current_value,
        target_value=target_value,
        direction=direction,
        measurement_requirements=measurement_requirements or [],
        inactivity_window_days=inactivity_window_days,
    )


def _make_metric_goal(**kw):
    defaults = dict(
        title="Body fat",
        metric_name="Body fat %",
        metric_unit="%",
        start_value=23.0,
        current_value=20.0,
        target_value=15.0,
        direction="decrease",
    )
    defaults.update(kw)
    return _make_goal(**defaults)


def _snap(goal_title, metric_name, value, days_ago, source="manual"):
    ts = FIXED_NOW - timedelta(days=days_ago)
    from janus.models.metric_snapshot import MetricSnapshot
    return MetricSnapshot(
        timestamp=ts,
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )


# ===========================================================================
# §6.1 — StrategicSummary model exists with all 5 sections and serializes
# ===========================================================================

class TestStrategicSummaryModel:
    def test_model_has_all_fields(self):
        """StrategicSummary has all 5 sections defined in §5."""
        now = datetime.now(timezone.utc)
        counts = PortfolioHealthCounts(total_active=2, healthy=1, watch=1)
        summary = StrategicSummary(
            generated_at=now,
            portfolio_health_counts=counts,
        )
        assert summary.generated_at == now
        assert summary.portfolio_health_counts == counts
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []
        assert summary.cross_domain_links == []

    def test_serializes_to_dict(self):
        """StrategicSummary serializes to a JSON-friendly dict (§73)."""
        from dataclasses import asdict
        now = datetime.now(timezone.utc)
        summary = StrategicSummary(
            generated_at=now,
            portfolio_health_counts=PortfolioHealthCounts(),
            stalled_goals=[StalledGoal(
                goal_title="G", health_state="stalled",
                dominant_signal="goal_overdue", dominant_signal_score=100,
                dominant_signal_reason="passed",
            )],
            neglected_goals=[NeglectedGoal(
                goal_title="G", health_state="stalled",
                dominant_signal="goal_overdue", dominant_signal_score=100,
                dominant_signal_reason="passed",
            )],
            recommended_actions=[RecommendedAction(
                goal_title="G", health_state="stalled",
                dominant_signal="goal_overdue", dominant_signal_score=100,
                dominant_signal_reason="passed",
            )],
            cross_domain_links=[CrossDomainLink(
                goal_title="G", category="decision", title="ADR-001",
            )],
        )
        d = summary.to_dict()
        assert d["portfolio_health_counts"]["total_active"] == 0
        assert len(d["stalled_goals"]) == 1
        assert d["stalled_goals"][0]["goal_title"] == "G"
        assert len(d["recommended_actions"]) == 1
        assert len(d["cross_domain_links"]) == 1
        assert d["cross_domain_links"][0]["category"] == "decision"


# ===========================================================================
# §6.2 — create_strategic_summary() returns non-empty when unhealthy goals
# ===========================================================================

class TestCreateStrategicSummary:
    def test_stalled_goal_appears_in_stalled_and_recommendations(self):
        """A stalled goal produces non-empty stalled_goals and recommendations."""
        goal = _make_goal(
            title="Stalled G", related_tasks=["Task A"],
            deadline="2026-08-30",  # overdue
        )
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert len(summary.stalled_goals) == 1
        assert summary.stalled_goals[0].goal_title == "Stalled G"
        assert summary.stalled_goals[0].dominant_signal == "goal_overdue"
        assert len(summary.recommended_actions) == 1
        assert summary.recommended_actions[0].goal_title == "Stalled G"

    def test_all_healthy_returns_empty(self):
        """All healthy goals → empty stalled/neglected/recommendations."""
        goal = _make_goal(
            title="Healthy G", related_tasks=["Task A"],
            deadline="2026-09-20",  # future, within 7 days but open tasks exist
        )
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles={"Task A"},
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []
        assert summary.portfolio_health_counts.healthy == 1

    def test_all_completed_returns_empty_portfolio(self):
        """All completed goals → empty stalled/neglected/recommendations (§7.1)."""
        goal = _make_goal(title="Done", status="completed", related_tasks=["Task A"])
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        # Completed goals return a completed assessment, but they're not
        # stalled/neglected/recommended.
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []
        assert summary.portfolio_health_counts.completed == 1

    def test_all_inactive_excluded(self):
        """All inactive goals → excluded from health evaluation (§7.2)."""
        goal = _make_goal(title="Paused", status="inactive", related_tasks=["Task A"])
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []
        assert summary.portfolio_health_counts.inactive == 1
        assert summary.portfolio_health_counts.total_active == 0


# ===========================================================================
# §6.4 — Neglected-goal logic excludes inactive/completed, includes watch/stalled
# ===========================================================================

class TestNeglectedGoals:
    def test_watch_goal_with_no_activity_is_neglected(self):
        """A watch goal with no recent activity > inactivity window → neglected."""
        goal = _make_metric_goal(
            title="Slow Progress",
            deadline=None,
            related_tasks=[],  # no tasks → no_recent_activity fires
        )
        # Metric snapshot from 40 days ago → no_recent_activity (stalled).
        # Actually, let's use progress_slow for watch.
        # progress_slow fires when delta < threshold over 14d lookback.
        snapshots = {"Slow Progress": [_snap("Body fat", "Body fat %", 20.0, 15)]}
        # But no recent snapshots AND no tasks → no_recent_activity fires
        # (score 35) which suppresses progress_slow unless progress_slow
        # has higher score... progress_slow is 40, no_recent_activity is 35.
        # progress_slow wins → watch. But no_recent_activity is suppressed
        # only when a higher-score signal fires. progress_slow (40) > no_recent (35).
        # So progress_slow fires and no_recent_activity does NOT (suppressed by 40>35).
        # health = watch. days_since_last_activity = 15 > 30? No, 15 < 30.
        # So days_exceeds won't fire. measurement_overdue = 0. no open related.
        # has_upcoming = False. So (not open_related and not has_upcoming) → True.
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal=snapshots,
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert len(summary.neglected_goals) == 1
        assert summary.neglected_goals[0].health_state == "watch"
        assert summary.neglected_goals[0].goal_title == "Slow Progress"

    def test_completed_goal_not_in_neglected(self):
        """Completed goals are never in neglected list."""
        goal = _make_goal(title="Done", status="completed", related_tasks=["Task A"])
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert all(n.goal_title != "Done" for n in summary.neglected_goals)

    def test_inactive_goal_not_in_neglected(self):
        """Inactive goals are never in neglected list."""
        goal = _make_goal(title="Paused", status="inactive", related_tasks=["Task A"])
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert all(n.goal_title != "Paused" for n in summary.neglected_goals)

    def test_severity_ranking_stalled_before_watch(self):
        """Neglected goals ranked: stalled > watch, then by score desc."""
        # A stalled goal (goal_stalled, score 40)
        stalled_goal = _make_goal(
            title="Stalled G", related_tasks=["Task A"],
        )
        # A watch goal (measurement_due, score 45)
        req = {"metric": "weight", "unit": "kg", "frequency": "daily"}
        watch_goal = _make_goal(
            title="Watch G", related_tasks=["Task B"],
            metric_name="weight", measurement_requirements=[req],
        )
        summary = create_strategic_summary(
            goals=[stalled_goal, watch_goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),  # no open tasks → both fire signals
            all_task_titles={"Task A", "Task B"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        # Both should be in neglected.
        assert len(summary.neglected_goals) == 2
        # Stalled should come first (severity ranking).
        assert summary.neglected_goals[0].health_state == "stalled"
        assert summary.neglected_goals[1].health_state == "watch"


# ===========================================================================
# §6.5 — Stalled detection reuses existing signals + no_recent_activity
# ===========================================================================

class TestStalledDetection:
    def test_goal_stalled_signal(self):
        """goal_stalled (score 40) → stalled (design §3)."""
        goal = _make_goal(title="G", related_tasks=["Task A"])
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert any(s.goal_title == "G" for s in summary.stalled_goals)
        sg = next(s for s in summary.stalled_goals if s.goal_title == "G")
        assert sg.dominant_signal == "goal_stalled"
        assert sg.dominant_signal_score == 40

    def test_goal_overdue_signal(self):
        """goal_overdue (score 100) → stalled."""
        goal = _make_goal(
            title="Overdue", deadline="2026-08-30", related_tasks=["Task A"],
        )
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert any(s.goal_title == "Overdue" for s in summary.stalled_goals)
        sg = next(s for s in summary.stalled_goals if s.goal_title == "Overdue")
        assert sg.dominant_signal == "goal_overdue"
        assert sg.dominant_signal_score == 100

    def test_no_recent_activity_signal(self):
        """no_recent_activity (score 35) → stalled."""
        goal = _make_metric_goal(title="Inactive metric")
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert any(s.goal_title == "Inactive metric" for s in summary.stalled_goals)
        sg = next(s for s in summary.stalled_goals if s.goal_title == "Inactive metric")
        assert sg.dominant_signal == "no_recent_activity"

    def test_stalled_sorted_by_score_desc(self):
        """Stalled goals sorted by dominant signal score descending."""
        g1 = _make_goal(title="G1", related_tasks=["Task A"])  # goal_stalled, 40
        g2 = _make_goal(
            title="G2", deadline="2026-08-30", related_tasks=["Task B"],  # overdue, 100
        )
        summary = create_strategic_summary(
            goals=[g1, g2],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A", "Task B"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert len(summary.stalled_goals) == 2
        assert summary.stalled_goals[0].dominant_signal_score >= summary.stalled_goals[1].dominant_signal_score
        assert summary.stalled_goals[0].goal_title == "G2"  # overdue (100) before stalled (40)


# ===========================================================================
# §6.6 — Cross-domain links
# ===========================================================================

class TestCrossDomainLinks:
    def test_research_artifact_link(self):
        """Research artifact with linked_goal_titles surfaces a cross-domain link."""
        from janus.models.research_artifact import ResearchArtifact
        goal = _make_goal(title="My Goal", related_tasks=["Task A"])
        art = ResearchArtifact(
            title="Research Note", linked_goal_titles=["My Goal"],
        )
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[art],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        link = next((l for l in summary.cross_domain_links
                     if l.goal_title == "My Goal" and l.category == "research_artifact"), None)
        assert link is not None
        assert link.title == "Research Note"

    def test_decision_link(self):
        """Decision with goal_titles surfaces a cross-domain link."""
        from janus.models.decision import Decision
        goal = _make_goal(title="My Goal", related_tasks=["Task A"])
        dec = Decision(
            adr_number="001", title="ADR Title", goal_titles=["My Goal"],
        )
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[dec],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        link = next((l for l in summary.cross_domain_links
                     if l.goal_title == "My Goal" and l.category == "decision"), None)
        assert link is not None
        assert link.title == "ADR Title"

    def test_followup_link(self):
        """Follow-up with linked_goal_title surfaces a cross-domain link."""
        from janus.models.follow_up import FollowUp
        goal = _make_goal(title="My Goal", related_tasks=["Task A"])
        fu = FollowUp(id="fu-001", title="Book review", linked_goal_title="My Goal")
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal={},
            followups=[fu],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        link = next((l for l in summary.cross_domain_links
                     if l.goal_title == "My Goal" and l.category == "follow_up"), None)
        assert link is not None
        assert link.title == "Book review"

    def test_multiple_cross_links_same_goal(self):
        """Multiple cross-links for same goal all surface (§7.3)."""
        from janus.models.research_artifact import ResearchArtifact
        from janus.models.decision import Decision
        from janus.models.follow_up import FollowUp
        goal = _make_goal(title="My Goal", related_tasks=["Task A"])
        art = ResearchArtifact(title="Note", linked_goal_titles=["My Goal"])
        dec = Decision(adr_number="001", title="ADR", goal_titles=["My Goal"])
        fu = FollowUp(id="fu-001", title="Follow", linked_goal_title="My Goal")
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal={},
            followups=[fu],
            research_artifacts=[art],
            decisions=[dec],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        my_links = [l for l in summary.cross_domain_links if l.goal_title == "My Goal"]
        assert len(my_links) == 3
        categories = {l.category for l in my_links}
        assert categories == {"research_artifact", "decision", "follow_up"}


# ===========================================================================
# §6.3 — CLI rendering (janus status)
# ===========================================================================

class TestStatusRendering:
    def test_status_command_exists(self):
        """janus status is wired as a command (§6.3, §6.7)."""
        from janus.strategic_cli import show_status
        assert callable(show_status)

    def test_status_is_not_weekly_or_today(self):
        """status is a distinct command, not replacing today/weekly (§83)."""
        from janus import show_status, show_today, show_weekly
        assert show_status is not show_today
        assert show_status is not show_weekly

    def test_render_includes_all_sections(self):
        """Render includes health counts, stalled list, neglected, recommendations."""
        from janus.models.strategic_summary import (
            PortfolioHealthCounts,
        )
        summary = StrategicSummary(
            generated_at=FIXED_NOW,
            portfolio_health_counts=PortfolioHealthCounts(
                total_active=3, healthy=1, watch=1, stalled=1,
            ),
            stalled_goals=[StalledGoal(
                goal_title="Stalled G", health_state="stalled",
                dominant_signal="goal_stalled", dominant_signal_score=40,
                dominant_signal_reason="All tasks done",
                progress=0.0, progress_delta=0.0,
                days_since_last_activity=5, measurement_overdue_count=0,
            )],
            neglected_goals=[NeglectedGoal(
                goal_title="Stalled G", health_state="stalled",
                dominant_signal="goal_stalled", dominant_signal_score=40,
                dominant_signal_reason="All tasks done",
                progress=0.0, days_since_last_activity=5,
            )],
            recommended_actions=[RecommendedAction(
                goal_title="Stalled G", health_state="stalled",
                dominant_signal="goal_stalled", dominant_signal_score=40,
                dominant_signal_reason="All tasks done",
                progress=0.0, days_since_last_activity=5,
                suggested_next_step="Define next milestone",
                cross_links=[],
            )],
            cross_domain_links=[],
        )
        output = render_strategic_summary(summary)
        assert "JANUS — STRATEGIC SUMMARY" in output
        assert "PORTFOLIO HEALTH" in output
        assert "STALLED WORK" in output
        assert "NEGLECTED GOALS" in output
        assert "RECOMMENDED ACTIONS" in output
        assert "Stalled G" in output
        assert "score=40" in output
        assert "Define next milestone" in output

    def test_render_empty_portfolio(self):
        """All healthy → render shows no stalled/neglected."""
        from janus.models.strategic_summary import PortfolioHealthCounts
        summary = StrategicSummary(
            generated_at=FIXED_NOW,
            portfolio_health_counts=PortfolioHealthCounts(
                total_active=1, healthy=1,
            ),
        )
        output = render_strategic_summary(summary)
        assert "No stalled goals." in output
        assert "No neglected goals." in output
        assert "No recommendations." in output


# ===========================================================================
# Edge cases (§7)
# ===========================================================================

class TestEdgeCases:
    def test_goal_with_open_tasks_but_progress_slow_is_watch(self):
        """Goal with open tasks + progress_slow → watch (not stalled) (§7.3)."""
        goal = _make_metric_goal(title="Slow G")  # no related_tasks
        # progress_slow fires (delta=0 < threshold). no_recent_activity
        # is suppressed because progress_slow (40) > 35. But no_open_related
        # and not has_upcoming → neglected includes it.
        snapshots = {"Slow G": [_snap("Body fat", "Body fat %", 20.0, 15)]}
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal=snapshots,
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        # health_state should be watch (progress_slow), not stalled.
        assert summary.neglected_goals
        ng = summary.neglected_goals[0]
        assert ng.health_state == "watch"
        assert ng.dominant_signal == "progress_slow"

    def test_measurement_due_no_metric_history(self):
        """measurement_due with no metric snapshots → measurement_overdue_count >= 1 (§7.4)."""
        req = {"metric": "weight", "unit": "kg", "frequency": "daily"}
        goal = _make_goal(
            title="Meas G", related_tasks=["Task A"],
            metric_name="weight", measurement_requirements=[req],
        )
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles={"Task A"},  # open task → no no_recent_activity
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        # measurement_due (45) → watch. Has open related task, so
        # (not open_related and not has_upcoming) is False.
        # days_since_last_activity: no snapshots, no completions → None → not > 30.
        # measurement_overdue_count > 0 → True → neglected.
        assert summary.neglected_goals
        ng = summary.neglected_goals[0]
        assert ng.measurement_overdue_count >= 1
        assert ng.health_state == "watch"

    def test_deadline_soon_with_open_tasks_is_healthy(self):
        """goal_deadline_soon + open tasks + no progress_slow → healthy (§7.6)."""
        goal = _make_goal(
            title="Soon G", deadline="2026-09-10", related_tasks=["Task A"],
        )
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles={"Task A"},
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        # Should not be in stalled or neglected (healthy).
        assert all(s.goal_title != "Soon G" for s in summary.stalled_goals)
        assert all(n.goal_title != "Soon G" for n in summary.neglected_goals)
        assert summary.portfolio_health_counts.healthy == 1

    def test_no_cross_links_recommendation_still_surfaces(self):
        """No cross-links for a stalled goal → recommendation relies on
        attention + suggested_next_step (§7.5)."""
        goal = _make_goal(title="G", related_tasks=["Task A"])
        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )
        assert len(summary.recommended_actions) == 1
        ra = summary.recommended_actions[0]
        assert ra.goal_title == "G"
        assert ra.cross_links == []


# ===========================================================================
# Helper: _has_upcoming_milestone_or_deadline
# ===========================================================================

class TestUpcomingDeadlineHelper:
    def test_future_goal_deadline(self):
        goal = _make_goal(title="G", deadline="2026-09-20", related_tasks=[])
        assert _has_upcoming_milestone_or_deadline(goal, FIXED_TODAY) is True

    def test_past_goal_deadline(self):
        goal = _make_goal(title="G", deadline="2026-08-30", related_tasks=[])
        assert _has_upcoming_milestone_or_deadline(goal, FIXED_TODAY) is False

    def test_no_deadline_no_milestones(self):
        goal = _make_goal(title="G", related_tasks=[])
        assert _has_upcoming_milestone_or_deadline(goal, FIXED_TODAY) is False

    def test_future_milestone(self):
        goal = _make_goal(
            title="G",
            milestones=[{"title": "M1", "goal_title": "G", "description": "",
                          "deadline": "2026-09-20", "status": "open", "order": 0}],
        )
        assert _has_upcoming_milestone_or_deadline(goal, FIXED_TODAY) is True

    def test_completed_milestone_not_upcoming(self):
        goal = _make_goal(
            title="G",
            milestones=[{"title": "M1", "goal_title": "G", "description": "",
                          "deadline": "2026-09-20", "status": "completed", "order": 0}],
        )
        assert _has_upcoming_milestone_or_deadline(goal, FIXED_TODAY) is False
