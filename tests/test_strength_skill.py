"""Targeted tests for the strength training skill (skills/strength/SKILL.md).

Covers the three required areas:

1. **Registration** — a model-driven WORKOUT_ADDED ActivityRecord is ingested
   via ``ingest_activities()`` and appended to ``data/workouts.md`` atomically.
2. **Analysis** — a previously registered workout can be loaded and analyzed via
   ``compute_exercise_summary`` / ``compute_overall_summary``.
3. **No direct data/ writes** — registration flows entirely through the
   ingestion gateway; the model never touches ``data/workouts.md`` directly.

Conventions mirror the existing test suite (``test_activity_ingest.py``,
``test_fitness.py``): isolated ``tmp_path`` workspace via ``monkeypatch``,
``Exercise``/``Set`` instances in the record evidence (matching the real
``_dispatch_workout`` code path which passes ``evidence["exercises"]`` directly
to ``StrengthWorkout``), no real ``data/`` touched.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from janus.models.workout import Exercise, Set, StrengthWorkout, WorkoutType
from janus.services.activity_ingest import (
    ActivityRecord,
    ActivityType,
    ingest_activities,
)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _dt(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)


def _make_exercises(exercises_data):
    """Convert plain-dict exercise definitions into Exercise/Set instances.

    ``_dispatch_workout`` passes ``record.evidence["exercises"]`` directly to
    ``StrengthWorkout(exercises=...)``, whose ``__post_init__`` validates that
    each element is an ``Exercise`` and each set is a ``Set``.  Plain dicts are
    rejected, so the model record must carry typed objects.
    """
    return [
        Exercise(
            name=ex["name"],
            sets=[
                Set(
                    reps=s["reps"],
                    weight_kg=s.get("weight_kg"),
                    rpe=s.get("rpe"),
                )
                for s in ex["sets"]
            ],
            notes=ex.get("notes"),
        )
        for ex in exercises_data
    ]


def _default_exercises():
    return _make_exercises([
        {
            "name": "Back Squat",
            "sets": [
                {"reps": 5, "weight_kg": 80.0, "rpe": 8.0},
                {"reps": 5, "weight_kg": 80.0, "rpe": 8.5},
                {"reps": 5, "weight_kg": 80.0, "rpe": 9.0},
            ],
            "notes": None,
        },
        {
            "name": "Walking Lunges",
            "sets": [
                {"reps": 16, "weight_kg": None, "rpe": 8.0},
                {"reps": 16, "weight_kg": None, "rpe": 8.0},
            ],
            "notes": "Bodyweight",
        },
    ])


def _strength_record(
    workout_id="w_str_1",
    date="2026-09-12",
    exercises=None,
    notes="Leg day — felt strong",
) -> ActivityRecord:
    """Build a model-driven WORKOUT_ADDED record for strength.

    ``evidence["exercises"]`` carries ``Exercise``/``Set`` instances, matching
    the actual ``_dispatch_workout`` implementation which passes them directly
    to ``StrengthWorkout.__post_init__`` validation.
    """
    if exercises is None:
        exercises = _default_exercises()
    return ActivityRecord(
        type=ActivityType.WORKOUT_ADDED,
        source="chat",
        timestamp=_dt(2026, 9, 12, 14, 30),
        workout_id=workout_id,
        workout_type="strength",
        evidence={
            "date": date,
            "exercises": exercises,
            "notes": notes,
        },
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────
@pytest.fixture
def iso_workspace(tmp_path, monkeypatch):
    """Redirect DATA_DIR, PROJECT_ROOT, and CONFIG_PATH to an isolated tmp_path.

    Mirrors the pattern in ``test_activity_ingest.py::isolated_data_dir`` so no
    real ``data/`` is ever touched.  Also patches ``workout_md.PROJECT_ROOT``
    so that ``load_workouts()`` reads from the same isolated workspace.
    """
    import janus.services.activity_ingest as ai
    import janus.integrations.workout_md as wmd

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_path = tmp_path / "config.toml"

    monkeypatch.setattr(ai, "DATA_DIR", data_dir)
    monkeypatch.setattr(ai, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ai, "CONFIG_PATH", config_path)
    monkeypatch.setattr(wmd, "PROJECT_ROOT", tmp_path)

    return {
        "data_dir": data_dir,
        "workouts": data_dir / "workouts.md",
        "root": tmp_path,
    }


# ── 1. Registration: model-driven ingestion of a strength workout ─────────────
class TestStrengthRegistration:
    """Verify a model-emitted WORKOUT_ADDED record is persisted to data/."""

    def test_register_single_strength_workout(self, iso_workspace):
        """A strength record with Exercise/Set instances is accepted and written."""
        rec = _strength_record(workout_id="sw-005")
        results = ingest_activities([rec])

        assert len(results) == 1
        assert results[0].accepted is True
        assert results[0].wrote is True
        assert results[0].action == "appended"
        assert results[0].error is None
        # file_path points to data/workouts.md
        assert results[0].file_path is not None
        assert str(results[0].file_path).endswith("workouts.md")

        # The file actually exists on disk (no manual editing).
        wrk = iso_workspace["workouts"]
        assert wrk.exists()
        content = wrk.read_text()
        assert "## Workout:" in content
        assert "sw-005" in content
        assert "strength" in content
        assert "Back Squat" in content
        assert "Walking Lunges" in content

    def test_registered_workout_round_trips(self, iso_workspace):
        """A persisted strength workout round-trips through load_workouts()."""
        from janus.integrations.workout_md import load_workouts

        rec = _strength_record(workout_id="sw-005")
        ingest_activities([rec])

        workouts = load_workouts()
        assert len(workouts) == 1
        w = workouts[0]
        assert isinstance(w, StrengthWorkout)
        assert w.id == "sw-005"
        assert w.workout_type == WorkoutType.STRENGTH
        assert len(w.exercises) == 2
        assert w.exercises[0].name == "Back Squat"
        assert len(w.exercises[0].sets) == 3
        assert w.exercises[0].sets[0].weight_kg == 80.0
        assert w.exercises[0].sets[0].rpe == 8.0
        # Bodyweight sets round-trip as None
        assert w.exercises[1].sets[0].weight_kg is None
        assert w.exercises[1].notes == "Bodyweight"

    def test_registered_workout_json_serialized(self, iso_workspace):
        """Exercises are stored as a JSON-encoded array in markdown."""
        rec = _strength_record(workout_id="sw-005")
        ingest_activities([rec])

        content = iso_workspace["workouts"].read_text()
        # The exercises line is a JSON array
        assert "exercises = [" in content
        assert "Back Squat" in content
        assert "Walking Lunges" in content
        # Bodyweight is serialized as null in JSON
        assert '"weight_kg": null' in content

    def test_register_appends_after_existing(self, iso_workspace):
        """A second workout is appended without disturbing existing content."""
        from janus.integrations.workout_md import load_workouts

        wrk = iso_workspace["workouts"]
        # Write a valid existing workout block so load_workouts() can parse it.
        wrk.write_text(
            "# Fitness Workouts\n\n"
            "## Workout:\n"
            "id = w_old\n"
            "date = 2026-09-01T10:00:00+00:00\n"
            "workout_type = strength\n"
            "exercises = []\n"
            "---\n"
        )
        rec = _strength_record(workout_id="sw-006")
        ingest_activities([rec])

        content = wrk.read_text()
        assert content.startswith("# Fitness Workouts")
        assert "w_old" in content
        assert "sw-006" in content

        loaded = load_workouts()
        assert len(loaded) == 2

    def test_register_multiple_exercises_one_workout(self, iso_workspace):
        """Multiple exercises in one record are all persisted."""
        exercises = _make_exercises([
            {"name": "Squat", "sets": [{"reps": 5, "weight_kg": 100.0, "rpe": 8.0}], "notes": None},
            {"name": "Bench", "sets": [{"reps": 8, "weight_kg": 60.0, "rpe": 7.5}], "notes": None},
            {"name": "Deadlift", "sets": [{"reps": 3, "weight_kg": 120.0, "rpe": 9.0}], "notes": None},
        ])
        rec = _strength_record(workout_id="sw-010", exercises=exercises)
        results = ingest_activities([rec])

        assert results[0].accepted is True
        assert results[0].action == "appended"
        content = iso_workspace["workouts"].read_text()
        assert "Squat" in content
        assert "Bench" in content
        assert "Deadlift" in content

    def test_register_generated_id_when_workout_id_absent(self, iso_workspace):
        """Without workout_id, a w-<hex> UUID is generated and written to file."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt(2026, 9, 12, 14, 30),
            workout_type="strength",
            evidence={
                "date": "2026-09-12",
                "exercises": _make_exercises([
                    {"name": "Squat", "sets": [{"reps": 5, "weight_kg": 80.0, "rpe": 8.0}], "notes": None},
                ]),
            },
        )
        results = ingest_activities([rec])

        assert results[0].accepted is True
        assert results[0].wrote is True
        # The gateway generates a w-<hex> ID when workout_id is absent.
        content = iso_workspace["workouts"].read_text()
        assert "id = w-" in content
        assert "Squat" in content

    def test_register_invalid_record_rejected(self, iso_workspace):
        """A record missing workout_type is rejected, not written."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt(2026, 9, 12, 14, 30),
            evidence={"exercises": []},
        )
        results = ingest_activities([rec])
        assert results[0].accepted is False
        assert results[0].wrote is False
        assert results[0].action == "rejected"
        assert results[0].error is not None
        assert "workout_type" in results[0].error
        # No file written
        assert not iso_workspace["workouts"].exists()


# ── 2. Analysis: query + compute on a registered workout ──────────────────────
class TestStrengthAnalysis:
    """Verify analysis functions work on workouts registered via ingestion."""

    def _register_and_load(self, iso_workspace, exercises=None):
        """Helper: register one strength workout then load it back."""
        from janus.integrations.workout_md import load_workouts

        rec = _strength_record(workout_id="sw-005", exercises=exercises)
        ingest_activities([rec])
        return load_workouts()[0]

    def test_find_workout_by_id(self, iso_workspace):
        """A registered workout is findable by its ID."""
        from janus.integrations.workout_md import find_workout_by_id

        self._register_and_load(iso_workspace)
        w = find_workout_by_id("sw-005")
        assert w is not None
        assert isinstance(w, StrengthWorkout)
        assert w.id == "sw-005"

    def test_find_history_by_exercise(self, iso_workspace):
        """find_history_by_exercise returns workouts containing the exercise."""
        from janus.integrations.workout_md import find_history_by_exercise

        rec = _strength_record(workout_id="sw-005")
        ingest_activities([rec])

        history = find_history_by_exercise("Back Squat")
        assert len(history) == 1
        assert history[0].id == "sw-005"

    def test_find_history_case_insensitive(self, iso_workspace):
        """Exercise name matching is case-insensitive."""
        from janus.integrations.workout_md import find_history_by_exercise

        rec = _strength_record(workout_id="sw-005")
        ingest_activities([rec])

        history = find_history_by_exercise("back squat")
        assert len(history) == 1

    def test_exercise_summary_volume(self, iso_workspace):
        """compute_exercise_summary reports correct volume for Back Squat."""
        from janus.integrations.workout_md import load_workouts
        from janus.services.workout_analytics import compute_exercise_summary

        rec = _strength_record(workout_id="sw-005")
        ingest_activities([rec])

        workouts = load_workouts()
        summary = compute_exercise_summary(workouts, "Back Squat")
        assert summary.workout_count == 1
        # 3 sets of 5x80 = 1200 total volume
        assert summary.highest_workout_volume_kg == 1200.0
        assert summary.highest_weight_kg == 80.0
        assert summary.latest_sets_description is not None
        assert "5x80.0kg" in summary.latest_sets_description

    def test_exercise_summary_bodyweight_excluded(self, iso_workspace):
        """Bodyweight sets contribute 0 volume and exclude highest_weight."""
        from janus.integrations.workout_md import load_workouts
        from janus.services.workout_analytics import compute_exercise_summary

        exercises = _make_exercises([
            {"name": "Pull-up", "sets": [{"reps": 8, "weight_kg": None, "rpe": None}], "notes": None},
        ])
        rec = _strength_record(workout_id="sw-006", exercises=exercises, notes=None)
        ingest_activities([rec])

        workouts = load_workouts()
        summary = compute_exercise_summary(workouts, "Pull-up")
        assert summary.workout_count == 1
        # All bodyweight: highest_weight is None, volume is 0.0
        assert summary.highest_weight_kg is None
        assert summary.highest_workout_volume_kg == 0.0

    def test_overall_summary_after_registration(self, iso_workspace):
        """compute_overall_summary counts the registered strength workout."""
        from janus.integrations.workout_md import load_workouts
        from janus.services.workout_analytics import compute_overall_summary

        rec = _strength_record(workout_id="sw-005")
        ingest_activities([rec])

        workouts = load_workouts()
        summary = compute_overall_summary(workouts)
        assert summary.total_workouts == 1
        assert summary.strength_count == 1
        assert summary.running_count == 0
        assert summary.most_recent_workout_id == "sw-005"


# ── 3. No manual data/ editing — registration through gateway only ────────────
class TestNoDirectDataWrites:
    """Verify registration never requires or performs manual data/ editing."""

    def test_no_manual_file_edit_for_registration(self, iso_workspace):
        """Registration is fully driven by ingest_activities(); no manual file edit."""
        wrk = iso_workspace["workouts"]
        # File does not exist before registration.
        assert not wrk.exists()

        rec = _strength_record(workout_id="sw-005")
        results = ingest_activities([rec])

        # The gateway created and wrote the file — the caller never touched it.
        assert results[0].wrote is True
        assert wrk.exists()
        content = wrk.read_text()
        assert "## Workout:" in content

    def test_registration_through_ingestion_not_save_workout(self, iso_workspace):
        """The model-driven path uses ingest_activities, routing through
        _dispatch_workout (via read_modify_write_with_retry), not save_workout.

        This mirrors the skill spec's safety constraint: model-driven code must
        not bypass the ingestion gateway.  We patch workout_md.save_workout to
        prove it is never called on the model-driven path.
        """
        from unittest.mock import patch

        rec = _strength_record(workout_id="sw-005")
        with patch("janus.integrations.workout_md.save_workout") as mock_save:
            results = ingest_activities([rec])

        assert results[0].accepted is True
        assert results[0].wrote is True
        # save_workout must NOT be called on the model-driven ingestion path.
        mock_save.assert_not_called()

    def test_dedup_rejects_duplicate_workout_id(self, iso_workspace):
        """Two records with the same workout_id → second rejected.

        This confirms registration is governed by the gateway's dedup logic,
        not by manual file inspection/editing.  The dedup key (workout_id)
        appears in the file content as ``id = <workout_id>``, so _check_tolerance
        detects the duplicate.
        """
        rec1 = _strength_record(workout_id="dup-001")
        rec2 = _strength_record(workout_id="dup-001")
        results = ingest_activities([rec1, rec2], dedup_policy="reject")
        assert results[0].accepted is True
        assert results[0].action == "appended"
        assert results[1].accepted is False
        assert results[1].action == "rejected"
        assert "duplicate" in results[1].error.lower()
