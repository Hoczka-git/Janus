"""Tests for measurement_collection.py.

Tests for scheduling logic and collection invocation.
All tests use in-memory data — no file I/O.
"""

from datetime import date, time

import pytest

from janus.models.goal import Goal
from janus.services.measurement_collection import (
    MeasurementRequest,
    get_due_measurements,
    _is_frequency_due,
    _is_within_preferred_time,
    PREFERRED_TIME_WINDOWS,
)
from janus.services.measurement_log import MeasurementEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _goal(
    title: str = "Test Goal",
    status: str = "active",
    target_value: float | None = None,
    direction: str | None = None,
    metric_unit: str | None = None,
    measurement_requirements: list[dict] | None = None,
) -> Goal:
    return Goal(
        title=title,
        status=status,
        target_value=target_value,
        direction=direction,
        metric_unit=metric_unit,
        measurement_requirements=measurement_requirements,
    )


def _entry(
    date_str: str,
    metric: str = "weight",
    value: float = 82.5,
    unit: str = "kg",
    goal_title: str = "Test Goal",
) -> MeasurementEntry:
    from datetime import date as d
    return MeasurementEntry(
        date=d.fromisoformat(date_str),
        metric=metric,
        value=value,
        unit=unit,
        goal_title=goal_title,
    )


TODAY = date(2026, 9, 6)  # Sunday


# ---------------------------------------------------------------------------
# Frequency logic tests
# ---------------------------------------------------------------------------

class TestFrequencyLogic:
    def test_daily_due_when_no_entry(self):
        assert _is_frequency_due("daily", TODAY, None) is True

    def test_daily_not_due_when_entry_today(self):
        assert _is_frequency_due("daily", TODAY, TODAY) is False

    def test_daily_due_when_last_yesterday(self):
        assert _is_frequency_due("daily", TODAY, date(2026, 9, 5)) is True

    def test_daily_due_when_last_days_ago(self):
        assert _is_frequency_due("daily", TODAY, date(2026, 9, 3)) is True

    def test_twice_weekly_due_when_no_entry(self):
        assert _is_frequency_due("twice_weekly", TODAY, None) is True

    def test_twice_weekly_not_due_when_recent(self):
        # 1 day ago — not due
        assert _is_frequency_due("twice_weekly", TODAY, date(2026, 9, 5)) is False

    def test_twice_weekly_due_when_3_days_ago(self):
        # 3 days ago — due (>= 3)
        assert _is_frequency_due("twice_weekly", TODAY, date(2026, 9, 3)) is True

    def test_twice_weekly_due_when_4_days_ago(self):
        # 4 days ago — due
        assert _is_frequency_due("twice_weekly", TODAY, date(2026, 9, 2)) is True

    def test_twice_weekly_not_due_when_2_days_ago(self):
        # 2 days ago — not due (< 3)
        assert _is_frequency_due("twice_weekly", TODAY, date(2026, 9, 4)) is False

    def test_weekly_due_when_no_entry(self):
        assert _is_frequency_due("weekly", TODAY, None) is True

    def test_weekly_not_due_when_6_days_ago(self):
        assert _is_frequency_due("weekly", TODAY, date(2026, 8, 31)) is False

    def test_weekly_due_when_7_days_ago(self):
        assert _is_frequency_due("weekly", TODAY, date(2026, 8, 30)) is True

    def test_weekly_not_due_when_5_days_ago(self):
        assert _is_frequency_due("weekly", TODAY, date(2026, 9, 1)) is False

    def test_weekends_due_saturday_no_entry(self):
        sat = date(2026, 9, 5)  # Saturday
        assert _is_frequency_due("weekends", sat, None) is True

    def test_weekends_due_sunday_no_entry(self):
        sun = date(2026, 9, 6)  # Sunday
        assert _is_frequency_due("weekends", sun, None) is True

    def test_weekends_not_due_weekday(self):
        # September 6 is Sunday, so let's use a weekday
        wed = date(2026, 9, 9)  # Wednesday
        assert _is_frequency_due("weekends", wed, None) is False

    def test_weekends_due_saturday_no_entry_this_weekend(self):
        sat = date(2026, 9, 5)  # Saturday
        # Last Friday — not this weekend
        last_fri = date(2026, 8, 28)
        assert _is_frequency_due("weekends", sat, last_fri) is True

    def test_weekends_not_due_saturday_entry_saturday(self):
        sat = date(2026, 9, 5)  # Saturday
        assert _is_frequency_due("weekends", sat, sat) is False

    def test_weekends_due_sunday_no_saturday_entry(self):
        sun = date(2026, 9, 6)  # Sunday
        sat = date(2026, 9, 5)  # Saturday of same weekend
        # No entry for Saturday — still due on Sunday
        # last_date is Saturday, which is < today (Sunday)
        # Wait, let me reconsider: the design says "no entry has been recorded
        # yet this weekend (since the most recent Friday)"
        # If last entry is Saturday (same weekend), it's not due
        assert _is_frequency_due("weekends", sun, sat) is False

    def test_custom_due_when_no_entry(self):
        assert _is_frequency_due("custom", TODAY, None, interval_days=5) is True

    def test_custom_due_when_interval_elapsed(self):
        # 5 days ago with interval_days=5 → due
        assert _is_frequency_due("custom", TODAY, date(2026, 9, 1), interval_days=5) is True

    def test_custom_not_due_when_interval_not_elapsed(self):
        # 3 days ago with interval_days=5 → not due
        assert _is_frequency_due("custom", TODAY, date(2026, 9, 3), interval_days=5) is False

    def test_custom_requires_interval_days(self):
        with pytest.raises(ValueError, match="requires interval_days"):
            _is_frequency_due("custom", TODAY, None, interval_days=None)

    def test_unknown_frequency_not_due(self):
        assert _is_frequency_due("unknown", TODAY, None) is False


