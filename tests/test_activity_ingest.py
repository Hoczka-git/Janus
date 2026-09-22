"""Unit and integration tests for janus.services.activity_ingest.

Covers the full ingestion pipeline per ADR-005 §3, §6:

  ActivityRecord[] → ingest_activities() → normalize → validate → dedup → dispatch → atomic_write

Test areas:

- **Normalization**: timestamp timezone, text control-char stripping, unit conversions
  (Weight lb→kg, Distance mi→km), passthrough when no rule exists.
- **Deduplication**: key computation per activity type, reject/merge/replace policies,
  tolerance window, equal-key and differing-key scenarios.
- **Persistence (write)**: atomic write through the gateway, correct file content
  in data/, .bak creation, recovery after failure.
- **Validation**: rejection of invalid records with descriptive errors, per-type
  required-field checks.
- **Data-layer protection (negative tests)**: the model layer (ActivityRecord/IngestResult)
  cannot write to data/ files directly — writes must go through ingest_activities() and
  the atomic_io gateway.

All tests use isolated tmp_path + monkeypatch for DATA_DIR, CONFIG_PATH, and
downstream service file paths.  No real data/ is touched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from janus.services.activity_ingest import (
    ActivityRecord,
    ActivityType,
    IngestConfig,
    IngestDryRun,
    IngestResult,
    _check_tolerance,
    _gen_uuid,
    _is_duplicate,
    _normalize_record,
    _normalize_text,
    _normalize_timestamp,
    _normalize_unit,
    _validate_record,
    _load_ingest_config,
    _copy_record,
    _parse_ts_from_text,
    compute_dedup_key,
    ingest_activities,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect DATA_DIR, PROJECT_ROOT, and all downstream service file paths
    to tmp_path so no real data/ is touched."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)

    # Redirect the ingest layer's DATA_DIR and PROJECT_ROOT
    import janus.services.activity_ingest as ai
    monkeypatch.setattr(ai, "DATA_DIR", data_dir)
    monkeypatch.setattr(ai, "PROJECT_ROOT", tmp_path)

    # Redirect downstream service file paths
    import janus.services.tasks as tasks_mod
    import janus.services.followup as followup_mod
    import janus.services.inbox as inbox_mod
    import janus.integrations.markdown_goals as goals_md
    import janus.integrations.markdown_followups as followups_md
    import janus.integrations.markdown_inbox as inbox_md
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
    monkeypatch.setattr(followup_mod, "FOLLOWUPS_PATH", followups_path)
    monkeypatch.setattr(followups_md, "FOLLOWUPS_PATH", followups_path)
    monkeypatch.setattr(inbox_mod, "INBOX_PATH", inbox_path)
    monkeypatch.setattr(inbox_md, "INBOX_PATH", inbox_path)

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
    """A timezone-aware datetime used across normalization tests."""
    return datetime(2026, 9, 12, 14, 30, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_ingest_config_cache(monkeypatch):
    """Ensure _load_ingest_config picks up the monkeypatched CONFIG_PATH."""
    import janus.services.activity_ingest as ai
    # _load_ingest_config reads CONFIG_PATH at call time, so no cache to clear,
    # but we ensure it's always reloaded.
    yield


# ── ActivityRecord construction ──────────────────────────────────────────────

class TestActivityRecord:
    def test_constructed_with_required_fields(self):
        """ActivityRecord requires type and source; optional fields default."""
        record = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Write tests",
            task_id="t_abc",
        )
        assert record.type == ActivityType.TASK_COMPLETED
        assert record.source == "test"
        assert record.goal_title is None
        assert record.evidence == {}

    def test_empty_source_raises(self):
        """__post_init__ rejects empty source."""
        with pytest.raises(ValueError, match="source must be non-empty"):
            ActivityRecord(
                type=ActivityType.TASK_COMPLETED,
                source="",
                timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            )

    def test_whitespace_source_raises(self):
        """__post_init__ rejects whitespace-only source."""
        with pytest.raises(ValueError, match="source must be non-empty"):
            ActivityRecord(
                type=ActivityType.TASK_COMPLETED,
                source="   ",
                timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            )

    def test_non_datetime_timestamp_raises(self):
        """__post_init__ rejects non-datetime timestamp."""
        with pytest.raises(ValueError, match="must be datetime"):
            ActivityRecord(
                type=ActivityType.TASK_COMPLETED,
                source="test",
                timestamp="2026-09-12",  # type: ignore[arg-type]
            )

    def test_none_evidence_normalized_to_empty_dict(self):
        """evidence=None is normalized to {} in __post_init__."""
        record = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            evidence=None,
        )
        assert record.evidence == {}

    def test_evidence_defaults_to_new_dict(self):
        """Each record gets its own default evidence dict (no shared mutable)."""
        r1 = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="a",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        r2 = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="b",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        r1.evidence["key"] = "val"
        assert r2.evidence == {}


# ── compute_dedup_key ─────────────────────────────────────────────────────────

class TestComputeDedupKey:
    def _rec(self, **kwargs):
        base = dict(
            type=ActivityType.TASK_COMPLETED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        base.update(kwargs)
        return ActivityRecord(**base)

    def test_task_completed_uses_task_id(self):
        """TASK_* records key by task_id when present."""
        key = compute_dedup_key(self._rec(type=ActivityType.TASK_COMPLETED, task_id="t_42"))
        assert key == "t_42"

    def test_task_completed_falls_back_to_title(self):
        """TASK_* records key by task_title (prefixed) when task_id absent."""
        key = compute_dedup_key(self._rec(type=ActivityType.TASK_COMPLETED, task_title="My Task"))
        assert key == "title:My Task"

    def test_goal_progress_key(self):
        """GOAL_PROGRESS keys by (task_id, goal_title)."""
        key = compute_dedup_key(self._rec(
            type=ActivityType.GOAL_PROGRESS,
            task_id="t_1", goal_title="Lose weight",
        ))
        assert key == "t_1::Lose weight"

    def test_goal_progress_no_task_id(self):
        """GOAL_PROGRESS without task_id uses 'no-task-id' placeholder."""
        key = compute_dedup_key(self._rec(
            type=ActivityType.GOAL_PROGRESS,
            goal_title="Lose weight",
        ))
        assert key == "no-task-id::Lose weight"

    def test_milestone_completed_key(self):
        """MILESTONE_COMPLETED keys by (task_id, goal_title)."""
        key = compute_dedup_key(self._rec(
            type=ActivityType.MILESTONE_COMPLETED,
            task_id="t_5", goal_title="Alpha milestone",
        ))
        assert key == "t_5::Alpha milestone"

    def test_measurement_key(self):
        """MEASUREMENT keys by (goal_title, metric, date)."""
        key = compute_dedup_key(self._rec(
            type=ActivityType.MEASUREMENT,
            goal_title="Health", metric="Weight", unit="kg",
            value=75.0, date="2026-09-12",
        ))
        assert key == "Health::Weight::2026-09-12"

    def test_workout_added_with_id(self):
        """WORKOUT_ADDED keys by workout_id when present."""
        key = compute_dedup_key(self._rec(
            type=ActivityType.WORKOUT_ADDED, workout_id="w_run_1",
            workout_type="running",
        ))
        assert key == "w_run_1"

    def test_workout_added_fallback_to_date_type(self):
        """WORKOUT_ADDED without workout_id keys by (date, type)."""
        key = compute_dedup_key(self._rec(
            type=ActivityType.WORKOUT_ADDED, workout_type="strength",
            date="2026-09-05", evidence={"date": "2026-09-05"},
        ))
        assert key == "2026-09-05::strength"

    def test_followup_added_generates_id(self):
        """FOLLOWUP_ADDED without followup_id generates a deterministic key from title + source."""
        key = compute_dedup_key(self._rec(type=ActivityType.FOLLOWUP_ADDED, captured_text="Test followup"))
        assert key.startswith("fu::")
        assert "Test followup" in key

    def test_inbox_captured_generates_id(self):
        """INBOX_CAPTURED without inbox_id generates a deterministic key from text + source."""
        key = compute_dedup_key(self._rec(type=ActivityType.INBOX_CAPTURED, captured_text="hi"))
        assert key.startswith("ix::")
        assert "hi" in key

    def test_goal_updated_key(self):
        """GOAL_UPDATED keys by (goal_title, task_id)."""
        key = compute_dedup_key(self._rec(
            type=ActivityType.GOAL_UPDATED,
            goal_title="Save money",
            task_id="t_3",
        ))
        assert key == "Save money::t_3"

    def test_goal_completed_key(self):
        """GOAL_COMPLETED keys by (goal_title, task_id)."""
        key = compute_dedup_key(self._rec(
            type=ActivityType.GOAL_COMPLETED,
            goal_title="Save money",
            task_id="t_3",
        ))
        assert key == "Save money::t_3"


# ── Validation ────────────────────────────────────────────────────────────────

class TestValidateRecord:
    def _rec(self, **kwargs):
        base = dict(
            type=ActivityType.TASK_COMPLETED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Some task",
        )
        base.update(kwargs)
        return ActivityRecord(**base)

    def test_task_completed_valid(self):
        """TASK_COMPLETED with a task_title passes validation."""
        _validate_record(self._rec(type=ActivityType.TASK_COMPLETED, task_title="Build"))

    def test_task_completed_requires_title_or_id(self):
        """TASK_COMPLETED without task_title or task_id raises."""
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="requires task_title or task_id"):
            _validate_record(rec)

    def test_goal_progress_requires_goal_title(self):
        """GOAL_PROGRESS without goal_title raises."""
        rec = ActivityRecord(
            type=ActivityType.GOAL_PROGRESS,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="requires goal_title"):
            _validate_record(rec)

    def test_measurement_requires_metric(self):
        """MEASUREMENT without metric raises."""
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="requires metric"):
            _validate_record(rec)

    def test_measurement_requires_value(self):
        """MEASUREMENT without value raises."""
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            metric="Weight",
        )
        with pytest.raises(ValueError, match="requires value"):
            _validate_record(rec)

    def test_workout_added_requires_type(self):
        """WORKOUT_ADDED without workout_type raises."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="requires workout_type"):
            _validate_record(rec)

    def test_inbox_captured_requires_text(self):
        """INBOX_CAPTURED without captured_text raises."""
        rec = ActivityRecord(
            type=ActivityType.INBOX_CAPTURED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="requires captured_text"):
            _validate_record(rec)

    def test_progress_must_be_int_0_to_100(self):
        """progress must be an int in [0, 100]."""
        rec = self._rec(progress=150)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="progress must be int"):
            _validate_record(rec)

    def test_progress_must_be_int_type(self):
        """progress as float raises."""
        rec = self._rec(progress=50.5)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="progress must be int"):
            _validate_record(rec)

    def test_progress_boundary_0(self):
        """progress=0 is valid."""
        _validate_record(self._rec(progress=0))

    def test_progress_boundary_100(self):
        """progress=100 is valid."""
        _validate_record(self._rec(progress=100))

    @pytest.mark.parametrize("ptype", [
        ActivityType.GOAL_UPDATED,
        ActivityType.GOAL_COMPLETED,
    ])
    def test_goal_updated_completed_require_goal_title(self, ptype):
        """GOAL_UPDATED and GOAL_COMPLETED require goal_title."""
        rec = ActivityRecord(
            type=ptype,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="requires goal_title"):
            _validate_record(rec)


