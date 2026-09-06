"""Tests for append-only metric snapshot history (data/metric_history.md).

Tests snapshot append, query, parsing, and file-creation-on-first-snapshot.
"""

from datetime import datetime, timezone

import pytest

from janus.integrations.metric_history import (
    METRIC_HISTORY_PATH,
    MetricSnapshot,
    append_metric_snapshot,
    get_metric_snapshots,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_snapshot(
    timestamp: str, goal_title: str, metric_name: str, value: float, source: str = "manual"
) -> MetricSnapshot:
    return MetricSnapshot(
        timestamp=datetime.fromisoformat(timestamp),
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )


def _ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str)


# ===========================================================================
# 1. append_metric_snapshot
# ===========================================================================

class TestAppendSnapshot:
    def test_creates_file_on_first_snapshot(self, tmp_path, monkeypatch):
        """Metric history file is created on first snapshot (not pre-created)."""
        hist_path = tmp_path / "metric_history.md"
        monkeypatch.setattr("janus.integrations.metric_history.METRIC_HISTORY_PATH", hist_path)
        assert not hist_path.exists()

        snap = _make_snapshot("2026-09-06T10:00:00+02:00", "Body fat", "Body fat %", 20.0)
        append_metric_snapshot(snap, path=hist_path)

        assert hist_path.exists()

    def test_first_snapshot_includes_header(self, tmp_path, monkeypatch):
        hist_path = tmp_path / "metric_history.md"
        monkeypatch.setattr("janus.integrations.metric_history.METRIC_HISTORY_PATH", hist_path)

        snap = _make_snapshot("2026-09-06T10:00:00+02:00", "Body fat", "Body fat %", 20.0)
        append_metric_snapshot(snap, path=hist_path)

        content = hist_path.read_text()
        assert "# Metric History" in content
        assert "# Format:" in content
        assert "20.0" in content
        assert "Body fat" in content

    def test_append_only_preserves_existing(self, tmp_path, monkeypatch):
        """Snapshots are append-only — existing entries are never modified."""
        hist_path = tmp_path / "metric_history.md"
        monkeypatch.setattr("janus.integrations.metric_history.METRIC_HISTORY_PATH", hist_path)

        snap1 = _make_snapshot("2026-09-06T10:00:00+02:00", "Body fat", "Body fat %", 20.0)
        snap2 = _make_snapshot("2026-09-13T10:00:00+02:00", "Body fat", "Body fat %", 19.5)

        append_metric_snapshot(snap1, path=hist_path)
        append_metric_snapshot(snap2, path=hist_path)

        content = hist_path.read_text()
        lines = [l for l in content.splitlines() if l.startswith("# 2026")]
        assert len(lines) == 2
        assert "20.0" in lines[0]
        assert "19.5" in lines[1]

    def test_no_header_on_subsequent_appends(self, tmp_path, monkeypatch):
        """Header is only written once (on file creation)."""
        hist_path = tmp_path / "metric_history.md"
        monkeypatch.setattr("janus.integrations.metric_history.METRIC_HISTORY_PATH", hist_path)

        snap1 = _make_snapshot("2026-09-06T10:00:00+02:00", "G", "m", 1.0)
        snap2 = _make_snapshot("2026-09-07T10:00:00+02:00", "G", "m", 2.0)
        append_metric_snapshot(snap1, path=hist_path)
        append_metric_snapshot(snap2, path=hist_path)

        content = hist_path.read_text()
        assert content.count("# Metric History") == 1
        assert content.count("# Format:") == 1


# ===========================================================================
# 2. get_metric_snapshots
# ===========================================================================