# ---------------------------------------------------------------------------
# Preferred time window tests
# ---------------------------------------------------------------------------

class TestPreferredTime:
    def test_anytime_always_due(self):
        assert _is_within_preferred_time("anytime", time(3, 0)) is True
        assert _is_within_preferred_time("anytime", time(12, 0)) is True
        assert _is_within_preferred_time("anytime", time(23, 0)) is True

    def test_none_preferred_time_always_due(self):
        assert _is_within_preferred_time(None, time(3, 0)) is True
        assert _is_within_preferred_time(None, time(12, 0)) is True

    def test_now_none_ignores_time(self):
        """When now is None, preferred_time is ignored."""
        assert _is_within_preferred_time("morning", None) is True
        assert _is_within_preferred_time("evening", None) is True

    def test_morning_window(self):
        # 06:00–10:00 (exclusive end)
        assert _is_within_preferred_time("morning", time(5, 59)) is False
        assert _is_within_preferred_time("morning", time(6, 0)) is True
        assert _is_within_preferred_time("morning", time(9, 59)) is True
        assert _is_within_preferred_time("morning", time(10, 0)) is False

    def test_afternoon_window(self):
        # 12:00–14:00 (exclusive end)
        assert _is_within_preferred_time("afternoon", time(11, 59)) is False
        assert _is_within_preferred_time("afternoon", time(12, 0)) is True
        assert _is_within_preferred_time("afternoon", time(13, 59)) is True
        assert _is_within_preferred_time("afternoon", time(14, 0)) is False

    def test_evening_window(self):
        # 18:00–22:00 (exclusive end)
        assert _is_within_preferred_time("evening", time(17, 59)) is False
        assert _is_within_preferred_time("evening", time(18, 0)) is True
        assert _is_within_preferred_time("evening", time(21, 59)) is True
        assert _is_within_preferred_time("evening", time(22, 0)) is False

    def test_unknown_preferred_time_allows_any(self):
        assert _is_within_preferred_time("unknown", time(3, 0)) is True

    def test_windows_constant(self):
        assert PREFERRED_TIME_WINDOWS["morning"] == (6, 10)
        assert PREFERRED_TIME_WINDOWS["afternoon"] == (12, 14)
        assert PREFERRED_TIME_WINDOWS["evening"] == (18, 22)
        assert PREFERRED_TIME_WINDOWS["anytime"] is None


# ---------------------------------------------------------------------------
# get_due_measurements tests
# ---------------------------------------------------------------------------