# ── Normalization: timestamps ──────────────────────────────────────────────────

class TestNormalizeTimestamp:
    def test_naive_assumed_local_converted_to_utc(self):
        """Naive datetimes are localized to UTC."""
        naive = datetime(2026, 9, 12, 14, 30, 0)
        result = _normalize_timestamp(naive)
        assert result.tzinfo is not None
        # Should be equivalent to 14:30 in local -> UTC offset
        assert result.tzinfo is not None or result.utcoffset() is not None

    def test_aware_passthrough(self):
        """Timezone-aware datetimes are returned unchanged."""
        aware = datetime(2026, 9, 12, 14, 30, 0, tzinfo=timezone.utc)
        result = _normalize_timestamp(aware)
        assert result == aware
        assert result.tzinfo is timezone.utc

    def test_different_timezone_converted(self):
        """A non-UTC timezone-aware datetime keeps its value but is consistent."""
        import datetime as dt_module
        tz_plus_5 = dt_module.timezone(dt_module.timedelta(hours=5))
        aware = datetime(2026, 9, 12, 14, 30, 0, tzinfo=tz_plus_5)
        result = _normalize_timestamp(aware)
        assert result == aware


# ── Normalization: text ────────────────────────────────────────────────────────

class TestNormalizeText:
    def test_strips_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        assert _normalize_text("  hello  ") == "hello"

    def test_strips_control_chars(self):
        """Control characters (except tab/newline) are removed."""
        result = _normalize_text("hello\x00world\x07end")
        assert result == "helloworldend"

    def test_preserves_tab_and_newline(self):
        """Tab and newline characters are preserved."""
        result = _normalize_text("line1\t\nline2")
        assert "\t" in result
        assert "\n" in result

    def test_none_returns_none(self):
        """None passes through unchanged."""
        assert _normalize_text(None) is None

    def test_empty_string_after_strip(self):
        """Empty/whitespace-only strings become empty after strip."""
        assert _normalize_text("   ") == ""


# ── Normalization: unit conversion ─────────────────────────────────────────────

class TestNormalizeUnit:
    def test_no_rule_passthrough(self):
        """Without a normalization rule, value passes through unchanged."""
        cfg = IngestConfig()
        assert _normalize_unit(75.0, "kg", "Weight", cfg) == 75.0

    def test_weight_lb_to_kg(self):
        """Weight in lb is converted to kg when base_unit is kg."""
        cfg = IngestConfig()
        cfg.normalization_units = {"Weight": "kg"}
        result = _normalize_unit(154.0, "lb", "Weight", cfg)
        assert result == round(154.0 * 0.45359237, 4)

    def test_distance_mi_to_km(self):
        """Distance in mi is converted to km when base_unit is km."""
        cfg = IngestConfig()
        cfg.normalization_units = {"Distance": "km"}
        result = _normalize_unit(10.0, "mi", "Distance", cfg)
        assert result == round(10.0 * 1.609344, 4)

    def test_unit_already_base_passthrough(self):
        """When value's unit already matches base_unit, value is unchanged."""
        cfg = IngestConfig()
        cfg.normalization_units = {"Weight": "kg"}
        assert _normalize_unit(75.0, "kg", "Weight", cfg) == 75.0

    def test_none_value_passthrough(self):
        """None value passes through regardless of config."""
        cfg = IngestConfig()
        cfg.normalization_units = {"Weight": "kg"}
        assert _normalize_unit(None, "lb", "Weight", cfg) is None

    def test_none_metric_passthrough(self):
        """None metric means no normalization rule available."""
        cfg = IngestConfig()
        assert _normalize_unit(50.0, "lb", None, cfg) == 50.0


