# CLI handler test pattern

## Handler tests for `workout add`

Style: match `tests/test_tasks_cli.py` — capsys for output/err, mock the persistence call, monkeypatch `load_workouts` for ID-dependent tests.

```python
import pytest
from unittest.mock import patch
from janus.models.workout import WorkoutType
from janus.workout_cli import handle_workout_add

class TestWorkoutAddCLI:
    def test_add_strength_minimal(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.workout_cli.save_workout") as mock_save:
            mock_save.return_value = None
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Back Squat",
                "--sets", "5x80kg@8,5x80kg@8.5",
            ])
        out = capsys.readouterr().out
        assert "Added workout: sw-001" in out
        assert "Type: strength" in out

    def test_add_running_with_optional(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.workout_cli.save_workout") as mock_save:
            mock_save.return_value = None
            handle_workout_add([
                "--type", "running",
                "--distance", "10.0",
                "--duration", "60",
                "--hr", "150",
                "--elevation", "100",
                "--notes", "Hill repeats",
            ])
        out = capsys.readouterr().out
        assert "Added workout: rw-001" in out
        assert "Notes: Hill repeats" in out

    def test_add_missing_type_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add(["--exercise", "Squat", "--sets", "5x80kg"])
        err = capsys.readouterr().err
        assert "type is required" in err
```

Rules:

- **Always monkeypatch `load_workouts` → `[]`** when testing ID-dependent output. Without this, `_generate_id` reads the real `data/workouts.md` and returns IDs like `sw-002` instead of `sw-001`.
- Mock the persistence call (`save_workout`), NOT the whole module. The handler should still run real parsing and validation — only the I/O side effect is suppressed.
- Assert on exact printed strings.
- For error cases: `pytest.raises(SystemExit)` + check `capsys.readouterr().err` for the error substring.

## Handler tests for `workout show`

Mock the query functions and assert on printed table.

```python
from janus.models.workout import Exercise, RunningWorkout, Set, StrengthWorkout, WorkoutType
from janus.workout_cli import handle_workout_show

def _dt_full(*parts):
    from datetime import datetime, timezone
    return datetime(*parts, tzinfo=timezone.utc)

class TestWorkoutShowCLI:
    def test_show_running(self, capsys):
        with patch("janus.workout_cli.find_running_workouts") as mock_find:
            mock_find.return_value = [
                RunningWorkout(
                    id="rw-001",
                    date=_dt_full(2026, 9, 1, 18, 0),
                    workout_type=WorkoutType.RUNNING,
                    distance_km=5.0,
                    duration_minutes=30.0,
                    avg_hr_bpm=145.0,
                    elevation_m=80.0,
                ),
            ]
            handle_workout_show(["--running"])
        out = capsys.readouterr().out
        assert "rw-001" in out
        assert "HR: 145.0bpm" in out   # note: float → 145.0bpm, not 145bpm
        assert "Elevation: 80.0m" in out

    def test_show_exercise(self, capsys):
        with patch("janus.workout_cli.find_history_by_exercise") as mock_find:
            mock_find.return_value = [
                StrengthWorkout(
                    id="sw-001",
                    date=_dt_full(2026, 9, 1, 10, 0),
                    workout_type=WorkoutType.STRENGTH,
                    exercises=[Exercise(name="Back Squat", sets=[Set(reps=5, weight_kg=80.0)])],
                ),
                StrengthWorkout(
                    id="sw-002",
                    date=_dt_full(2026, 9, 8, 10, 0),
                    workout_type=WorkoutType.STRENGTH,
                    exercises=[Exercise(name="Back Squat", sets=[Set(reps=5, weight_kg=85.0)])],
                ),
            ]
            handle_workout_show(["--exercise", "Back Squat"])
        out = capsys.readouterr().out
        assert "History for exercise: Back Squat" in out
        assert "sw-001" in out
        assert "sw-002" in out
```

Watch out: float values print with `.0` (e.g. `145.0bpm`, not `145bpm`). Assert the actual output, don't assume integer formatting.

## Full test file structure

```python
"""Tests for the 'janus workout add' and 'janus workout show' CLI handlers.

Style zgodny z test_tasks_cli.py — mockowanie service callów + capys output.
"""

from datetime import date, timezone
from io import StringIO
from unittest.mock import patch

import pytest

from janus.models.workout import Exercise, RunningWorkout, Set, StrengthWorkout, WorkoutType
from janus.workout_cli import (
    _generate_id,
    _parse_date,
    _parse_datetime,
    _parse_sets,
    handle_workout_add,
    handle_workout_show,
)


def _dt(*parts):
    """datetime(year, month, day, hour, minute, second, tzinfo=UTC)."""
    return date(*parts) if len(parts) == 3 else None


def _dt_full(*parts):
    from datetime import datetime
    return datetime(*parts, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

class TestIDGeneration:
    def test_generate_strength_id_no_existing(self, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        result = _generate_id(WorkoutType.STRENGTH)
        assert result == "sw-001"

    def test_generate_running_id_no_existing(self, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        result = _generate_id(WorkoutType.RUNNING)
        assert result == "rw-001"

    def test_generate_strength_id_with_existing(self, monkeypatch):
        from janus.models.workout import StrengthWorkout, WorkoutType
        existing = [
            StrengthWorkout(id="sw-001", date=_dt_full(2026, 1, 1), workout_type=WorkoutType.STRENGTH),
            StrengthWorkout(id="sw-003", date=_dt_full(2026, 1, 2), workout_type=WorkoutType.STRENGTH),
        ]
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: existing)
        result = _generate_id(WorkoutType.STRENGTH)
        assert result == "sw-004"


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

class TestDateParsing:
    def test_parse_date_none_returns_today(self):
        result = _parse_date(None)
        assert isinstance(result, date)

    def test_parse_date_valid(self):
        result = _parse_date("2026-09-01")
        assert result == date(2026, 9, 1)

    def test_parse_date_invalid_exits(self, capsys):
        with pytest.raises(SystemExit):
            _parse_date("not-a-date")
        err = capsys.readouterr().err
        assert "invalid date" in err


# ---------------------------------------------------------------------------
# Sets parsing
# ---------------------------------------------------------------------------

class TestSetsParsing:
    def test_parse_simple_sets(self):
        sets = _parse_sets("5x80kg@8.0,5x80kg@8.5,5x80kg")
        assert len(sets) == 3
        assert sets[0].reps == 5
        assert sets[0].weight_kg == 80.0
        assert sets[0].rpe == 8.0
        assert sets[1].reps == 5
        assert sets[1].weight_kg == 80.0
        assert sets[1].rpe == 8.5
        assert sets[2].reps == 5
        assert sets[2].weight_kg == 80.0
        assert sets[2].rpe is None

    def test_parse_bodyweight_set(self):
        sets = _parse_sets("10x")
        assert len(sets) == 1
        assert sets[0].reps == 10
        assert sets[0].weight_kg is None

    def test_parse_invalid_format_exits(self, capsys):
        with pytest.raises(SystemExit):
            _parse_sets("invalid")
        err = capsys.readouterr().err
        assert "invalid set format" in err


# ---------------------------------------------------------------------------
# Workout Add CLI
# ---------------------------------------------------------------------------

class TestWorkoutAddCLI:
    # ... (see above)


# ---------------------------------------------------------------------------
# Workout Show CLI
# ---------------------------------------------------------------------------

class TestWorkoutShowCLI:
    # ... (see above)
```