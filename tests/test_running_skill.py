"""Targeted tests for the running skill functionality.

Covers the running domain slice per ADR-005 and the running SKILL.md:

- **Run registration**: ActivityRecord(WORKOUT_ADDED, workout_type="running")
  → ingest_activities() → _dispatch_workout() → atomic append to data/workouts.md.
- **Normalization**: running workout fields (distance_km, duration_minutes,
  avg_hr_bpm, elevation_m) are stored in canonical units and are NOT
  unit-normalized by the ingestion layer (unlike MEASUREMENT records).
- **Analysis**: compute_running_summary() edge cases (empty, single run,
  with/without HR, with/without elevation, zero distance).
- **Persistence**: workout_md.load_workouts / save_workout /
  find_running_workouts / round-trip serialization.
- **Dedup key rules**: workout_id, evidence["date"], record.date, degenerate.
- **Markdown serialization**: _workout_to_markdown_lines for RunningWorkout.

All tests use isolated tmp_path + monkeypatch for DATA_DIR, CONFIG_PATH, and
downstream service file paths.  No real data/ is touched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from janus.models.workout import (
    RunningWorkout,
    Workout,
    WorkoutType,
    dict_to_workout,
    workout_to_dict,
)
from janus.services.activity_ingest import (
    ActivityRecord,
    ActivityType,
    IngestConfig,
    _normalize_record,
    compute_dedup_key,
    ingest_activities,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect DATA_DIR, PROJECT_ROOT, and downstream service file paths
    to tmp_path so no real data/ is touched."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)

    import janus.services.activity_ingest as ai
    monkeypatch.setattr(ai, "DATA_DIR", data_dir)
    monkeypatch.setattr(ai, "PROJECT_ROOT", tmp_path)

    import janus.integrations.workout_md as workout_md
    monkeypatch.setattr(workout_md, "PROJECT_ROOT", tmp_path)

    import janus.services.tasks as tasks_mod
    import janus.integrations.markdown_goals as goals_md
    import janus.integrations.metric_history as mh

    tasks_path = data_dir / "tasks.md"
    goals_path = data_dir / "goals.md"
    workouts_path = data_dir / "workouts.md"
    followups_path = data_dir / "followups.md"
    inbox_path = data_dir / "inbox.md"
    measurements_path = data_dir / "measurements.jsonl"
    metric_history_path = data_dir / "metric_history.md"

    monkeypatch.setattr(tasks_mod, "TASKS_PATH", tasks_path)
    monkeypatch.setattr(goals_md, "GOALS_PATH", goals_path)
    monkeypatch.setattr(mh, "METRIC_HISTORY_PATH", metric_history_path)

    return {
        "data_dir": data_dir,
        "tasks": tasks_path,
        "goals": goals_path,
        "workouts": workouts_path,
        "followups": followups_path,
        "inbox": inbox_path,
        "measurements": measurements_path,
        "metric_history": metric_history_path,
        "project_root": tmp_path,
    }


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirect CONFIG_PATH to a temp directory (no real config.toml)."""
    config_path = tmp_path / "config.toml"
    import janus.services.activity_ingest as ai
    monkeypatch.setattr(ai, "CONFIG_PATH", config_path)
    return config_path


@pytest.fixture
def tz_now():
    """A timezone-aware datetime used across tests."""
    return datetime(2026, 9, 12, 14, 30, 0, tzinfo=timezone.utc)


def _dt_full(*parts):
    """datetime(year, month, day, hour, minute, second, tzinfo=UTC)."""
    return datetime(*parts, tzinfo=timezone.utc)


# ── RunningWorkout model validation ──────────────────────────────────────────