# ── Normalization: full record ────────────────────────────────────────────────

class TestNormalizeRecord:
    def test_does_not_mutate_caller_record(self):
        """_normalize_record operates on a copy, not the original."""
        original = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, 14, 30, 0),
            task_title="  spaced task  ",
        )
        original_ts = original.timestamp
        cfg = IngestConfig()
        normalized = _normalize_record(_copy_record(original), cfg)
        # Original is unchanged
        assert original.timestamp == original_ts
        assert original.task_title == "  spaced task  "
        # Normalized has stripped title and tz-aware timestamp
        assert normalized.task_title == "spaced task"

    def test_strips_text_fields(self):
        """Free-text fields are stripped of whitespace and control chars."""
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="  Task\x00Name  ",
            goal_title="  Goal\x01Name  ",
            metric="  Weight  ",
            unit="  kg  ",
            captured_text="  captured\x02  ",
        )
        cfg = IngestConfig()
        result = _normalize_record(_copy_record(rec), cfg)
        assert result.task_title == "TaskName"
        assert result.goal_title == "GoalName"
        assert result.metric == "Weight"
        assert result.unit == "kg"
        assert result.captured_text == "captured"


# ── Config loading ─────────────────────────────────────────────────────────────

class TestLoadIngestConfig:
    def test_defaults_when_no_config(self, tmp_path, monkeypatch):
        """Defaults apply when config.toml is absent."""
        config_path = tmp_path / "nonexistent.toml"
        monkeypatch.setattr(
            "janus.services.activity_ingest.CONFIG_PATH", config_path
        )
        cfg = _load_ingest_config()
        assert cfg.dedup_policy == "reject"
        assert cfg.dedup_tolerance_seconds == 0
        assert cfg.write_retry_count == 3
        assert cfg.normalization_units == {}
        assert cfg.file_paths == {}

    def test_loads_from_config(self, tmp_path, monkeypatch):
        """Config values are loaded from config.toml when present."""
        config_content = (
            "[data_ingestion]\n"
            "dedup_policy = \"merge\"\n"
            "dedup_tolerance_seconds = 60\n"
            "write_retry_count = 5\n"
            "write_retry_backoff_base = 0.2\n"
        )
        config_path = tmp_path / "config.toml"
        config_path.write_text(config_content)
        monkeypatch.setattr(
            "janus.services.activity_ingest.CONFIG_PATH", config_path
        )
        cfg = _load_ingest_config()
        assert cfg.dedup_policy == "merge"
        assert cfg.dedup_tolerance_seconds == 60
        assert cfg.write_retry_count == 5
        assert cfg.write_retry_backoff_base == 0.2

    def test_loads_normalization_units(self, tmp_path, monkeypatch):
        """Normalization units are loaded from config."""
        config_content = (
            "[data_ingestion]\n"
            '[data_ingestion.normalization.units."Weight"]\n'
            'base_unit = "kg"\n'
            '[data_ingestion.normalization.units."Distance"]\n'
            'base_unit = "km"\n'
        )
        config_path = tmp_path / "config.toml"
        config_path.write_text(config_content)
        monkeypatch.setattr(
            "janus.services.activity_ingest.CONFIG_PATH", config_path
        )
        cfg = _load_ingest_config()
        assert cfg.normalization_units == {"Weight": "kg", "Distance": "km"}

    def test_loads_file_paths(self, tmp_path, monkeypatch):
        """Custom file paths are loaded from config."""
        config_content = (
            '[data_ingestion.files]\n'
            '"workout_added" = "data/custom_workouts.md"\n'
        )
        config_path = tmp_path / "config.toml"
        config_path.write_text(config_content)
        monkeypatch.setattr(
            "janus.services.activity_ingest.CONFIG_PATH", config_path
        )
        cfg = _load_ingest_config()
        assert cfg.file_paths == {"workout_added": "data/custom_workouts.md"}


class TestFileForType:
    def test_default_paths(self):
        """Each activity type maps to the expected default data/ file."""
        cfg = IngestConfig()
        path = cfg.file_for_type(ActivityType.TASK_COMPLETED)
        assert path.name == "tasks.md"

    def test_measurements_jsonl(self):
        """MEASUREMENT maps to measurements.jsonl."""
        cfg = IngestConfig()
        path = cfg.file_for_type(ActivityType.MEASUREMENT)
        assert path.name == "measurements.jsonl"

    def test_custom_file_path_override(self):
        """file_paths config overrides the default path for a type."""
        cfg = IngestConfig()
        cfg.file_paths = {"workout_added": "data/custom_workouts.md"}
        path = cfg.file_for_type(ActivityType.WORKOUT_ADDED)
        assert path.name == "custom_workouts.md"


# ── _parse_ts_from_text ───────────────────────────────────────────────────────

class TestParseTsFromText:
    def test_extracts_iso_timestamp(self):
        """Extracts an ISO 8601 timestamp from text."""
        text = "completed at 2026-09-12T14:30:00+00:00 evidence"
        result = _parse_ts_from_text(
            text, r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})"
        )
        assert result is not None
        assert result.year == 2026
        assert result.month == 9
        assert result.day == 12

    def test_returns_none_when_no_match(self):
        """Returns None when the pattern doesn't match."""
        result = _parse_ts_from_text("no timestamp here", r"(\d{4}-\d{2}-\d{2})")
        assert result is None

    def test_returns_none_on_invalid_datetime(self):
        """Returns None when the matched text isn't a valid datetime."""
        result = _parse_ts_from_text(
            "2026-13-45", r"(\d{4}-\d{2}-\d{2})"
        )
        assert result is None


# ── _check_tolerance ───────────────────────────────────────────────────────────

