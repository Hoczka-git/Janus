"""Tests for the 'janus workout add' and 'janus workout show' CLI handlers.

Style zgodny z test_tasks_cli.py — mockowanie service callów + capys output.
"""

from datetime import date, timezone
from io import StringIO
from unittest.mock import patch

import pytest

from janus.models.workout import Exercise, RunningWorkout, Set, StrengthWorkout, WorkoutType
from janus.services.activity_ingest import IngestResult
from janus.workout_cli import (
    _format_set_weight,
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
# Weight formatting
# ---------------------------------------------------------------------------


class TestFormatSetWeight:
    def test_format_weighted_set(self):
        assert _format_set_weight(80.0) == "80.0kg"

    def test_format_int_weight(self):
        assert _format_set_weight(60) == "60kg"

    def test_format_bodyweight_set(self):
        assert _format_set_weight(None) == "bodyweight"


# ---------------------------------------------------------------------------
# Workout Add CLI
# ---------------------------------------------------------------------------

class TestWorkoutAddCLI:
    def _mock_ingest_ok(self):
        """Return a mock IngestResult with action='created' (non-rejected)."""
        return IngestResult(
            record_id="test", accepted=True, wrote=True,
            file_path="data/test.md", action="created",
        )

    def test_add_strength_minimal(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.services.workout_analytics.add_workout_via_ingest", return_value=self._mock_ingest_ok()):
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
        with patch("janus.services.workout_analytics.add_workout_via_ingest", return_value=self._mock_ingest_ok()):
            handle_workout_add([
                "--type", "running",
                "--distance", "5.0",
                "--duration", "30",
            ])

        out = capsys.readouterr().out
        assert "Added workout: rw-001" in out

    def test_add_running_with_optional(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.services.workout_analytics.add_workout_via_ingest", return_value=self._mock_ingest_ok()):
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
        with patch("janus.services.workout_analytics.add_workout_via_ingest", return_value=self._mock_ingest_ok()):
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
        with patch("janus.services.workout_analytics.add_workout_via_ingest", return_value=self._mock_ingest_ok()):
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
        with patch("janus.services.workout_analytics.add_workout_via_ingest", return_value=self._mock_ingest_ok()):
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
        assert "--sets must follow --exercise" in err

    def test_add_strength_missing_sets_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add(["--type", "strength", "--exercise", "Squat"])
        err = capsys.readouterr().err
        assert "--exercise must be followed by --sets" in err

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

    def test_show_by_id_strength(self, capsys):
        with patch("janus.workout_cli.find_workout_by_id") as mock_find:
            mock_find.return_value = StrengthWorkout(
                id="sw-003",
                date=_dt_full(2026, 9, 5, 10, 0),
                workout_type=WorkoutType.STRENGTH,
                exercises=[Exercise(name="Back Squat", sets=[
                    Set(reps=5, weight_kg=80.0, rpe=8.0),
                    Set(reps=5, weight_kg=80.0, rpe=8.5),
                ])],
                notes="Heavy day",
            )
            handle_workout_show(["sw-003"])

        out = capsys.readouterr().out
        assert "Workout: sw-003" in out
        assert "Type: strength" in out
        assert "Date: 2026-09-05" in out
        assert "Notes: Heavy day" in out
        assert "Exercise: Back Squat" in out
        assert "Set 1: 5 reps x 80.0kg @ RPE 8.0" in out
        assert "Set 2: 5 reps x 80.0kg @ RPE 8.5" in out

    def test_show_by_id_running(self, capsys):
        with patch("janus.workout_cli.find_workout_by_id") as mock_find:
            mock_find.return_value = RunningWorkout(
                id="rw-002",
                date=_dt_full(2026, 9, 3, 18, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=10.0,
                duration_minutes=45.0,
                avg_hr_bpm=150.0,
                elevation_m=100.0,
            )
            handle_workout_show(["rw-002"])

        out = capsys.readouterr().out
        assert "Workout: rw-002" in out
        assert "Type: running" in out
        assert "Distance: 10.0km" in out
        assert "Duration: 45.0min" in out
        assert "Avg HR: 150.0bpm" in out
        assert "Elevation: 100.0m" in out

    def test_show_by_id_not_found(self, capsys):
        with patch("janus.workout_cli.find_workout_by_id") as mock_find:
            mock_find.return_value = None
            handle_workout_show(["sw-999"])

        out = capsys.readouterr().out
        assert "No workout found with ID: sw-999" in out

    def test_show_by_id_takes_priority_over_last(self, capsys):
        with patch("janus.workout_cli.find_workout_by_id") as mock_find:
            mock_find.return_value = StrengthWorkout(
                id="sw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.STRENGTH,
                exercises=[Exercise(name="Squat", sets=[Set(reps=5, weight_kg=80.0)])],
            )
            handle_workout_show(["sw-001", "--last", "10"])

        out = capsys.readouterr().out
        assert "Workout: sw-001" in out
        mock_find.assert_called_once_with("sw-001")


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

    def test_add_strength_multiple_exercises(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.services.workout_analytics.add_workout_via_ingest", return_value=self._mock_ingest_ok()) as mock_ingest:
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Back Squat", "--sets", "5x80kg@8",
                "--exercise", "Bench Press", "--sets", "8x60kg@7",
                "--date", "2026-10-02",
                "--plan", "PLAN 14",
                "--training", "C",
                "--week", "4",
            ])

        out = capsys.readouterr().out
        assert "Added workout: sw-001" in out
        assert "Type: strength" in out
        assert "Date: 2026-10-02" in out

        # Verify the ingest call received all parameters
        call_kwargs = mock_ingest.call_args
        assert call_kwargs.kwargs["date"] == "2026-10-02T00:00:00+00:00"
        assert call_kwargs.kwargs["plan"] == "PLAN 14"
        assert call_kwargs.kwargs["training"] == "C"
        assert call_kwargs.kwargs["week"] == 4
        exercises = call_kwargs.kwargs["exercises"]
        assert len(exercises) == 2
        assert exercises[0].name == "Back Squat"
        assert exercises[0].sets[0].reps == 5
        assert exercises[0].sets[0].weight_kg == 80.0
        assert exercises[0].sets[0].rpe == 8.0
        assert exercises[1].name == "Bench Press"
        assert exercises[1].sets[0].reps == 8
        assert exercises[1].sets[0].weight_kg == 60.0
        assert exercises[1].sets[0].rpe == 7.0

    def test_add_strength_idempotent_duplicate(self, capsys, monkeypatch):
        """Running the same command twice should result in only one persisted record."""
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        call_count = 0

        def mock_ingest(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._mock_ingest_ok()
            # Second call: simulate dedup rejection
            return IngestResult(
                record_id="test", accepted=False, wrote=False,
                file_path="data/workouts.md", action="rejected",
                error="duplicate",
            )

        with patch("janus.services.workout_analytics.add_workout_via_ingest", side_effect=mock_ingest):
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Squat", "--sets", "5x80kg",
                "--date", "2026-10-02",
                "--plan", "PLAN 14",
                "--training", "C",
                "--week", "4",
            ])
            out1 = capsys.readouterr().out
            assert "Added workout: sw-001" in out1

            with pytest.raises(SystemExit):
                handle_workout_add([
                    "--type", "strength",
                    "--exercise", "Squat", "--sets", "5x80kg",
                    "--date", "2026-10-02",
                    "--plan", "PLAN 14",
                    "--training", "C",
                    "--week", "4",
                ])
            err2 = capsys.readouterr().err
            assert "already exists" in err2

        assert call_count == 2

    def test_add_strength_with_plan_training_week(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.services.workout_analytics.add_workout_via_ingest", return_value=self._mock_ingest_ok()) as mock_ingest:
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Deadlift", "--sets", "3x100kg",
                "--plan", "PLAN 14",
                "--training", "C",
                "--week", "4",
            ])

        call_kwargs = mock_ingest.call_args
        assert call_kwargs.kwargs["plan"] == "PLAN 14"
        assert call_kwargs.kwargs["training"] == "C"
        assert call_kwargs.kwargs["week"] == 4

    def test_add_strength_without_plan_training_week(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        with patch("janus.services.workout_analytics.add_workout_via_ingest", return_value=self._mock_ingest_ok()) as mock_ingest:
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Squat", "--sets", "5x80kg",
            ])

        call_kwargs = mock_ingest.call_args
        assert call_kwargs.kwargs["plan"] is None
        assert call_kwargs.kwargs["training"] is None
        assert call_kwargs.kwargs["week"] is None

    def test_add_invalid_week_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Squat", "--sets", "5x80kg",
                "--week", "0",
            ])
        err = capsys.readouterr().err
        assert "invalid week" in err

    def test_add_exercise_without_sets_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_add([
                "--type", "strength",
                "--exercise", "Squat",
            ])
        err = capsys.readouterr().err
        assert "--exercise must be followed by --sets" in err


