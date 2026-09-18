"""Markdown persistence dla workoutów Janus.

Canonical storage: data/workouts.md
Format: nagłówek + sekcje "## Workout:" z polami klucz=wartość.

Pojedynczy plik, rewrite przy zapisie (jak markdown_tasks.py / markdown_goals.py).
"""

from datetime import date, datetime, timezone
from json import dumps as json_dumps, loads as json_loads, JSONDecodeError
from pathlib import Path
from typing import Any, Optional, Union

from janus.integrations.atomic_io import atomic_write, compute_content_hash

from janus.models.workout import (
    Exercise,
    RunningWorkout,
    Set,
    StrengthWorkout,
    Workout,
    WorkoutType,
    dict_to_workout,
    workout_to_dict,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_HEADER = "# Fitness Workouts\n"


def _workouts_path() -> Path:
    """Path to data/workouts.md, computed from current PROJECT_ROOT.

    Lazily evaluated so that tests can patch PROJECT_ROOT and redirect I/O.
    """
    return PROJECT_ROOT / "data" / "workouts.md"


def load_workouts() -> list[Workout]:
    """Load all workouts from data/workouts.md."""
    path = _workouts_path()
    if not path.exists():
        return []

    workouts: list[Workout] = []
    current: dict[str, Any] | None = None
    seen_ids: set[str] = set()

    with path.open() as f:
        for line in f:
            stripped = line.strip()

            if stripped.startswith("## Workout:"):
                if current is not None:
                    workouts.append(_finalize_workout(current, seen_ids))
                current = {"raw": stripped[len("## Workout:"):].strip()}
            elif current is not None:
                if "=" in stripped and not stripped.startswith("#"):
                    key, _, value = stripped.partition("=")
                    current[key.strip()] = value.strip()

        if current is not None:
            workouts.append(_finalize_workout(current, seen_ids))

    return workouts


def save_workout(workout: Workout) -> None:
    """Append a single workout to data/workouts.md."""
    existing = load_workouts()
    existing.append(workout)
    _write_workouts(existing)


def save_workouts(workouts: list[Workout]) -> None:
    """Replace entire data/workouts.md with the given list."""
    _write_workouts(workouts)


def _write_workouts(workouts: list[Workout]) -> None:
    lines: list[str] = [_HEADER]

    for workout in workouts:
        lines.extend(_workout_to_markdown_lines(workout))
        lines.append("")

    path = _workouts_path()
    content = "\n".join(lines) + "\n"
    # Read current content for conflict detection
    expected_hash = None
    if path.exists():
        expected_hash = compute_content_hash(path.read_text(encoding="utf-8"))
    atomic_write(
        path,
        content,
        expected_hash=expected_hash,
        written_by="workout_md._write_workouts",
    )


def _workout_to_markdown_lines(workout: Workout) -> list[str]:
    lines: list[str] = []
    lines.append("## Workout:")
    d = workout_to_dict(workout)

    for key in ("id", "date", "workout_type", "source", "created_at", "updated_at"):
        if key in d and d[key] is not None:
            lines.append(f"{key} = {d[key]}")

    if isinstance(workout, StrengthWorkout):
        if workout.notes:
            lines.append(f"notes = {workout.notes}")
        if d.get("exercises"):
            lines.append(f"exercises = {json_dumps(d['exercises'])}")
    elif isinstance(workout, RunningWorkout):
        lines.append(f"distance_km = {workout.distance_km}")
        lines.append(f"duration_minutes = {workout.duration_minutes}")
        if workout.avg_hr_bpm is not None:
            lines.append(f"avg_hr_bpm = {workout.avg_hr_bpm}")
        if workout.elevation_m is not None:
            lines.append(f"elevation_m = {workout.elevation_m}")
        if workout.notes:
            lines.append(f"notes = {workout.notes}")

    return lines


def _finalize_workout(data: dict[str, Any], seen_ids: set[str] | None = None) -> Workout:
    """Finalize a parsed workout dict, validating required fields and
    workout_id uniqueness.

    When *seen_ids* is provided, the workout's ``id`` is checked against the
    set and added to it; a duplicate raises ``ValueError`` so that corrupt
    duplicate records in ``data/workouts.md`` are rejected rather than
    silently returned twice by :func:`load_workouts`.
    """
    required = ("id", "date", "workout_type")
    for key in required:
        if key not in data:
            raise ValueError(f"Workout missing required field '{key}'")
    if seen_ids is not None:
        wid = data["id"]
        if wid in seen_ids:
            raise ValueError(
                f"Duplicate workout_id '{wid}' — already seen during load"
            )
        seen_ids.add(wid)
    # exercises is stored as a JSON string in the markdown file
    if "exercises" in data and isinstance(data["exercises"], str):
        try:
            data["exercises"] = json_loads(data["exercises"])
        except JSONDecodeError:
            data["exercises"] = []
    return dict_to_workout(data)


def find_workouts_by_date_range(
    start: datetime | date | None = None,
    end: datetime | date | None = None,
) -> list[Workout]:
    """Return workouts with date in [start, end] (inclusive on both sides).

    Both ``date`` and ``datetime`` inputs are accepted.  A plain ``date`` is
    converted to ``datetime`` at midnight UTC for ``start`` and at
    23:59:59.999999 UTC for ``end``.  A ``datetime`` is used as-is, but
    ``end`` is always expanded to the end of its day so that passing
    ``datetime(2026, 9, 3)`` (midnight) includes all of Sep 3.
    """
    # Convert date → datetime for consistent comparison
    if isinstance(start, date) and not isinstance(start, datetime):
        start = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    if isinstance(end, date) and not isinstance(end, datetime):
        end = datetime(
            end.year, end.month, end.day, 23, 59, 59, 999999, tzinfo=timezone.utc
        )

    workouts = load_workouts()
    # Sort by date, then by id for deterministic order when dates match
    sorted_ws = sorted(workouts, key=lambda w: (w.date, w.id))
    result: list[Workout] = []
    for w in sorted_ws:
        if start is not None and w.date < start:
            continue
        if end is not None and w.date > end.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ):
            continue
        result.append(w)
    return result


def find_history_by_exercise(name: str) -> list[StrengthWorkout]:
    """Return all strength workouts containing the given exercise name."""
    workouts = load_workouts()
    result: list[StrengthWorkout] = []
    for w in workouts:
        if not isinstance(w, StrengthWorkout):
            continue
        for ex in w.exercises:
            if ex.name.lower() == name.lower():
                result.append(w)
                break
    return result


def find_running_workouts() -> list[RunningWorkout]:
    """Return all running workouts."""
    workouts = load_workouts()
    return [w for w in workouts if isinstance(w, RunningWorkout)]


def find_last_n(n: int) -> list[Workout]:
    """Return the last n workouts (most recent first)."""
    workouts = load_workouts()
    if n <= 0:
        return []
    sorted_ws = sorted(workouts, key=lambda w: w.date, reverse=True)
    return sorted_ws[:n]


def find_workout_by_id(workout_id: str) -> Optional[Workout]:
    """Return a single workout matching the given ID, or None if not found."""
    workouts = load_workouts()
    for w in workouts:
        if w.id == workout_id:
            return w
    return None