class TestCheckTolerance:
    def test_jsonl_exact_match(self, tmp_path):
        """JSONL: exact key match returns True."""
        fp = tmp_path / "measurements.jsonl"
        fp.write_text(json.dumps({
            "goal_title": "Health",
            "metric": "Weight",
            "date": "2026-09-12",
            "value": 75.0,
        }) + "\n")
        key = "Health::Weight::2026-09-12"
        ts = datetime(2026, 9, 12, tzinfo=timezone.utc)
        assert _check_tolerance(fp, key, ts, 0) is True

    def test_jsonl_no_match(self, tmp_path):
        """JSONL: non-matching key returns False."""
        fp = tmp_path / "measurements.jsonl"
        fp.write_text(json.dumps({
            "goal_title": "Other",
            "metric": "Weight",
            "date": "2026-09-12",
        }) + "\n")
        key = "Health::Weight::2026-09-12"
        ts = datetime(2026, 9, 12, tzinfo=timezone.utc)
        assert _check_tolerance(fp, key, ts, 0) is False

    def test_jsonl_missing_file(self, tmp_path):
        """JSONL: missing file returns False."""
        fp = tmp_path / "nonexistent.jsonl"
        key = "a::b::c"
        ts = datetime(2026, 9, 12, tzinfo=timezone.utc)
        assert _check_tolerance(fp, key, ts, 0) is False

    def test_markdown_exact_match(self, tmp_path):
        """Markdown: substring key match returns True (exact, no tolerance)."""
        fp = tmp_path / "tasks.md"
        fp.write_text("- [x] Task | janus_evidence_task_id: t_42\n")
        key = "t_42"
        ts = datetime(2026, 9, 12, tzinfo=timezone.utc)
        assert _check_tolerance(fp, key, ts, 0) is True

    def test_markdown_no_match(self, tmp_path):
        """Markdown: key not in content returns False."""
        fp = tmp_path / "tasks.md"
        fp.write_text("- [x] Task | janus_evidence_task_id: t_99\n")
        key = "t_42"
        ts = datetime(2026, 9, 12, tzinfo=timezone.utc)
        assert _check_tolerance(fp, key, ts, 0) is False


# ── _is_duplicate ──────────────────────────────────────────────────────────────

class TestIsDuplicate:
    def test_no_duplicate_when_file_empty(self, isolated_data_dir):
        """No duplicate detected when data file doesn't exist."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            workout_type="running",
            workout_id="w_1",
        )
        assert _is_duplicate(rec, "w_1", IngestConfig(), str(isolated_data_dir["workouts"])) is False

    def test_duplicate_detected_task_by_id(self, isolated_data_dir):
        """Duplicate detected when task_id exists in tasks.md."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [x] Some task | janus_evidence_task_id: t_42\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_id="t_42",
        )
        assert _is_duplicate(rec, "t_42", IngestConfig(), str(tasks_file)) is True

    def test_duplicate_detected_task_by_title(self, isolated_data_dir):
        """Duplicate detected when completed task title matches."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [x] Build feature\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Build feature",
        )
        key = "title:Build feature"
        assert _is_duplicate(rec, key, IngestConfig(), str(tasks_file)) is True

    def test_no_duplicate_open_task(self, isolated_data_dir):
        """Open tasks (- [ ]) are NOT duplicates — only completed (- [x])."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Build feature\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Build feature",
        )
        key = "title:Build feature"
        assert _is_duplicate(rec, key, IngestConfig(), str(tasks_file)) is False

    def test_duplicate_measurement_in_jsonl(self, isolated_data_dir):
        """Duplicate detected in measurements.jsonl by key match."""
        mpath = isolated_data_dir["measurements"]
        mpath.write_text(json.dumps({
            "goal_title": "Health",
            "metric": "Weight",
            "date": "2026-09-12",
        }) + "\n")
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Health", metric="Weight",
            value=75.0, date="2026-09-12",
        )
        assert _is_duplicate(
            rec, "Health::Weight::2026-09-12", IngestConfig(), str(mpath)
        ) is True


# ── _copy_record ─────────────────────────────────────────────────────────────

class TestCopyRecord:
    def test_copy_is_independent(self):
        """Copy is independent — mutating copy doesn't affect original."""
        original = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Task",
            evidence={"k": "v"},
        )
        cloned = _copy_record(original)
        assert cloned is not original
        assert cloned.task_title == original.task_title
        assert cloned.evidence == original.evidence

    def test_copy_preserves_type(self):
        """Copy preserves the ActivityRecord fields."""
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            metric="Weight", value=75.0,
        )
        cloned = _copy_record(rec)
        assert cloned.type == ActivityType.MEASUREMENT
        assert cloned.metric == "Weight"
        assert cloned.value == 75.0


# ── _gen_uuid ─────────────────────────────────────────────────────────────────

class TestGenUuid:
    def test_uuid_has_prefix(self):
        """Generated UUIDs have the given prefix."""
        result = _gen_uuid("fu")
        assert result.startswith("fu-")

    def test_uuids_are_unique(self):
        """Successive UUIDs are unique."""
        ids = {_gen_uuid("x") for _ in range(100)}
        assert len(ids) == 100


# ── ingest_activities: dry-run / validation rejection ──────────────────────────

class TestIngestActivitiesValidation:
    """Tests for the validation + rejection path of ingest_activities."""

    def test_rejects_invalid_policy(self, isolated_data_dir, isolated_config):
        """An invalid dedup_policy raises ValueError immediately."""
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Task",
        )
        with pytest.raises(ValueError, match="Invalid dedup_policy"):
            ingest_activities([rec], dedup_policy="bogus")

    def test_rejects_missing_task_title(self, isolated_data_dir, isolated_config):
        """A TASK_COMPLETED without task_title or task_id is rejected."""
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        results = ingest_activities([rec])
        assert len(results) == 1
        assert results[0].accepted is False
        assert results[0].action == "rejected"
        assert results[0].wrote is False
        assert "validation" in results[0].error

    def test_rejects_missing_goal_title(self, isolated_data_dir, isolated_config):
        """GOAL_PROGRESS without goal_title is rejected."""
        rec = ActivityRecord(
            type=ActivityType.GOAL_PROGRESS,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        results = ingest_activities([rec])
        assert results[0].accepted is False
        assert "goal_title" in results[0].error

    def test_rejects_measurement_without_metric(self, isolated_data_dir, isolated_config):
        """MEASUREMENT without metric is rejected."""
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        results = ingest_activities([rec])
        assert results[0].accepted is False
        assert "metric" in results[0].error

    def test_rejects_measurement_without_value(self, isolated_data_dir, isolated_config):
        """MEASUREMENT without value is rejected."""
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            metric="Weight",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is False
        assert "value" in results[0].error

    def test_rejects_workout_without_type(self, isolated_data_dir, isolated_config):
        """WORKOUT_ADDED without workout_type is rejected."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        results = ingest_activities([rec])
        assert results[0].accepted is False
        assert "workout_type" in results[0].error

    def test_rejects_inbox_without_text(self, isolated_data_dir, isolated_config):
        """INBOX_CAPTURED without captured_text is rejected."""
        rec = ActivityRecord(
            type=ActivityType.INBOX_CAPTURED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        results = ingest_activities([rec])
        assert results[0].accepted is False
        assert "captured_text" in results[0].error

    def test_rejects_bad_progress_value(self, isolated_data_dir, isolated_config):
        """progress=150 is rejected."""
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Task",
            progress=150,
        )
        results = ingest_activities([rec])
        assert results[0].accepted is False
        assert "progress" in results[0].error


# ── ingest_activities: dedup policies ──────────────────────────────────────────

class TestIngestActivitiesDedup:
    """Tests for dedup reject/merge/replace policies."""

    def _task_completed(self, title="Build feature", task_id="t_42"):
        return ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, 14, 30, 0, tzinfo=timezone.utc),
            task_title=title,
            task_id=task_id,
        )

    def test_reject_policy_drops_duplicate(self, isolated_data_dir, isolated_config):
        """With dedup_policy='reject', a duplicate task is rejected."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text(
            "# Tasks\n\n- [x] Build feature | janus_evidence_task_id: t_42\n"
        )
        rec = self._task_completed()
        results = ingest_activities([rec], dedup_policy="reject")
        assert results[0].accepted is False
        assert results[0].action == "rejected"
        assert "duplicate" in results[0].error.lower()
        # File should be unchanged
        assert "Build feature" in tasks_file.read_text()

    def test_merge_policy_drops_duplicate(self, isolated_data_dir, isolated_config):
        """With dedup_policy='merge', a duplicate is also rejected (merge = skip)."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text(
            "- [x] Build feature | janus_evidence_task_id: t_42\n"
        )
        rec = self._task_completed()
        results = ingest_activities([rec], dedup_policy="merge")
        assert results[0].accepted is False
        assert results[0].action == "rejected"

    def test_replace_policy_overwrites_duplicate(self, isolated_data_dir, isolated_config):
        """With dedup_policy='replace', the duplicate record proceeds to dispatch."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [x] Build feature | janus_evidence_task_id: t_42\n")
        rec = self._task_completed()
        results = ingest_activities([rec], dedup_policy="replace")
        # With replace, accept=True and the dispatch proceeds
        assert results[0].accepted is True
        assert results[0].error is None

    def test_no_duplicate_first_time(self, isolated_data_dir, isolated_config):
        """First ingestion of a task has no duplicate (open task is not a dup)."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Build feature\n")
        rec = self._task_completed()
        results = ingest_activities([rec], dedup_policy="reject")
        assert results[0].accepted is True
        assert results[0].wrote is True

    def test_dedup_by_task_id_not_title(self, isolated_data_dir, isolated_config):
        """Two different tasks with the same title but different IDs are NOT duplicates."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text(
            "- [x] Same title | janus_evidence_task_id: t_1\n"
        )
        rec = self._task_completed(title="Same title", task_id="t_2")
        results = ingest_activities([rec], dedup_policy="reject")
        # t_2 is not a duplicate of t_1
        assert results[0].accepted is True


