"""Measurement collection service for Janus.

Determines which measurements are currently due for collection based on
Goal measurement requirements and the existing measurement log.

This is a pure function from (goals, entries, today, now) → due measurements.
It has no side effects and no awareness of how the result will be used.
"""

from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import IntEnum

from janus.models.goal import Goal
from janus.services.measurement_log import MeasurementEntry, find_last_entry


# ---------------------------------------------------------------------------
# Constants from design §4.2 and §4.3
# ---------------------------------------------------------------------------

_VALID_FREQUENCIES = {"daily", "twice_weekly", "weekly", "weekends", "custom"}
_VALID_PREFERRED_TIMES = {"morning", "afternoon", "evening", "anytime"}


class PreferredTimeWindow(IntEnum):
    """Preferred time windows for measurement collection."""
    MORNING_START = 6
    MORNING_END = 10       # exclusive
    AFTERNOON_START = 12
    AFTERNOON_END = 14     # exclusive
    EVENING_START = 18
    EVENING_END = 22       # exclusive


PREFERRED_TIME_WINDOWS: dict[str, tuple[int, int] | None] = {
    "morning": (PreferredTimeWindow.MORNING_START, PreferredTimeWindow.MORNING_END),
    "afternoon": (PreferredTimeWindow.AFTERNOON_START, PreferredTimeWindow.AFTERNOON_END),
    "evening": (PreferredTimeWindow.EVENING_START, PreferredTimeWindow.EVENING_END),
    "anytime": None,
}


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------

@dataclass
class MeasurementRequest:
    """A measurement that is currently due for collection."""
    goal_title: str
    metric: str
    unit: str
    frequency: str
    preferred_time: str | None
    last_recorded: date | None       # date of last measurement, if any
    last_value: float | None         # value of last measurement, if any
    target_value: float | None       # copied from Goal for context
    direction: str | None            # copied from Goal for context
    interval_days: int | None        # only for custom frequency


# ---------------------------------------------------------------------------
# Frequency schedule logic
# ---------------------------------------------------------------------------

def _is_frequency_due(
    frequency: str,
    today: date,
    last_date: date | None,
    interval_days: int | None = None,
) -> bool:
    """Determine whether a measurement is due based on its frequency.

    Args:
        frequency: One of daily, twice_weekly, weekly, weekends, custom.
        today: The date being evaluated.
        last_date: Date of the most recent entry, or None if no entry exists.
        interval_days: Required for frequency="custom".

    Returns:
        True if a new collection is due.
    """
    if frequency == "weekends":
        # Due on Saturday or Sunday if no entry has been recorded yet this weekend.
        # "This weekend" means since the most recent Friday.
        if today.weekday() not in (5, 6):  # Saturday=5, Sunday=6
            return False
        if last_date is None:
            return True
        # Find the most recent Friday (weekday=4)
        days_since_friday = (today.weekday() - 4) % 7
        recent_friday = today - timedelta(days=days_since_friday)
        # Not due if last entry was this weekend (after Friday)
        return last_date < recent_friday

    elif frequency == "custom":
        if interval_days is None:
            raise ValueError("frequency='custom' requires interval_days")
        if last_date is None:
            return True
        return (today - last_date).days >= interval_days

    elif frequency == "daily":
        # Due if no entry for today — check by date, not elapsed days
        if last_date is None:
            return True
        return last_date < today

    elif frequency == "twice_weekly":
        # Due if the last entry is 3 or more days ago
        if last_date is None:
            return True
        return (today - last_date).days >= 3

    elif frequency == "weekly":
        # Due if the last entry is 7 or more days ago
        if last_date is None:
            return True
        return (today - last_date).days >= 7

    else:
        # Unknown frequency — not due (unknown frequencies are ignored)
        return False


# ---------------------------------------------------------------------------
# Preferred time window logic
# ---------------------------------------------------------------------------

def _is_within_preferred_time(preferred_time: str | None, now: time | None) -> bool:
    """Determine whether the current time falls within the preferred window.

    Args:
        preferred_time: One of morning, afternoon, evening, anytime, or None.
        now: Current time, or None if unavailable.

    Returns:
        True if the measurement should be considered due based on time.

    - If now is None, preferred_time is ignored and the measurement is due.
    - If preferred_time is "anytime" or None, no restriction applies.
    - If now is outside the preferred window, the measurement is not due.
    """
    if now is None:
        return True

    if preferred_time is None or preferred_time == "anytime":
        return True

    window = PREFERRED_TIME_WINDOWS.get(preferred_time)
    if window is None:
        return True  # Unknown preferred_time — no restriction

    start_hour, end_hour = window
    current_hour = now.hour
    return start_hour <= current_hour < end_hour


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def get_due_measurements(
    goals: list[Goal],
    entries: list[MeasurementEntry],
    today: date,
    now: time | None = None,
) -> list[MeasurementRequest]:
    """Return measurements that are currently due for collection.

    A measurement is due when:
    1. Its goal is active AND has measurement_requirements.
    2. The frequency schedule says a new collection is due.
    3. If preferred_time is set, the current time is within the preferred window.

    Args:
        goals: Active goals with potential requirements.
        entries: Historical measurement log.
        today: The date being evaluated (for "is it time today?" logic).
        now: Current time (for preferred_time window checks). If None,
             preferred_time is ignored and all due measurements are returned
             regardless of time.

    Returns:
        List of MeasurementRequest objects for measurements that are due.
    """
    due: list[MeasurementRequest] = []

    for goal in goals:
        # Only active goals with measurement requirements are considered
        if goal.status != "active":
            continue
        if not goal.measurement_requirements:
            continue

        for req in goal.measurement_requirements:
            metric = req.get("metric")
            if not metric:
                continue

            frequency = req.get("frequency", "daily")
            if frequency not in _VALID_FREQUENCIES:
                continue  # Unknown frequency — skip

            preferred_time = req.get("preferred_time")
            interval_days = req.get("interval_days") if frequency == "custom" else None

            # Check preferred time window
            if not _is_within_preferred_time(preferred_time, now):
                continue

            # Find the last recorded entry for this goal + metric
            last_entry = find_last_entry(entries, goal.title, metric)

            last_date = last_entry.date if last_entry else None
            last_value = last_entry.value if last_entry else None

            # Check frequency schedule
            if not _is_frequency_due(frequency, today, last_date, interval_days):
                continue

            due.append(MeasurementRequest(
                goal_title=goal.title,
                metric=metric,
                unit=req.get("unit", goal.metric_unit or ""),
                frequency=frequency,
                preferred_time=preferred_time,
                last_recorded=last_date,
                last_value=last_value,
                target_value=goal.target_value,
                direction=goal.direction,
                interval_days=interval_days,
            ))

    return due
