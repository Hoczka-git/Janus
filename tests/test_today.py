"""Tests for today.py presentation layer — rendering behavior only.

These tests verify that show_today() renders events, tasks, goals, and focus
correctly with the new Attention Engine integration. Business logic
(classification, ordering, scoring) is covered in test_attention.py and
test_daily_briefing.py and must not be duplicated here.
"""

from datetime import date, datetime, timezone
from io import StringIO
from unittest.mock import patch

import pytest

from janus.models.event import Event
from janus.models.task import Task
from janus.models.goal import Goal
from janus.services.daily_briefing import create_daily_briefing
from janus.today import show_today


FIXED_TODAY = date(2026, 8, 28)


def _make_event(title: str, hour: int, minute: int, source: str) -> Event:
    start = datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                     hour, minute, tzinfo=timezone.utc)
    return Event(title=title, start=start, all_day=False, source=source)


def _make_all_day_event(title: str, source: str) -> Event:
    start = datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                     0, 0, tzinfo=timezone.utc)
    return Event(title=title, start=start, all_day=True, source=source)


def _make_task(title: str, due: date | None, priority: int) -> Task:
    return Task(title=title, due_date=due, priority=priority)


def _make_goal(title: str, status: str = "active",
               related_tasks: list[str] | None = None) -> Goal:
    return Goal(title=title, status=status,
                related_tasks=related_tasks or [])


