"""Tests for Commitment model — Phase C (Personal State)."""

from datetime import date, datetime

import pytest

from janus.models.commitment import Commitment, CommitmentStatus


class TestCommitment:
    """Tests for the Commitment model."""

    def test_create_minimal(self):
        """Test creating a minimal Commitment."""
        cm = Commitment(id="cm-1", title="Test commitment")
        assert cm.id == "cm-1"
        assert cm.title == "Test commitment"
        assert cm.status == CommitmentStatus.ACTIVE
        assert cm.due_date is None
        assert cm.created_at is not None
        assert cm.completed_at is None
        assert cm.linked_goal_title == ""
        assert cm.notes == ""

    def test_create_full(self):
        """Test creating a full Commitment."""
        now = datetime.now()
        due = date(2026, 12, 31)
        cm = Commitment(
            id="cm-2",
            title="Full commitment",
            status=CommitmentStatus.COMPLETED,
            due_date=due,
            created_at=now,
            completed_at=now,
            linked_goal_title="Goal 1",
            notes="Some notes",
        )
        assert cm.id == "cm-2"
        assert cm.title == "Full commitment"
        assert cm.status == CommitmentStatus.COMPLETED
        assert cm.due_date == due
        assert cm.created_at == now
        assert cm.completed_at == now
        assert cm.linked_goal_title == "Goal 1"
        assert cm.notes == "Some notes"

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            Commitment(id="", title="Test")

    def test_empty_title_raises(self):
        """Test that empty title raises ValueError."""
        with pytest.raises(ValueError, match="title must not be empty"):
            Commitment(id="cm-1", title="")

    def test_invalid_status_raises(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            Commitment(id="cm-1", title="Test", status="invalid")

    def test_status_values(self):
        """Test all status values."""
        for status in CommitmentStatus:
            cm = Commitment(id="cm-1", title="Test", status=status)
            assert cm.status == status

    def test_to_dict(self):
        """Test serialization to dict."""
        cm = Commitment(id="cm-1", title="Test")
        d = cm.to_dict()
        assert d["id"] == "cm-1"
        assert d["title"] == "Test"
        assert d["status"] == "active"
        assert "created_at" in d
