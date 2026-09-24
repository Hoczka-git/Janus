"""Tests for metric progression semantics: classification, task-to-metric rules,
and preservation of explicit/manual updates.

This suite complements ``test_metric_provenance.py`` (which focuses on the
preservation/precedence matrix) by covering:

- **Metric type classification** — the ``MetricType`` and ``MetricSource``
  enums in ``src/janus/models/metric_type.py``, the ``is_metric_source()``
  validator, and ``MetricSnapshot`` source validation.
- **Task-to-metric rule application** — ``update_goal_progress`` handling of
  ``metric_updates`` lists, metric-name matching/skipping, multi-metric goals,
  the legacy ``current_value`` evidence path, and task retry / re-completion
  idempotency.
- **Preservation of explicit/manual updates** — end-to-end precedence through
  the full ingest + service path (measurement overriding a protected manual
  value, import always winning, manual always winning over manual).

References:
- ``docs/research-findings/metric_type_taxonomy.md`` (Category A–E)
- ``docs/research-findings/task_to_metric_mapping_rules.md``
- ``docs/research-findings/manual_metric_update_preservation_spec.md`` (§5–§12)
"""
from datetime import datetime, timezone, timedelta

import pytest

from janus.models.goal import Goal
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.metric_type import (
    MetricSource,
    MetricType,
    MANUAL_VALUE_PROTECTION_WINDOW_HOURS,
    VALUE_UPDATE_TOLERANCE,
    is_metric_source,
)
from janus.services.goals import (
    _apply_metric_value,
    _protection_window_expired,
    _values_equal,
    add_goal,
    get_goal,
    update_goal_fields,
    update_goal_progress,
)


# ── fixtures / helpers ───────────────────────────────────────────────────────

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


def _write_goals(tmp_path, content):
    p = tmp_path / "goals.md"
    p.write_text(content)
    return p