# ---------------------------------------------------------------------------
# StrengthWorkout model — plan/training/week fields
# ---------------------------------------------------------------------------

class TestStrengthWorkoutModel:
    def test_strength_workout_with_plan_training_week(self):
        from datetime import datetime, timezone
        w = StrengthWorkout(
            id="sw-001",
            date=datetime(2026, 10, 2, tzinfo=timezone.utc),
            workout_type=WorkoutType.STRENGTH,
            exercises=[Exercise(name="Squat", sets=[Set(reps=5, weight_kg=80.0)])],
            plan="PLAN 14",
            training="C",
            week=4,
        )
        assert w.plan == "PLAN 14"
        assert w.training == "C"
        assert w.week == 4

    def test_strength_workout_without_plan_training_week(self):
        from datetime import datetime, timezone
        w = StrengthWorkout(
            id="sw-001",
            date=datetime(2026, 10, 2, tzinfo=timezone.utc),
            workout_type=WorkoutType.STRENGTH,
            exercises=[Exercise(name="Squat", sets=[Set(reps=5, weight_kg=80.0)])],
        )
        assert w.plan is None
        assert w.training is None
        assert w.week is None

    def test_strength_workout_invalid_week_zero(self):
        from datetime import datetime, timezone
        with pytest.raises(ValueError, match="week must be int >= 1"):
            StrengthWorkout(
                id="sw-001",
                date=datetime(2026, 10, 2, tzinfo=timezone.utc),
                workout_type=WorkoutType.STRENGTH,
                exercises=[],
                week=0,
            )

    def test_strength_workout_invalid_week_negative(self):
        from datetime import datetime, timezone
        with pytest.raises(ValueError, match="week must be int >= 1"):
            StrengthWorkout(
                id="sw-001",
                date=datetime(2026, 10, 2, tzinfo=timezone.utc),
                workout_type=WorkoutType.STRENGTH,
                exercises=[],
                week=-1,
            )

    def test_strength_workout_invalid_plan_empty(self):
        from datetime import datetime, timezone
        with pytest.raises(ValueError, match="plan must be non-empty string"):
            StrengthWorkout(
                id="sw-001",
                date=datetime(2026, 10, 2, tzinfo=timezone.utc),
                workout_type=WorkoutType.STRENGTH,
                exercises=[],
                plan="",
            )

    def test_strength_workout_invalid_training_empty(self):
        from datetime import datetime, timezone
        with pytest.raises(ValueError, match="training must be non-empty string"):
            StrengthWorkout(
                id="sw-001",
                date=datetime(2026, 10, 2, tzinfo=timezone.utc),
                workout_type=WorkoutType.STRENGTH,
                exercises=[],
                training="  ",
            )

    def test_strength_workout_serialization_roundtrip(self):
        from datetime import datetime, timezone
        from janus.models.workout import workout_to_dict, dict_to_workout
        w = StrengthWorkout(
            id="sw-001",
            date=datetime(2026, 10, 2, tzinfo=timezone.utc),
            workout_type=WorkoutType.STRENGTH,
            exercises=[Exercise(name="Squat", sets=[Set(reps=5, weight_kg=80.0, rpe=8.0)])],
            plan="PLAN 14",
            training="C",
            week=4,
        )
        d = workout_to_dict(w)
        assert d["plan"] == "PLAN 14"
        assert d["training"] == "C"
        assert d["week"] == 4

        w2 = dict_to_workout(d)
        assert w2.plan == "PLAN 14"
        assert w2.training == "C"
        assert w2.week == 4


