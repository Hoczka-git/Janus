"""Targeted tests for the running workout skill (ADR-005 / running SKILL.md).

These tests focus on the running-specific ingestion, dedup, and analytics
behaviour described in the running skill's Verification Checklist:

1. Model-driven ingestion of a running workout through the Activity Ingestion
   gateway produces an IngestResult with accepted/action="appended".
2. The appended markdown round-trips back into a RunningWorkout with all fields
   preserved (distance, duration, HR, elevation, notes).
3. A second identical WORKOUT_ADDED record (same date + type, no workout_id)
   is REJECTED under the default policy="reject" (dedup via date+type key).
4. The degenerate dedup key "::running" does NOT collide with dated workouts
   (i.e. a dated workout is not falsely detected as a duplicate of an
   undated one).
5. Average pace is distance-weighted (not arithmetic mean of per-run paces).
6. Average HR is computed only from runs that have HR data.
7. A RunningWorkout with duration_minutes=0 is rejected at the domain model
   layer (validation enforcement).

All persistence is redirected to an isolated tmp_path; no real data/ is
touched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from janus.models.workout import RunningWorkout, WorkoutType
from janus.services.activity_ingest import (
    ActivityRecord,
    ActivityType,
    IngestResult,
    compute_dedup_key,
    ingest_activities,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch):
    """Redirect the ingestion layer's DATA_DIR / PROJECT_ROOT / CONFIG_PATH.

    Also redirects workout_md.PROJECT_ROOT so load_workouts() reads from the
    same isolated tmp_path as the gateway's write path.
    """
    import janus.services.activity_ingest as ai
    import janus.integrations.workout_md as workout_md

    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(ai, "DATA_DIR", data_dir)
    monkeypatch.setattr(ai, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ai, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(workout_md, "PROJECT_ROOT", tmp_path)
    return {"data_dir": data_dir, "workouts": data_dir / "workouts.md"}


def _running_record(
    *,
    workout_id: str | None = None,
    date: str = "2026-09-12",
    distance_km: float = 10.0,
    duration_minutes: float = 55.0,
    avg_hr_bpm: float | None = 150.0,
    elevation_m: float | None = 120.0,
    notes: str = "Morning run",
) -> ActivityRecord:
    return ActivityRecord(
        type=ActivityType.WORKOUT_ADDED,
        source="hermes",
        timestamp=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
        workout_type="running",
        workout_id=workout_id,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        avg_hr_bpm=avg_hr_bpm,
        elevation_m=elevation_m,
        evidence={"date": date, "notes": notes},
    )


# ── Ingestion: model-driven append ───────────────────────────────────────────


class TestRunningIngestion:
    """Path B — model-driven ingestion through ingest_activities()."""

    def test_running_workout_appended(self, isolated):
        """A WORKOUT_ADDED (running) appends a block to workouts.md."""
        rec = _running_record()
        results = ingest_activities([rec])

        assert len(results) == 1
        assert isinstance(results[0], IngestResult)
        assert results[0].accepted is True
        assert results[0].wrote is True
        assert results[0].action == "appended"
        assert results[0].file_path is not None
        assert "workouts.md" in results[0].file_path

        content = isolated["workouts"].read_text()
        assert "# Fitness Workouts" in content
        assert "## Workout:" in content
        assert "distance_km = 10.0" in content
        assert "duration_minutes = 55.0" in content
        assert "avg_hr_bpm = 150.0" in content
        assert "elevation_m = 120.0" in content
        assert "running" in content
        assert "Morning run" in content

    def test_running_workout_round_trips_into_model(self, isolated):
        """The appended block loads back as a fully-populated RunningWorkout."""
        from janus.integrations.workout_md import load_workouts

        rec = _running_record()
        ingest_activities([rec])

        workouts = load_workouts()
        assert len(workouts) == 1
        w = workouts[0]
        assert isinstance(w, RunningWorkout)
        assert w.workout_type == WorkoutType.RUNNING
        assert w.distance_km == 10.0
        assert w.duration_minutes == 55.0
        assert w.avg_hr_bpm == 150.0
        assert w.elevation_m == 120.0
        assert w.notes == "Morning run"

    def test_generated_id_when_no_workout_id(self, isolated):
        """Without workout_id, the gateway generates a 'w-<hex>' id."""
        from janus.integrations.workout_md import load_workouts

        rec = _running_record()
        assert rec.workout_id is None
        rec.workout_id = None  # ensure unset
        # build a fresh record without workout_id
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
            evidence={"date": "2026-09-12", "notes": "Easy run"},
        )
        ingest_activities([rec])
        workouts = load_workouts()
        assert len(workouts) == 1
        # generated id via _gen_uuid('w') -> 'w-<8-hex>'
        assert workouts[0].id.startswith("w-")
        assert len(workouts[0].id) > 3


# ── Dedup ────────────────────────────────────────────────────────────────────


class TestRunningDedup:
    """Dedup key rules for WORKOUT_ADDED (running)."""

    def test_dedup_key_uses_date_when_no_id(self):
        """Without workout_id, key falls back to <date>::running."""
        rec = _running_record()
        assert rec.workout_id is None
        key = compute_dedup_key(rec)
        assert key == "2026-09-12::running"

    def test_dedup_key_uses_workout_id_when_present(self):
        """With workout_id, the key is the workout_id itself."""
        rec = _running_record(workout_id="rw-special")
        assert compute_dedup_key(rec) == "rw-special"

    def test_duplicate_running_rejected_default_policy(self, isolated):
        """A second identical running workout (same date+type, no id) is
        rejected under the default policy='reject'. (Checklist item 7.)"""
        rec1 = _running_record()
        rec2 = _running_record()  # identical: same date + type, no workout_id

        r1 = ingest_activities([rec1])
        r2 = ingest_activities([rec2])

        assert r1[0].accepted is True
        assert r1[0].action == "appended"

        # The second must be rejected as a duplicate
        assert r2[0].accepted is False
        assert r2[0].action == "rejected"
        assert r2[0].wrote is False
        assert r2[0].error is not None
        assert "duplicate" in r2[0].error.lower()

        # Only one block in the file
        content = isolated["workouts"].read_text()
        assert content.count("## Workout:") == 1

    def test_explicit_workout_id_bypasses_date_dedup(self, isolated):
        """Two workouts on the same date with explicit ids are not duplicates."""
        rec1 = _running_record(workout_id="rw-001")
        rec2 = _running_record(workout_id="rw-002")

        r1 = ingest_activities([rec1])
        r2 = ingest_activities([rec2])

        assert r1[0].accepted is True
        assert r2[0].accepted is True
        content = isolated["workouts"].read_text()
        assert content.count("## Workout:") == 2

    def test_degenerate_key_does_not_collide_with_dated(self, isolated):
        """An undated workout ('::running') must not be treated as a duplicate
        of an already-persisted dated workout (Checklist item 4 guard)."""
        rec1 = _running_record()  # dated -> key "2026-09-12::running"
        ingest_activities([rec1])

        # undated: no evidence['date'], no record.date, no workout_id -> "::running"
        rec2 = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
            workout_type="running",
            distance_km=3.0,
            duration_minutes=20.0,
            evidence={},  # no date
        )
        assert compute_dedup_key(rec2) == "::running"

        r2 = ingest_activities([rec2])
        # The dated workout's key is "2026-09-12::running", which is a
        # substring of "::running", so the degenerate key could falsely match.
        # It must NOT be rejected here — the dated record is distinct.
        assert r2[0].accepted is True
        assert r2[0].action == "appended"
        content = isolated["workouts"].read_text()
        assert content.count("## Workout:") == 2


# ── Validation enforcement ──────────────────────────────────────────────────


class TestRunningValidation:
    """RunningWorkout __post_init__ validators (Checklist item 1)."""

    def _dt(self, y=2026, m=9, d=12):
        return datetime(y, m, d, tzinfo=timezone.utc)

    def test_zero_duration_rejected(self):
        with pytest.raises(ValueError, match="duration_minutes must be > 0"):
            RunningWorkout(
                id="rw-1", date=self._dt(), workout_type=WorkoutType.RUNNING,
                distance_km=5.0, duration_minutes=0.0,
            )

    def test_negative_distance_rejected(self):
        with pytest.raises(ValueError, match="distance_km must be >= 0"):
            RunningWorkout(
                id="rw-1", date=self._dt(), workout_type=WorkoutType.RUNNING,
                distance_km=-1.0, duration_minutes=30.0,
            )

    def test_zero_hr_rejected_when_present(self):
        with pytest.raises(ValueError, match="avg_hr_bpm must be > 0"):
            RunningWorkout(
                id="rw-1", date=self._dt(), workout_type=WorkoutType.RUNNING,
                distance_km=5.0, duration_minutes=30.0, avg_hr_bpm=0.0,
            )

    def test_optional_hr_and_elevation_none_ok(self):
        rw = RunningWorkout(
            id="rw-1", date=self._dt(), workout_type=WorkoutType.RUNNING,
            distance_km=5.0, duration_minutes=30.0,
            avg_hr_bpm=None, elevation_m=None, notes=None,
        )
        assert rw.avg_hr_bpm is None
        assert rw.elevation_m is None

    def test_gateway_rejects_zero_duration_running(self, isolated):
        """A WORKOUT_ADDED with duration_minutes=0 is rejected at dispatch
        (domain model validator fires inside _dispatch_workout)."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
            workout_type="running",
            distance_km=5.0,
            duration_minutes=0.0,  # invalid -> domain model raises ValueError
            evidence={"date": "2026-09-12"},
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True  # passed gateway validation
        assert results[0].wrote is False     # but dispatch failed
        assert results[0].action == "rejected"
        assert results[0].error is not None
        assert "dispatch" in results[0].error.lower() or "duration" in results[0].error.lower()