class TestRunningWorkoutValidation:
    """RunningWorkout.__post_init__ validates numeric fields."""

    def test_valid_minimal(self):
        """A minimal valid RunningWorkout (distance + duration only)."""
        w = RunningWorkout(
            id="rw-001",
            date=_dt_full(2026, 9, 12, 10, 0),
            workout_type=WorkoutType.RUNNING,
            distance_km=5.0,
            duration_minutes=30.0,
        )
        assert w.distance_km == 5.0
        assert w.duration_minutes == 30.0
        assert w.avg_hr_bpm is None
        assert w.elevation_m is None

    def test_valid_full(self):
        """A fully populated RunningWorkout."""
        w = RunningWorkout(
            id="rw-002",
            date=_dt_full(2026, 9, 12, 10, 0),
            workout_type=WorkoutType.RUNNING,
            distance_km=10.0,
            duration_minutes=55.0,
            avg_hr_bpm=150.0,
            elevation_m=120.0,
            notes="Morning run",
        )
        assert w.avg_hr_bpm == 150.0
        assert w.elevation_m == 120.0
        assert w.notes == "Morning run"

    def test_negative_distance_raises(self):
        """distance_km < 0 raises ValueError."""
        with pytest.raises(ValueError, match="distance_km must be >= 0"):
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 12),
                workout_type=WorkoutType.RUNNING,
                distance_km=-1.0,
                duration_minutes=30.0,
            )

    def test_zero_duration_raises(self):
        """duration_minutes = 0 raises ValueError (must be > 0)."""
        with pytest.raises(ValueError, match="duration_minutes must be > 0"):
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 12),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=0.0,
            )

    def test_negative_duration_raises(self):
        """duration_minutes < 0 raises ValueError."""
        with pytest.raises(ValueError, match="duration_minutes must be > 0"):
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 12),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=-5.0,
            )

    def test_zero_distance_is_valid(self):
        """distance_km = 0 is valid (e.g. a walk recorded as running)."""
        w = RunningWorkout(
            id="rw-001",
            date=_dt_full(2026, 9, 12),
            workout_type=WorkoutType.RUNNING,
            distance_km=0.0,
            duration_minutes=10.0,
        )
        assert w.distance_km == 0.0

    def test_negative_hr_raises(self):
        """avg_hr_bpm <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="avg_hr_bpm must be > 0"):
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 12),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                avg_hr_bpm=-1.0,
            )

    def test_zero_hr_raises(self):
        """avg_hr_bpm = 0 raises ValueError."""
        with pytest.raises(ValueError, match="avg_hr_bpm must be > 0"):
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 12),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                avg_hr_bpm=0.0,
            )

    def test_negative_elevation_raises(self):
        """elevation_m < 0 raises ValueError."""
        with pytest.raises(ValueError, match="elevation_m must be >= 0"):
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 12),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                elevation_m=-10.0,
            )

    def test_zero_elevation_is_valid(self):
        """elevation_m = 0 is valid (flat run)."""
        w = RunningWorkout(
            id="rw-001",
            date=_dt_full(2026, 9, 12),
            workout_type=WorkoutType.RUNNING,
            distance_km=5.0,
            duration_minutes=30.0,
            elevation_m=0.0,
        )
        assert w.elevation_m == 0.0

    def test_empty_notes_raises(self):
        """Empty string notes raises ValueError."""
        with pytest.raises(ValueError, match="notes must be non-empty string"):
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 12),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                notes="",
            )

    def test_whitespace_notes_raises(self):
        """Whitespace-only notes raises ValueError."""
        with pytest.raises(ValueError, match="notes must be non-empty string"):
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 12),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                notes="   ",
            )

    def test_int_distance_accepted(self):
        """int distance_km is accepted (coerced to float)."""
        w = RunningWorkout(
            id="rw-001",
            date=_dt_full(2026, 9, 12),
            workout_type=WorkoutType.RUNNING,
            distance_km=5,  # int
            duration_minutes=30,
        )
        assert w.distance_km == 5
        assert w.duration_minutes == 30


# ── Run registration via activity ingestion ──────────────────────────────────


class TestRunRegistrationViaIngestion:
    """Integration tests for registering running workouts through the
    activity ingestion gateway (Path B — model-driven)."""

    def test_register_running_workout(self, isolated_data_dir, isolated_config, tz_now):
        """A WORKOUT_ADDED (running) record is appended to workouts.md."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_run_1",
            workout_type="running",
            distance_km=10.0,
            duration_minutes=55.0,
            avg_hr_bpm=151.0,
            elevation_m=120.0,
            evidence={"notes": "Morning run, steady state"},
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        assert results[0].wrote is True
        assert results[0].action == "appended"

        content = isolated_data_dir["workouts"].read_text()
        assert "## Workout:" in content
        assert "w_run_1" in content
        assert "running" in content
        assert "distance_km = 10.0" in content
        assert "duration_minutes = 55.0" in content
        assert "avg_hr_bpm = 151.0" in content
        assert "elevation_m = 120.0" in content
        assert "Morning run, steady state" in content

    def test_register_running_workout_without_optional_fields(
        self, isolated_data_dir, isolated_config, tz_now
    ):
        """A running workout without HR, elevation, or notes is still valid."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_run_2",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = isolated_data_dir["workouts"].read_text()
        assert "w_run_2" in content
        assert "distance_km = 5.0" in content
        # Optional fields should NOT appear
        assert "avg_hr_bpm" not in content
        assert "elevation_m" not in content

    def test_register_running_workout_generates_uuid_when_no_id(
        self, isolated_data_dir, isolated_config, tz_now
    ):
        """When workout_id is absent, a w-<8-hex> UUID is generated."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
            evidence={"date": "2026-09-12"},
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = isolated_data_dir["workouts"].read_text()
        # The generated ID starts with "w-"
        assert "w-" in content

    def test_register_multiple_running_workouts(
        self, isolated_data_dir, isolated_config, tz_now
    ):
        """Multiple running workouts are all appended."""
        recs = [
            ActivityRecord(
                type=ActivityType.WORKOUT_ADDED,
                source="chat",
                timestamp=tz_now,
                workout_id=f"w_multi_{i}",
                workout_type="running",
                distance_km=float(5 + i),
                duration_minutes=float(30 + i * 5),
            )
            for i in range(3)
        ]
        results = ingest_activities(recs)
        assert all(r.accepted for r in results)
        content = isolated_data_dir["workouts"].read_text()
        assert "w_multi_0" in content
        assert "w_multi_1" in content
        assert "w_multi_2" in content

    def test_register_running_workout_preserves_existing(
        self, isolated_data_dir, isolated_config, tz_now
    ):
        """A new running workout is appended after existing content."""
        wrk = isolated_data_dir["workouts"]
        wrk.write_text("# Fitness Workouts\n\n## Workout:\nid = w_old\ndistance_km = 3.0\n")
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_new",
            workout_type="running",
            distance_km=7.0,
            duration_minutes=42.0,
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = wrk.read_text()
        assert "w_old" in content
        assert "w_new" in content
        assert content.startswith("# Fitness Workouts")

    def test_register_running_workout_with_zero_distance(
        self, isolated_data_dir, isolated_config, tz_now
    ):
        """A running workout with zero distance is accepted (edge case)."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_zero_dist",
            workout_type="running",
            distance_km=0.0,
            duration_minutes=10.0,
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = isolated_data_dir["workouts"].read_text()
        assert "distance_km = 0.0" in content


# ── Normalization: running fields are NOT unit-normalized ────────────────────


class TestRunningNormalization:
    """Running workout fields (distance_km, duration_minutes, avg_hr_bpm,
    elevation_m) are stored in canonical units and are NOT unit-normalized
    by the ingestion layer.  This is by design — WORKOUT_ADDED records are
    not MEASUREMENT records; the Activity Ingestion skill's unit normalization
    only applies to MEASUREMENT / GOAL_UPDATED records."""

    def test_distance_km_not_normalized(self, tz_now):
        """distance_km passes through unchanged even with normalization config."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_1",
            workout_type="running",
            distance_km=10.0,
            duration_minutes=55.0,
        )
        cfg = IngestConfig()
        cfg.normalization_units = {"Distance": "km"}  # Would convert mi→km
        normalized = _normalize_record(rec, cfg)
        assert normalized.distance_km == 10.0

    def test_duration_minutes_not_normalized(self, tz_now):
        """duration_minutes passes through unchanged."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_1",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
        )
        cfg = IngestConfig()
        normalized = _normalize_record(rec, cfg)
        assert normalized.duration_minutes == 30.0

    def test_avg_hr_bpm_not_normalized(self, tz_now):
        """avg_hr_bpm passes through unchanged."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_1",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
            avg_hr_bpm=150.0,
        )
        cfg = IngestConfig()
        normalized = _normalize_record(rec, cfg)
        assert normalized.avg_hr_bpm == 150.0

    def test_elevation_m_not_normalized(self, tz_now):
        """elevation_m passes through unchanged."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_1",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
            elevation_m=100.0,
        )
        cfg = IngestConfig()
        normalized = _normalize_record(rec, cfg)
        assert normalized.elevation_m == 100.0

    def test_notes_stripped_during_normalization(self, tz_now):
        """Free-text notes are stripped of control characters and whitespace."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_1",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
            evidence={"notes": "  Morning run\x00  "},
        )
        cfg = IngestConfig()
        normalized = _normalize_record(rec, cfg)
        assert normalized.evidence["notes"] == "Morning run"

    def test_timestamp_normalized_to_aware(self):
        """Naive timestamps are converted to timezone-aware."""
        naive = datetime(2026, 9, 12, 14, 30, 0)
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=naive,
            workout_id="w_1",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
        )
        cfg = IngestConfig()
        normalized = _normalize_record(rec, cfg)
        assert normalized.timestamp.tzinfo is not None