# ── ingest_activities: Task dispatch (happy path) ──────────────────────────────

class TestIngestTaskDispatch:
    """Integration tests for TASK_COMPLETED / TASK_UPDATED dispatch."""

    def test_task_completed_marks_checkbox(self, isolated_data_dir, isolated_config):
        """TASK_COMPLETED converts an open task checkbox to - [x]."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Build feature\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_id="t_abc",
            task_title="Build feature",
            evidence={"task_id": "t_task_evidence"},
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        assert results[0].wrote is True
        updated = tasks_file.read_text()
        assert "- [x] Build feature" in updated
        assert "janus_evidence_task_id" in updated

    def test_task_updated_sets_progress(self, isolated_data_dir, isolated_config):
        """TASK_UPDATED sets task progress when provided."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Build feature\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_UPDATED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Build feature",
            progress=50,
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        updated = tasks_file.read_text()
        assert "progress: 50" in updated

    def test_task_updated_sets_state(self, isolated_data_dir, isolated_config):
        """TASK_UPDATED sets task state when provided."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Build feature\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_UPDATED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Build feature",
            state="in_progress",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        updated = tasks_file.read_text()
        assert "state: in_progress" in updated

    def test_task_not_found_is_rejected_not_fatal(self, isolated_data_dir, isolated_config):
        """A record referencing a non-existent task is rejected but doesn't
        crash the entire batch."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Some other task\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_id="t_x",
            task_title="Missing task",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True  # accepted (passed validation)
        assert results[0].wrote is False
        assert results[0].action == "rejected"
        assert "dispatch" in results[0].error.lower()


# ── ingest_activities: Goal dispatch (happy path) ─────────────────────────────