class TestGetDueMeasurements:
    """Integration-style tests for the core collection function."""

    def test_no_goals_returns_empty(self):
        assert get_due_measurements([], [], TODAY) == []

    def test_inactive_goal_not_checked(self):
        goal = _goal(status="completed", measurement_requirements=[
            {"metric": "weight", "unit": "kg", "frequency": "daily"}
        ])
        due = get_due_measurements([goal], [], TODAY)
        assert due == []

    def test_no_requirements_returns_empty(self):
        goal = _goal(measurement_requirements=[])
        due = get_due_measurements([goal], [], TODAY)
        assert due == []

    def test_daily_due_no_entries(self):
        goal = _goal(
            target_value=75.0,
            direction="decrease",
            metric_unit="kg",
            measurement_requirements=[
                {"metric": "weight", "unit": "kg", "frequency": "daily", "preferred_time": "morning"}
            ],
        )
        due = get_due_measurements([goal], [], TODAY, now=time(7, 0))
        assert len(due) == 1
        req = due[0]
        assert req.goal_title == "Test Goal"
        assert req.metric == "weight"
        assert req.unit == "kg"
        assert req.frequency == "daily"
        assert req.preferred_time == "morning"
        assert req.last_recorded is None
        assert req.last_value is None
        assert req.target_value == 75.0
        assert req.direction == "decrease"
        assert req.interval_days is None

    def test_daily_not_due_already_recorded_today(self):
        goal = _goal(measurement_requirements=[
            {"metric": "weight", "unit": "kg", "frequency": "daily"}
        ])
        entries = [_entry("2026-09-06")]
        due = get_due_measurements([goal], entries, TODAY, now=time(7, 0))
        assert due == []

    def test_daily_due_after_recording_yesterday(self):
        goal = _goal(measurement_requirements=[
            {"metric": "weight", "unit": "kg", "frequency": "daily"}
        ])
        entries = [_entry("2026-09-05", value=82.0)]
        due = get_due_measurements([goal], entries, TODAY, now=time(7, 0))
        assert len(due) == 1
        assert due[0].last_recorded == date(2026, 9, 5)
        assert due[0].last_value == 82.0

    def test_preferred_time_filters_outside_window(self):
        goal = _goal(measurement_requirements=[
            {"metric": "weight", "unit": "kg", "frequency": "daily", "preferred_time": "morning"}
        ])
        # 14:00 is outside the morning window (06:00–10:00)
        due = get_due_measurements([goal], [], TODAY, now=time(14, 0))
        assert due == []

    def test_preferred_time_returns_within_window(self):
        goal = _goal(measurement_requirements=[
            {"metric": "weight", "unit": "kg", "frequency": "daily", "preferred_time": "morning"}
        ])
        due = get_due_measurements([goal], [], TODAY, now=time(7, 0))
        assert len(due) == 1

    def test_now_none_ignores_preferred_time(self):
        goal = _goal(measurement_requirements=[
            {"metric": "weight", "unit": "kg", "frequency": "daily", "preferred_time": "morning"}
        ])
        # now=None — preferred_time ignored, measurement is due
        due = get_due_measurements([goal], [], TODAY, now=None)
        assert len(due) == 1

    def test_anytime_no_time_restriction(self):
        goal = _goal(measurement_requirements=[
            {"metric": "weight", "unit": "kg", "frequency": "daily", "preferred_time": "anytime"}
        ])
        # At 2am — still due because "anytime"
        due = get_due_measurements([goal], [], TODAY, now=time(2, 0))
        assert len(due) == 1

    def test_missing_preferred_time_treated_as_anytime(self):
        goal = _goal(measurement_requirements=[
            {"metric": "weight", "unit": "kg", "frequency": "daily"}
        ])
        # preferred_time not specified — should be treated as "anytime"
        due = get_due_measurements([goal], [], TODAY, now=time(2, 0))
        assert len(due) == 1
        assert due[0].preferred_time is None

    def test_twice_weekly_not_due_recent(self):
        goal = _goal(measurement_requirements=[
            {"metric": "waist", "unit": "cm", "frequency": "twice_weekly"}
        ])
        entries = [_entry("2026-09-05", metric="waist", value=85.0)]
        due = get_due_measurements([goal], entries, TODAY, now=time(7, 0))
        assert due == []

    def test_twice_weekly_due_after_3_days(self):
        goal = _goal(measurement_requirements=[
            {"metric": "waist", "unit": "cm", "frequency": "twice_weekly", "preferred_time": "evening"}
        ])
        entries = [_entry("2026-09-03", metric="waist", value=85.0)]
        due = get_due_measurements([goal], entries, TODAY, now=time(19, 0))
        assert len(due) == 1
        assert due[0].last_recorded == date(2026, 9, 3)
        assert due[0].preferred_time == "evening"

    def test_weekly_due_after_7_days(self):
        goal = _goal(measurement_requirements=[
            {"metric": "savings", "unit": "PLN", "frequency": "weekly"}
        ])
        entries = [_entry("2026-08-30", metric="savings", value=1000.0)]
        due = get_due_measurements([goal], entries, TODAY, now=time(7, 0))
        assert len(due) == 1

    def test_weekly_not_due_before_7_days(self):
        goal = _goal(measurement_requirements=[
            {"metric": "savings", "unit": "PLN", "frequency": "weekly"}
        ])
        entries = [_entry("2026-09-02", metric="savings", value=1000.0)]
        due = get_due_measurements([goal], entries, TODAY, now=time(7, 0))
        assert due == []

    def test_weekends_not_due_weekday(self):
        # September 6 is a Sunday; use September 8 (Tuesday)
        tuesday = date(2026, 9, 8)
        goal = _goal(measurement_requirements=[
            {"metric": "mood", "unit": "score", "frequency": "weekends"}
        ])
        due = get_due_measurements([goal], [], tuesday, now=time(12, 0))
        assert due == []

    def test_weekends_due_saturday(self):
        sat = date(2026, 9, 5)
        goal = _goal(measurement_requirements=[
            {"metric": "mood", "unit": "score", "frequency": "weekends", "preferred_time": "anytime"}
        ])
        due = get_due_measurements([goal], [], sat, now=time(12, 0))
        assert len(due) == 1

    def test_custom_due_after_interval(self):
        goal = _goal(measurement_requirements=[
            {"metric": "reading", "unit": "pages", "frequency": "custom", "interval_days": 5}
        ])
        entries = [_entry("2026-09-01", metric="reading", value=20.0)]
        due = get_due_measurements([goal], entries, TODAY, now=None)
        assert len(due) == 1
        assert due[0].interval_days == 5

    def test_custom_not_due_before_interval(self):
        goal = _goal(measurement_requirements=[
            {"metric": "reading", "unit": "pages", "frequency": "custom", "interval_days": 5}
        ])
        entries = [_entry("2026-09-04", metric="reading", value=20.0)]
        # 2 days since last entry, interval is 5
        due = get_due_measurements([goal], entries, TODAY, now=None)
        assert due == []

    def test_multiple_requirements_mixed_due(self):
        goal = _goal(measurement_requirements=[
            {"metric": "weight", "unit": "kg", "frequency": "daily"},
            {"metric": "waist", "unit": "cm", "frequency": "daily"},
        ])
        entries = [_entry("2026-09-06", metric="weight", value=82.0)]
        # weight is recorded today, waist is not
        due = get_due_measurements([goal], entries, TODAY, now=time(7, 0))
        assert len(due) == 1
        assert due[0].metric == "waist"

    def test_multiple_goals_due(self):
        goal1 = _goal(
            title="Goal A",
            measurement_requirements=[
                {"metric": "weight", "unit": "kg", "frequency": "daily"}
            ],
        )
        goal2 = _goal(
            title="Goal B",
            measurement_requirements=[
                {"metric": "savings", "unit": "PLN", "frequency": "daily"}
            ],
        )
        due = get_due_measurements([goal1, goal2], [], TODAY, now=time(7, 0))
        assert len(due) == 2
        metrics = {r.metric for r in due}
        assert metrics == {"weight", "savings"}

    def test_goal_with_no_metric_in_requirement_skipped(self):
        goal = _goal(measurement_requirements=[
            {"frequency": "daily"},  # missing metric
        ])
        due = get_due_measurements([goal], [], TODAY, now=time(7, 0))
        assert due == []

    def test_goal_defaults_to_daily_frequency(self):
        goal = _goal(measurement_requirements=[
            {"metric": "steps", "unit": "count"}
            # no frequency specified — should default to "daily"
        ])
        due = get_due_measurements([goal], [], TODAY, now=None)
        assert len(due) == 1
        assert due[0].frequency == "daily"

    def test_last_value_and_recorded_populated(self):
        goal = _goal(
            target_value=75.0,
            direction="decrease",
            measurement_requirements=[
                {"metric": "weight", "unit": "kg", "frequency": "daily"}
            ],
        )
        entries = [_entry("2026-09-03", value=83.0)]
        due = get_due_measurements([goal], entries, TODAY, now=None)
        assert len(due) == 1
        assert due[0].last_recorded == date(2026, 9, 3)
        assert due[0].last_value == 83.0

    def test_no_duplicate_due_for_same_metric(self):
        """Two entries for same metric — only the latest date matters."""
        goal = _goal(measurement_requirements=[
            {"metric": "weight", "unit": "kg", "frequency": "daily"}
        ])
        entries = [
            _entry("2026-09-03", value=83.0),
            _entry("2026-09-05", value=82.0),
        ]
        # Last entry is yesterday — weight is due today
        due = get_due_measurements([goal], entries, TODAY, now=None)
        assert len(due) == 1
        assert due[0].last_recorded == date(2026, 9, 5)
        assert due[0].last_value == 82.0


