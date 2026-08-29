"""Testy dla Fitness MVP — persistence, queryfunkcje, round-trip.

Zgodne z istniejącym stylem Janus:
- izolowane testy z pustym workspace'm
- mockowanie plików tam, gdzie trzeba
- testy dla strength, running, invalid values, bodyweight, persistence.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from janus.integrations.workout_md import (
    _HEADER,
    _write_workouts,
    find_history_by_exercise,
    find_last_n,
    find_running_workouts,
    find_workouts_by_date_range,
    load_workouts,
    save_workout,
)
from janus.models.workout import (
    Exercise,
    RunningWorkout,
    Set,
    StrengthWorkout,
    WorkoutType,
)


# ---------------------------------------------------------------------------
# Helpery
# ---------------------------------------------------------------------------

def _dt(*parts):
    """datetime(year, month, day, hour, minute, second, tzinfo=UTC)."""
    return datetime(*parts, tzinfo=timezone.utc)


def _strength_workout(
    workout_id: str = "sw-001",
    date: datetime | None = None,
    source: str | None = None,
    exercises: list[Exercise] | None = None,
    notes: str | None = None,
) -> StrengthWorkout:
    if date is None:
        date = _dt(2026, 8, 29, 10, 0, 0)
    if exercises is None:
        exercises = [
            Exercise(
                name="Back Squat",
                sets=[
                    Set(reps=5, weight_kg=80.0, rpe=8.0),
                    Set(reps=5, weight_kg=80.0, rpe=8.5),
                    Set(reps=5, weight_kg=80.0, rpe=None),
                ],
            ),
            Exercise(
                name="Bench Press",
                sets=[
                    Set(reps=8, weight_kg=60.0, rpe=7.0),
                    Set(reps=8, weight_kg=60.0, rpe=7.5),
                ],
            ),
        ]
    return StrengthWorkout(
        id=workout_id,
        date=date,
        workout_type=WorkoutType.STRENGTH,
        source=source,
        exercises=exercises,
        notes=notes,
    )


def _running_workout(
    workout_id: str = "rw-001",
    date: datetime | None = None,
    source: str | None = None,
    distance_km: float = 5.0,
    duration_minutes: float = 30.0,
    avg_hr_bpm: float | None = None,
    elevation_m: float | None = None,
    notes: str | None = None,
) -> RunningWorkout:
    if date is None:
        date = _dt(2026, 8, 29, 18, 0, 0)
    return RunningWorkout(
        id=workout_id,
        date=date,
        workout_type=WorkoutType.RUNNING,
        source=source,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        avg_hr_bpm=avg_hr_bpm,
        elevation_m=elevation_m,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Model validation — invalid values
# ---------------------------------------------------------------------------

class TestWorkoutValidation:
    """Validation rules z __post_init__."""

    def test_set_negative_reps_rejected(self):
        with pytest.raises(ValueError, match="reps must be int >= 0"):
            Set(reps=-1)

    def test_set_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="weight_kg must be >= 0"):
            Set(reps=5, weight_kg=-5.0)

    def test_set_valid_bodyweight(self):
        s = Set(reps=10, weight_kg=None)  # bodyweight
        assert s.weight_kg is None
        assert s.reps == 10

    def test_set_valid_zero_weight(self):
        s = Set(reps=5, weight_kg=0.0)  # zero added weight
        assert s.weight_kg == 0.0

    def test_set_rpe_out_of_range_rejected(self):
        with pytest.raises(ValueError, match="rpe must be 1-10"):
            Set(reps=5, rpe=11.0)

    def test_set_rpe_zero_rejected(self):
        with pytest.raises(ValueError, match="rpe must be 1-10"):
            Set(reps=5, rpe=0.0)

    def test_set_valid_with_rpe(self):
        s = Set(reps=5, weight_kg=50.0, rpe=8.5)
        assert s.rpe == 8.5

    def test_exercise_empty_name_rejected(self):
        with pytest.raises(ValueError, match="name must be non-empty"):
            Exercise(name="  ", sets=[])

    def test_exercise_all_sets_valid(self):
        ex = Exercise(
            name="Push-up",
            sets=[Set(reps=15, weight_kg=None), Set(reps=12, weight_kg=None)],
        )
        assert ex.name == "Push-up"
        assert len(ex.sets) == 2

    def test_workout_invalid_id_rejected(self):
        with pytest.raises(ValueError, match="id must be non-empty"):
            StrengthWorkout(id="  ", date=_dt(2026, 1, 1), workout_type=WorkoutType.STRENGTH)

    def test_workout_invalid_date_rejected(self):
        with pytest.raises(ValueError, match="date must be datetime"):
            StrengthWorkout(id="w1", date="2026-01-01", workout_type=WorkoutType.STRENGTH)

    def test_running_negative_distance_rejected(self):
        with pytest.raises(ValueError, match="distance_km must be >= 0"):
            RunningWorkout(id="r1", date=_dt(2026, 1, 1), workout_type=WorkoutType.RUNNING, distance_km=-1.0)

    def test_running_zero_duration_rejected(self):
        with pytest.raises(ValueError, match="duration_minutes must be > 0"):
            RunningWorkout(id="r1", date=_dt(2026, 1, 1), workout_type=WorkoutType.RUNNING, duration_minutes=0)

    def test_running_negative_duration_rejected(self):
        with pytest.raises(ValueError, match="duration_minutes must be > 0"):
            RunningWorkout(id="r1", date=_dt(2026, 1, 1), workout_type=WorkoutType.RUNNING, duration_minutes=-5)

    def test_running_zero_hr_rejected(self):
        with pytest.raises(ValueError, match="avg_hr_bpm must be > 0"):
            RunningWorkout(id="r1", date=_dt(2026, 1, 1), workout_type=WorkoutType.RUNNING, duration_minutes=30, avg_hr_bpm=0)

    def test_running_negative_elevation_rejected(self):
        with pytest.raises(ValueError, match="elevation_m must be >= 0"):
            RunningWorkout(id="r1", date=_dt(2026, 1, 1), workout_type=WorkoutType.RUNNING, duration_minutes=30, elevation_m=-100)

    def test_running_valid_optional_fields(self):
        rw = RunningWorkout(
            id="r1",
            date=_dt(2026, 8, 29),
            workout_type=WorkoutType.RUNNING,
            distance_km=10.0,
            duration_minutes=60.0,
            avg_hr_bpm=150.0,
            elevation_m=120.0,
            notes="Evening run",
        )
        assert rw.avg_hr_bpm == 150.0
        assert rw.elevation_m == 120.0
        assert rw.notes == "Evening run"


# ---------------------------------------------------------------------------
# Persistence — round-trip i zapis/odczyt
# ---------------------------------------------------------------------------

class TestPersistenceRoundTrip:
    """load/save i round-trip model → markdown → model."""

    @pytest.fixture(autouse=True)
    def _isolated_workspace(self, tmp_path):
        """Każdy test otrzymuje czysty tmp_path jako PROJECT_ROOT."""
        self.root = tmp_path
        self.actual_path = tmp_path / "data" / "workouts.md"
        self.patch = patch("janus.integrations.workout_md.PROJECT_ROOT", tmp_path)
        self.patch.start()
        yield
        self.patch.stop()

    def _write_and_load(self, workouts: list) -> list:
        _write_workouts(workouts)
        return load_workouts()

    def test_save_and_load_single_strength(self):
        sw = _strength_workout("sw-001", _dt(2026, 9, 1, 10, 0))
        loaded = self._write_and_load([sw])
        assert len(loaded) == 1
        assert isinstance(loaded[0], StrengthWorkout)
        assert loaded[0].id == "sw-001"
        assert loaded[0].exercises[0].name == "Back Squat"
        assert loaded[0].exercises[0].sets[0].weight_kg == 80.0

    def test_save_and_load_single_running(self):
        rw = _running_workout("rw-001", _dt(2026, 9, 1, 18, 0), distance_km=10.0, duration_minutes=60.0)
        loaded = self._write_and_load([rw])
        assert len(loaded) == 1
        assert isinstance(loaded[0], RunningWorkout)
        assert loaded[0].id == "rw-001"
        assert loaded[0].distance_km == 10.0
        assert loaded[0].duration_minutes == 60.0

    def test_save_multiple_workouts_and_load_all(self):
        sw = _strength_workout("sw-001", _dt(2026, 9, 1, 10, 0))
        rw = _running_workout("rw-001", _dt(2026, 9, 2, 18, 0), distance_km=5.0, duration_minutes=30.0)
        loaded = self._write_and_load([sw, rw])
        assert len(loaded) == 2
        assert isinstance(loaded[0], StrengthWorkout)
        assert isinstance(loaded[1], RunningWorkout)

    def test_empty_workouts_file_returns_empty_list(self):
        # Bez pliku — load() zwraca []
        assert load_workouts() == []

    def test_preserves_notes(self):
        sw = _strength_workout(notes="Leg day", exercises=[
            Exercise(name="Squat", sets=[Set(reps=5, weight_kg=70.0)], notes="Main lift"),
        ])
        loaded = self._write_and_load([sw])
        assert loaded[0].notes == "Leg day"
        assert loaded[0].exercises[0].notes == "Main lift"

    def test_preserves_source(self):
        sw = _strength_workout(source="manual")
        loaded = self._write_and_load([sw])
        assert loaded[0].source == "manual"

    def test_preserves_bodyweight_sets(self):
        sw = _strength_workout(exercises=[
            Exercise(name="Pull-up", sets=[Set(reps=8, weight_kg=None)]),
        ])
        loaded = self._write_and_load([sw])
        assert loaded[0].exercises[0].sets[0].weight_kg is None

    def test_preserves_optional_running_fields(self):
        rw = _running_workout(
            avg_hr_bpm=145.0,
            elevation_m=80.0,
            notes="Hill repeats",
        )
        loaded = self._write_and_load([rw])
        assert loaded[0].avg_hr_bpm == 145.0
        assert loaded[0].elevation_m == 80.0
        assert loaded[0].notes == "Hill repeats"

    def test_preserves_optional_running_fields_as_none(self):
        rw = _running_workout(avg_hr_bpm=None, elevation_m=None, notes=None)
        loaded = self._write_and_load([rw])
        assert loaded[0].avg_hr_bpm is None
        assert loaded[0].elevation_m is None
        assert loaded[0].notes is None


# ---------------------------------------------------------------------------
# Queryfunkcje — daty, exercise, running, last N
# ---------------------------------------------------------------------------

class TestQueryFunctions:
    """Queryfunkcje działają na zamockowanym pliku."""

    @pytest.fixture(autouse=True)
    def _isolated_workspace(self, tmp_path):
        self.root = tmp_path
        self.patch = patch("janus.integrations.workout_md.PROJECT_ROOT", tmp_path)
        self.patch.start()
        yield
        self.patch.stop()

    def _save(self, workouts: list):
        _write_workouts(workouts)

    def test_find_by_date_range_all(self):
        sw1 = _strength_workout("sw-001", _dt(2026, 9, 1, 10, 0))
        sw2 = _strength_workout("sw-002", _dt(2026, 9, 2, 10, 0))
        sw3 = _strength_workout("sw-003", _dt(2026, 9, 3, 10, 0))
        self._save([sw1, sw2, sw3])

        result = find_workouts_by_date_range(_dt(2026, 9, 1), _dt(2026, 9, 3))
        assert len(result) == 3
        assert result[0].id == "sw-001"
        assert result[2].id == "sw-003"

    def test_find_by_date_range_partial(self):
        sw1 = _strength_workout("sw-001", _dt(2026, 9, 1))
        sw2 = _strength_workout("sw-002", _dt(2026, 9, 2))
        sw3 = _strength_workout("sw-003", _dt(2026, 9, 3))
        self._save([sw1, sw2, sw3])

        result = find_workouts_by_date_range(_dt(2026, 9, 2), _dt(2026, 9, 2))
        assert len(result) == 1
        assert result[0].id == "sw-002"

    def test_find_by_date_range_no_match(self):
        sw = _strength_workout("sw-001", _dt(2026, 9, 1))
        self._save([sw])

        result = find_workouts_by_date_range(_dt(2026, 10, 1), _dt(2026, 10, 2))
        assert result == []

    def test_find_by_date_range_with_start_only(self):
        sw1 = _strength_workout("sw-001", _dt(2026, 9, 1))
        sw2 = _strength_workout("sw-002", _dt(2026, 9, 2))
        self._save([sw1, sw2])

        result = find_workouts_by_date_range(start=_dt(2026, 9, 1))
        assert len(result) == 2

    def test_find_by_date_range_with_end_only(self):
        sw1 = _strength_workout("sw-001", _dt(2026, 9, 1))
        sw2 = _strength_workout("sw-002", _dt(2026, 9, 2))
        self._save([sw1, sw2])

        result = find_workouts_by_date_range(end=_dt(2026, 9, 1))
        assert len(result) == 1
        assert result[0].id == "sw-001"

    def test_find_history_by_exercise_multiple_workouts(self):
        sw1 = _strength_workout(
            workout_id="sw-001",
            date=_dt(2026, 9, 1),
            exercises=[Exercise(name="Back Squat", sets=[Set(reps=5, weight_kg=80.0)])],
        )
        sw2 = _strength_workout(
            workout_id="sw-002",
            date=_dt(2026, 9, 8),
            exercises=[Exercise(name="Back Squat", sets=[Set(reps=5, weight_kg=85.0)])],
        )
        sw3 = _strength_workout(
            workout_id="sw-003",
            date=_dt(2026, 9, 15),
            exercises=[Exercise(name="Bench Press", sets=[Set(reps=5, weight_kg=60.0)])],
        )
        self._save([sw1, sw2, sw3])

        result = find_history_by_exercise("Back Squat")
        assert len(result) == 2
        assert result[0].id == "sw-001"
        assert result[1].id == "sw-002"

    def test_find_history_by_exercise_case_insensitive(self):
        sw = _strength_workout(
            exercises=[Exercise(name="Back Squat", sets=[Set(reps=5, weight_kg=80.0)])],
        )
        self._save([sw])

        result = find_history_by_exercise("back squat")
        assert len(result) == 1
        assert result[0].exercises[0].name == "Back Squat"

    def test_find_history_by_exercise_no_match(self):
        sw = _strength_workout(exercises=[Exercise(name="Bench Press", sets=[Set(reps=5, weight_kg=60.0)])])
        self._save([sw])

        result = find_history_by_exercise("Squat")
        assert result == []

    def test_find_history_by_exercise_only_strength(self):
        sw = _strength_workout(exercises=[Exercise(name="Pull-up", sets=[Set(reps=5, weight_kg=None)])])
        rw = _running_workout(distance_km=5.0, duration_minutes=30.0)
        self._save([sw, rw])

        result = find_history_by_exercise("Pull-up")
        assert len(result) == 1
        # Running workout jest zawarty w historii, ale nie ma tego ćwiczenia — filtered out
        assert all(isinstance(r, StrengthWorkout) for r in result)

    def test_find_running_workouts_returns_only_running(self):
        sw = _strength_workout()
        rw1 = _running_workout("rw-001", distance_km=5.0, duration_minutes=30.0)
        rw2 = _running_workout("rw-002", distance_km=10.0, duration_minutes=60.0)
        self._save([sw, rw1, rw2])

        result = find_running_workouts()
        assert len(result) == 2
        assert all(isinstance(r, RunningWorkout) for r in result)

    def test_find_running_workouts_empty_when_no_running(self):
        sw = _strength_workout()
        self._save([sw])

        result = find_running_workouts()
        assert result == []

    def test_find_last_n_returns_most_recent_first(self):
        sw1 = _strength_workout("sw-001", _dt(2026, 9, 1))
        sw2 = _strength_workout("sw-002", _dt(2026, 9, 2))
        sw3 = _strength_workout("sw-003", _dt(2026, 9, 3))
        self._save([sw1, sw2, sw3])

        result = find_last_n(2)
        assert len(result) == 2
        assert result[0].id == "sw-003"
        assert result[1].id == "sw-002"

    def test_find_last_n_returns_all_when_n_greater_than_count(self):
        sw = _strength_workout("sw-001", _dt(2026, 9, 1))
        self._save([sw])

        result = find_last_n(10)
        assert len(result) == 1
        assert result[0].id == "sw-001"

    def test_find_last_n_empty_when_no_workouts(self):
        result = find_last_n(5)
        assert result == []

    def test_find_last_n_zero_returns_empty(self):
        sw = _strength_workout()
        self._save([sw])

        result = find_last_n(0)
        assert result == []

    def test_find_last_n_negative_returns_empty(self):
        sw = _strength_workout()
        self._save([sw])

        result = find_last_n(-1)
        assert result == []

    def test_find_last_n_mixed_types_strengthen_first(self):
        sw = _strength_workout("sw-001", _dt(2026, 9, 1))
        rw = _running_workout("rw-001", _dt(2026, 9, 2), distance_km=5.0)
        rw2 = _running_workout("rw-002", _dt(2026, 9, 3), distance_km=10.0)
        self._save([sw, rw, rw2])

        result = find_last_n(2)
        assert len(result) == 2
        assert result[0].id == "rw-002"
        assert result[1].id == "rw-001"
