"""Tests for the 'janus workout summary' CLI handler."""


from datetime import date, timezone
from io import StringIO

import pytest

from janus.models.workout import Exercise, RunningWorkout, Set, StrengthWorkout, WorkoutType
from janus.workout_cli import handle_workout_summary


def _dt_full(*parts):
    from datetime import datetime
    return datetime(*parts, tzinfo=timezone.utc)


class TestWorkoutSummaryCLI:
    def test_summary_overall_no_workouts(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        handle_workout_summary([])

        out = capsys.readouterr().out
        assert "Total workouts: 0" in out
        assert "No workouts found" in out

    def test_summary_overall_with_workouts(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [
            StrengthWorkout(
                id="sw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.STRENGTH,
            ),
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 2, 18, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
            ),
            RunningWorkout(
                id="rw-002",
                date=_dt_full(2026, 9, 3, 19, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=10.0,
                duration_minutes=58.56,
            ),
        ])
        handle_workout_summary([])

        out = capsys.readouterr().out
        assert "Total workouts: 3" in out
        assert "Strength workouts: 1" in out
        assert "Running workouts: 2" in out
        assert "Most recent: rw-002" in out
        assert "2026-09-03" in out

    def test_summary_running_no_workouts(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        handle_workout_summary(["--running"])

        out = capsys.readouterr().out
        assert "No running workouts found" in out

    def test_summary_running_basic(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 18, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                avg_hr_bpm=145.0,
            ),
            RunningWorkout(
                id="rw-002",
                date=_dt_full(2026, 9, 2, 19, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=10.0,
                duration_minutes=60.0,
            ),
        ])
        handle_workout_summary(["--running"])

        out = capsys.readouterr().out
        assert "Total runs: 2" in out
        assert "Total distance: 15.0km" in out
        assert "Total duration: 90.0min" in out
        assert "Avg pace: 6.00 min/km" in out
        assert "Best pace: 6.00 min/km" in out
        assert "Avg HR: 145bpm (1/2 runs)" in out
        assert "Longest run: 10.0km" in out

    def test_summary_running_distance_weighted_pace(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 18, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
            ),
            RunningWorkout(
                id="rw-002",
                date=_dt_full(2026, 9, 2, 19, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=10.0,
                duration_minutes=60.0,
            ),
        ])
        handle_workout_summary(["--running"])

        out = capsys.readouterr().out
        assert "Avg pace: 6.00 min/km" in out
        assert "Best pace: 6.00 min/km" in out
        assert "Avg HR:" not in out

    def test_summary_running_hr_only_from_runs_with_hr(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 18, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                avg_hr_bpm=145.0,
            ),
            RunningWorkout(
                id="rw-002",
                date=_dt_full(2026, 9, 2, 19, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=10.0,
                duration_minutes=60.0,
                avg_hr_bpm=155.0,
            ),
            RunningWorkout(
                id="rw-003",
                date=_dt_full(2026, 9, 3, 19, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=8.0,
                duration_minutes=48.0,
            ),
        ])
        handle_workout_summary(["--running"])

        out = capsys.readouterr().out
        assert "Avg HR: 150bpm (2/3 runs)" in out

    def test_summary_exercise_no_workouts(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
        handle_workout_summary(["--exercise", "Back Squat"])

        out = capsys.readouterr().out
        assert "No workouts found for exercise: Back Squat" in out

    def test_summary_exercise_basic(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [
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
                exercises=[Exercise(name="Back Squat", sets=[Set(reps=5, weight_kg=82.5)])],
            ),
        ])
        handle_workout_summary(["--exercise", "Back Squat"])

        out = capsys.readouterr().out
        assert "Summary for exercise: Back Squat" in out
        assert "Workouts: 2" in out
        assert "Latest sets: 5x82.5kg" in out
        assert "Highest weight: 82.5kg" in out
        assert "Highest workout volume: 412.5kg" in out
        assert "2026-09-01" in out
        assert "2026-09-08" in out
        assert "80.0kg" in out
        assert "82.5kg" in out

    def test_summary_exercise_progression_per_workout_one_point(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [
            StrengthWorkout(
                id="sw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.STRENGTH,
                exercises=[Exercise(name="Back Squat", sets=[
                    Set(reps=5, weight_kg=80.0),
                    Set(reps=5, weight_kg=80.0),
                ])],
            ),
            StrengthWorkout(
                id="sw-002",
                date=_dt_full(2026, 9, 8, 10, 0),
                workout_type=WorkoutType.STRENGTH,
                exercises=[Exercise(name="Back Squat", sets=[
                    Set(reps=3, weight_kg=85.0),
                    Set(reps=3, weight_kg=85.0),
                    Set(reps=3, weight_kg=82.5),
                ])],
            ),
        ])
        handle_workout_summary(["--exercise", "Back Squat"])

        out = capsys.readouterr().out
        assert "2026-09-01 | max: 80.0kg | volume: 800.0kg" in out
        assert "2026-09-08 | max: 85.0kg | volume: 757.5kg" in out

    def test_summary_exercise_bodyweight_only_volume_excluded(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [
            StrengthWorkout(
                id="sw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.STRENGTH,
                exercises=[Exercise(name="Pull-ups", sets=[Set(reps=10, weight_kg=None)])],
            ),
        ])
        handle_workout_summary(["--exercise", "Pull-ups"])

        out = capsys.readouterr().out
        assert "Summary for exercise: Pull-ups" in out
        assert "Workouts: 1" in out
        assert "bodyweight" in out
        assert "volume: 0.0kg" in out

    def test_summary_exercise_case_insensitive(self, capsys, monkeypatch):
        monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [
            StrengthWorkout(
                id="sw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.STRENGTH,
                exercises=[Exercise(name="Back Squat", sets=[Set(reps=5, weight_kg=80.0)])],
            ),
        ])
        handle_workout_summary(["--exercise", "back squat"])

        out = capsys.readouterr().out
        assert "Summary for exercise: back squat" in out
        assert "Workouts: 1" in out

    def test_summary_running_and_exercise_mutually_exclusive(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_summary(["--running", "--exercise", "Squat"])
        err = capsys.readouterr().err
        assert "mutually exclusive" in err

    def test_summary_unknown_argument_exits(self, capsys):
        with pytest.raises(SystemExit):
            handle_workout_summary(["--unknown", "value"])
        err = capsys.readouterr().err
        assert "unknown argument" in err