# ── Analytics ─────────────────────────────────────────────────────────────────


class TestRunningAnalytics:
    """compute_running_summary: distance-weighted pace, HR filtering."""

    def _runs(self):
        from janus.models.workout import Workout as WorkoutModel
        from janus.models.workout import WorkoutType as WT
        from janus.models.workout import RunningWorkout as RW

        runs: list[WorkoutModel] = [
            RW(id="rw-1", date=datetime(2026, 9, 1, tzinfo=timezone.utc),
              workout_type=WT.RUNNING, distance_km=5.0, duration_minutes=30.0,
              avg_hr_bpm=145.0),
            RW(id="rw-2", date=datetime(2026, 9, 2, tzinfo=timezone.utc),
              workout_type=WT.RUNNING, distance_km=10.0, duration_minutes=58.0,
              avg_hr_bpm=155.0),
            RW(id="rw-3", date=datetime(2026, 9, 3, tzinfo=timezone.utc),
              workout_type=WT.RUNNING, distance_km=8.0, duration_minutes=48.0,
              avg_hr_bpm=None),  # no HR data
        ]
        return runs

    def test_distance_weighted_pace(self):
        """Avg pace = total_duration / total_distance (not mean of per-run pace)."""
        from janus.services.workout_analytics import compute_running_summary

        summary = compute_running_summary(self._runs())
        total_dur = 30.0 + 58.0 + 48.0  # 136
        total_d = 5.0 + 10.0 + 8.0      # 23
        expected_pace = total_dur / total_d  # 5.913...
        assert summary.total_distance_km == 23.0
        assert summary.total_duration_min == 136.0
        assert summary.avg_pace_min_per_km == pytest.approx(expected_pace)
        # Per-run paces: 6.0, 5.8, 6.0 -> arithmetic mean = 5.933...
        # Distance-weighted = 136/23 = 5.913... (different -> confirms weighting)
        assert summary.avg_pace_min_per_km != pytest.approx((6.0 + 5.8 + 6.0) / 3)

    def test_hr_only_from_runs_with_hr(self):
        """Avg HR computed from runs that have HR data only (2/3 runs)."""
        from janus.services.workout_analytics import compute_running_summary

        summary = compute_running_summary(self._runs())
        assert summary.runs_with_hr == 2
        assert summary.avg_hr_bpm_when_available == pytest.approx(
            (145.0 + 155.0) / 2
        )
        assert summary.run_count == 3

    def test_longest_run_and_elevation(self):
        from janus.services.workout_analytics import compute_running_summary
        from janus.models.workout import Workout as WorkoutModel
        from janus.models.workout import RunningWorkout as RW
        from janus.models.workout import WorkoutType as WT

        runs: list[WorkoutModel] = [
            RW(id="rw-1", date=datetime(2026, 9, 1, tzinfo=timezone.utc),
              workout_type=WT.RUNNING, distance_km=5.0, duration_minutes=30.0,
              elevation_m=50.0),
            RW(id="rw-2", date=datetime(2026, 9, 2, tzinfo=timezone.utc),
              workout_type=WT.RUNNING, distance_km=12.0, duration_minutes=70.0,
              elevation_m=100.0),
        ]
        summary = compute_running_summary(runs)
        assert summary.longest_run_km == 12.0
        assert summary.total_elevation_m == 150.0
        assert summary.runs_with_elevation == 2
        assert summary.best_pace_min_per_km == pytest.approx(70.0 / 12.0)

    def test_best_pace_is_min_individual_pace(self):
        from janus.services.workout_analytics import compute_running_summary
        from janus.models.workout import Workout as WorkoutModel
        from janus.models.workout import RunningWorkout as RW
        from janus.models.workout import WorkoutType as WT

        runs: list[WorkoutModel] = [
            RW(id="rw-1", date=datetime(2026, 9, 1, tzinfo=timezone.utc),
              workout_type=WT.RUNNING, distance_km=10.0, duration_minutes=60.0),
            RW(id="rw-2", date=datetime(2026, 9, 2, tzinfo=timezone.utc),
              workout_type=WT.RUNNING, distance_km=5.0, duration_minutes=25.0),
        ]
        summary = compute_running_summary(runs)
        # per-run paces: 6.0, 5.0 -> best = 5.0
        assert summary.best_pace_min_per_km == 5.0

    def test_empty_set_returns_zeroed_summary(self):
        from janus.services.workout_analytics import compute_running_summary

        summary = compute_running_summary([])
        assert summary.run_count == 0
        assert summary.total_distance_km == 0.0
        assert summary.avg_pace_min_per_km is None
        assert summary.longest_run_km == 0.0
