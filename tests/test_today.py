"""Tests for today.py presentation layer — rendering behavior only.

These tests verify that show_today() renders events, tasks, and focus
correctly. Business logic (classification, ordering) is covered in
test_daily_briefing.py and must not be duplicated here.
"""

from datetime import date, datetime, timezone
from io import StringIO
from unittest.mock import patch

import pytest

from janus.models.event import Event
from janus.models.task import Task
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


def _capture_show_today(events, tasks, today=FIXED_TODAY):
    """Run show_today() with mocked dependencies and return printed output."""
    with patch("janus.today.list_upcoming_events", return_value=events), \
         patch("janus.today.load_tasks", return_value=tasks), \
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
        output = _capture_show_today(events, tasks)

        assert "SCHEDULE" in output
        assert "Team standup" in output
        assert "09:30" in output
        assert "Job" in output


class TestAllDayEventRendering:
    def test_all_day_event_format(self):
        events = [_make_all_day_event("Company holiday", "Personal")]
        tasks = []
        output = _capture_show_today(events, tasks)

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
        output = _capture_show_today(events, tasks)

        assert "Job event" in output
        assert "Personal event" in output
        assert "Janus event" in output
        # Each source label must appear next to its event title
        assert "Job" in output
        assert "Personal" in output
        assert "Janus" in output


class TestRequiresAttentionRendering:
    def test_overdue_section(self):
        tasks = [_make_task("Overdue task", date(2026, 8, 25), 1)]
        events = []
        output = _capture_show_today(events, tasks)

        assert "REQUIRES ATTENTION" in output
        assert "Overdue:" in output
        assert "Overdue task" in output

    def test_due_today_section(self):
        tasks = [_make_task("Due today task", FIXED_TODAY, 1)]
        events = []
        output = _capture_show_today(events, tasks)

        assert "REQUIRES ATTENTION" in output
        assert "Due today:" in output
        assert "Due today task" in output

    def test_high_priority_section(self):
        tasks = [_make_task("High priority task", date(2026, 9, 10), 3)]
        events = []
        output = _capture_show_today(events, tasks)

        assert "REQUIRES ATTENTION" in output
        assert "High priority:" in output
        assert "High priority task" in output

    def test_mixed_attention_sections(self):
        tasks = [
            _make_task("Overdue", date(2026, 8, 25), 1),
            _make_task("Due today", FIXED_TODAY, 2),
            _make_task("High priority", date(2026, 9, 10), 3),
        ]
        events = []
        output = _capture_show_today(events, tasks)

        assert "Overdue:" in output
        assert "Due today:" in output
        assert "High priority:" in output
        assert "Overdue" in output
        assert "Due today" in output
        assert "High priority" in output


class TestSuggestedFocusRendering:
    def test_focus_section_present(self):
        tasks = [
            _make_task("Task one", date(2026, 8, 25), 1),
            _make_task("Task two", FIXED_TODAY, 1),
            _make_task("Task three", date(2026, 9, 10), 3),
        ]
        events = []
        output = _capture_show_today(events, tasks)

        assert "SUGGESTED FOCUS" in output
        assert "1." in output
        assert "Task one" in output
        assert "2." in output
        assert "Task two" in output
        assert "3." in output
        assert "Task three" in output

    def test_focus_empty_when_no_tasks(self):
        tasks = []
        events = []
        output = _capture_show_today(events, tasks)

        assert "SUGGESTED FOCUS" not in output


class TestEmptyStateRendering:
    def test_no_events_no_tasks(self):
        events = []
        tasks = []
        output = _capture_show_today(events, tasks)

        assert "SCHEDULE" in output
        assert "No events scheduled today." in output
        assert "REQUIRES ATTENTION" in output
        assert "Nothing requires your attention today." in output
        assert "SUGGESTED FOCUS" not in output