# ---------------------------------------------------------------------------
# Dedup key with session identifiers
# ---------------------------------------------------------------------------

class TestDedupKeyWithSessionIdentifiers:
    def test_dedup_key_with_plan_training_week(self):
        from janus.services.activity_ingest import ActivityRecord, ActivityType, compute_dedup_key
        from datetime import datetime, timezone
        record = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="cli",
            timestamp=datetime(2026, 10, 2, tzinfo=timezone.utc),
            workout_type="strength",
            evidence={
                "date": "2026-10-02",
                "plan": "PLAN 14",
                "training": "C",
                "week": 4,
            },
        )
        key = compute_dedup_key(record)
        assert key == "2026-10-02::strength::PLAN 14::C::4"

    def test_dedup_key_without_session_identifiers(self):
        from janus.services.activity_ingest import ActivityRecord, ActivityType, compute_dedup_key
        from datetime import datetime, timezone
        record = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="cli",
            timestamp=datetime(2026, 10, 2, tzinfo=timezone.utc),
            workout_type="strength",
            evidence={"date": "2026-10-02"},
        )
        key = compute_dedup_key(record)
        assert key == "2026-10-02::strength::::::"

    def test_dedup_key_with_workout_id(self):
        from janus.services.activity_ingest import ActivityRecord, ActivityType, compute_dedup_key
        from datetime import datetime, timezone
        record = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="cli",
            timestamp=datetime(2026, 10, 2, tzinfo=timezone.utc),
            workout_id="sw-001",
            workout_type="strength",
            evidence={
                "date": "2026-10-02",
                "plan": "PLAN 14",
                "training": "C",
                "week": 4,
            },
        )
        key = compute_dedup_key(record)
        assert key == "sw-001"