class TestGetMetricSnapshots:
    def test_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        hist_path = tmp_path / "metric_history.md"
        monkeypatch.setattr("janus.integrations.metric_history.METRIC_HISTORY_PATH", hist_path)
        result = get_metric_snapshots("Body fat", path=hist_path)
        assert result == []

    def test_returns_matching_goal(self, tmp_path, monkeypatch):
        hist_path = tmp_path / "metric_history.md"
        snap1 = _make_snapshot("2026-09-06T10:00:00+02:00", "Body fat", "Body fat %", 20.0)
        snap2 = _make_snapshot("2026-09-06T11:00:00+02:00", "Other", "Weight", 70.0)
        append_metric_snapshot(snap1, path=hist_path)
        append_metric_snapshot(snap2, path=hist_path)

        result = get_metric_snapshots("Body fat", path=hist_path)
        assert len(result) == 1
        assert result[0].value == 20.0
        assert result[0].goal_title == "Body fat"

    def test_sorted_by_timestamp(self, tmp_path, monkeypatch):
        hist_path = tmp_path / "metric_history.md"
        snap1 = _make_snapshot("2026-09-13T10:00:00+02:00", "G", "m", 2.0)
        snap2 = _make_snapshot("2026-09-06T10:00:00+02:00", "G", "m", 1.0)
        snap3 = _make_snapshot("2026-09-20T10:00:00+02:00", "G", "m", 3.0)
        append_metric_snapshot(snap1, path=hist_path)
        append_metric_snapshot(snap2, path=hist_path)
        append_metric_snapshot(snap3, path=hist_path)

        result = get_metric_snapshots("G", path=hist_path)
        assert [s.value for s in result] == [1.0, 2.0, 3.0]

    def test_filtered_by_since(self, tmp_path, monkeypatch):
        hist_path = tmp_path / "metric_history.md"
        snap1 = _make_snapshot("2026-09-06T10:00:00+02:00", "G", "m", 1.0)
        snap2 = _make_snapshot("2026-09-20T10:00:00+02:00", "G", "m", 3.0)
        append_metric_snapshot(snap1, path=hist_path)
        append_metric_snapshot(snap2, path=hist_path)

        since = _ts("2026-09-15T00:00:00+02:00")
        result = get_metric_snapshots("G", since=since, path=hist_path)
        assert len(result) == 1
        assert result[0].value == 3.0

    def test_filtered_by_until(self, tmp_path, monkeypatch):
        hist_path = tmp_path / "metric_history.md"
        snap1 = _make_snapshot("2026-09-06T10:00:00+02:00", "G", "m", 1.0)
        snap2 = _make_snapshot("2026-09-20T10:00:00+02:00", "G", "m", 3.0)
        append_metric_snapshot(snap1, path=hist_path)
        append_metric_snapshot(snap2, path=hist_path)

        until = _ts("2026-09-15T00:00:00+02:00")
        result = get_metric_snapshots("G", until=until, path=hist_path)
        assert len(result) == 1
        assert result[0].value == 1.0

    def test_filtered_by_since_and_until(self, tmp_path, monkeypatch):
        hist_path = tmp_path / "metric_history.md"
        for ts, val in [
            ("2026-09-01T10:00:00+02:00", 1.0),
            ("2026-09-10T10:00:00+02:00", 2.0),
            ("2026-09-20T10:00:00+02:00", 3.0),
        ]:
            append_metric_snapshot(
                _make_snapshot(ts, "G", "m", val), path=hist_path
            )

        since = _ts("2026-09-05T00:00:00+02:00")
        until = _ts("2026-09-15T00:00:00+02:00")
        result = get_metric_snapshots("G", since=since, until=until, path=hist_path)
        assert len(result) == 1
        assert result[0].value == 2.0

    def test_skips_malformed_lines(self, tmp_path, monkeypatch):
        hist_path = tmp_path / "metric_history.md"
        snap = _make_snapshot("2026-09-06T10:00:00+02:00", "G", "m", 1.0)
        append_metric_snapshot(snap, path=hist_path)
        # Append a malformed line manually
        with hist_path.open("a") as f:
            f.write("# not enough fields | only one\n")
            f.write("# bad_ts | G | m | not_a_number | manual\n")

        result = get_metric_snapshots("G", path=hist_path)
        assert len(result) == 1
        assert result[0].value == 1.0