def _setup(tmp_path, monkeypatch, content="# Goals\n"):
    gf = _write_goals(tmp_path, content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", gf)
    mh = tmp_path / "metric_history.md"
    monkeypatch.setattr(
        "janus.integrations.metric_history.METRIC_HISTORY_PATH", mh
    )
    return gf


def _seed_metric_goal(tmp_path, monkeypatch):
    return _setup(tmp_path, monkeypatch, _METRIC_GOAL)


def _setup_ingest(tmp_path, monkeypatch):
    """Patch goals.md and metric_history.md paths for ingest tests."""
    gf = _write_goals(tmp_path, _METRIC_GOAL)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", gf)
    mh = tmp_path / "metric_history.md"
    monkeypatch.setattr(
        "janus.integrations.metric_history.METRIC_HISTORY_PATH", mh
    )
    return gf


def _snap_list(tmp_path, goal_title="Weight"):
    """Read snapshots directly from the history file."""
    from janus.integrations.metric_history import get_metric_snapshots
    mh = tmp_path / "metric_history.md"
    return get_metric_snapshots(goal_title, path=mh)


# ── 1. Metric type classification (MetricType enum) ───────────────────────────

class TestMetricTypeClassification:
    """Verify the MetricType enum covers all categories A-E from the taxonomy."""

    def test_all_seven_categories_defined(self):
        """MetricType must enumerate all categories A-E from the taxonomy
        (metric_type_taxonomy.md §3)."""
        expected = {
            "snapshot",                  # Category A — raw time-series (MetricSnapshot)
            "measurement",               # Category A — raw time-series (MeasurementEntry)
            "goal_metric",               # Category B — goal-level metric configuration
            "measurement_requirement",   # Category B — measurement schedule
            "derived",                   # Category C — computed-on-demand aggregates
            "signal",                    # Category D — event-like derived value
            "activity",                  # Category E — typed ingestion event
        }
        actual = {m.value for m in MetricType}
        assert actual == expected

    def test_metric_type_values_are_strings(self):
        for m in MetricType:
            assert isinstance(m.value, str)
            assert m.value == str(m)

    def test_metric_type_is_str_enum(self):
        assert isinstance(MetricType.SNAPSHOT, str)
        assert MetricType.SNAPSHOT == "snapshot"

    def test_metric_type_member_access(self):
        assert MetricType("snapshot") is MetricType.SNAPSHOT
        assert MetricType("measurement") is MetricType.MEASUREMENT
        assert MetricType("goal_metric") is MetricType.GOAL_METRIC
        assert MetricType("measurement_requirement") is MetricType.MEASUREMENT_REQUIREMENT
        assert MetricType("derived") is MetricType.DERIVED
        assert MetricType("signal") is MetricType.SIGNAL
        assert MetricType("activity") is MetricType.ACTIVITY


# ── 1b. Metric source classification (MetricSource enum + validator) ──────────

class TestMetricSourceClassification:
    """Verify MetricSource enum and is_metric_source() validator."""

    def test_all_four_sources(self):
        expected = {"manual", "measurement", "import", "task_derived"}
        assert {m.value for m in MetricSource} == expected

    @pytest.mark.parametrize("label,member", [
        ("manual", MetricSource.MANUAL),
        ("measurement", MetricSource.MEASUREMENT),
        ("import", MetricSource.IMPORT),
        ("task_derived", MetricSource.TASK_DERIVED),
    ])
    def test_source_values_match(self, label, member):
        assert member.value == label
        assert str(member) == label

    @pytest.mark.parametrize("value", [
        "manual", "measurement", "import", "task_derived",
        MetricSource.MANUAL, MetricSource.MEASUREMENT,
        MetricSource.IMPORT, MetricSource.TASK_DERIVED,
    ])
    def test_is_metric_source_accepts_valid(self, value):
        assert is_metric_source(value) is True

    @pytest.mark.parametrize("value", [
        "task",          # missing _derived
        "TASK_DERIVED",  # wrong case
        "measure",       # truncated
        "",
        "unknown",
        42,
        None,
        ["manual"],
        {"manual": 1},
    ])
    def test_is_metric_source_rejects_invalid(self, value):
        assert is_metric_source(value) is False


# ── 1c. MetricSnapshot source validation ──────────────────────────────────────

class TestMetricSnapshotSourceValidation:
    """MetricSnapshot must validate its source field and normalize it."""

    def test_valid_source_accepted(self):
        snap = MetricSnapshot(
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight",
            metric_name="Weight",
            value=70.0,
            source="manual",
        )
        assert snap.source == MetricSource.MANUAL

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError, match="Invalid MetricSnapshot source"):
            MetricSnapshot(
                timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
                goal_title="Weight",
                metric_name="Weight",
                value=70.0,
                source="bogus_source",
            )

    def test_task_derived_source_valid(self):
        """task_derived is a canonical MetricSnapshot source (preservation §2)."""
        snap = MetricSnapshot(
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight",
            metric_name="Weight",
            value=70.0,
            source=MetricSource.TASK_DERIVED,
        )
        assert snap.source == "task_derived"

    def test_metric_type_is_str_value(self):
        """MetricType members are strings (taxonomy §5: all metric values are
        float; the type itself is a string category label)."""
        assert MetricType.DERIVED == "derived"
        assert MetricType.SIGNAL == "signal"


# ── 2. Task-to-metric rule application ────────────────────────────────────────