def _capture_show_today(events, tasks, goals, today=FIXED_TODAY):
    """Run show_today() with mocked dependencies and return printed output."""
    with patch("janus.today.list_upcoming_events", return_value=events), \
         patch("janus.today.load_tasks", return_value=tasks), \
         patch("janus.today.load_goals", return_value=goals), \
         patch("janus.today.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.__eq__ = lambda self, other: self.toordinal() == other.toordinal()
        mock_date.__hash__ = lambda self: hash(self.toordinal())
        mock_date.isoformat.return_value = today.isoformat()

        buf = StringIO()
        with patch("sys.stdout", buf):
            show_today()
        return buf.getvalue()


class TestTimedEventRendering:
    def test_single_timed_event(self):
        events = [_make_event("Team standup", 9, 30, "Job")]
        tasks = []
        goals = []
        output = _capture_show_today(events, tasks, goals)

        assert "SCHEDULE" in output
        assert "Team standup" in output
        assert "09:30" in output
        assert "Job" in output


class TestAllDayEventRendering:
    def test_all_day_event_format(self):
        events = [_make_all_day_event("Company holiday", "Personal")]
        tasks = []
        goals = []
        output = _capture_show_today(events, tasks, goals)

        assert "SCHEDULE" in output
        assert "Company holiday" in output
        assert "All day" in output


class TestEventSourceRendering:
    def test_event_displays_source(self):
        events = [
            _make_event("Job event", 10, 0, "Job"),
            _make_event("Personal event", 14, 0, "Personal"),
            _make_event("Janus event", 18, 0, "Janus"),
        ]
        tasks = []
        goals = []
        output = _capture_show_today(events, tasks, goals)

        assert "Job event" in output
        assert "Personal event" in output
        assert "Janus event" in output
        assert "Job" in output
        assert "Personal" in output
        assert "Janus" in output


class TestRequiresAttentionRendering:
    def test_overdue_section(self):
        tasks = [_make_task("Overdue task", date(2026, 8, 25), 1)]
        events = []
        goals = []
        output = _capture_show_today(events, tasks, goals)

        assert "REQUIRES ATTENTION" in output
        assert "Overdue task" in output
        assert "Overdue by" in output

    def test_due_today_section(self):
        tasks = [_make_task("Due today task", FIXED_TODAY, 1)]
        events = []
        goals = []
        output = _capture_show_today(events, tasks, goals)

        assert "REQUIRES ATTENTION" in output
        assert "Due today task" in output
        assert "Due today" in output

    def test_high_priority_section(self):
        tasks = [_make_task("High priority task", date(2026, 9, 10), 3)]
        events = []
        goals = []
        output = _capture_show_today(events, tasks, goals)

        assert "REQUIRES ATTENTION" in output
        assert "High priority task" in output
        assert "High priority" in output

    def test_mixed_attention_sections(self):
        tasks = [
            _make_task("Overdue", date(2026, 8, 25), 1),
            _make_task("Due today", FIXED_TODAY, 2),
            _make_task("High priority", date(2026, 9, 10), 3),
        ]
        events = []
        goals = []
        output = _capture_show_today(events, tasks, goals)

        assert "Overdue" in output
        assert "Due today" in output
        assert "High priority" in output
        # Each item should have its reason shown
        assert "Overdue by" in output
        assert "Due today" in output
        assert "High priority" in output

    def test_goal_stalled_in_attention(self, monkeypatch):
        import janus.services.attention as attn

        def _load_from_string(_path):
            titles = set()
            for line in "- [x] Prepare training plan".splitlines():
                line = line.strip()
                if line.startswith("- [ ]") or line.startswith("- [x]"):
                    title = line[5:].strip().split("|", 1)[0].strip()
                    if title:
                        titles.add(title)
            return titles

        monkeypatch.setattr(attn, "_load_all_task_titles", _load_from_string)
        tasks = []
        goals = [_make_goal("Training goal", "active",
                            related_tasks=["Prepare training plan"])]
        output = _capture_show_today([], tasks, goals)

        assert "REQUIRES ATTENTION" in output
        assert "Training goal" in output
        assert "All linked tasks are completed" in output


class TestSuggestedFocusRendering:
    def test_focus_section_present(self):
        tasks = [
            _make_task("Task one", date(2026, 8, 25), 1),
            _make_task("Task two", FIXED_TODAY, 1),
            _make_task("Task three", date(2026, 9, 10), 3),
        ]
        events = []
        goals = []
        output = _capture_show_today(events, tasks, goals)

        assert "SUGGESTED FOCUS" in output
        assert "Task one" in output  # highest score (overdue = 100)

    def test_focus_empty_when_no_tasks(self):
        tasks = []
        events = []
        goals = []
        output = _capture_show_today(events, tasks, goals)

        assert "SUGGESTED FOCUS" not in output


class TestEmptyStateRendering:
    def test_no_events_no_tasks(self):
        events = []
        tasks = []
        goals = []
        output = _capture_show_today(events, tasks, goals)

        assert "SCHEDULE" in output
        assert "No events scheduled today." in output
        assert "REQUIRES ATTENTION" in output
        assert "Nothing requires your attention today." in output
        assert "SUGGESTED FOCUS" not in output

class TestCalendarPlanningRendering:
    def test_free_slots_rendered(self, monkeypatch):
        """Free calendar slots are shown in the Today view."""
        from janus.models.time_block import TimeBlock
        from janus.models.daily_briefing import DailyBriefing

        free_slot = TimeBlock(
            start=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
        )

        monkeypatch.setattr(
            "janus.today.create_daily_briefing",
            lambda events, tasks, goals, today: DailyBriefing(
                events=events,
                free_slots=[free_slot],
                has_calendar=True,
            ),
        )

        output = _capture_show_today([], [], [])

        assert "FREE TIME" in output
        assert "10:00–12:00" in output
        assert "120 min" in output

    def test_overload_warning_rendered(self, monkeypatch):
        """Calendar overload warning is shown when present."""
        from janus.models.daily_briefing import DailyBriefing

        monkeypatch.setattr(
            "janus.today.create_daily_briefing",
            lambda events, tasks, goals, today: DailyBriefing(
                events=events,
                overload_warning="[measured] HIGH MEETING LOAD",
                has_calendar=True,
            ),
        )

        output = _capture_show_today([], [], [])

        assert "CALENDAR LOAD" in output
        assert "[measured] HIGH MEETING LOAD" in output

    def test_placements_rendered(self, monkeypatch):
        """Suggested task placements are shown."""
        from janus.models.daily_briefing import DailyBriefing
        from janus.models.time_block import Placement, TimeBlock

        slot = TimeBlock(
            start=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
        )
        placement = Placement(
            task_title="Write report",
            slot=slot,
            reason="Due today; fits in available 120-min block",
        )

        monkeypatch.setattr(
            "janus.today.create_daily_briefing",
            lambda events, tasks, goals, today: DailyBriefing(
                events=events,
                placements=[placement],
                has_calendar=True,
            ),
        )

        output = _capture_show_today([], [], [])

        assert "SUGGESTED PLACEMENTS" in output
        assert "Write report" in output
        assert "10:00–12:00" in output
        assert "Due today" in output


class TestCrossMidnightEvents:
    def test_event_started_previous_day_is_included(self, monkeypatch):
        """An event spanning midnight must reach the daily briefing."""
        from janus.models.daily_briefing import DailyBriefing

        event = Event(
            title="Overnight meeting",
            start=datetime(2026, 8, 27, 23, 0, tzinfo=timezone.utc),
            end=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
            all_day=False,
            source="Job",
        )

        captured = {}

        def fake_create_briefing(events, tasks, goals, today):
            captured["events"] = events
            return DailyBriefing(events=events)

        monkeypatch.setattr(
            "janus.today.create_daily_briefing",
            fake_create_briefing,
        )

        _capture_show_today([event], [], [])

        assert captured["events"] == [event]