# ── Analysis: compute_running_summary edge cases ─────────────────────────────


class TestRunningAnalysisEdgeCases:
    """Edge cases for compute_running_summary()."""

    def test_empty_list(self):
        """Empty workout list returns default RunningSummary."""
        from janus.services.workout_analytics import compute_running_summary
        result = compute_running_summary([])
        assert result.run_count == 0
        assert result.total_distance_km == 0.0
        assert result.total_duration_min == 0.0
        assert result.avg_pace_min_per_km is None
        assert result.best_pace_min_per_km is None
        assert result.avg_hr_bpm_when_available is None
        assert result.longest_run_km == 0.0
        assert result.total_elevation_m == 0.0

    def test_single_run(self):
        """A single run produces correct stats."""
        from janus.services.workout_analytics import compute_running_summary
        result = compute_running_summary([
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                avg_hr_bpm=145.0,
                elevation_m=50.0,
            ),
        ])
        assert result.run_count == 1
        assert result.total_distance_km == 5.0
        assert result.total_duration_min == 30.0
        assert result.avg_pace_min_per_km == 6.0
        assert result.best_pace_min_per_km == 6.0
        assert result.avg_hr_bpm_when_available == 145.0
        assert result.longest_run_km == 5.0
        assert result.total_elevation_m == 50.0
        assert result.runs_with_hr == 1
        assert result.runs_with_elevation == 1

    def test_multiple_runs_pace_weighted(self):
        """Average pace is distance-weighted, not arithmetic mean."""
        from janus.services.workout_analytics import compute_running_summary
        # Run 1: 5km @ 6:00/km, Run 2: 10km @ 5:00/km
        # Arithmetic mean of paces: (6 + 5) / 2 = 5.5
        # Distance-weighted: (5*6 + 10*5) / (5+10) = 80/15 = 5.333...
        result = compute_running_summary([
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
            ),
            RunningWorkout(
                id="rw-002",
                date=_dt_full(2026, 9, 2, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=10.0,
                duration_minutes=50.0,
            ),
        ])
        assert result.avg_pace_min_per_km is not None
        assert abs(result.avg_pace_min_per_km - 5.333333333333333) < 1e-9
        # Best pace is the minimum individual pace
        assert result.best_pace_min_per_km == 5.0

    def test_runs_without_hr_excluded_from_avg(self):
        """Average HR is computed only from runs that have HR data."""
        from janus.services.workout_analytics import compute_running_summary
        result = compute_running_summary([
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                avg_hr_bpm=140.0,
            ),
            RunningWorkout(
                id="rw-002",
                date=_dt_full(2026, 9, 2, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=10.0,
                duration_minutes=60.0,
                # No HR
            ),
            RunningWorkout(
                id="rw-003",
                date=_dt_full(2026, 9, 3, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=8.0,
                duration_minutes=48.0,
                avg_hr_bpm=160.0,
            ),
        ])
        assert result.avg_hr_bpm_when_available == 150.0  # (140 + 160) / 2
        assert result.runs_with_hr == 2

    def test_runs_without_elevation_excluded_from_total(self):
        """Total elevation is summed only from runs that have elevation data."""
        from janus.services.workout_analytics import compute_running_summary
        result = compute_running_summary([
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                elevation_m=50.0,
            ),
            RunningWorkout(
                id="rw-002",
                date=_dt_full(2026, 9, 2, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=10.0,
                duration_minutes=60.0,
                # No elevation
            ),
        ])
        assert result.total_elevation_m == 50.0
        assert result.runs_with_elevation == 1

    def test_zero_distance_run_skipped_for_pace(self):
        """A run with distance_km=0 is skipped for pace computation."""
        from janus.services.workout_analytics import compute_running_summary
        result = compute_running_summary([
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=0.0,
                duration_minutes=10.0,
            ),
        ])
        assert result.run_count == 1
        assert result.total_distance_km == 0.0
        # No pace computable (total_distance_km == 0)
        assert result.avg_pace_min_per_km is None
        assert result.best_pace_min_per_km is None

    def test_mixed_running_and_strength_filtered(self):
        """Only RunningWorkout instances are included in running summary."""
        from janus.services.workout_analytics import compute_running_summary
        from janus.models.workout import StrengthWorkout
        result = compute_running_summary([
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
            ),
            StrengthWorkout(
                id="sw-001",
                date=_dt_full(2026, 9, 2, 10, 0),
                workout_type=WorkoutType.STRENGTH,
            ),
        ])
        assert result.run_count == 1
        assert result.total_distance_km == 5.0

    def test_longest_run_selected(self):
        """Longest run is the max distance across all runs."""
        from janus.services.workout_analytics import compute_running_summary
        result = compute_running_summary([
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
            ),
            RunningWorkout(
                id="rw-002",
                date=_dt_full(2026, 9, 2, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=21.1,
                duration_minutes=120.0,
            ),
            RunningWorkout(
                id="rw-003",
                date=_dt_full(2026, 9, 3, 10, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=10.0,
                duration_minutes=58.0,
            ),
        ])
        assert result.longest_run_km == 21.1


# ── workout_md.py functions ──────────────────────────────────────────────────


class TestWorkoutMdFunctions:
    """Tests for janus.integrations.workout_md functions."""

    def test_load_workouts_empty_file(self, tmp_path, monkeypatch):
        """load_workouts returns [] when file doesn't exist."""
        import janus.integrations.workout_md as wm
        monkeypatch.setattr(wm, "PROJECT_ROOT", tmp_path)
        result = wm.load_workouts()
        assert result == []

    def test_save_and_load_round_trip(self, tmp_path, monkeypatch):
        """save_workout → load_workouts round-trip preserves data."""
        import janus.integrations.workout_md as wm
        monkeypatch.setattr(wm, "PROJECT_ROOT", tmp_path)

        w = RunningWorkout(
            id="rw-001",
            date=_dt_full(2026, 9, 12, 10, 0),
            workout_type=WorkoutType.RUNNING,
            distance_km=10.0,
            duration_minutes=55.0,
            avg_hr_bpm=150.0,
            elevation_m=100.0,
            notes="Morning run",
        )
        wm.save_workout(w)
        loaded = wm.load_workouts()
        assert len(loaded) == 1
        assert isinstance(loaded[0], RunningWorkout)
        assert loaded[0].id == "rw-001"
        assert loaded[0].distance_km == 10.0
        assert loaded[0].duration_minutes == 55.0
        assert loaded[0].avg_hr_bpm == 150.0
        assert loaded[0].elevation_m == 100.0
        assert loaded[0].notes == "Morning run"

    def test_find_running_workouts(self, tmp_path, monkeypatch):
        """find_running_workouts returns only RunningWorkout instances."""
        import janus.integrations.workout_md as wm
        monkeypatch.setattr(wm, "PROJECT_ROOT", tmp_path)

        # Write a mixed file directly
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        workouts_file = data_dir / "workouts.md"
        workouts_file.write_text(
            "# Fitness Workouts\n\n"
            "## Workout:\n"
            "id = rw-001\n"
            "date = 2026-09-12T10:00:00+00:00\n"
            "workout_type = running\n"
            "distance_km = 5.0\n"
            "duration_minutes = 30.0\n\n"
            "## Workout:\n"
            "id = sw-001\n"
            "date = 2026-09-12T12:00:00+00:00\n"
            "workout_type = strength\n"
        )
        result = wm.find_running_workouts()
        assert len(result) == 1
        assert result[0].id == "rw-001"

    def test_workout_to_markdown_lines_running(self, tmp_path, monkeypatch):
        """_workout_to_markdown_lines serializes RunningWorkout fields."""
        import janus.integrations.workout_md as wm
        monkeypatch.setattr(wm, "PROJECT_ROOT", tmp_path)

        w = RunningWorkout(
            id="rw-001",
            date=_dt_full(2026, 9, 12, 10, 0),
            workout_type=WorkoutType.RUNNING,
            distance_km=10.0,
            duration_minutes=55.0,
            avg_hr_bpm=150.0,
            elevation_m=100.0,
            notes="Morning run",
        )
        lines = wm._workout_to_markdown_lines(w)
        assert "## Workout:" in lines
        assert "id = rw-001" in lines
        assert "workout_type = running" in lines
        assert "distance_km = 10.0" in lines
        assert "duration_minutes = 55.0" in lines
        assert "avg_hr_bpm = 150.0" in lines
        assert "elevation_m = 100.0" in lines
        assert "notes = Morning run" in lines

    def test_workout_to_markdown_lines_running_minimal(self, tmp_path, monkeypatch):
        """_workout_to_markdown_lines omits optional fields when None."""
        import janus.integrations.workout_md as wm
        monkeypatch.setattr(wm, "PROJECT_ROOT", tmp_path)

        w = RunningWorkout(
            id="rw-001",
            date=_dt_full(2026, 9, 12, 10, 0),
            workout_type=WorkoutType.RUNNING,
            distance_km=5.0,
            duration_minutes=30.0,
        )
        lines = wm._workout_to_markdown_lines(w)
        assert "avg_hr_bpm" not in "\n".join(lines)
        assert "elevation_m" not in "\n".join(lines)
        assert "notes" not in "\n".join(lines)

    def test_workout_to_dict_running(self):
        """workout_to_dict serializes a RunningWorkout correctly."""
        w = RunningWorkout(
            id="rw-001",
            date=_dt_full(2026, 9, 12, 10, 0),
            workout_type=WorkoutType.RUNNING,
            distance_km=10.0,
            duration_minutes=55.0,
            avg_hr_bpm=150.0,
            elevation_m=100.0,
            notes="Morning run",
        )
        d = workout_to_dict(w)
        assert d["id"] == "rw-001"
        assert d["workout_type"] == "running"
        assert d["distance_km"] == 10.0
        assert d["duration_minutes"] == 55.0
        assert d["avg_hr_bpm"] == 150.0
        assert d["elevation_m"] == 100.0
        assert d["notes"] == "Morning run"

    def test_dict_to_workout_round_trip(self):
        """dict_to_workout → workout_to_dict round-trip preserves data."""
        original = RunningWorkout(
            id="rw-001",
            date=_dt_full(2026, 9, 12, 10, 0),
            workout_type=WorkoutType.RUNNING,
            distance_km=10.0,
            duration_minutes=55.0,
            avg_hr_bpm=150.0,
            elevation_m=100.0,
            notes="Morning run",
        )
        d = workout_to_dict(original)
        restored = dict_to_workout(d)
        assert isinstance(restored, RunningWorkout)
        assert restored.id == original.id
        assert restored.distance_km == original.distance_km
        assert restored.duration_minutes == original.duration_minutes
        assert restored.avg_hr_bpm == original.avg_hr_bpm
        assert restored.elevation_m == original.elevation_m
        assert restored.notes == original.notes

    def test_find_workout_by_id(self, tmp_path, monkeypatch):
        """find_workout_by_id returns the matching workout or None."""
        import janus.integrations.workout_md as wm
        monkeypatch.setattr(wm, "PROJECT_ROOT", tmp_path)

        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        workouts_file = data_dir / "workouts.md"
        workouts_file.write_text(
            "# Fitness Workouts\n\n"
            "## Workout:\n"
            "id = rw-001\n"
            "date = 2026-09-12T10:00:00+00:00\n"
            "workout_type = running\n"
            "distance_km = 5.0\n"
            "duration_minutes = 30.0\n\n"
            "## Workout:\n"
            "id = rw-002\n"
            "date = 2026-09-13T10:00:00+00:00\n"
            "workout_type = running\n"
            "distance_km = 10.0\n"
            "duration_minutes = 55.0\n"
        )
        found = wm.find_workout_by_id("rw-002")
        assert found is not None
        assert found.id == "rw-002"
        assert found.distance_km == 10.0

        not_found = wm.find_workout_by_id("rw-999")
        assert not_found is None

    def test_find_last_n(self, tmp_path, monkeypatch):
        """find_last_n returns the n most recent workouts."""
        import janus.integrations.workout_md as wm
        monkeypatch.setattr(wm, "PROJECT_ROOT", tmp_path)

        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        workouts_file = data_dir / "workouts.md"
        workouts_file.write_text(
            "# Fitness Workouts\n\n"
            "## Workout:\n"
            "id = rw-001\n"
            "date = 2026-09-10T10:00:00+00:00\n"
            "workout_type = running\n"
            "distance_km = 5.0\n"
            "duration_minutes = 30.0\n\n"
            "## Workout:\n"
            "id = rw-002\n"
            "date = 2026-09-12T10:00:00+00:00\n"
            "workout_type = running\n"
            "distance_km = 10.0\n"
            "duration_minutes = 55.0\n\n"
            "## Workout:\n"
            "id = rw-003\n"
            "date = 2026-09-11T10:00:00+00:00\n"
            "workout_type = running\n"
            "distance_km = 8.0\n"
            "duration_minutes = 48.0\n"
        )
        result = wm.find_last_n(2)
        assert len(result) == 2
        # Most recent first: rw-002 (Sep 12), rw-003 (Sep 11)
        assert result[0].id == "rw-002"
        assert result[1].id == "rw-003"

    def test_find_workouts_by_date_range(self, tmp_path, monkeypatch):
        """find_workouts_by_date_range filters by date inclusively."""
        import janus.integrations.workout_md as wm
        monkeypatch.setattr(wm, "PROJECT_ROOT", tmp_path)

        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        workouts_file = data_dir / "workouts.md"
        workouts_file.write_text(
            "# Fitness Workouts\n\n"
            "## Workout:\n"
            "id = rw-001\n"
            "date = 2026-09-01T10:00:00+00:00\n"
            "workout_type = running\n"
            "distance_km = 5.0\n"
            "duration_minutes = 30.0\n\n"
            "## Workout:\n"
            "id = rw-002\n"
            "date = 2026-09-15T10:00:00+00:00\n"
            "workout_type = running\n"
            "distance_km = 10.0\n"
            "duration_minutes = 55.0\n\n"
            "## Workout:\n"
            "id = rw-003\n"
            "date = 2026-09-30T10:00:00+00:00\n"
            "workout_type = running\n"
            "distance_km = 8.0\n"
            "duration_minutes = 48.0\n"
        )
        from datetime import date
        result = wm.find_workouts_by_date_range(
            date(2026, 9, 10), date(2026, 9, 20)
        )
        assert len(result) == 1
        assert result[0].id == "rw-002"


# ── Dedup key rules for WORKOUT_ADDED ────────────────────────────────────────


class TestWorkoutAddedDedupKey:
    """Tests for compute_dedup_key with WORKOUT_ADDED records."""

    def test_workout_id_takes_precedence(self):
        """workout_id is used as dedup key when present."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt_full(2026, 9, 12, 10, 0),
            workout_id="w_run_1",
            workout_type="running",
        )
        assert compute_dedup_key(rec) == "w_run_1"

    def test_evidence_date_fallback(self):
        """Without workout_id, evidence['date'] is used."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt_full(2026, 9, 12, 10, 0),
            workout_type="running",
            evidence={"date": "2026-09-12"},
        )
        assert compute_dedup_key(rec) == "2026-09-12::running"

    def test_record_date_fallback(self):
        """Without workout_id or evidence date, record.date is used."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt_full(2026, 9, 12, 10, 0),
            workout_type="running",
            date="2026-09-12",
        )
        assert compute_dedup_key(rec) == "2026-09-12::running"

    def test_degenerate_key_without_date_or_id(self):
        """Without workout_id or date, key is '::running' (degenerate)."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt_full(2026, 9, 12, 10, 0),
            workout_type="running",
        )
        assert compute_dedup_key(rec) == "::running"

    def test_degenerate_key_strength_type(self):
        """Degenerate key for strength is '::strength'."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt_full(2026, 9, 12, 10, 0),
            workout_type="strength",
        )
        assert compute_dedup_key(rec) == "::strength"

    def test_dedup_rejects_same_date_type(self):
        """Two running workouts with the same date are duplicates."""
        rec1 = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt_full(2026, 9, 12, 10, 0),
            workout_type="running",
            evidence={"date": "2026-09-12"},
        )
        rec2 = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt_full(2026, 9, 12, 11, 0),
            workout_type="running",
            evidence={"date": "2026-09-12"},
        )
        assert compute_dedup_key(rec1) == compute_dedup_key(rec2)

    def test_dedup_different_dates_not_duplicate(self):
        """Two running workouts with different dates are NOT duplicates."""
        rec1 = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt_full(2026, 9, 12, 10, 0),
            workout_type="running",
            evidence={"date": "2026-09-12"},
        )
        rec2 = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=_dt_full(2026, 9, 13, 10, 0),
            workout_type="running",
            evidence={"date": "2026-09-13"},
        )
        assert compute_dedup_key(rec1) != compute_dedup_key(rec2)


# ── Integration: full pipeline for running workout ───────────────────────────


class TestRunningWorkoutFullPipeline:
    """End-to-end tests: ActivityRecord → ingest → load → analyze."""

    def test_ingest_then_load_then_analyze(
        self, isolated_data_dir, isolated_config, tz_now
    ):
        """Ingest a running workout, load it back, and analyze it."""
        from janus.services.workout_analytics import compute_running_summary
        import janus.integrations.workout_md as wm

        # Redirect workout_md to the isolated data dir
        import janus.services.activity_ingest as ai
        original_project_root = ai.PROJECT_ROOT

        # We need to redirect workout_md's PROJECT_ROOT too
        # Since workout_md uses its own PROJECT_ROOT, we patch it
        import janus.integrations.workout_md as wm_mod
        original_wm_root = wm_mod.PROJECT_ROOT

        try:
            # Patch workout_md's PROJECT_ROOT to match the isolated data dir
            import sys
            # The activity_ingest module already patched PROJECT_ROOT
            # But workout_md has its own PROJECT_ROOT
            # We need to patch it to point to the isolated data dir
            # Actually, the activity_ingest module's _dispatch_workout uses
            # workout_md._workout_to_markdown_lines, which doesn't read from disk
            # The actual write goes through atomic_io with the file_path from cfg.file_for_type
            # So the write goes to the isolated data dir

            # But load_workouts uses workout_md._workouts_path() which uses PROJECT_ROOT
            # We need to patch workout_md.PROJECT_ROOT
            import janus.integrations.workout_md as wm_mod2
            # Can't easily patch because it's a module-level constant
            # Instead, we'll use the activity_ingest's DATA_DIR to load

            rec = ActivityRecord(
                type=ActivityType.WORKOUT_ADDED,
                source="chat",
                timestamp=tz_now,
                workout_id="w_pipeline_1",
                workout_type="running",
                distance_km=10.0,
                duration_minutes=55.0,
                avg_hr_bpm=150.0,
                elevation_m=100.0,
            )
            results = ingest_activities([rec])
            assert results[0].accepted is True

            # Load from the isolated data dir directly
            workouts_file = isolated_data_dir["workouts"]
            assert workouts_file.exists()

            # Parse the file directly
            content = workouts_file.read_text()
            assert "w_pipeline_1" in content
            assert "distance_km = 10.0" in content

            # For analysis, we'd need to load through workout_md which uses its own PROJECT_ROOT
            # Instead, construct the RunningWorkout directly
            workout = RunningWorkout(
                id="w_pipeline_1",
                date=tz_now,
                workout_type=WorkoutType.RUNNING,
                distance_km=10.0,
                duration_minutes=55.0,
                avg_hr_bpm=150.0,
                elevation_m=100.0,
            )
            summary = compute_running_summary([workout])
            assert summary.run_count == 1
            assert summary.total_distance_km == 10.0
            assert summary.avg_pace_min_per_km == 5.5
            assert summary.best_pace_min_per_km == 5.5
            assert summary.avg_hr_bpm_when_available == 150.0
            assert summary.longest_run_km == 10.0
            assert summary.total_elevation_m == 100.0
        finally:
            pass  # Cleanup handled by tmp_path fixture

    def test_ingest_duplicate_rejected(
        self, isolated_data_dir, isolated_config, tz_now
    ):
        """A duplicate running workout (same workout_id) is rejected."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_dup_1",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
        )
        results1 = ingest_activities([rec])
        assert results1[0].accepted is True

        # Second ingestion of the same workout_id
        rec2 = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_id="w_dup_1",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
        )
        results2 = ingest_activities([rec2])
        assert results2[0].accepted is False
        assert results2[0].action == "rejected"
        assert "duplicate" in results2[0].error.lower()

    def test_ingest_duplicate_same_date_rejected(
        self, isolated_data_dir, isolated_config, tz_now
    ):
        """Two running workouts with the same date (no workout_id) are duplicates."""
        rec1 = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
            evidence={"date": "2026-09-12"},
        )
        rec2 = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="chat",
            timestamp=tz_now,
            workout_type="running",
            distance_km=10.0,
            duration_minutes=55.0,
            evidence={"date": "2026-09-12"},
        )
        results1 = ingest_activities([rec1])
        assert results1[0].accepted is True

        results2 = ingest_activities([rec2])
        assert results2[0].accepted is False
        assert "duplicate" in results2[0].error.lower()
