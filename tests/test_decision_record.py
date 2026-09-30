"""Tests for DecisionRecord model — §9.2 (6-stage decision record shape)."""

from datetime import datetime

import pytest

from janus.models.decision_record import DecisionRecord, DecisionRecordStatus


class TestDecisionRecord:
    """Tests for the DecisionRecord model."""

    def test_create_minimal(self):
        """Test creating a minimal DecisionRecord."""
        dr = DecisionRecord(id="dr-1", title="Test decision")
        assert dr.id == "dr-1"
        assert dr.title == "Test decision"
        assert dr.status == DecisionRecordStatus.DRAFT
        assert dr.why == ""
        assert dr.what == ""
        assert dr.action == ""
        assert dr.evidence == ""
        assert dr.result == ""
        assert dr.decision == ""
        assert dr.created_at is not None
        assert dr.updated_at is not None
        assert dr.linked_goal_title == ""
        assert dr.linked_adr == ""
        assert dr.tags == []

    def test_create_full(self):
        """Test creating a full DecisionRecord."""
        now = datetime.now()
        dr = DecisionRecord(
            id="dr-2",
            title="Full decision",
            status=DecisionRecordStatus.ACCEPTED,
            why="Need to improve performance",
            what="Optimize database queries",
            action="Add indexes and optimize queries",
            evidence="Query performance analysis",
            result="50% performance improvement",
            decision="Proceed with optimization",
            created_at=now,
            updated_at=now,
            linked_goal_title="Goal 1",
            linked_adr="001",
            tags=["performance", "database"],
        )
        assert dr.id == "dr-2"
        assert dr.title == "Full decision"
        assert dr.status == DecisionRecordStatus.ACCEPTED
        assert dr.why == "Need to improve performance"
        assert dr.what == "Optimize database queries"
        assert dr.action == "Add indexes and optimize queries"
        assert dr.evidence == "Query performance analysis"
        assert dr.result == "50% performance improvement"
        assert dr.decision == "Proceed with optimization"
        assert dr.created_at == now
        assert dr.updated_at == now
        assert dr.linked_goal_title == "Goal 1"
        assert dr.linked_adr == "001"
        assert dr.tags == ["performance", "database"]

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            DecisionRecord(id="", title="Test")

    def test_empty_title_raises(self):
        """Test that empty title raises ValueError."""
        with pytest.raises(ValueError, match="title must not be empty"):
            DecisionRecord(id="dr-1", title="")

    def test_invalid_status_raises(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            DecisionRecord(id="dr-1", title="Test", status="invalid")

    def test_status_values(self):
        """Test all status values."""
        for status in DecisionRecordStatus:
            dr = DecisionRecord(id="dr-1", title="Test", status=status)
            assert dr.status == status

    def test_is_complete_false(self):
        """Test is_complete returns False when stages are empty."""
        dr = DecisionRecord(id="dr-1", title="Test")
        assert dr.is_complete is False

    def test_is_complete_true(self):
        """Test is_complete returns True when all stages are filled."""
        dr = DecisionRecord(
            id="dr-1",
            title="Test",
            why="why",
            what="what",
            action="action",
            evidence="evidence",
            result="result",
            decision="decision",
        )
        assert dr.is_complete is True

    def test_completion_percentage(self):
        """Test completion_percentage calculation."""
        dr = DecisionRecord(id="dr-1", title="Test")
        assert dr.completion_percentage == 0.0

        dr.why = "why"
        assert dr.completion_percentage == 1.0 / 6.0

        dr.what = "what"
        assert dr.completion_percentage == 2.0 / 6.0

        dr.action = "action"
        dr.evidence = "evidence"
        dr.result = "result"
        dr.decision = "decision"
        assert dr.completion_percentage == 1.0

    def test_tags_dedup(self):
        """Test that tags are deduplicated."""
        dr = DecisionRecord(id="dr-1", title="Test", tags=["a", "b", "a"])
        assert dr.tags == ["a", "b"]

    def test_to_dict(self):
        """Test serialization to dict."""
        dr = DecisionRecord(id="dr-1", title="Test")
        d = dr.to_dict()
        assert d["id"] == "dr-1"
        assert d["title"] == "Test"
        assert d["status"] == "draft"
        assert d["is_complete"] is False
        assert d["completion_percentage"] == 0.0
        assert "created_at" in d
        assert "updated_at" in d
