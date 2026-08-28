from datetime import date, datetime, timezone

import pytest

from janus.integrations.google_calendar import list_upcoming_events, parse_event


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_event(summary: str | None, start_dt: datetime, end_dt: datetime | None = None):
    ev = {
        "summary": summary,
        "start": {"dateTime": start_dt.isoformat()},
    }
    if end_dt:
        ev["end"] = {"dateTime": end_dt.isoformat()}
    return ev


def _calendar_event(title: str, start_dt: datetime, end_dt: datetime | None = None):
    ev = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat()},
    }
    if end_dt:
        ev["end"] = {"dateTime": end_dt.isoformat()}
    return ev


class FakeCalendarService:
    def __init__(self, events_by_calendar):
        self._events_by_calendar = events_by_calendar

    def events(self):
        return self

    def list(self, calendarId: str = "", **kwargs):
        result = list(self._events_by_calendar.get(calendarId, []))
        return self._FakeResponse(result)

    class _FakeResponse:
        def __init__(self, items):
            self._items = items

        def execute(self):
            return {"items": self._items}


@pytest.fixture
def fake_google_calendar(monkeypatch):
    def _maker(events_by_calendar):
        svc = FakeCalendarService(events_by_calendar)

        def _get_service():
            return svc

        monkeypatch.setattr(
            "janus.integrations.google_calendar.get_calendar_service",
            _get_service,
        )
        return svc

    return _maker


# ── parse_event ─────────────────────────────────────────────────────────────

def test_parse_event_timed():
    start = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    event_data = _make_event("Daily standup", start, end)

    result = parse_event(event_data, source="Job")

    assert result.title == "Daily standup"
    assert result.start == start
    assert result.end == end
    assert result.all_day is False
    assert result.source == "Job"


def test_parse_event_all_day():
    start = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
    event_data = {
        "summary": "Company holiday",
        "start": {"date": "2026-08-28"},
    }

    result = parse_event(event_data, source="Personal")

    assert result.title == "Company holiday"
    assert result.start == start
    assert result.end is None
    assert result.all_day is True
    assert result.source == "Personal"


def test_parse_event_missing_summary():
    start = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
    event_data = _make_event(None, start)

    result = parse_event(event_data, source="Job")

    assert result.title == "Untitled event"
    assert result.source == "Job"


def test_parse_event_with_end_time():
    start = datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 28, 11, 30, tzinfo=timezone.utc)
    event_data = _make_event("Training", start, end)

    result = parse_event(event_data, source="Personal")

    assert result.end == end
    assert result.source == "Personal"


# ── multi-calendar loading + sorting ────────────────────────────────────────

def test_multi_calendar_loading_joins_events(
    fake_google_calendar,
    monkeypatch,
):
    job_ev = _calendar_event(
        "Sprint planning",
        datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
    )
    personal_ev = _calendar_event(
        "Gym session",
        datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc),
    )

    fake_google_calendar(
        {
            "JOB_CALENDAR_ID": [job_ev],
            "PERSONAL_CALENDAR_ID": [personal_ev],
        }
    )

    monkeypatch.setattr(
        "janus.integrations.google_calendar._load_config",
        lambda: [
            ("JOB_CALENDAR_ID", "Job"),
            ("PERSONAL_CALENDAR_ID", "Personal"),
        ],
    )

    events = list_upcoming_events()

    assert len(events) == 2
    assert events[0].title == "Sprint planning"
    assert events[0].source == "Job"
    assert events[1].title == "Gym session"
    assert events[1].source == "Personal"


def test_events_sorted_chronologically(
    fake_google_calendar,
    monkeypatch,
):
    late_job = _calendar_event(
        "Code review",
        datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc),
    )
    early_personal = _calendar_event(
        "Morning run",
        datetime(2026, 8, 28, 7, 0, tzinfo=timezone.utc),
    )

    fake_google_calendar(
        {
            "JOB_CALENDAR_ID": [late_job],
            "PERSONAL_CALENDAR_ID": [early_personal],
        }
    )

    monkeypatch.setattr(
        "janus.integrations.google_calendar._load_config",
        lambda: [
            ("JOB_CALENDAR_ID", "Job"),
            ("PERSONAL_CALENDAR_ID", "Personal"),
        ],
    )

    events = list_upcoming_events()

    assert len(events) == 2
    assert events[0].title == "Morning run"
    assert events[0].source == "Personal"
    assert events[1].title == "Code review"
    assert events[1].source == "Job"


def test_source_assignment(
    fake_google_calendar,
    monkeypatch,
):
    ev = _calendar_event(
        "1:1 with manager",
        datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
    )

    fake_google_calendar({"JOB_CALENDAR_ID": [ev]})

    monkeypatch.setattr(
        "janus.integrations.google_calendar._load_config",
        lambda: [("JOB_CALENDAR_ID", "Job")],
    )

    events = list_upcoming_events()

    assert len(events) == 1
    assert events[0].source == "Job"


def test_source_assignment_personal(
    fake_google_calendar,
    monkeypatch,
):
    ev = _calendar_event(
        "Weekend hike planning",
        datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc),
    )

    fake_google_calendar({"PERSONAL_CALENDAR_ID": [ev]})

    monkeypatch.setattr(
        "janus.integrations.google_calendar._load_config",
        lambda: [("PERSONAL_CALENDAR_ID", "Personal")],
    )

    events = list_upcoming_events()

    assert len(events) == 1
    assert events[0].source == "Personal"
