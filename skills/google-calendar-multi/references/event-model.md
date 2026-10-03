# Event Model — Source Field and All-Day Timezone Handling

## Why `source` on Event

The `Event` dataclass carries a `source: str | None` field that holds the **human-readable calendar name** (e.g. "Job", "Personal"), not the Google `calendarId` (e.g. `"JOB_CALENDAR_ID"`).

**Reasons:**
- Output is legible: `09:00 — Daily standup — Job` vs `09:00 — Daily standup — JOB_CALENDAR_ID`
- Decouples display from implementation: calendar IDs can change without touching output logic
- Makes the source of truth explicit: the name comes from config, not from the API response

**Rule:** `source` is set **after** fetching events from the API, in `list_upcoming_events()`. The `parse_event()` function accepts an optional `source` parameter but the primary assignment happens in the aggregation loop.

## Dataclass definition

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Event:
    title: str
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    source: str | None = None
```

## All-day event timezone handling

Google Calendar returns all-day events as:

```json
{"start": {"date": "2026-08-28"}}
```

No time, no timezone. `datetime.combine(date, datetime.min.time())` produces a **naive** datetime.

**Problem:** If timed events are timezone-aware (they are — Google returns `dateTime` with `Z` offset), mixing naive and aware datetimes causes:
- `TypeError` when sorting/comparing
- Inconsistent behavior in timezone-sensitive code

**Fix:** Make all-day `Event.start` timezone-aware too:

```python
datetime.combine(
    date.fromisoformat(start_data["date"]),
    datetime.min.time(),
    tzinfo=timezone.utc,
)
```

This ensures every `Event.start` is consistently UTC-aware.

**Sort key must also be timezone-aware:**

```python
all_events.sort(key=lambda e: (
    e.start is None or e.all_day,
    e.start or datetime.min.replace(tzinfo=timezone.utc),
))
```

Note `datetime.min.replace(tzinfo=timezone.utc)` — plain `datetime.min` is naive and would mismatch.
