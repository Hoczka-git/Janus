"""Tests for measurement_log.py.

All tests use temp fixtures ONLY — no real data files touched.
"""

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from janus.services.measurement_log import (
    MeasurementEntry,
    append_entry,
    find_entries_since,
    find_last_entry,
    load_entries,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(
    date_str: str,
    metric: str = "weight",
    value: float = 82.5,
    unit: str = "kg",
    goal_title: str = "Test Goal",
    collected_at: str | None = None,
) -> MeasurementEntry:
    return MeasurementEntry(
        date=date.fromisoformat(date_str),
        metric=metric,
        value=value,
        unit=unit,
        goal_title=goal_title,
        collected_at=datetime.fromisoformat(collected_at) if collected_at else None,
    )


def _write_jsonl(path: Path, entries: list[dict]) -> Path:
    with path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


# ---------------------------------------------------------------------------
# MeasurementEntry serialization
# ---------------------------------------------------------------------------

class TestMeasurementEntry:
    def test_to_json(self):
        entry = _entry("2026-09-06", collected_at="2026-09-06T07:15:00+02:00")
        result = entry.to_json()
        assert result["date"] == "2026-09-06"
        assert result["metric"] == "weight"
        assert result["value"] == 82.5
        assert result["unit"] == "kg"
        assert result["goal_title"] == "Test Goal"
        assert result["collected_at"] == "2026-09-06T07:15:00+02:00"

    def test_to_json_without_collected_at(self):
        entry = _entry("2026-09-06")
        result = entry.to_json()
        assert "collected_at" not in result or result.get("collected_at") is None

    def test_from_json(self):
        data = {
            "date": "2026-09-06",
            "metric": "weight",
            "value": 82.5,
            "unit": "kg",
            "goal_title": "Test Goal",
            "collected_at": "2026-09-06T07:15:00+02:00",
        }
        entry = MeasurementEntry.from_json(data)
        assert entry.date == date(2026, 9, 6)
        assert entry.metric == "weight"
        assert entry.value == 82.5
        assert entry.unit == "kg"
        assert entry.goal_title == "Test Goal"
        assert entry.collected_at == datetime.fromisoformat("2026-09-06T07:15:00+02:00")

    def test_from_json_minimal(self):
        data = {
            "date": "2026-09-06",
            "metric": "weight",
            "value": 70.0,
            "unit": "kg",
            "goal_title": "Test Goal",
        }
        entry = MeasurementEntry.from_json(data)
        assert entry.collected_at is None

    def test_roundtrip(self):
        entry = _entry("2026-09-06", collected_at="2026-09-06T07:15:00+02:00")
        json_data = entry.to_json()
        restored = MeasurementEntry.from_json(json_data)
        assert restored == entry


# ---------------------------------------------------------------------------
# load_entries
# ---------------------------------------------------------------------------

class TestLoadEntries:
    def test_valid_file(self, tmp_path):
        path = _write_jsonl(tmp_path / "measurements.jsonl", [
            {"date": "2026-09-06", "metric": "weight", "value": 82.5, "unit": "kg",
             "goal_title": "Body fat"},
            {"date": "2026-09-05", "metric": "waist", "value": 85.0, "unit": "cm",
             "goal_title": "Body fat", "collected_at": "2026-09-05T08:00:00+02:00"},
        ])
        entries = load_entries(path)
        assert len(entries) == 2
        assert entries[0].metric == "weight"
        assert entries[0].value == 82.5
        assert entries[1].metric == "waist"
        assert entries[1].collected_at is not None

    def test_missing_file_returns_empty(self, tmp_path):
        entries = load_entries(tmp_path / "nonexistent.jsonl")
        assert entries == []

    def test_empty_file_returns_empty(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        entries = load_entries(path)
        assert entries == []

    def test_blank_lines_skipped(self, tmp_path):
        path = tmp_path / "measurements.jsonl"
        path.write_text(
            "\n"
            '{"date": "2026-09-06", "metric": "weight", "value": 82.5, "unit": "kg", "goal_title": "G"}\n'
            "\n"
        )
        entries = load_entries(path)
        assert len(entries) == 1

    def test_malformed_line_skipped(self, tmp_path):
        path = tmp_path / "measurements.jsonl"
        path.write_text(
            '{"date": "2026-09-06", "metric": "weight", "value": 82.5, "unit": "kg", "goal_title": "G"}\n'
            'NOT VALID JSON\n'
        )
        entries = load_entries(path)
        assert len(entries) == 1  # malformed line skipped

    def test_default_path(self, tmp_path, monkeypatch):
        """When path is None, uses MEASUREMENTS_PATH."""
        log_path = tmp_path / "measurements.jsonl"
        _write_jsonl(log_path, [
            {"date": "2026-09-06", "metric": "weight", "value": 82.5, "unit": "kg",
             "goal_title": "G"},
        ])
        monkeypatch.setattr("janus.services.measurement_log.MEASUREMENTS_PATH", log_path)
        entries = load_entries()
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# find_last_entry
# ---------------------------------------------------------------------------

class TestFindLastEntry:
    def test_found(self):
        entries = [
            _entry("2026-09-01", metric="weight", value=85.0),
            _entry("2026-09-05", metric="weight", value=82.5),
            _entry("2026-09-03", metric="weight", value=83.0),
        ]
        result = find_last_entry(entries, "Test Goal", "weight")
        assert result is not None
        assert result.date == date(2026, 9, 5)
        assert result.value == 82.5

    def test_not_found_returns_none(self):
        entries = [_entry("2026-09-05")]
        result = find_last_entry(entries, "Test Goal", "nonexistent")
        assert result is None

    def test_empty_entries_returns_none(self):
        result = find_last_entry([], "Test Goal", "weight")
        assert result is None

    def test_filters_by_goal_and_metric(self):
        entries = [
            _entry("2026-09-05", metric="weight", value=82.5, goal_title="Goal A"),
            _entry("2026-09-06", metric="weight", value=80.0, goal_title="Goal B"),
            _entry("2026-09-04", metric="waist", value=85.0, goal_title="Goal A"),
        ]
        result = find_last_entry(entries, "Goal A", "weight")
        assert result is not None
        assert result.date == date(2026, 9, 5)


# ---------------------------------------------------------------------------
# find_entries_since
# ---------------------------------------------------------------------------

class TestFindEntriesSince:
    def test_returns_entries_on_or_after_since(self):
        entries = [
            _entry("2026-09-01"),
            _entry("2026-09-03"),
            _entry("2026-09-05"),
            _entry("2026-09-07"),
        ]
        result = find_entries_since(entries, "Test Goal", "weight", date(2026, 9, 3))
        assert len(result) == 3
        assert result[0].date == date(2026, 9, 3)
        assert result[2].date == date(2026, 9, 7)

    def test_no_matching_entries(self):
        entries = [_entry("2026-09-05", metric="weight")]
        result = find_entries_since(entries, "Test Goal", "waist", date(2026, 9, 1))
        assert result == []

    def test_since_date_equal_to_entry_date(self):
        entries = [_entry("2026-09-05")]
        result = find_entries_since(entries, "Test Goal", "weight", date(2026, 9, 5))
        assert len(result) == 1


# ---------------------------------------------------------------------------
# append_entry
# ---------------------------------------------------------------------------

class TestAppendEntry:
    def test_appends_to_new_file(self, tmp_path):
        path = tmp_path / "measurements.jsonl"
        entry = _entry("2026-09-06")
        append_entry(path, entry)
        data = path.read_text().strip()
        parsed = json.loads(data)
        assert parsed["date"] == "2026-09-06"
        assert parsed["metric"] == "weight"

    def test_appends_to_existing_file(self, tmp_path):
        path = _write_jsonl(tmp_path / "measurements.jsonl", [
            {"date": "2026-09-05", "metric": "weight", "value": 82.5, "unit": "kg",
             "goal_title": "G"},
        ])
        entry = _entry("2026-09-06", value=81.0)
        append_entry(path, entry)
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[1])["value"] == 81.0

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "subdir" / "measurements.jsonl"
        entry = _entry("2026-09-06")
        append_entry(path, entry)
        assert path.exists()

    def test_appends_with_collected_at(self, tmp_path):
        path = tmp_path / "measurements.jsonl"
        entry = _entry("2026-09-06", collected_at="2026-09-06T07:15:00+02:00")
        append_entry(path, entry)
        parsed = json.loads(path.read_text().strip())
        assert parsed["collected_at"] == "2026-09-06T07:15:00+02:00"
