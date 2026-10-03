# FakeCalendarService — Mock Google Calendar API for Tests

## Pattern

When unit-testing Google Calendar integration, never hit the real API. Build a fake that mirrors the API surface you actually use.

## FakeCalendarService

```python
class FakeCalendarService:
    def __init__(self, events_by_calendar: dict[str, list[dict]]):
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
```

**Why this shape:**
- `service.events()` returns `self` (the service itself) — matches `googleapiclient.discovery.build("calendar", "v3")`
- `.list(calendarId=..., ...)` returns a response object with `.execute()` — matches the real API chain
- `calendarId` mapping lets you return different events per calendar
- Copying the list (`list(...)`) avoids mutation of the original dict

## Wiring with pytest monkeypatch

```python
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
```

The fixture returns a `_maker` function so each test can pass its own events-per-calendar dict.

## Usage in a test

```python
def test_multi_calendar_loading(fake_google_calendar, monkeypatch):
    job_ev = {"summary": "Sprint planning", "start": {"dateTime": "2026-08-28T09:00:00+00:00"}}
    personal_ev = {"summary": "Gym session", "start": {"dateTime": "2026-08-28T18:00:00+00:00"}}

    fake_google_calendar({
        "JOB_CALENDAR_ID": [job_ev],
        "PERSONAL_CALENDAR_ID": [personal_ev],
    })

    monkeypatch.setattr(
        "janus.integrations.google_calendar._load_config",
        lambda: [("JOB_CALENDAR_ID", "Job"), ("PERSONAL_CALENDAR_ID", "Personal")],
    )

    events = list_upcoming_events()

    assert len(events) == 2
    assert events[0].title == "Sprint planning"
    assert events[0].source == "Job"
    assert events[1].title == "Gym session"
    assert events[1].source == "Personal"
```

## Event dict format

The fake returns dicts in the shape Google API returns:

```python
{
    "summary": "Event title",
    "start": {"dateTime": "2026-08-28T09:00:00+00:00"},  # timed
    # or
    "start": {"date": "2026-08-28"},  # all-day
    "end": {"dateTime": "2026-08-28T10:00:00+00:00"},  # optional
}
```

For all-day events, omit `end` or set it to `{}`.
