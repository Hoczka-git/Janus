"""Tests for calendar-aware planning integration in the Daily Briefing service."""

from datetime import date, datetime, timedelta, timezone

import pytest

from janus.models.attention import AttentionItem
from janus.models.event import Event
from janus.models.task import Task
from janus.models.goal import Goal
from janus.models.time_block import TimeBlock
from janus.services.daily_briefing import create_daily_briefing

FIXED_TODAY = date(2026, 8, 28)
LOCAL_TZ = timezone(timedelta(hours=2))


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                    hour, minute, tzinfo=LOCAL_TZ)


def _timed_event(title: str, sh: int, sm: int, eh: int, em: int) -> Event:
    return Event(title=title, start=_ts(sh, sm), end=_ts(eh, em), all_day=False)


def _task(title: str, due=None, priority: int = 1, extra_metadata=None) -> Task:
    return Task(title=title, due_date=due, priority=priority,
                extra_metadata=extra_metadata)


class TestNoCalendarConfigured:
    @pytest.fixture(autouse=True)
    def _mock_calendar_config(self, monkeypatch):
        monkeypatch.setattr(
            "janus.integrations.google_calendar._load_config",
            lambda: [],
        )

    def test_no_calendar_no_free_slots(self):
        """When calendars aren't configured, free_slots is empty."""
        briefing = create_daily_briefing([], [], [], FIXED_TODAY)
        assert briefing.free_slots == []
        assert briefing.overload_warning is None
        assert briefing.placements == []
        assert briefing.has_calendar is False

    def test_no_calendar_preserves_attention_items(self):
        """Without calendar config, attention items are unchanged (no overload)."""
        tasks = [_task("Overdue", due=date(2026, 8, 25), priority=1)]
        briefing = create_daily_briefing([], tasks, [], FIXED_TODAY)
        # No overload item prepended.
        assert len(briefing.attention_items) == 1
        assert briefing.attention_items[0].category == "overdue_task"
        assert briefing.suggested_focus is not None


class TestWithCalendarMocked:
    """Tests with calendar config mocked ON to exercise planning logic."""

    @pytest.fixture(autouse=True)
    def _mock_calendar_config(self, monkeypatch):
        monkeypatch.setattr(
            "janus.integrations.google_calendar._load_config",
            lambda: [("primary@example.com", "Personal")],
        )
        # Mock config loading to use defaults (no real config.toml).
        from janus.services.overload import PlanningConfig
        monkeypatch.setattr(
            "janus.services.overload.load_planning_config",
            lambda: PlanningConfig(),
        )

    def test_free_slots_full_window_when_no_events(self):
        """Calendar configured, no events → full work window as one slot."""
        briefing = create_daily_briefing([], [], [], FIXED_TODAY)
        assert briefing.has_calendar is True
        assert len(briefing.free_slots) == 1
        assert briefing.free_slots[0].is_free
        assert briefing.free_slots[0].duration_minutes == 480
        assert briefing.overload_warning is None

    def test_free_slots_gaps_when_events_present(self):
        """Calendar configured with events → free slots computed."""
        events = [_timed_event("Meeting", 9, 0, 10, 0)]
        briefing = create_daily_briefing(events, [], [], FIXED_TODAY)
        assert len(briefing.free_slots) == 1
        assert briefing.free_slots[0].start == _ts(10, 0)
        assert briefing.free_slots[0].end == _ts(17, 0)
        assert briefing.free_slots[0].duration_minutes == 420

    def test_overload_critical_full_day_booked(self):
        """Fully booked work day → critical overload warning."""
        events = [_timed_event("Meeting", 9, 0, 17, 0)]
        tasks = []
        briefing = create_daily_briefing(events, tasks, [], FIXED_TODAY)
        assert briefing.overload_warning is not None
        # Overload message indicates high load with [measured] confidence.
        assert "[measured]" in briefing.overload_warning
        assert "HIGH MEETING LOAD" in briefing.overload_warning
        # Overload prepended as a score-200 attention item.
        first = briefing.attention_items[0]
        assert first.category == "overload_warning"
        assert first.score == 200

    def test_overload_warning_does_not_steal_suggested_focus(self):
        """suggested_focus stays as the top task, not the overload warning."""
        events = [_timed_event("Meeting", 9, 0, 17, 0)]
        tasks = [_task("Overdue", due=date(2026, 8, 25), priority=1)]
        briefing = create_daily_briefing(events, tasks, [], FIXED_TODAY)
        assert briefing.suggested_focus is not None
        assert briefing.suggested_focus.category == "overdue_task"

    def test_placements_generated_from_attention_items(self):
        """With free slots and urgent tasks, placements are computed."""
        tasks = [
            _task("Buy groceries", due=FIXED_TODAY, priority=2),
            _task("Write report", due=date(2026, 9, 10), priority=3),
        ]
        briefing = create_daily_briefing([], tasks, [], FIXED_TODAY)
        assert len(briefing.placements) >= 1
        # Each placement has a task title, a free slot, and a reason.
        for p in briefing.placements:
            assert p.task_title
            assert p.slot.is_free
            assert p.reason

    def test_placements_empty_when_no_free_slots(self):
        """Fully booked → no placements."""
        events = [_timed_event("Meeting", 9, 0, 17, 0)]
        tasks = [_task("Task", due=FIXED_TODAY, priority=1)]
        briefing = create_daily_briefing(events, tasks, [], FIXED_TODAY)
        assert briefing.placements == []