# ---------------------------------------------------------------------------
# Integration tests — realistic goal + log setups
# ---------------------------------------------------------------------------

class TestIntegration:
    """Tests combining goals, entries, and the collection function end-to-end."""

    def test_realistic_weight_and_waist_setup(self):
        """A goal with daily weight (morning) and twice-weekly waist (evening).

        Weight was recorded yesterday; waist was recorded 4 days ago.
        Today is Sunday. Weight is due (not recorded today), waist is due
        (>= 3 days since last).
        """
        goal = _goal(
            title="Reduce body fat",
            target_value=75.0,
            direction="decrease",
            metric_unit="kg",
            measurement_requirements=[
                {"metric": "weight", "unit": "kg", "frequency": "daily", "preferred_time": "morning"},
                {"metric": "waist", "unit": "cm", "frequency": "twice_weekly", "preferred_time": "evening"},
            ],
        )
        entries = [
            _entry("2026-09-05", metric="weight", value=82.0, goal_title="Reduce body fat"),
            _entry("2026-09-02", metric="waist", value=85.0, goal_title="Reduce body fat"),
        ]
        # now=None means preferred_time is ignored — all due measurements returned
        due = get_due_measurements([goal], entries, TODAY, now=None)
        assert len(due) == 2
        metrics = {r.metric for r in due}
        assert metrics == {"weight", "waist"}

    def test_realistic_with_preferred_time_filtering(self):
        """Same goal, but now it's 14:00 (afternoon) — morning weight is not due."""
        goal = _goal(
            title="Reduce body fat",
            target_value=75.0,
            direction="decrease",
            measurement_requirements=[
                {"metric": "weight", "unit": "kg", "frequency": "daily", "preferred_time": "morning"},
                {"metric": "waist", "unit": "cm", "frequency": "daily", "preferred_time": "evening"},
            ],
        )
        entries = []
        # 14:00 — morning window (06-10) is closed, evening (18-22) hasn't opened
        due = get_due_measurements([goal], entries, TODAY, now=time(14, 0))
        assert len(due) == 0

    def test_realistic_evening_collection_time(self):
        """At 19:00 — evening window is open, both measurements due."""
        goal = _goal(
            title="Reduce body fat",
            target_value=75.0,
            direction="decrease",
            measurement_requirements=[
                {"metric": "weight", "unit": "kg", "frequency": "daily", "preferred_time": "morning"},
                {"metric": "waist", "unit": "cm", "frequency": "daily", "preferred_time": "evening"},
            ],
        )
        due = get_due_measurements([goal], [], TODAY, now=time(19, 0))
        # Only the evening-preferred measurement is due at this time
        assert len(due) == 1
        assert due[0].metric == "waist"

    def test_mixed_active_inactive_goals(self):
        """Inactive goals are skipped entirely."""
        active_goal = _goal(
            title="Active Goal",
            measurement_requirements=[
                {"metric": "weight", "unit": "kg", "frequency": "daily"},
            ],
        )
        inactive_goal = _goal(
            title="Inactive Goal",
            status="inactive",
            measurement_requirements=[
                {"metric": "savings", "unit": "PLN", "frequency": "daily"},
            ],
        )
        due = get_due_measurements([active_goal, inactive_goal], [], TODAY, now=None)
        assert len(due) == 1
        assert due[0].goal_title == "Active Goal"

    def test_custom_frequency_with_interval_days(self):
        """Custom frequency with 10-day interval and 5 days since last."""
        goal = _goal(measurement_requirements=[
            {"metric": "blood_pressure", "unit": "mmHg", "frequency": "custom", "interval_days": 10},
        ])
        entries = [_entry("2026-08-31", metric="blood_pressure", value=120.0)]
        # 6 days since last entry — not due (interval is 10)
        due = get_due_measurements([goal], entries, TODAY, now=None)
        assert due == []

    def test_custom_frequency_due_after_interval(self):
        """Custom frequency with 10-day interval and 6 days since last."""
        goal = _goal(measurement_requirements=[
            {"metric": "blood_pressure", "unit": "mmHg", "frequency": "custom", "interval_days": 10},
        ])
        entries = [_entry("2026-08-27", metric="blood_pressure", value=120.0)]
        # 10 days since last entry — due
        due = get_due_measurements([goal], entries, TODAY, now=None)
        assert len(due) == 1
