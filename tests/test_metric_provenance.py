"""Tests for metric update-source provenance and task-to-metric precedence rules.

Covers the acceptance criteria from
``docs/research-findings/manual_metric_update_preservation_spec.md`` (§12) and
``docs/research-findings/task_to_metric_mapping_rules.md``:

- §12.1 Precedence (manual protects within 24h; measurement/import always win)
- §12.2 Provenance metadata (last_value_source / _updated_at / _task_id)
- §12.3 Snapshot audit trail (accepted mutations append; rejected/idempotent don't)
- §12.4 Conflict handling (recent_activity still recorded on rejection)
- §12.5 Edge cases (retry after manual; multi-metric; no-metric goal)
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from janus.models.goal import Goal
from janus.models.metric_type import (
    MetricSource,
    MANUAL_VALUE_PROTECTION_WINDOW_HOURS,
)
from janus.services.goals import (
    add_goal,
    get_goal,
    update_goal_fields,
    update_goal_progress,
    _apply_metric_value,
    _protection_window_expired,
    _values_equal,
)


# ── fixtures ───────────────────────────────────────────────────────────────────

def _write_goals(tmp_path, content):
    p = tmp_path / "goals.md"
    p.write_text(content)
    return p


def _setup(tmp_path, monkeypatch, content="# Goals\n"):
    gf = _write_goals(tmp_path, content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", gf)
    mh = tmp_path / "metric_history.md"
    monkeypatch.setattr("janus.integrations.metric_history.METRIC_HISTORY_PATH", mh)
    return gf


_METRIC_GOAL = (
    "# Goals\n\n"
    "## Goal: Weight\n"
    "Status: active\n"
    "Metric: Weight\n"
    "Unit: kg\n"
    "Start: 80\n"
    "Current: 78\n"
    "Target: 70\n"
    "Direction: decrease\n"
)


def _seed_metric_goal(tmp_path, monkeypatch):
    return _setup(tmp_path, monkeypatch, _METRIC_GOAL)


# ── provenance on update_goal_fields (§12.2) ──────────────────────────────────

class TestManualProvenance:
    def test_current_value_sets_manual_provenance(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        g = update_goal_fields("Weight", current_value=76.5)
        assert g.last_value_source == MetricSource.MANUAL
        assert g.last_value_updated_at is not None
        assert g.last_value_task_id is None

    def test_manual_provenance_roundtrips_through_file(self, tmp_path, monkeypatch):
        gf = _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=76.5)
        content = gf.read_text()
        assert "LastValueSource: manual" in content
        assert "LastValueUpdatedAt:" in content
        # task_id must NOT be written for manual source
        assert "LastValueTaskId:" not in content

    def test_no_provenance_when_no_current_value(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        g = update_goal_fields("Weight", description="new")
        assert g.last_value_source is None
        assert g.last_value_task_id is None

    def test_manual_update_overwrites_previous_manual(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=76.0)
        update_goal_fields("Weight", current_value=75.0)
        g = get_goal("Weight")
        assert g.current_value == 75.0
        assert g.last_value_source == MetricSource.MANUAL


# ── task_derived provenance + snapshot (§12.2/§12.3) ─────────────────────────

class TestTaskDerivedProvenance:
    def test_task_completion_sets_task_derived_provenance(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {"completed_at": "2026-09-09", "current_value": 76.5}
        g = update_goal_progress("Weight", "t_1", "Diet plan", evidence)
        assert g.current_value == 76.5
        assert g.last_value_source == MetricSource.TASK_DERIVED
        assert g.last_value_task_id == "t_1"
        assert g.last_value_updated_at is not None

    def test_task_completion_appends_task_derived_snapshot(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        from janus.integrations.metric_history import get_metric_snapshots
        evidence = {"completed_at": "2026-09-09", "current_value": 76.5}
        update_goal_progress("Weight", "t_1", "Diet plan", evidence)
        snaps = get_metric_snapshots("Weight")
        assert len(snaps) == 1
        assert snaps[0].source == MetricSource.TASK_DERIVED
        assert snaps[0].value == 76.5

    def test_metric_updates_list_appends_matching_metric(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        from janus.integrations.metric_history import get_metric_snapshots
        evidence = {
            "completed_at": "2026-09-09",
            "metric_updates": [
                {"metric_name": "Weight", "value": 75.0, "unit": "kg"},
                {"metric_name": "Body fat", "value": 20.0},  # mismatch → skipped
            ],
        }
        g = update_goal_progress("Weight", "t_1", "Diet", evidence)
        assert g.current_value == 75.0
        snaps = get_metric_snapshots("Weight")
        assert len(snaps) == 1
        assert snaps[0].value == 75.0
        # last_value_task_id set by the task_derived source
        assert g.last_value_task_id == "t_1"


# ── Precedence matrix (§12.1) ──────────────────────────────────────────────────

class TestPrecedence:
    def test_task_derived_rejected_within_protection_window(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        # Manual update sets provenance + protection window start.
        update_goal_fields("Weight", current_value=77.0)
        g_before = get_goal("Weight")
        assert g_before.current_value == 77.0
        # Task completion moments later → rejected.
        evidence = {"completed_at": "2026-09-09"}
        g = update_goal_progress("Weight", "t_1", "Task", evidence)
        assert g.current_value == 77.0  # unchanged
        assert g.last_value_source == MetricSource.MANUAL

    def test_task_derived_accepted_after_protection_window(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        # Plant a manual update with a stale timestamp (outside window).
        from janus.services.goals import update_goal
        g = get_goal("Weight")
        g.current_value = 77.0
        g.last_value_source = str(MetricSource.MANUAL)
        g.last_value_updated_at = (
            datetime.now(timezone.utc) - timedelta(hours=MANUAL_VALUE_PROTECTION_WINDOW_HOURS + 1)
        ).isoformat()
        update_goal(g)
        evidence = {"completed_at": "2026-09-09", "current_value": 76.0}
        g2 = update_goal_progress("Weight", "t_1", "Task", evidence)
        assert g2.current_value == 76.0
        assert g2.last_value_source == MetricSource.TASK_DERIVED

    def test_measurement_always_accepted(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        # Plant a manual update (protected).
        update_goal_fields("Weight", current_value=77.0)
        g = get_goal("Weight")
        assert g.last_value_source == MetricSource.MANUAL
        # Measurement should overwrite the protected manual value.
        new_val, reason = _apply_metric_value(
            g, 70.0, MetricSource.MEASUREMENT, task_id=None
        )
        assert reason is None
        assert g.current_value == 70.0
        assert g.last_value_source == MetricSource.MEASUREMENT
        assert g.last_value_task_id is None

    def test_import_always_accepted(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)
        g = get_goal("Weight")
        new_val, reason = _apply_metric_value(
            g, 50.0, MetricSource.IMPORT, task_id=None
        )
        assert reason is None
        assert g.current_value == 50.0
        assert g.last_value_source == MetricSource.IMPORT


# ── Idempotency (§6.1) ──────────────────────────────────────────────────────

class TestIdempotency:
    def test_same_value_is_noop(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)
        update_at_count = get_goal("Weight").last_value_updated_at
        # Apply same value via task_derived → idempotent, no overwrite.
        evidence = {"completed_at": "2026-09-09", "current_value": 77.0}
        g = update_goal_progress("Weight", "t_1", "Task", evidence)
        assert g.current_value == 77.0
        assert g.last_value_updated_at == update_at_count
        assert g.last_value_source == MetricSource.MANUAL

    def test_values_equal_helper(self):
        assert _values_equal(1.0, 1.0)
        assert _values_equal(1.0, 1.0 + 1e-12)
        assert not _values_equal(1.0, 2.0)
        assert not _values_equal(None, 1.0)
        assert _values_equal(None, None)


# ── Conflict handling (§12.4): activity still recorded on rejection ─────────

class TestConflictActivityRecorded:
    def test_recent_activity_recorded_on_rejected_overwrite(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)
        # Task completes but its value is rejected by protection window.
        evidence = {
            "completed_at": "2026-09-09",
            "current_value": 76.0,
            "pr_url": "https://example.com/pr/1",
        }
        g = update_goal_progress("Weight", "t_reject", "Rejected task", evidence)
        # current_value NOT overwritten
        assert g.current_value == 77.0
        assert g.last_value_source == MetricSource.MANUAL
        # ...but the activity is still recorded
        assert g.recent_activity is not None
        assert len(g.recent_activity) == 1
        assert g.recent_activity[0]["task_id"] == "t_reject"
        assert g.recent_activity[0]["summary"] == "Rejected task"


# ── Edge cases (§12.5) ──────────────────────────────────────────────────────

class TestEdgeCases:
    def test_goal_without_metric_no_snapshot(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch,
               "# Goals\n\n## Goal: NoMetric\nStatus: active\n")
        from janus.integrations.metric_history import get_metric_snapshots
        evidence = {"completed_at": "2026-09-09", "current_value": 42.0}
        update_goal_progress("NoMetric", "t_1", "Task", evidence)
        assert not Path(tmp_path, "metric_history.md").exists()
        assert get_metric_snapshots("NoMetric") == []

    def test_metric_mismatch_silently_skipped(self, tmp_path, monkeypatch):
        _seed_metric_goal(tmp_path, monkeypatch)
        # Goal metric is "Weight"; evidence targets a different metric.
        evidence = {"metric_updates": [{"metric_name": "Body fat", "value": 20.0}]}
        g = update_goal_progress("Weight", "t_1", "Task", evidence)
        assert g.current_value == 78.0  # unchanged (seeded 78)

    def test_protection_window_expired_helper(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, _METRIC_GOAL)
        g = get_goal("Weight")
        g.last_value_source = str(MetricSource.MANUAL)
        g.last_value_updated_at = None
        assert _protection_window_expired(g) is True
        # Fresh timestamp → protected
        g.last_value_updated_at = datetime.now(timezone.utc).isoformat()
        assert _protection_window_expired(g) is False
        # Stale timestamp → expired
        g.last_value_updated_at = (
            datetime.now(timezone.utc)
            - timedelta(hours=MANUAL_VALUE_PROTECTION_WINDOW_HOURS + 1)
        ).isoformat()
        assert _protection_window_expired(g) is True


# ── Measurement dispatch propagates to goal (§4.3) ────────────────────────────

class TestMeasurementDispatch:
    def test_measurement_updates_goal_current_value(self, tmp_path, monkeypatch):
        from janus.services.activity_ingest import ingest_activities, ActivityRecord, ActivityType
        _seed_metric_goal(tmp_path, monkeypatch)
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="measurement_runner",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight", metric="Weight", value=71.0, unit="kg",
            date="2026-09-12",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        g = get_goal("Weight")
        assert g.current_value == 71.0
        assert g.last_value_source == MetricSource.MEASUREMENT
        assert g.last_value_task_id is None

    def test_measurement_snapshot_source_is_measurement(self, tmp_path, monkeypatch):
        from janus.services.activity_ingest import ingest_activities, ActivityRecord, ActivityType
        from janus.integrations.metric_history import get_metric_snapshots
        _seed_metric_goal(tmp_path, monkeypatch)
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="measurement_runner",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight", metric="Weight", value=71.0, unit="kg",
            date="2026-09-12",
        )
        ingest_activities([rec])
        snaps = get_metric_snapshots("Weight")
        assert len(snaps) >= 1
        assert all(s.source == MetricSource.MEASUREMENT for s in snaps)

    def test_measurement_with_no_matching_metric_does_not_change_value(self, tmp_path, monkeypatch):
        from janus.services.activity_ingest import ingest_activities, ActivityRecord, ActivityType
        _seed_metric_goal(tmp_path, monkeypatch)
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="runner",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight", metric="Body fat", value=20.0, unit="%",
            date="2026-09-12",
        )
        ingest_activities([rec])
        g = get_goal("Weight")
        assert g.current_value == 78.0  # unchanged
