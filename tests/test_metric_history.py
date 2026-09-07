<<<<<<< HEAD
"""Tests for metric_history.py persistence layer.

Covers §12.4 acceptance criteria:
- get_metric_snapshots returns correct snapshots filtered by time range
- Metric history file is created on first snapshot (not pre-activated)
- Snapshots are append-only (existing entries never modified or deleted)
- append_snapshot creates the file with header if it doesn't exist
- load_snapshots handles missing files and malformed lines
"""

from datetime import datetime, timezone, timedelta
=======
"""Tests for append-only metric snapshot history (data/metric_history.md).

Tests snapshot append, query, parsing, and file-creation-on-first-snapshot.
"""

from datetime import datetime, timezone
>>>>>>> origin/master

import pytest

from janus.integrations.metric_history import (
<<<<<<< HEAD
    MetricSnapshot,
    load_snapshots,
    get_metric_snapshots,
    append_snapshot,
    METRIC_HISTORY_PATH,
)


def _snap(dt_str, goal_title="G", metric_name="Metric", value=10.0, source="manual"):
    """Helper: create a MetricSnapshot from an ISO date string."""
    return MetricSnapshot(
        timestamp=datetime.fromisoformat(dt_str),
=======
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
>>>>>>> origin/master
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )


<<<<<<< HEAD
# =============================================================================
# §12.4 Metric Snapshot History
# =============================================================================

