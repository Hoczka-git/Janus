"""Markdown persistence dla workoutów Janus.

Canonical storage: data/workouts.md
Format: nagłówek + sekcje "## Workout:" z polami klucz=wartość.

Pojedynczy plik, rewrite przy zapisie (jak markdown_tasks.py / markdown_goals.py).
"""

from datetime import datetime
from json import dumps as json_dumps, loads as json_loads, JSONDecodeError
from pathlib import Path
from typing import Any

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

    with path.open() as f:
        for line in f:
            stripped = line.strip()

            if stripped.startswith("## Workout:"):
                if current is not None:
                    workouts.append(_finalize_workout(current))
                current = {"raw": stripped[len("## Workout:"):].strip()}
            elif current is not None:
                if "=" in stripped and not stripped.startswith("#"):
                    key, _, value = stripped.partition("=")
                    current[key.strip()] = value.strip()

        if current is not None:
            workouts.append(_finalize_workout(current))

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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


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


def _finalize_workout(data: dict[str, Any]) -> Workout:
    required = ("id", "date", "workout_type")
    for key in required:
        if key not in data:
            raise ValueError(f"Workout missing required field '{key}'")
    # exercises is stored as a JSON string in the markdown file
    if "exercises" in data and isinstance(data["exercises"], str):
        try:
            data["exercises"] = json_loads(data["exercises"])
        except JSONDecodeError:
            data["exercises"] = []
    return dict_to_workout(data)


def find_workouts_by_date_range(
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Workout]:
    """Return workouts with date in [start, end] (inclusive on both sides)."""
    workouts = load_workouts()
    # Sort by date, then by id for deterministic order when dates match
    sorted_ws = sorted(workouts, key=lambda w: (w.date, w.id))
    result: list[Workout] = []
    for w in sorted_ws:
        if start is not None and w.date < start:
            continue
        if end is not None and w.date > end.replace(hour=23, minute=59, second=59, microsecond=999999):
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