class TestTaskToMetricRules:
    """Verify update_goal_progress applies the task-to-metric mapping rules
    from task_to_metric_mapping_rules.md §3.2."""

    def test_metric_updates_list_single_matching(self, tmp_path, monkeypatch):
        """§3.2: a single metric_updates entry whose metric_name matches the
        goal's metric_name advances current_value."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {
            "completed_at": "2026-09-09",
            "metric_updates": [
                {"metric_name": "Weight", "value": 75.0, "unit": "kg"},
            ],
        }
        g = update_goal_progress("Weight", "t_1", "Strength", evidence)
        assert g.current_value == 75.0
        assert g.metric_unit == "kg"
        assert g.last_value_source == MetricSource.TASK_DERIVED
        assert g.last_value_task_id == "t_1"

    def test_metric_updates_multiple_matches_last_wins(self, tmp_path, monkeypatch):
        """§10.4 / preservation §10.4: multiple matching entries are each
        evaluated; the last accepted one wins current_value, and last_value_*
        reflects the last applied entry."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {
            "completed_at": "2026-09-09",
            "metric_updates": [
                {"metric_name": "Weight", "value": 77.0},
                {"metric_name": "Weight", "value": 76.0},
                {"metric_name": "Weight", "value": 75.0},
            ],
        }
        g = update_goal_progress("Weight", "t_multi", "Multi-step", evidence)
        assert g.current_value == 75.0
        assert g.last_value_task_id == "t_multi"

    def test_metric_updates_mismatch_silently_skipped(self, tmp_path, monkeypatch):
        """§4.4: a metric_updates entry whose metric_name does not match the
        goal's metric_name is silently skipped."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {
            "completed_at": "2026-09-09",
            "metric_updates": [
                {"metric_name": "Body fat %", "value": 20.0},
            ],
        }
        g = update_goal_progress("Weight", "t_1", "Task", evidence)
        assert g.current_value == 78.0  # unchanged

    def test_metric_updates_mixed_match_and_mismatch(self, tmp_path, monkeypatch):
        """§10.4: when metric_updates contains both a matching and a
        mismatched entry, only the matching one applies."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {
            "completed_at": "2026-09-09",
            "metric_updates": [
                {"metric_name": "Body fat %", "value": 99.0},  # skipped
                {"metric_name": "Weight", "value": 74.0},       # applied
            ],
        }
        g = update_goal_progress("Weight", "t_1", "Task", evidence)
        assert g.current_value == 74.0

    def test_metric_updates_non_dict_entries_skipped(self, tmp_path, monkeypatch):
        """Defensive: non-dict entries in metric_updates are skipped."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {
            "completed_at": "2026-09-09",
            "metric_updates": ["not a dict", None, {"metric_name": "Weight", "value": 73.0}],
        }
        g = update_goal_progress("Weight", "t_1", "Task", evidence)
        assert g.current_value == 73.0

    def test_metric_updates_without_value_skipped(self, tmp_path, monkeypatch):
        """§4.4: an entry with no value is skipped (mu_val is None)."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {
            "completed_at": "2026-09-09",
            "metric_updates": [
                {"metric_name": "Weight"},  # no value
                {"metric_name": "Weight", "value": 75.0},
            ],
        }
        g = update_goal_progress("Weight", "t_1", "Task", evidence)
        assert g.current_value == 75.0

    def test_legacy_current_value_in_evidence(self, tmp_path, monkeypatch):
        """§3.2 legacy path: evidence.current_value advances current_value when
        no metric_updates list is present."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {"completed_at": "2026-09-09", "current_value": 76.0}
        g = update_goal_progress("Weight", "t_legacy", "Legacy", evidence)
        assert g.current_value == 76.0
        assert g.last_value_source == MetricSource.TASK_DERIVED

    def test_metric_updates_takes_precedence_over_legacy_current_value(self, tmp_path, monkeypatch):
        """§3.5 priority: metric_updates supersedes legacy current_value."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {
            "completed_at": "2026-09-09",
            "current_value": 99.0,  # would set to 99 via legacy path
            "metric_updates": [
                {"metric_name": "Weight", "value": 75.0},
            ],
        }
        g = update_goal_progress("Weight", "t_1", "Task", evidence)
        assert g.current_value == 75.0

    def test_task_completion_without_metric_evidence_preserves_value(self, tmp_path, monkeypatch):
        """§4.3: no metric_updates / current_value → current_value untouched."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {"completed_at": "2026-09-09"}
        g = update_goal_progress("Weight", "t_1", "No evidence", evidence)
        assert g.current_value == 78.0
        assert g.last_value_source is None
        assert g.last_value_task_id is None

    def test_task_retry_idempotent_activity(self, tmp_path, monkeypatch):
        """§4.1 / spec: re-completion with same task_id replaces, not duplicates,
        the recent_activity entry."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {"completed_at": "2026-09-09", "current_value": 76.0}
        update_goal_progress("Weight", "t_retry", "Round 1", evidence)
        update_goal_progress("Weight", "t_retry", "Round 2", evidence)
        g = get_goal("Weight")
        assert len(g.recent_activity) == 1
        assert g.recent_activity[0]["summary"] == "Round 2"


# ── 2b. Task retry after manual update (precedence on re-completion) ──────────

