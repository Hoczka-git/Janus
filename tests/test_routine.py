"""Tests for Routine model — Phase C (Personal State)."""

from datetime import datetime

import pytest

from janus.models.routine import Routine, RoutineFrequency


class TestRoutine:
    """Tests for the Routine model."""

    def test_create_minimal(self):
        """Test creating a minimal Routine."""
        rt = Routine(id="rt-1", title="Test routine")
        assert rt.id == "rt-1"
        assert rt.title == "Test routine"
        assert rt.frequency == RoutineFrequency.DAILY
        assert rt.status == "active"
        assert rt.created_at is not None
        assert rt.last_completed is None
        assert rt.streak == 0
        assert rt.linked_goal_title == ""
        assert rt.notes == ""

    def test_create_full(self):
        """Test creating a full Routine."""
        now = datetime.now()
        rt = Routine(
            id="rt-2",
            title="Full routine",
            frequency=RoutineFrequency.WEEKLY,
            status="paused",
            created_at=now,
            last_completed=now,
            streak=5,
            linked_goal_title="Goal 1",
            notes="Some notes",
        )
        assert rt.id == "rt-2"
        assert rt.title == "Full routine"
        assert rt.frequency == RoutineFrequency.WEEKLY
        assert rt.status == "paused"
        assert rt.created_at == now
        assert rt.last_completed == now
        assert rt.streak == 5
        assert rt.linked_goal_title == "Goal 1"
        assert rt.notes == "Some notes"

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            Routine(id="", title="Test")

    def test_empty_title_raises(self):
        """Test that empty title raises ValueError."""
        with pytest.raises(ValueError, match="title must not be empty"):
            Routine(id="rt-1", title="")

    def test_invalid_frequency_raises(self):
        """Test that invalid frequency raises ValueError."""
        with pytest.raises(ValueError, match="Invalid frequency"):
            Routine(id="rt-1", title="Test", frequency="invalid")

    def test_invalid_status_raises(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            Routine(id="rt-1", title="Test", status="invalid")

    def test_frequency_values(self):
        """Test all frequency values."""
        for freq in RoutineFrequency:
            rt = Routine(id="rt-1", title="Test", frequency=freq)
            assert rt.frequency == freq

    def test_to_dict(self):
        """Test serialization to dict."""
        rt = Routine(id="rt-1", title="Test")
        d = rt.to_dict()
        assert d["id"] == "rt-1"
        assert d["title"] == "Test"
        assert d["frequency"] == "daily"
        assert "created_at" in d
