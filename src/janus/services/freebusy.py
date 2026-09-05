"""Free/busy slot computation for Janus calendar-aware planning.

Computes available focus blocks from calendar events within configured
work-hours windows.
"""

from datetime import date, datetime, timedelta, tzinfo
from typing import Optional

from janus.models.event import Event
from janus.models.time_block import TimeBlock


def _to_tz(dt: datetime, tz: tzinfo) -> datetime:
    """Convert a datetime to the target timezone.

    Naive datetimes are assumed to already be in the target tz (the user's
    local timezone) per the existing today-filter convention.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _work_window(day: date, work_hours: tuple[int, int], tz) -> tuple[datetime, datetime]:
    start_h, end_h = work_hours
    window_start = datetime(
        day.year, day.month, day.day, start_h, 0, tzinfo=tz
    )
    window_end = datetime(
        day.year, day.month, day.day, end_h, 0, tzinfo=tz
    )
    return window_start, window_end


def _build_busy_intervals(events: list[Event], day: date, tz) -> list[tuple[datetime, datetime]]:
    """Build sorted, merged busy intervals (clamped to work hours) for the day."""
    busy: list[tuple[datetime, datetime]] = []
    for event in events:
        if event.start is None:
            continue
        if event.all_day:
            continue  # all-day events excluded from slot computation (§5.2)
        start_dt = _to_tz(event.start, tz)
        if start_dt.date() != day:
            continue
        if event.end is not None:
            end_dt = _to_tz(event.end, tz)
        else:
            # Conservative 60-min busy assumption (§5.2)
            end_dt = start_dt + timedelta(hours=1)
        busy.append((start_dt, end_dt))

    if not busy:
        return []

    busy.sort(key=lambda iv: iv[0])
    merged: list[tuple[datetime, datetime]] = [busy[0]]
    for cur_start, cur_end in busy[1:]:
        last_start, last_end = merged[-1]
        if cur_start <= last_end:
            merged[-1] = (last_start, max(last_end, cur_end))
        else:
            merged.append((cur_start, cur_end))
    return merged


def compute_free_slots(
    events: list[Event],
    day: date,
    work_hours: tuple[int, int] = (9, 17),
    min_slot_minutes: int = 30,
    tz: Optional[tzinfo] = None,
) -> list[TimeBlock]:
    """Compute free focus blocks from calendar events for a given day.

    Args:
        events: All events (timed + all-day). Only today's timed events are
            considered for busy-interval computation.
        day: The date to analyze.
        work_hours: (start_hour, end_hour) 24-hour window. Default (9, 17).
        min_slot_minutes: Minimum consecutive free minutes to qualify. Default 30.
        tz: Target timezone. When None, derived from the first timezone-aware
            event so free-block display aligns with event display times; falls
            back to the local timezone for naive datetimes or empty input.

    Returns:
        Free slots sorted by start time. Empty list when no free slots meet
        the minimum threshold.
    """
    if tz is None:
        aware_tzs = [
            e.start.tzinfo
            for e in events
            if e.start is not None and e.start.tzinfo is not None
        ]
        tz = aware_tzs[0] if aware_tzs else datetime.now().astimezone().tzinfo

    window_start, window_end = _work_window(day, work_hours, tz)
    busy_intervals = _build_busy_intervals(events, day, tz)

    # Clamp busy intervals to the work-hours window.
    clamped: list[tuple[datetime, datetime]] = []
    for b_start, b_end in busy_intervals:
        if b_end <= window_start or b_start >= window_end:
            continue  # entirely outside work window
        clamped.append((max(b_start, window_start), min(b_end, window_end)))

    clamped.sort(key=lambda iv: iv[0])

    # Compute gaps within the work window.
    gaps: list[TimeBlock] = []
    cursor = window_start
    for b_start, b_end in clamped:
        if b_start > cursor:
            free = TimeBlock(start=cursor, end=b_start, title="", type="free")
            if free.duration_minutes >= min_slot_minutes:
                gaps.append(free)
        cursor = max(cursor, b_end)

    # Gap after last busy interval up to window end.
    if cursor < window_end:
        free = TimeBlock(start=cursor, end=window_end, title="", type="free")
        if free.duration_minutes >= min_slot_minutes:
            gaps.append(free)

    return gaps