class TestTaskRetryAfterManual:
    """§10.1: task retry / re-completion after a manual update."""

    def test_retry_rejected_within_window(self, tmp_path, monkeypatch):
        """A re-completed task whose value would overwrite a fresh manual
        update is rejected by the protection window."""
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)
        # Re-complete a different task that tries to set a new value.
        evidence = {"completed_at": "2026-09-09", "current_value": 76.0}
        g = update_goal_progress("Weight", "t_retry", "Retry", evidence)
        assert g.current_value == 77.0  # manual wins
        assert g.last_value_source == MetricSource.MANUAL

    def test_retry_after_manual_within_window_rejected_no_snapshot(self, tmp_path, monkeypatch):
        """A rejected task_derived update does not append a snapshot."""
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)
        evidence = {"completed_at": "2026-09-09", "current_value": 76.0}
        update_goal_progress("Weight", "t_retry", "Retry", evidence)
        snaps = _snap_list(tmp_path)
        # Only the manual snapshot from update_goal_fields, none from the
        # rejected task_derived update.
        assert len(snaps) == 1
        assert snaps[0].source == MetricSource.MANUAL


# ── 3. Preservation of explicit/manual updates (precedence matrix) ────────────

class TestPrecedenceMatrix:
    """Verification of the full precedence matrix (preservation spec §5.6)
    through the service-layer _apply_metric_value helper."""

    def test_no_prior_value_any_source_accepted(self, tmp_path, monkeypatch):
        """§5.6 row 1: None prior → all sources accepted.

        Each source is tested against a goal with no prior provenance, since
        applying one source changes the goal's last_value_source."""
        _seed_metric_goal(tmp_path, monkeypatch)
        sources = [
            (MetricSource.MANUAL, "manual"),
            (MetricSource.MEASUREMENT, "measurement"),
            (MetricSource.IMPORT, "import"),
            (MetricSource.TASK_DERIVED, "task_derived"),
        ]
        for src, label in sources:
            g = get_goal("Weight")
            g.current_value = None
            g.last_value_source = None
            g.last_value_updated_at = None
            g.last_value_task_id = None
            _, reason = _apply_metric_value(
                g, 50.0, src,
                task_id="t" if src == MetricSource.TASK_DERIVED else None,
            )
            assert reason is None, f"{label} should be accepted with no prior value"
            assert g.last_value_source == label

    def test_manual_rejects_task_within_window(self, tmp_path, monkeypatch):
        """§5.6 row 2: manual prior + task_derived incoming + within window → REJECT."""
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)
        g = get_goal("Weight")
        _, reason = _apply_metric_value(g, 75.0, MetricSource.TASK_DERIVED, task_id="t_x")
        assert reason is not None
        assert g.current_value == 77.0  # untouched
        assert g.last_value_source == MetricSource.MANUAL

    def test_manual_accepts_task_after_window(self, tmp_path, monkeypatch):
        """§5.6 row 2: manual prior but window expired → task_derived accepted."""
        _seed_metric_goal(tmp_path, monkeypatch)
        g = get_goal("Weight")
        g.current_value = 77.0
        g.last_value_source = MetricSource.MANUAL
        g.last_value_updated_at = (
            datetime.now(timezone.utc)
            - timedelta(hours=MANUAL_VALUE_PROTECTION_WINDOW_HOURS + 1)
        ).isoformat()
        _, reason = _apply_metric_value(g, 75.0, MetricSource.TASK_DERIVED, task_id="t_x")
        assert reason is None
        assert g.current_value == 75.0
        assert g.last_value_source == MetricSource.TASK_DERIVED

    def test_manual_accepts_measurement_within_window(self, tmp_path, monkeypatch):
        """§5.6 row 2 + §5.2: manual prior + measurement incoming → always ACCEPT."""
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)
        g = get_goal("Weight")
        _, reason = _apply_metric_value(g, 70.0, MetricSource.MEASUREMENT, task_id=None)
        assert reason is None
        assert g.current_value == 70.0
        assert g.last_value_source == MetricSource.MEASUREMENT
        assert g.last_value_task_id is None

    def test_manual_accepts_import_within_window(self, tmp_path, monkeypatch):
        """§5.6 row 2 + §5.5: manual prior + import incoming → always ACCEPT."""
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)
        g = get_goal("Weight")
        _, reason = _apply_metric_value(g, 50.0, MetricSource.IMPORT, task_id=None)
        assert reason is None
        assert g.current_value == 50.0
        assert g.last_value_source == MetricSource.IMPORT

    def test_task_derived_prior_accepts_all(self, tmp_path, monkeypatch):
        """§5.6 row 4: task_derived prior → all incoming sources accepted.

        Each incoming source is tested against a freshly-planted task_derived
        prior, since applying one source changes the goal's last_value_source
        and the protection check depends on it."""
        _seed_metric_goal(tmp_path, monkeypatch)
        sources = [
            (MetricSource.MANUAL, "manual"),
            (MetricSource.MEASUREMENT, "measurement"),
            (MetricSource.TASK_DERIVED, "task_derived"),
            (MetricSource.IMPORT, "import"),
        ]
        for src, label in sources:
            g = get_goal("Weight")
            g.current_value = 77.0
            g.last_value_source = MetricSource.TASK_DERIVED
            g.last_value_updated_at = datetime.now(timezone.utc).isoformat()
            _, reason = _apply_metric_value(
                g, 76.0, src,
                task_id=None if src != MetricSource.TASK_DERIVED else "t2",
            )
            assert reason is None, f"{label} should be accepted after task_derived"
            assert g.current_value == 76.0
            assert g.last_value_source == label

    def test_import_prior_rejects_nothing(self, tmp_path, monkeypatch):
        """§5.6 row 5: import prior → all incoming sources accepted.

        Each incoming source is tested against a freshly-planted import
        prior, since applying one source changes the goal's last_value_source
        and the protection check depends on it."""
        sources = [
            (MetricSource.MANUAL, "manual"),
            (MetricSource.MEASUREMENT, "measurement"),
            (MetricSource.TASK_DERIVED, "task_derived"),
            (MetricSource.IMPORT, "import"),
        ]
        for src, label in sources:
            _seed_metric_goal(tmp_path, monkeypatch)
            g = get_goal("Weight")
            g.current_value = 77.0
            g.last_value_source = MetricSource.IMPORT
            g.last_value_updated_at = datetime.now(timezone.utc).isoformat()
            _, reason = _apply_metric_value(g, 50.0, src, task_id="t" if src == MetricSource.TASK_DERIVED else None)
            assert reason is None, f"{label} should be accepted after import"