class TestLoadSnapshots:
    def test_empty_list_when_file_missing(self, tmp_path):
        """load_snapshots returns empty list when file doesn't exist."""
        missing = tmp_path / "nonexistent.md"
        assert load_snapshots(missing) == []

    def test_load_valid_snapshots(self, tmp_path):
        """load_snapshots parses valid lines correctly."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "# Metric History\n"
            "# Format: ISO-timestamp | goal_title | metric_name | value | source\n"
            "2026-09-06T10:00:00+02:00 | Body fat | Body fat % | 20.0 | manual\n"
            "2026-09-13T10:00:00+02:00 | Body fat | Body fat % | 19.5 | manual\n"
        )
        snaps = load_snapshots(history)
        assert len(snaps) == 2
        assert snaps[0].value == 20.0
        assert snaps[1].value == 19.5
        assert snaps[0].goal_title == "Body fat"
        assert snaps[0].metric_name == "Body fat %"
        assert snaps[0].source == "manual"

    def test_skip_comment_lines(self, tmp_path):
        """load_snapshots skips all comment lines (starting with #)."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "# Metric History\n"
            "# Format: ...\n"
            "2026-09-06T10:00:00+02:00 | G | M | 10.0 | manual\n"
        )
        snaps = load_snapshots(history)
        assert len(snaps) == 1

    def test_skip_malformed_lines(self, tmp_path):
        """load_snapshots skips malformed lines without crashing."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "# Metric History\n"
            "not a valid line\n"
            "2026-09-06T10:00:00+02:00 | G | M | not_a_number | manual\n"
            "2026-09-06T10:00:00+02:00 | G | M | 10.0 | manual\n"
        )
        snaps = load_snapshots(history)
        assert len(snaps) == 1  # only the valid one

    def test_skip_missing_fields(self, tmp_path):
        """load_snapshots skips lines with too few fields."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "2026-09-06T10:00:00+02:00 | G | M | 10.0\n"  # only 4 fields
        )
        snaps = load_snapshots(history)
        assert len(snaps) == 0

    def test_skip_empty_goal_or_metric(self, tmp_path):
        """load_snapshots skips lines with empty goal_title or metric_name."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "2026-09-06T10:00:00+02:00 |  | M | 10.0 | manual\n"
            "2026-09-06T10:00:00+02:00 | G |  | 10.0 | manual\n"
            "2026-09-06T10:00:00+02:00 | G | M | 10.0 | manual\n"
        )
        snaps = load_snapshots(history)
        assert len(snaps) == 1


class TestGetMetricSnapshots:
    def test_filter_by_goal_title(self, tmp_path):
        """get_metric_snapshots filters by goal_title."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "2026-09-06T10:00:00+02:00 | Goal A | M | 10.0 | manual\n"
            "2026-09-07T10:00:00+02:00 | Goal B | M | 20.0 | manual\n"
            "2026-09-08T10:00:00+02:00 | Goal A | M | 15.0 | manual\n"
        )
        snaps = get_metric_snapshots("Goal A", path=history)
        assert len(snaps) == 2
        assert all(s.goal_title == "Goal A" for s in snaps)

    def test_filter_by_since(self, tmp_path):
        """get_metric_snapshots filters by since (inclusive)."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "2026-09-01T10:00:00+02:00 | G | M | 10.0 | manual\n"
            "2026-09-05T10:00:00+02:00 | G | M | 20.0 | manual\n"
            "2026-09-10T10:00:00+02:00 | G | M | 30.0 | manual\n"
        )
        since = datetime.fromisoformat("2026-09-05T00:00:00+02:00")
        snaps = get_metric_snapshots("G", since=since, path=history)
        assert len(snaps) == 2
        assert snaps[0].value == 20.0
        assert snaps[1].value == 30.0

    def test_filter_by_until(self, tmp_path):
        """get_metric_snapshots filters by until (inclusive)."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "2026-09-01T10:00:00+02:00 | G | M | 10.0 | manual\n"
            "2026-09-05T10:00:00+02:00 | G | M | 20.0 | manual\n"
            "2026-09-10T10:00:00+02:00 | G | M | 30.0 | manual\n"
        )
        until = datetime.fromisoformat("2026-09-05T23:59:59+02:00")
        snaps = get_metric_snapshots("G", until=until, path=history)
        assert len(snaps) == 2
        assert snaps[0].value == 10.0
        assert snaps[1].value == 20.0

    def test_filter_by_since_and_until(self, tmp_path):
        """get_metric_snapshots filters by both since and until."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "2026-09-01T10:00:00+02:00 | G | M | 10.0 | manual\n"
            "2026-09-05T10:00:00+02:00 | G | M | 20.0 | manual\n"
            "2026-09-10T10:00:00+02:00 | G | M | 30.0 | manual\n"
            "2026-09-15T10:00:00+02:00 | G | M | 40.0 | manual\n"
        )
        since = datetime.fromisoformat("2026-09-05T00:00:00+02:00")
        until = datetime.fromisoformat("2026-09-10T23:59:59+02:00")
        snaps = get_metric_snapshots("G", since=since, until=until, path=history)
        assert len(snaps) == 2
        assert snaps[0].value == 20.0
        assert snaps[1].value == 30.0

    def test_results_sorted_by_timestamp(self, tmp_path):
        """get_metric_snapshots returns results sorted by timestamp ascending."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "2026-09-10T10:00:00+02:00 | G | M | 30.0 | manual\n"
            "2026-09-01T10:00:00+02:00 | G | M | 10.0 | manual\n"
            "2026-09-05T10:00:00+02:00 | G | M | 20.0 | manual\n"
        )
        snaps = get_metric_snapshots("G", path=history)
        assert len(snaps) == 3
        assert snaps[0].value == 10.0
        assert snaps[1].value == 20.0
        assert snaps[2].value == 30.0

    def test_empty_when_goal_not_found(self, tmp_path):
        """get_metric_snapshots returns empty when goal has no snapshots."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "2026-09-06T10:00:00+02:00 | Other | M | 10.0 | manual\n"
        )
        snaps = get_metric_snapshots("Missing", path=history)
        assert len(snaps) == 0

    def test_accepts_date_for_since_until(self, tmp_path):
        """get_metric_snapshots accepts date objects for since/until."""
        from datetime import date
        history = tmp_path / "metric_history.md"
        history.write_text(
            "2026-09-01T10:00:00+02:00 | G | M | 10.0 | manual\n"
            "2026-09-05T10:00:00+02:00 | G | M | 20.0 | manual\n"
            "2026-09-10T10:00:00+02:00 | G | M | 30.0 | manual\n"
        )
        since = date(2026, 9, 5)
        snaps = get_metric_snapshots("G", since=since, path=history)
        assert len(snaps) == 2  # 9-05 and 9-10


class TestAppendSnapshot:
    def test_creates_file_with_header(self, tmp_path):
        """append_snapshot creates the file with header on first write."""
        history = tmp_path / "metric_history.md"
        snap = _snap("2026-09-06T10:00:00+02:00", value=20.0)
        append_snapshot(snap, path=history)
        assert history.exists()
        content = history.read_text()
        assert "# Metric History" in content
        assert "# Format:" in content
        assert "20.0" in content

    def test_appends_to_existing_file(self, tmp_path):
        """append_snapshot appends to an existing file without rewriting."""
        history = tmp_path / "metric_history.md"
        history.write_text(
            "# Metric History\n"
            "# Format: ISO-timestamp | goal_title | metric_name | value | source\n"
            "2026-09-01T10:00:00+02:00 | G | M | 10.0 | manual\n"
        )
        snap = _snap("2026-09-06T10:00:00+02:00", value=20.0)
        append_snapshot(snap, path=history)
        lines = history.read_text().strip().split("\n")
        # header (2 lines) + first entry + second entry
        assert len(lines) == 4
        # Verify the existing entry is preserved
        assert "10.0" in lines[2]
        assert "20.0" in lines[3]

    def test_append_only_no_modification(self, tmp_path):
        """Existing entries are never modified by append_snapshot."""
        history = tmp_path / "metric_history.md"
        snap1 = _snap("2026-09-01T10:00:00+02:00", value=10.0)
        snap2 = _snap("2026-09-06T10:00:00+02:00", value=20.0)
        snap3 = _snap("2026-09-10T10:00:00+02:00", value=30.0)
        append_snapshot(snap1, path=history)
        append_snapshot(snap2, path=history)
        append_snapshot(snap3, path=history)
        snaps = load_snapshots(history)
        assert len(snaps) == 3
        assert snaps[0].value == 10.0
        assert snaps[1].value == 20.0
        assert snaps[2].value == 30.0
        # Verify the first entry was not modified
        content = history.read_text()
        first_data_line = [l for l in content.split("\n") if "10.0" in l and "G" in l][0]
        assert "2026-09-01T10:00:00" in first_data_line

    def test_creates_parent_directory(self, tmp_path):
        """append_snapshot creates parent directories if needed."""
        history = tmp_path / "subdir" / "nested" / "metric_history.md"
        snap = _snap("2026-09-06T10:00:00+02:00", value=20.0)
        append_snapshot(snap, path=history)
        assert history.exists()
        assert history.parent.exists()

    def test_snapshot_with_different_sources(self, tmp_path):
        """append_snapshot records different source types."""
        history = tmp_path / "metric_history.md"
        snap1 = _snap("2026-09-01T10:00:00+02:00", value=10.0, source="manual")
        snap2 = _snap("2026-09-06T10:00:00+02:00", value=20.0, source="measurement")
        snap3 = _snap("2026-09-10T10:00:00+02:00", value=30.0, source="import")
        append_snapshot(snap1, path=history)
        append_snapshot(snap2, path=history)
        append_snapshot(snap3, path=history)
        snaps = load_snapshots(history)
        assert len(snaps) == 3
        assert snaps[0].source == "manual"
        assert snaps[1].source == "measurement"
        assert snaps[2].source == "import"
=======
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
>>>>>>> origin/master
