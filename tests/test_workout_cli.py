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

    def test_generate_running_id_with_existing(self, monkeypatch):
        from janus.models.workout import RunningWorkout, WorkoutType
        existing = [
            RunningWorkout(id="rw-010", date=_dt_full(2026, 1, 1), workout_type=WorkoutType.RUNNING, distance_km=5.0, duration_minutes=30),
        ]
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: existing)
        result = _generate_id(WorkoutType.RUNNING)
        assert result == "rw-011"


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

    def test_parse_invalid_reps_exits(self, capsys):
        with pytest.raises(SystemExit):
            _parse_sets("abcx80kg")
        err = capsys.readouterr().err
        assert "invalid reps" in err

    def test_parse_invalid_weight_exits(self, capsys):
        with pytest.raises(SystemExit):
            _parse_sets("5xabc")
        err = capsys.readouterr().err
        assert "invalid weight" in err

    def test_parse_invalid_rpe_exits(self, capsys):
        with pytest.raises(SystemExit):
            _parse_sets("5x80kg@notanumber")
        err = capsys.readouterr().err
        assert "invalid RPE" in err


# ---------------------------------------------------------------------------
# Workout Add CLI
# ---------------------------------------------------------------------------

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

    def test_add_running_minimal(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.workout_cli.save_workout") as mock_save:
            mock_save.return_value = None
            handle_workout_add([
                "--type", "running",
                "--distance", "5.0",
                "--duration", "30",
            ])

        out = capsys.readouterr().out
        assert "Added workout: rw-001" in out

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

    def test_add_strength_with_date(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.workout_cli.save_workout") as mock_save:
            mock_save.return_value = None
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Bench Press",
                "--sets", "8x60kg@7",
                "--date", "2026-09-01",
            ])

        out = capsys.readouterr().out
        assert "Added workout: sw-001" in out
        assert "Date: 2026-09-01" in out

    def test_add_strength_with_source(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.workout_cli.save_workout") as mock_save:
            mock_save.return_value = None
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Deadlift",
                "--sets", "3x100kg",
                "--source", "strava",
            ])

        out = capsys.readouterr().out
        assert "Added workout: sw-001" in out

    def test_add_running_with_date(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.workout_cli.save_workout") as mock_save:
            mock_save.return_value = None
            handle_workout_add([
                "--type", "running",
                "--distance", "5.0",
                "--duration", "30",
                "--date", "2026-09-02",
            ])

        out = capsys.readouterr().out
        assert "Date: 2026-09-02" in out

    def test_add_missing_type_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add(["--exercise", "Squat", "--sets", "5x80kg"])
        err = capsys.readouterr().err
        assert "type is required" in err

    def test_add_strength_missing_exercise_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add(["--type", "strength", "--sets", "5x80kg"])
        err = capsys.readouterr().err
        assert "--exercise is required" in err

    def test_add_strength_missing_sets_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add(["--type", "strength", "--exercise", "Squat"])
        err = capsys.readouterr().err
        assert "--sets is required" in err

    def test_add_running_missing_distance_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add(["--type", "running", "--duration", "30"])
        err = capsys.readouterr().err
        assert "--distance is required" in err

    def test_add_running_missing_duration_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add(["--type", "running", "--distance", "5.0"])
        err = capsys.readouterr().err
        assert "--duration is required" in err

    def test_add_invalid_type_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add(["--type", "cycling", "--distance", "5.0", "--duration", "30"])
        err = capsys.readouterr().err
        assert "invalid workout type" in err

    def test_add_unknown_argument_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add(["--type", "strength", "--exercise", "Squat", "--sets", "5x80kg", "--unknown", "value"])
        err = capsys.readouterr().err
        assert "unknown argument" in err

    def test_add_invalid_date_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Squat",
                "--sets", "5x80kg",
                "--date", "not-a-date",
            ])
        err = capsys.readouterr().err
        assert "invalid date" in err

    def test_add_invalid_distance_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add([
                "--type", "running",
                "--distance", "notanumber",
                "--duration", "30",
            ])
        err = capsys.readouterr().err
        assert "invalid distance" in err

    def test_add_invalid_duration_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add([
                "--type", "running",
                "--distance", "5.0",
                "--duration", "notanumber",
            ])
        err = capsys.readouterr().err
        assert "invalid duration" in err

    def test_add_invalid_sets_format_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Squat",
                "--sets", "invalid",
            ])
        err = capsys.readouterr().err
        assert "invalid set format" in err


# ---------------------------------------------------------------------------
# Workout Show CLI
# ---------------------------------------------------------------------------

class TestWorkoutShowCLI:
    def test_show_default_last_n(self, capsys):
        with patch("janus.workout_cli.find_last_n") as mock_find:
            mock_find.return_value = [
                StrengthWorkout(
                    id="sw-001",
                    date=_dt_full(2026, 9, 1, 10, 0),
                    workout_type=WorkoutType.STRENGTH,
                    exercises=[],
                ),
                RunningWorkout(
                    id="rw-001",
                    date=_dt_full(2026, 9, 2, 18, 0),
                    workout_type=WorkoutType.RUNNING,
                    distance_km=5.0,
                    duration_minutes=30.0,
                ),
            ]
            handle_workout_show([])

        out = capsys.readouterr().out
        assert "sw-001" in out
        assert "rw-001" in out

    def test_show_with_last(self, capsys):
        with patch("janus.workout_cli.find_last_n") as mock_find:
            mock_find.return_value = []
            handle_workout_show(["--last", "10"])

        out = capsys.readouterr().out
        assert "No workouts found" in out

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
        assert "HR: 145.0bpm" in out
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

    def test_show_date_range(self, capsys):
        with patch("janus.workout_cli.find_workouts_by_date_range") as mock_find:
            mock_find.return_value = [
                StrengthWorkout(
                    id="sw-001",
                    date=_dt_full(2026, 9, 5, 10, 0),
                    workout_type=WorkoutType.STRENGTH,
                    exercises=[],
                ),
                RunningWorkout(
                    id="rw-001",
                    date=_dt_full(2026, 9, 10, 18, 0),
                    workout_type=WorkoutType.RUNNING,
                    distance_km=5.0,
                    duration_minutes=30.0,
                ),
            ]
            handle_workout_show(["--from", "2026-09-01", "--to", "2026-09-30"])

        out = capsys.readouterr().out
        assert "from 2026-09-01" in out
        assert "to 2026-09-30" in out
        assert "sw-001" in out
        assert "rw-001" in out

    def test_show_no_workouts_found(self, capsys):
        with patch("janus.workout_cli.find_last_n") as mock_find:
            mock_find.return_value = []
            handle_workout_show([])

        out = capsys.readouterr().out
        assert "No workouts found" in out

    def test_show_running_and_exercise_mutually_exclusive(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_show(["--running", "--exercise", "Squat"])
        err = capsys.readouterr().err
        assert "mutually exclusive" in err

    def test_show_invalid_last_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_show(["--last", "0"])
        err = capsys.readouterr().err
        assert "invalid" in err

    def test_show_invalid_from_date_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_show(["--from", "not-a-date"])
        err = capsys.readouterr().err
        assert "invalid from date" in err

    def test_show_unknown_argument_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_show(["--unknown", "value"])
        err = capsys.readouterr().err
        assert "unknown argument" in err