# ── 3b. End-to-end: measurement ingest overrides protected manual ─────────────

class TestMeasurementOverridesProtectedManual:
    """§5.2 / §4.3: a measurement dispatched via ingest_activities overwrites
    a protected manual value (measurement always wins)."""

    def test_measurement_via_ingest_overwrites_manual(self, tmp_path, monkeypatch):
        from janus.services.activity_ingest import (
            ingest_activities, ActivityRecord, ActivityType,
        )
        _setup_ingest(tmp_path, monkeypatch)
        # Plant a protected manual value.
        update_goal_fields("Weight", current_value=77.0)
        assert get_goal("Weight").last_value_source == MetricSource.MANUAL

        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="scale_reader",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight",
            metric="Weight",
            value=69.0,
            unit="kg",
            date="2026-09-12",
        )
        result = ingest_activities([rec])
        assert result[0].accepted is True
        g = get_goal("Weight")
        assert g.current_value == 69.0
        assert g.last_value_source == MetricSource.MEASUREMENT

    def test_measurement_via_ingest_no_match_preserves_value(self, tmp_path, monkeypatch):
        from janus.services.activity_ingest import (
            ingest_activities, ActivityRecord, ActivityType,
        )
        """§4.4 / §4.3: measurement for a different metric does NOT update
        goal.current_value but still appends a snapshot to the history log."""
        _setup_ingest(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)

        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="scale_reader",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight",
            metric="Body fat",
            value=20.0,
            unit="%",
            date="2026-09-12",
        )
        ingest_activities([rec])
        g = get_goal("Weight")
        assert g.current_value == 77.0  # unchanged — metric mismatch
        # The measurement snapshot was still recorded in the history log.
        snaps = _snap_list(tmp_path)
        assert any(s.metric_name == "Body fat" for s in snaps)

    def test_measurement_via_ingest_appends_measurement_snapshot(self, tmp_path, monkeypatch):
        from janus.services.activity_ingest import (
            ingest_activities, ActivityRecord, ActivityType,
        )
        """§4.3: measurement ingestion appends a snapshot with source=measurement."""
        _setup_ingest(tmp_path, monkeypatch)
        rec = ActivityRecord(
            type=ActivityType.MEASUREMENT,
            source="scale_reader",
            timestamp=datetime(2026, 9, 12, tzinfo=timezone.utc),
            goal_title="Weight",
            metric="Weight",
            value=71.0,
            unit="kg",
            date="2026-09-12",
        )
        ingest_activities([rec])
        snaps = _snap_list(tmp_path)
        assert any(s.source == MetricSource.MEASUREMENT for s in snaps)


