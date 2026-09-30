"""Tests for GapDetection model — Phase G (Self-Extending Skills)."""

from datetime import datetime

import pytest

from janus.models.gap_detection import GapDetection, GapStatus


class TestGapDetection:
    """Tests for the GapDetection model."""

    def test_create_minimal(self):
        """Test creating a minimal GapDetection."""
        gd = GapDetection(id="gd-1", description="Missing skill for X")
        assert gd.id == "gd-1"
        assert gd.description == "Missing skill for X"
        assert gd.status == GapStatus.DETECTED
        assert gd.detected_at is not None
        assert gd.context == ""
        assert gd.required_capability == ""
        assert gd.priority == 3
        assert gd.linked_task_title == ""
        assert gd.linked_goal_title == ""
        assert gd.notes == ""

    def test_create_full(self):
        """Test creating a full GapDetection."""
        now = datetime.now()
        gd = GapDetection(
            id="gd-2",
            description="Full gap",
            status=GapStatus.PROPOSED,
            detected_at=now,
            context="During task execution",
            required_capability="Python script for data processing",
            priority=5,
            linked_task_title="Task 1",
            linked_goal_title="Goal 1",
            notes="Some notes",
        )
        assert gd.id == "gd-2"
        assert gd.description == "Full gap"
        assert gd.status == GapStatus.PROPOSED
        assert gd.detected_at == now
        assert gd.context == "During task execution"
        assert gd.required_capability == "Python script for data processing"
        assert gd.priority == 5
        assert gd.linked_task_title == "Task 1"
        assert gd.linked_goal_title == "Goal 1"
        assert gd.notes == "Some notes"

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            GapDetection(id="", description="Test")

    def test_empty_description_raises(self):
        """Test that empty description raises ValueError."""
        with pytest.raises(ValueError, match="description must not be empty"):
            GapDetection(id="gd-1", description="")

    def test_invalid_status_raises(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            GapDetection(id="gd-1", description="Test", status="invalid")

    def test_invalid_priority_raises(self):
        """Test that invalid priority raises ValueError."""
        with pytest.raises(ValueError, match="Invalid priority"):
            GapDetection(id="gd-1", description="Test", priority=6)

    def test_status_values(self):
        """Test all status values."""
        for status in GapStatus:
            gd = GapDetection(id="gd-1", description="Test", status=status)
            assert gd.status == status

    def test_to_dict(self):
        """Test serialization to dict."""
        gd = GapDetection(id="gd-1", description="Test")
        d = gd.to_dict()
        assert d["id"] == "gd-1"
        assert d["description"] == "Test"
        assert d["status"] == "detected"
        assert "detected_at" in d
