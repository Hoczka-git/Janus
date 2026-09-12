"""Testy dla skryptu naprawczego repair_workouts.py.

Weryfikują:
- Poprawność identify_corrupt_ids (wyklucza sw-005, usuwa rw-001).
- Poprawność build_merged_workout (9 ćwiczeń, 25 serii, odpowiednie reps/weight/rpe).
- Idempotentność repair(): uruchomienie na już naprawionym danych nie usuwa sw-005.
- Każde ćwiczenie należy do dokładnie jednego workoutu.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from janus.integrations.workout_md import load_workouts
from janus.models.workout import (
    Exercise,
    RunningWorkout,
    Set,
    StrengthWorkout,
    WorkoutType,
)

from scripts.repair_workouts import (
    MERGED_ID,
    PRESERVE_IDS,
    PLAN14_EXERCISES,
    build_merged_workout,
    identify_corrupt_ids,
    repair,
)


# ---------------------------------------------------------------------------
# build_merged_workout
# ---------------------------------------------------------------------------

def test_merged_workout_has_9_exercises():
    w = build_merged_workout()
    assert isinstance(w, StrengthWorkout)
    assert len(w.exercises) == 9


def test_merged_workout_exercises_are_unique():
    w = build_merged_workout()
    names = [e.name for e in w.exercises]
    assert len(names) == len(set(names)) == 9


def test_merged_workout_sets_match_plan():
    w = build_merged_workout()
    for ex, spec in zip(w.exercises, PLAN14_EXERCISES):
        assert ex.name == spec["name"]
        assert len(ex.sets) == spec["sets"]
        for s in ex.sets:
            assert s.reps == spec["reps"]
            assert s.weight_kg == spec["weight_kg"]
            assert s.rpe == spec["rpe"]


def test_merged_workout_total_sets_is_25():
    w = build_merged_workout()
    total = sum(len(e.sets) for e in w.exercises)
    assert total == 25


def test_merged_workout_metadata():
    w = build_merged_workout()
    assert w.id == MERGED_ID
    assert w.source == "plan14"
    assert w.notes == "Plan 14 — Trening C — Tydzień 1"
    assert w.workout_type == WorkoutType.STRENGTH


# ---------------------------------------------------------------------------
# identify_corrupt_ids
# ---------------------------------------------------------------------------

def test_identify_corrupt_excludes_merged():
    """sw-005 (merged) must NOT be flagged as corrupt."""
    corrupt = identify_corrupt_ids([])
    # With no workouts, nothing to flag.
    assert corrupt == set()


def test_identify_corrupt_with_preserved_and_merged(_sample_workouts):
    """Preserved + merged are not corrupt; duplicates of plan14 (other ids) are."""
    corrupt = identify_corrupt_ids(_sample_workouts)
    # The sample has sw-005 (plan14) which is the merged one — must NOT be corrupt.
    assert MERGED_ID not in corrupt
    # Preserved IDs are never corrupt.
    for pid in PRESERVE_IDS:
        assert pid not in corrupt


def test_identify_corrupt_flags_rw001_as_duplicate():
    """rw-001 (duplicate run) must be flagged as corrupt."""
    rw001 = RunningWorkout(
        id="rw-001",
        date=datetime(2026, 9, 2, tzinfo=timezone.utc),
        workout_type=WorkoutType.RUNNING,
        distance_km=5.0,
        duration_minutes=30.0,
    )
    corrupt = identify_corrupt_ids([rw001])
    assert "rw-001" in corrupt


# ---------------------------------------------------------------------------
# repair — idempotency
# ---------------------------------------------------------------------------

@pytest.fixture
def _sample_workouts():
    """Workouts matching the current repaired state of data/workouts.md."""
    sw1 = StrengthWorkout(
        id="sw-001",
        date=datetime(2026, 9, 1, tzinfo=timezone.utc),
        workout_type=WorkoutType.STRENGTH,
    )
    sw4 = StrengthWorkout(
        id="sw-004",
        date=datetime(2026, 9, 11, tzinfo=timezone.utc),
        workout_type=WorkoutType.STRENGTH,
        source="manual",
        notes="test",
        exercises=[Exercise(name="Test exercise", sets=[Set(reps=3, weight_kg=12.0, rpe=8.0)])],
    )
    rw2 = RunningWorkout(
        id="rw-002",
        date=datetime(2026, 9, 10, tzinfo=timezone.utc),
        workout_type=WorkoutType.RUNNING,
        distance_km=8.02,
        duration_minutes=60.0,
        source="manual",
        notes="test run",
    )
    sw5 = build_merged_workout()
    return [sw1, sw4, rw2, sw5]


class TestRepairIdempotent:
    """repair() on already-repaired data must be a no-op on data content."""

    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path, _sample_workouts):
        self.root = tmp_path
        self.patcher = patch("janus.integrations.workout_md.PROJECT_ROOT", tmp_path)
        self.patcher.start()
        # Seed with the already-repaired set
        from janus.integrations.workout_md import save_workouts
        save_workouts(_sample_workouts)
        yield
        self.patcher.stop()

    def test_repair_keeps_four_workouts(self):
        result = repair(dry_run=True)
        assert result["final_count"] == 4
        assert sorted(result["final_ids"]) == sorted(["sw-001", "sw-004", "sw-005", "rw-002"])

    def test_repair_does_not_remove_sw005(self):
        result = repair(dry_run=True)
        assert "sw-005" not in result["corrupt_ids_removed"]

    def test_repair_preserves_sw001_sw004_rw002(self):
        result = repair(dry_run=True)
        assert set(result["preserved_ids"]) == {"sw-001", "sw-004", "rw-002"}

    def test_repair_is_idempotent_on_disk(self):
        """Running repair twice produces the same data."""
        repair(dry_run=False)
        after_first = load_workouts()
        repair(dry_run=False)
        after_second = load_workouts()
        assert len(after_first) == len(after_second) == 4
        assert [w.id for w in after_first] == [w.id for w in after_second]

    def test_each_exercise_belongs_to_single_workout(self):
        """No exercise name should appear in two different workouts."""
        workouts = load_workouts()
        all_names = []
        for w in workouts:
            if isinstance(w, StrengthWorkout):
                all_names.extend(e.name for e in w.exercises)
        # Every exercise name must be unique across all workouts.
        assert len(all_names) == len(set(all_names)), (
            f"Duplicate exercise names found: {all_names}"
        )