# ── 3c. Provenance metadata round-trip through persistence ─────────────────────

class TestProvenanceRoundTrip:
    """Verify provenance fields persist correctly through data/goals.md."""

    def test_task_derived_provenance_persisted(self, tmp_path, monkeypatch):
        gf = _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {"completed_at": "2026-09-09", "current_value": 76.0}
        update_goal_progress("Weight", "t_1", "Diet", evidence)
        content = gf.read_text()
        assert "LastValueSource: task_derived" in content
        assert "LastValueTaskId: t_1" in content
        assert "LastValueUpdatedAt:" in content

    def test_manual_provenance_no_task_id(self, tmp_path, monkeypatch):
        """Manual updates must NOT write LastValueTaskId (§3.2 / §9.1)."""
        gf = _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=79.0)
        content = gf.read_text()
        assert "LastValueSource: manual" in content
        assert "LastValueTaskId:" not in content

    def test_last_value_task_id_cleared_on_non_task_update(self, tmp_path, monkeypatch):
        """When a non-task-derived update overwrites a task_derived value,
        last_value_task_id is cleared."""
        _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {"completed_at": "2026-09-09", "current_value": 76.0}
        update_goal_progress("Weight", "t_1", "Task", evidence)
        assert get_goal("Weight").last_value_task_id == "t_1"
        # Manual update overwrites; task_id must be cleared.
        update_goal_fields("Weight", current_value=75.0)
        g = get_goal("Weight")
        assert g.last_value_source == MetricSource.MANUAL
        assert g.last_value_task_id is None

    def test_last_value_task_id_persisted_and_reloaded(self, tmp_path, monkeypatch):
        """Provenance fields survive a reload from goals.md."""
        gf = _seed_metric_goal(tmp_path, monkeypatch)
        evidence = {"completed_at": "2026-09-09", "current_value": 76.0}
        update_goal_progress("Weight", "t_survive", "Task", evidence)
        # Reload from file.
        g = get_goal("Weight")
        assert g.last_value_source == MetricSource.TASK_DERIVED
        assert g.last_value_task_id == "t_survive"
        assert g.last_value_updated_at is not None

    def test_provenance_fields_default_none_on_plain_goal(self, tmp_path, monkeypatch):
        """A goal loaded without provenance fields has None provenance
        (backward-compatible — preservation spec §3.3)."""
        _setup(tmp_path, monkeypatch,
               "# Goals\n\n## Goal: Plain\nStatus: active\nMetric: Steps\nCurrent: 1000\n")
        g = get_goal("Plain")
        assert g.last_value_source is None
        assert g.last_value_updated_at is None
        assert g.last_value_task_id is None


# ── 3d. Snapshot audit trail completeness ─────────────────────────────────────

