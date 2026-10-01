"""Tests for OutcomeRecord model — Phase B (Evidence & Audit)."""

from datetime import datetime

import pytest

from janus.models.outcome_record import OutcomeRecord, OutcomeStatus


class TestOutcomeRecord:
    """Tests for the OutcomeRecord model."""

    def test_create_minimal(self):
        """Test creating a minimal OutcomeRecord."""
        record = OutcomeRecord(id="or-1", title="Test outcome")
        assert record.id == "or-1"
        assert record.title == "Test outcome"
        assert record.status == OutcomeStatus.SUCCESS
        assert record.attempted == ""
        assert record.result == ""
        assert record.learned == ""
        assert record.linked_task_title == ""
        assert record.linked_goal_title == ""
        assert record.linked_adr == ""
        assert record.tags == []
        assert record.created_at is not None

    def test_create_full(self):
        """Test creating a full OutcomeRecord."""
        now = datetime.now()
        record = OutcomeRecord(
            id="or-2",
            title="Full outcome",
            status=OutcomeStatus.PARTIAL,
            attempted="Attempted to implement feature X",
            result="Partially implemented feature X",
            learned="Need more time for full implementation",
            linked_task_title="Task 1",
            linked_goal_title="Goal 1",
            linked_adr="001",
            created_at=now,
            tags=["feature", "partial"],
        )
        assert record.id == "or-2"
        assert record.title == "Full outcome"
        assert record.status == OutcomeStatus.PARTIAL
        assert record.attempted == "Attempted to implement feature X"
        assert record.result == "Partially implemented feature X"
        assert record.learned == "Need more time for full implementation"
        assert record.linked_task_title == "Task 1"
        assert record.linked_goal_title == "Goal 1"
        assert record.linked_adr == "001"
        assert record.created_at == now
        assert record.tags == ["feature", "partial"]

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            OutcomeRecord(id="", title="Test")

    def test_empty_title_raises(self):
        """Test that empty title raises ValueError."""
        with pytest.raises(ValueError, match="title must not be empty"):
            OutcomeRecord(id="or-1", title="")

    def test_invalid_status_raises(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            OutcomeRecord(id="or-1", title="Test", status="invalid")

    def test_status_values(self):
        """Test all status values."""
        for status in OutcomeStatus:
            record = OutcomeRecord(id="or-1", title="Test", status=status)
            assert record.status == status

    def test_tags_dedup(self):
        """Test that tags are deduplicated."""
        record = OutcomeRecord(id="or-1", title="Test", tags=["a", "b", "a"])
        assert record.tags == ["a", "b"]

    def test_to_dict(self):
        """Test serialization to dict."""
        record = OutcomeRecord(
            id="or-1",
            title="Test",
            status=OutcomeStatus.SUCCESS,
            tags=["test"],
        )
        d = record.to_dict()
        assert d["id"] == "or-1"
        assert d["title"] == "Test"
        assert d["status"] == "success"
        assert d["tags"] == ["test"]
        assert "created_at" in d