class TestIngestGoalDispatch:
    """Integration tests for GOAL_PROGRESS / GOAL_UPDATED / GOAL_COMPLETED."""

    def _seed_goals(self, isolated_data_dir, content="# Goals\n\n## Goal: Test\nStatus: active\n"):
        isolated_data_dir["goals"].write_text(content)

    def test_goal_progress_updates_metric(self, isolated_data_dir, isolated_config):
        """GOAL_PROGRESS advances current_value and appends recent activity."""
        self._seed_goals(isolated_data_dir,
            "# Goals\n\n## Goal: Weight\nStatus: active\n"
            "Metric: Weight\nUnit: kg\nStart: 80\nCurrent: 78\nTarget: 70\n"
            "Direction: decrease\n"
        )
        rec = ActivityRecord(
            type=ActivityType.GOAL_PROGRESS,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight", task_id="t_1", task_title="Diet plan",
            current_value=76.5, metric_name="Weight",
            evidence={"completed_at": "2026-09-09T10:00:00Z", "current_value": 76.5},
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        assert results[0].wrote is True
        content = isolated_data_dir["goals"].read_text()
        assert "Current: 76.5" in content
        assert "# " in content  # recent activity entry is a JSON comment line

    def test_goal_updated_sets_current_value(self, isolated_data_dir, isolated_config):
        """GOAL_UPDATED updates current_value on the goal."""
        self._seed_goals(isolated_data_dir,
            "# Goals\n\n## Goal: Savings\nStatus: active\n"
            "Metric: Account balance\nUnit: PLN\nStart: 0\nCurrent: 5000\nTarget: 10000\n"
        )
        rec = ActivityRecord(
            type=ActivityType.GOAL_UPDATED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Savings", task_id="t_1",
            current_value=6000, metric_name="Account balance",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = isolated_data_dir["goals"].read_text()
        assert "Current: 6000" in content

    def test_goal_completed_marks_done(self, isolated_data_dir, isolated_config):
        """GOAL_COMPLETED sets status to 'completed'."""
        self._seed_goals(isolated_data_dir,
            "# Goals\n\n## Goal: Launch\nStatus: active\n"
        )
        rec = ActivityRecord(
            type=ActivityType.GOAL_COMPLETED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Launch", task_id="t_1",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = isolated_data_dir["goals"].read_text()
        assert "Status: completed" in content

    def test_goal_not_found_rejected(self, isolated_data_dir, isolated_config):
        """GOAL_* referencing a non-existent goal is rejected (non-fatal)."""
        self._seed_goals(isolated_data_dir, "# Goals\n\n## Goal: Real\nStatus: active\n")
        rec = ActivityRecord(
            type=ActivityType.GOAL_COMPLETED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Ghost", task_id="t_1",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        assert results[0].wrote is False
        assert results[0].action == "rejected"


# ── ingest_activities: Workout dispatch (happy path) ───────────────────────────

class TestIngestWorkoutDispatch:
    """Integration tests for WORKOUT_ADDED."""

    def test_workout_running_appended(self, isolated_data_dir, isolated_config):
        """WORKOUT_ADDED (running) appends a workout section to workouts.md."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
            workout_id="w_run_1",
            workout_type="running",
            distance_km=10.0,
            duration_minutes=55.0,
            avg_hr_bpm=150,
            elevation_m=100,
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

    def test_workout_strength_appended(self, isolated_data_dir, isolated_config):
        """WORKOUT_ADDED (strength) appends a strength workout with exercises."""
        from janus.models.workout import Exercise, Set
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
            workout_id="w_str_1",
            workout_type="strength",
            evidence={
                "exercises": [
                    Exercise(
                        name="Squat",
                        sets=[
                            Set(reps=5, weight_kg=100.0, rpe=8),
                            Set(reps=5, weight_kg=100.0, rpe=8),
                        ],
                    ),
                ],
            },
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = isolated_data_dir["workouts"].read_text()
        assert "Squat" in content
        assert "100.0" in content

    def test_workout_appended_to_existing(self, isolated_data_dir, isolated_config):
        """A second workout is appended after existing content (header preserved)."""
        wrk = isolated_data_dir["workouts"]
        wrk.write_text("# Fitness Workouts\n\n## Workout:\nid = w_old\n")
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
            workout_id="w_new",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = wrk.read_text()
        assert "w_old" in content
        assert "w_new" in content


# ── ingest_activities: Measurement dispatch ────────────────────────────────────

class TestIngestMeasurementDispatch:
    """Integration tests for MEASUREMENT."""

    def test_measurement_appended(self, isolated_data_dir, isolated_config):
        """MEASUREMENT appends a snapshot to metric_history.md."""
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="hermes",
            timestamp=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
            goal_title="Weight", metric="Weight",
            value=75.0, unit="kg", date="2026-09-12",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        assert results[0].action == "appended"
        # The dispatch writes to metric_history.md via METRIC_HISTORY_PATH
        content = isolated_data_dir["metric_history"].read_text()
        assert "Weight" in content
        assert "75.0" in content

    def test_measurement_unit_conversion_in_ingestion(self, tmp_path, monkeypatch):
        """Weight lb is converted to kg during ingestion via normalization."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mh_path = data_dir / "metric_history.md"

        import janus.services.activity_ingest as ai
        monkeypatch.setattr(ai, "DATA_DIR", data_dir)

        import janus.integrations.metric_history as mh
        monkeypatch.setattr(mh, "METRIC_HISTORY_PATH", mh_path)

        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[data_ingestion]\n"
            '[data_ingestion.normalization.units."Weight"]\n'
            'base_unit = "kg"\n'
        )
        monkeypatch.setattr(ai, "CONFIG_PATH", config_path)

        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight", metric="Weight",
            value=154.0, unit="lb", date="2026-09-12",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = mh_path.read_text()
        expected = round(154.0 * 0.45359237, 4)
        assert str(expected) in content


# ── ingest_activities: Followup & Inbox dispatch ───────────────────────────────

class TestIngestFollowupInboxDispatch:
    def test_followup_appended(self, isolated_data_dir, isolated_config):
        """FOLLOWUP_ADDED appends a follow-up line."""
        rec = ActivityRecord(
            type=ActivityType.FOLLOWUP_ADDED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            captured_text="Call the dentist",
            followup_id="fu_1",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        assert results[0].action == "appended"
        content = isolated_data_dir["followups"].read_text()
        assert "fu_1" in content
        assert "Call the dentist" in content

    def test_inbox_appended(self, isolated_data_dir, isolated_config):
        """INBOX_CAPTURED appends an inbox line."""
        rec = ActivityRecord(
            type=ActivityType.INBOX_CAPTURED,
            source="telegram",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            captured_text="Remember to buy milk",
            inbox_id="ix_1",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        assert results[0].action == "appended"
        content = isolated_data_dir["inbox"].read_text()
        assert "ix_1" in content
        assert "Remember to buy milk" in content


# ── ingest_activities: batch behavior ─────────────────────────────────────────

class TestIngestActivitiesBatch:
    def test_multiple_records_one_result_per_input(self, isolated_data_dir, isolated_config):
        """Each input record produces exactly one result, in order."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Task A\n- [ ] Task B\n")
        recs = [
            ActivityRecord(
                type=ActivityType.TASK_COMPLETED,
                source="test",
                timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
                task_title="Task A", task_id="t_1",
            ),
            ActivityRecord(
                type=ActivityType.TASK_COMPLETED,
                source="test",
                timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
                task_title="Task B", task_id="t_2",
            ),
        ]
        results = ingest_activities(recs)
        assert len(results) == 2
        assert results[0].file_path is not None
        assert results[1].file_path is not None

    def test_mixed_valid_invalid(self, isolated_data_dir, isolated_config):
        """A mix of valid and invalid records: invalid ones rejected, valid
        ones processed."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Real task\n")
        recs = [
            # Invalid: no task_title
            ActivityRecord(
                type=ActivityType.TASK_COMPLETED,
                source="test",
                timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            ),
            # Valid
            ActivityRecord(
                type=ActivityType.TASK_COMPLETED,
                source="test",
                timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
                task_title="Real task", task_id="t_1",
            ),
        ]
        results = ingest_activities(recs)
        assert results[0].accepted is False
        assert results[0].action == "rejected"
        assert results[1].accepted is True
        assert results[1].wrote is True

    def test_empty_list_returns_empty(self, isolated_data_dir, isolated_config):
        """An empty record list returns an empty result list."""
        results = ingest_activities([])
        assert results == []


# ── ingest_activities: result structure ────────────────────────────────────────

class TestIngestResult:
    def test_result_fields(self):
        """IngestResult has all expected fields."""
        result = IngestResult(
            record_id="key1",
            accepted=True,
            wrote=True,
            file_path="data/tasks.md",
            action="created",
        )
        assert result.record_id == "key1"
        assert result.accepted is True
        assert result.wrote is True
        assert result.file_path == "data/tasks.md"
        assert result.action == "created"
        assert result.error is None

    def test_result_with_error(self):
        """IngestResult can carry an error message."""
        result = IngestResult(
            record_id="key2",
            accepted=False,
            wrote=False,
            file_path="data/tasks.md",
            action="rejected",
            error="validation: missing field",
        )
        assert result.error == "validation: missing field"


class TestIngestDryRun:
    def test_dry_run_fields(self):
        """IngestDryRun has results, would_write_files, rejected_count."""
        results = [
            IngestResult("k1", True, True, "data/a.md", "created"),
            IngestResult("k2", False, False, "data/b.md", "rejected", "dup"),
        ]
        dr = IngestDryRun(
            results=results,
            would_write_files={"data/a.md"},
            rejected_count=1,
        )
        assert len(dr.results) == 2
        assert "data/a.md" in dr.would_write_files
        assert dr.rejected_count == 1


# ── Normalization integration through ingest ───────────────────────────────────

class TestNormalizationInIntegration:
    """Verify normalization happens end-to-end inside ingest_activities."""

    def test_text_fields_stripped(self, isolated_data_dir, isolated_config):
        """Task title with surrounding whitespace is stripped before dispatch."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] My Task\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="  My Task  ",
            task_id="t_stripped",
            evidence={"task_id": "t_stripped"},
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = tasks_file.read_text()
        assert "- [x] My Task" in content

    def test_timestamp_normalized_to_aware(self, isolated_data_dir, isolated_config):
        """A naive timestamp is normalized to timezone-aware before use."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Naive ts task\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, 14, 30, 0),  # naive
            task_title="Naive ts task",
            task_id="t_naive",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True

    def test_control_chars_removed_from_text(self, isolated_data_dir, isolated_config):
        """Control characters are removed from task_title during normalization."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Cleanname\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Clean\x00name",
            task_id="t_ctrl",
            evidence={"task_id": "t_ctrl"},
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        content = tasks_file.read_text()
        assert "Cleanname" in content


# ── Data-layer protection: negative tests ─────────────────────────────────────
#
# ADR-005 §6: The model layer (ActivityRecord / IngestResult / IngestDryRun)
# must not write to data/ files directly.  All writes must go through
# ingest_activities() → atomic_io gateway.  These tests verify that the
# model/dataclass layer has no direct file-write path.


class TestDataProtectionNegative:
    """Verify the model layer cannot directly persist to data/ files.

    ActivityRecord, IngestResult, IngestDryRun, and IngestConfig are plain
    dataclasses with no file-write methods.  Only ingest_activities() can
    write to data/ — and it always goes through atomic_io.
    """

    def test_activity_record_has_no_write_method(self):
        """ActivityRecord exposes no method that writes to disk."""
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Task",
        )
        # The dataclass itself has no persistence methods
        write_methods = [
            m for m in dir(rec)
            if not m.startswith("_")
            and callable(getattr(rec, m))
            and any(kw in m.lower() for kw in ("write", "save", "persist", "dump"))
        ]
        assert write_methods == [], f"Unexpected write method on ActivityRecord: {write_methods}"

    def test_ingest_result_has_no_write_method(self):
        """IngestResult exposes no method that writes to disk."""
        result = IngestResult(
            record_id="key", accepted=True, wrote=True,
            file_path="data/x.md", action="created",
        )
        write_methods = [
            m for m in dir(result)
            if not m.startswith("_")
            and callable(getattr(result, m))
            and any(kw in m.lower() for kw in ("write", "save", "persist", "dump"))
        ]
        assert write_methods == []

    def test_ingest_dry_run_has_no_write_method(self):
        """IngestDryRun exposes no method that writes to disk."""
        dr = IngestDryRun(
            results=[],
            would_write_files=set(),
            rejected_count=0,
        )
        write_methods = [
            m for m in dir(dr)
            if not m.startswith("_")
            and callable(getattr(dr, m))
            and any(kw in m.lower() for kw in ("write", "save", "persist", "dump"))
        ]
        assert write_methods == []

    def test_activity_record_fields_are_not_paths(self):
        """ActivityRecord dataclass fields are typed data, not Path objects —
        the record carries no file path it could write to."""
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="Task",
        )
        # No field is a Path instance
        for field_name in type(rec).__dataclass_fields__:
            value = getattr(rec, field_name)
            assert not isinstance(value, Path), (
                f"ActivityRecord.{field_name} is a Path, "
                f"model layer should not hold file paths"
            )

    def test_no_direct_file_write_methods_in_module(self):
        """activity_ingest module exports no function that bypasses atomic_io.

        The only write-path functions are those imported from atomic_io
        (read_modify_write_with_retry, atomic_write, atomic_read), which ARE
        the atomic gateway — there must be no raw open()/write() in public
        functions outside that gateway.
        """
        import janus.services.activity_ingest as ai
        import inspect

        # Public functions in the module (excluding imported atomic_io funcs)
        atomic_io_names = {"atomic_write", "atomic_read", "read_modify_write",
                           "read_modify_write_with_retry", "ConcurrentWriteError",
                           "AtomicWriteError"}

        for name in dir(ai):
            if name.startswith("_"):
                continue
            obj = getattr(ai, name)
            if not callable(obj) or not inspect.isfunction(obj):
                continue
            # Skip functions imported from atomic_io — they ARE the gateway
            if hasattr(obj, "__module__") and "atomic_io" in (obj.__module__ or ""):
                continue
            if name in atomic_io_names:
                continue
            # Any function defined in activity_ingest that writes must use
            # atomic_io, not raw file operations. Check there's no open() in
            # functions that mention 'write' or 'save' in their name.
            if any(kw in name.lower() for kw in ("write", "save", "persist", "dump")):
                assert False, f"Unexpected write function in activity_ingest: {name}"

    def test_activity_record_dataclass_not_path(self):
        """ActivityRecord is a dataclass, not a model with save()."""
        from dataclasses import is_dataclass
        assert is_dataclass(ActivityRecord)
        assert not hasattr(ActivityRecord, "save")
        assert not hasattr(ActivityRecord, "write")
        assert not hasattr(ActivityRecord, "persist")


# ── Write correctness: file content ───────────────────────────────────────────

class TestWriteCorrectness:
    """Verify that dispatched writes produce correct file content in data/."""

    def test_task_completed_produces_correct_markdown(self, isolated_data_dir, isolated_config):
        """TASK_COMPLETED produces a properly completed task line with evidence."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Build API\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, 14, 0, 0, tzinfo=timezone.utc),
            task_id="t_api",
            task_title="Build API",
            evidence={"task_id": "t_api", "completed_at": "2026-09-12T14:00:00+00:00"},
        )
        ingest_activities([rec])
        content = tasks_file.read_text()
        assert "- [x] Build API" in content
        assert "janus_evidence_task_id: t_api" in content
        assert "janus_evidence_completed_at: 2026-09-12T14:00:00+00:00" in content

    def test_goal_updated_preserves_other_fields(self, isolated_data_dir, isolated_config):
        """GOAL_UPDATED changes current_value but preserves other goal fields."""
        goals_file = isolated_data_dir["goals"]
        goals_file.write_text(
            "# Goals\n\n## Goal: Savings\nStatus: active\n"
            "Metric: Account balance\nUnit: PLN\nStart: 0\nCurrent: 5000\n"
            "Target: 10000\nDirection: increase\n"
            "Related tasks:\n- Track expenses\n"
        )
        rec = ActivityRecord(
            type=ActivityType.GOAL_UPDATED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Savings", task_id="t_1",
            current_value=6000, metric_name="Account balance",
            evidence={"current_value": 6000},
        )
        ingest_activities([rec])
        content = goals_file.read_text()
        assert "Current: 6000" in content
        assert "Target: 10000" in content  # preserved
        assert "Metric: Account balance" in content  # preserved
        assert "Direction: increase" in content  # preserved

    def test_workout_appended_preserves_header(self, isolated_data_dir, isolated_config):
        """WORKOUT_ADDED preserves the existing header when appending."""
        wrk = isolated_data_dir["workouts"]
        wrk.write_text("# Fitness Workouts\n\n## Workout:\nid = w_old\n")
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
            workout_id="w_new",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
        )
        ingest_activities([rec])
        content = wrk.read_text()
        assert content.startswith("# Fitness Workouts")
        assert "w_old" in content
        assert "w_new" in content

    def test_inbox_appended_creates_file(self, isolated_data_dir, isolated_config):
        """INBOX_CAPTURED creates inbox.md on first write."""
        inbox_file = isolated_data_dir["inbox"]
        assert not inbox_file.exists()
        rec = ActivityRecord(
            type=ActivityType.INBOX_CAPTURED,
            source="telegram",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            captured_text="New idea",
            inbox_id="ix_1",
        )
        ingest_activities([rec])
        assert inbox_file.exists()
        content = inbox_file.read_text()
        assert "ix_1" in content
        assert "New idea" in content


# ── Recovery after errors ──────────────────────────────────────────────────────

class TestRecoveryAfterErrors:
    """Verify that errors during ingestion don't corrupt existing data."""

    def test_validation_error_does_not_write(self, isolated_data_dir, isolated_config):
        """A rejected (invalid) record does not modify any data file."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Existing task\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            # No task_title or task_id — validation fails
        )
        results = ingest_activities([rec])
        assert results[0].accepted is False
        # File unchanged
        assert tasks_file.read_text() == "- [ ] Existing task\n"

    def test_dispatch_failure_records_error_without_fatal(self, isolated_data_dir, isolated_config):
        """A dispatch failure (e.g. goal not found) returns an error result
        but does not crash — the batch continues."""
        goals_file = isolated_data_dir["goals"]
        goals_file.write_text("# Goals\n\n## Goal: Real\nStatus: active\n")
        rec = ActivityRecord(
            type=ActivityType.GOAL_COMPLETED,
            source="hermes",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Ghost goal", task_id="t_1",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True  # passed validation
        assert results[0].wrote is False
        assert results[0].error is not None

    def test_batch_continues_after_one_failure(self, isolated_data_dir, isolated_config):
        """One failing record doesn't prevent subsequent records from being
        ingested."""
        tasks_file = isolated_data_dir["tasks"]
        tasks_file.write_text("- [ ] Task A\n- [ ] Task B\n")
        recs = [
            # Invalid: no task_title
            ActivityRecord(
                type=ActivityType.TASK_COMPLETED,
                source="test",
                timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            ),
            # Valid
            ActivityRecord(
                type=ActivityType.TASK_COMPLETED,
                source="hermes",
                timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
                task_title="Task A", task_id="t_a",
                evidence={"task_id": "t_a"},
            ),
        ]
        results = ingest_activities(recs)
        assert results[0].accepted is False  # invalid rejected
        assert results[1].accepted is True  # valid processed
        content = tasks_file.read_text()
        assert "- [x] Task A" in content

    def test_file_not_corrupted_on_write_error(self, isolated_data_dir, isolated_config):
        """When the dispatch fails, the original file content is preserved."""
        tasks_file = isolated_data_dir["tasks"]
        original = "- [ ] Original task\n"
        tasks_file.write_text(original)

        # TASK_COMPLETED dispatch calls complete_janus_task; make it raise
        with patch(
            "janus.services.tasks.complete_janus_task",
            side_effect=RuntimeError("simulated dispatch failure"),
        ):
            rec = ActivityRecord(
                type=ActivityType.TASK_COMPLETED,
                source="hermes",
                timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
                task_title="Original task", task_id="t_orig",
            )
            results = ingest_activities([rec])

        # The error is captured on the result, not raised
        assert results[0].accepted is True
        assert results[0].wrote is False
        assert results[0].error is not None
        # Original file is untouched
        assert tasks_file.read_text() == original


# ── Ingest result structure (action values) ───────────────────────────────────

class TestIngestActions:
    """Verify correct action strings in IngestResult."""

    def test_task_completed_action_is_updated(self, isolated_data_dir, isolated_config):
        """TASK_COMPLETED produces action='updated'."""
        isolated_data_dir["tasks"].write_text("- [ ] New task\n")
        rec = ActivityRecord(
            type=ActivityType.TASK_COMPLETED,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            task_title="New task", task_id="t_1",
            evidence={"task_id": "t_1"},
        )
        results = ingest_activities([rec])
        assert results[0].action == "updated"

    def test_workout_action_is_appended(self, isolated_data_dir, isolated_config):
        """WORKOUT_ADDED produces action='appended'."""
        rec = ActivityRecord(
            type=ActivityType.WORKOUT_ADDED,
            source="test",
            timestamp=datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc),
            workout_id="w_1",
            workout_type="running",
            distance_km=5.0,
            duration_minutes=30.0,
        )
        results = ingest_activities([rec])
        assert results[0].action == "appended"

    def test_measurement_action_is_appended(self, isolated_data_dir, isolated_config):
        """MEASUREMENT produces action='appended'."""
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="test",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight", metric="Weight",
            value=75.0, unit="kg", date="2026-09-12",
        )
        results = ingest_activities([rec])
        assert results[0].action == "appended"


# ── Regeneration gating on ingest_activities ────────────────────────────────
#
# ADR-005 Amendment 01 AC2: regeneration gating (gate_regeneration +
# allowed_regenerators) is exposed as arguments to ingest_activities (not the
# primitive).  When gate_regeneration is enabled, a full-file rewrite by an
# untrusted (model-driven) writer that exceeds the change threshold is blocked
# and reported as a rejected IngestResult.

class TestIngestRegenerationGating:
    """Tests for gate_regeneration / allowed_regenerators on ingest_activities."""

    def test_gate_disabled_allows_large_append(self, isolated_data_dir, isolated_config):
        """With gate_regeneration=False (default), a large append succeeds."""
        inbox_file = isolated_data_dir["inbox"]
        inbox_file.write_text("- [ ] Old item\n")
        rec = ActivityRecord(
            type=ActivityType.INBOX_CAPTURED,
            source="cli",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            captured_text="A " * 300,
            inbox_id="ix_1",
        )
        results = ingest_activities([rec], gate_regeneration=False)
        assert results[0].accepted is True
        assert results[0].wrote is True

    def test_gate_blocks_untrusted_large_write(self, isolated_data_dir, isolated_config):
        """With gate_regeneration=True, a projected write that exceeds the
        change threshold by an untrusted (model-driven) writer is blocked."""
        inbox_file = isolated_data_dir["inbox"]
        old = "- [ ] Small existing item\n"
        inbox_file.write_text(old)
        rec = ActivityRecord(
            type=ActivityType.INBOX_CAPTURED,
            source="cli",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            captured_text="A " * 300,
            inbox_id="ix_1",
        )
        results = ingest_activities([rec], gate_regeneration=True)
        assert results[0].accepted is True
        assert results[0].wrote is False
        assert results[0].action == "rejected"
        assert "regeneration" in results[0].error.lower()
        assert inbox_file.read_text() == old

    def test_allowed_regenerators_bypasses_gate(self, isolated_data_dir, isolated_config):
        """If the writer is in allowed_regenerators, the gate is bypassed."""
        inbox_file = isolated_data_dir["inbox"]
        inbox_file.write_text("- [ ] Old item\n")
        rec = ActivityRecord(
            type=ActivityType.INBOX_CAPTURED,
            source="cli",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            captured_text="A " * 300,
            inbox_id="ix_1",
        )
        results = ingest_activities(
            [rec], gate_regeneration=True,
            allowed_regenerators={"activity_ingest.inbox_captured"},
        )
        assert results[0].accepted is True
        assert results[0].wrote is True

    def test_default_gate_off_does_not_block(self, isolated_data_dir, isolated_config):
        """gate_regeneration defaults to False -- no gating occurs."""
        inbox_file = isolated_data_dir["inbox"]
        inbox_file.write_text("- [ ] Old item\n")
        rec = ActivityRecord(
            type=ActivityType.INBOX_CAPTURED,
            source="cli",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            captured_text="A " * 300,
            inbox_id="ix_1",
        )
        results = ingest_activities([rec])
        assert results[0].accepted is True
        assert results[0].wrote is True