class TestSnapshotAuditTrail:
    """Every accepted current_value mutation appends a snapshot with the
    correct source; rejected and idempotent updates do not (§7.2/§6.1)."""

    def test_manual_then_task_derived_appends_two_distinct(self, tmp_path, monkeypatch):
        """Two accepted mutations (manual + task_derived) produce two snapshots
        with the correct source labels.  The manual value is planted stale so
        the task_derived update is accepted (§5.1 protection window)."""
        _seed_metric_goal(tmp_path, monkeypatch)
        # Plant a stale manual value (outside protection window) so the
        # subsequent task_derived update is accepted.
        from janus.services.goals import update_goal
        g = get_goal("Weight")
        g.current_value = 79.0
        g.last_value_source = MetricSource.MANUAL
        g.last_value_updated_at = (
            datetime.now(timezone.utc)
            - timedelta(hours=MANUAL_VALUE_PROTECTION_WINDOW_HOURS + 1)
        ).isoformat()
        update_goal(g)
        # Manual snapshot (append_metric_snapshot is called inside update_goal_fields
        # but not update_goal; append one explicitly for the audit trail).
        from janus.integrations.metric_history import append_metric_snapshot
        append_metric_snapshot(MetricSnapshot(
            timestamp=datetime.now(timezone.utc).astimezone(),
            goal_title="Weight",
            metric_name="Weight",
            value=79.0,
            source=MetricSource.MANUAL,
        ))
        # Now a task_derived update (accepted since manual was stale).
        update_goal_progress(
            "Weight", "t_1", "Task",
            {"completed_at": "2026-09-09", "current_value": 76.0},
        )
        snaps = _snap_list(tmp_path)
        assert len(snaps) == 2
        assert snaps[0].source == MetricSource.MANUAL
        assert snaps[1].source == MetricSource.TASK_DERIVED
        assert snaps[0].value == 79.0
        assert snaps[1].value == 76.0

    def test_rejected_update_no_snapshot(self, tmp_path, monkeypatch):
        """§7.2: a rejected task_derived update (protected manual) does not
        append a snapshot."""
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)
        # Now a task_derived update that gets rejected.
        update_goal_progress(
            "Weight", "t_rej", "Task",
            {"completed_at": "2026-09-09", "current_value": 76.0},
        )
        snaps = _snap_list(tmp_path)
        assert len(snaps) == 1
        assert snaps[0].source == MetricSource.MANUAL

    def test_idempotent_update_no_duplicate_snapshot(self, tmp_path, monkeypatch):
        """§6.1: idempotent (same-value) update does not append a snapshot."""
        _seed_metric_goal(tmp_path, monkeypatch)
        update_goal_fields("Weight", current_value=77.0)
        before = len(_snap_list(tmp_path))
        # Idempotent: same value via task_derived → no-op, no new snapshot.
        update_goal_progress(
            "Weight", "t_idem", "Task",
            {"completed_at": "2026-09-09", "current_value": 77.0},
        )
        after = len(_snap_list(tmp_path))
        assert after == before


# ── 3e. add_goal does not set provenance (provenance only from mutations) ──────

class TestAddGoalNoProvenance:
    """add_goal creates a goal but does NOT set provenance fields — those are
    only populated by current_value mutations (§3.3: backward compat)."""

    def test_add_goal_with_current_value_no_provenance(self, tmp_path, monkeypatch):
        """Setting current_value at add_goal time does NOT populate provenance
        (it is a seed, not a mutation). The provenance fields stay None until
        a subsequent update_goal_fields call."""
        _setup(tmp_path, monkeypatch)
        g = add_goal(
            "Seeded", metric_name="Weight", current_value=80.0,
            start_value=82.0, target_value=70.0, direction="decrease",
        )
        assert g.current_value == 80.0
        assert g.last_value_source is None
        assert g.last_value_updated_at is None
        assert g.last_value_task_id is None

    def test_add_goal_then_update_sets_provenance(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        add_goal(
            "Seeded", metric_name="Weight", current_value=80.0,
            start_value=82.0, target_value=70.0, direction="decrease",
        )
        g = update_goal_fields("Seeded", current_value=79.0)
        assert g.last_value_source == MetricSource.MANUAL
        assert g.last_value_updated_at is not None

    def test_invalid_last_value_source_rejected_at_construction(self):
        """Goal.__post_init__ must reject an unknown last_value_source."""
        with pytest.raises(ValueError, match="Invalid last_value_source"):
            Goal(title="X", last_value_source="bogus")

    def test_non_task_source_with_task_id_cleared(self):
        """Goal.__post_init__ clears last_value_task_id when source != task_derived."""
        g = Goal(title="X", last_value_source=MetricSource.MANUAL,
                 last_value_task_id="t_123")
        assert g.last_value_task_id is None

    def test_task_source_with_task_id_preserved(self):
        """Goal.__post_init__ keeps last_value_task_id for task_derived source."""
        g = Goal(title="X", last_value_source=MetricSource.TASK_DERIVED,
                 last_value_task_id="t_123")
        assert g.last_value_task_id == "t_123"