# ---------------------------------------------------------------------------
# Markdown serialization with plan/training/week
# ---------------------------------------------------------------------------

class TestMarkdownSerialization:
    def test_strength_workout_markdown_with_plan_training_week(self, tmp_path, monkeypatch):
        """_workout_to_markdown_lines includes plan/training/week for StrengthWorkout."""
        from janus.integrations import workout_md
        monkeypatch.setattr(workout_md, "PROJECT_ROOT", tmp_path)
        from datetime import datetime, timezone
        w = StrengthWorkout(
            id="sw-001",
            date=datetime(2026, 10, 2, tzinfo=timezone.utc),
            workout_type=WorkoutType.STRENGTH,
            exercises=[Exercise(name="Squat", sets=[Set(reps=5, weight_kg=80.0)])],
            plan="PLAN 14",
            training="C",
            week=4,
        )
        lines = workout_md._workout_to_markdown_lines(w)
        assert "plan = PLAN 14" in lines
        assert "training = C" in lines
        assert "week = 4" in lines

    def test_strength_workout_markdown_without_plan_training_week(self, tmp_path, monkeypatch):
        """_workout_to_markdown_lines omits plan/training/week when None."""
        from janus.integrations import workout_md
        monkeypatch.setattr(workout_md, "PROJECT_ROOT", tmp_path)
        from datetime import datetime, timezone
        w = StrengthWorkout(
            id="sw-001",
            date=datetime(2026, 10, 2, tzinfo=timezone.utc),
            workout_type=WorkoutType.STRENGTH,
            exercises=[Exercise(name="Squat", sets=[Set(reps=5, weight_kg=80.0)])],
        )
        lines = workout_md._workout_to_markdown_lines(w)
        assert not any("plan =" in line for line in lines)
        assert not any("training =" in line for line in lines)
        assert not any("week =" in line for line in lines)


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

    def test_show_exercise_bodyweight_displays_bodyweight(self, capsys):
        with patch("janus.workout_cli.find_history_by_exercise") as mock_find:
            mock_find.return_value = [
                StrengthWorkout(
                    id="sw-001",
                    date=_dt_full(2026, 9, 1, 10, 0),
                    workout_type=WorkoutType.STRENGTH,
                    exercises=[Exercise(name="Push-up", sets=[Set(reps=15, weight_kg=None)])],
                ),
            ]
            handle_workout_show(["--exercise", "Push-up"])

        out = capsys.readouterr().out
        assert "bodyweight" in out
        assert "Nonekg" not in out

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