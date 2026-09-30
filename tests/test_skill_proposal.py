"""Tests for SkillProposal model — Phase G (Self-Extending Skills)."""

from datetime import datetime

import pytest

from janus.models.skill_proposal import SkillProposal, ProposalStatus


class TestSkillProposal:
    """Tests for the SkillProposal model."""

    def test_create_minimal(self):
        """Test creating a minimal SkillProposal."""
        sp = SkillProposal(id="sp-1", title="Test proposal")
        assert sp.id == "sp-1"
        assert sp.title == "Test proposal"
        assert sp.description == ""
        assert sp.status == ProposalStatus.PROPOSED
        assert sp.proposed_at is not None
        assert sp.approved_at is None
        assert sp.gap_id == ""
        assert sp.proposed_code == ""
        assert sp.proposed_tests == ""
        assert sp.estimated_effort == "medium"
        assert sp.notes == ""

    def test_create_full(self):
        """Test creating a full SkillProposal."""
        now = datetime.now()
        sp = SkillProposal(
            id="sp-2",
            title="Full proposal",
            description="Detailed description",
            status=ProposalStatus.APPROVED,
            proposed_at=now,
            approved_at=now,
            gap_id="gd-1",
            proposed_code="print('hello')",
            proposed_tests="def test(): pass",
            estimated_effort="high",
            notes="Some notes",
        )
        assert sp.id == "sp-2"
        assert sp.title == "Full proposal"
        assert sp.description == "Detailed description"
        assert sp.status == ProposalStatus.APPROVED
        assert sp.proposed_at == now
        assert sp.approved_at == now
        assert sp.gap_id == "gd-1"
        assert sp.proposed_code == "print('hello')"
        assert sp.proposed_tests == "def test(): pass"
        assert sp.estimated_effort == "high"
        assert sp.notes == "Some notes"

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            SkillProposal(id="", title="Test")

    def test_empty_title_raises(self):
        """Test that empty title raises ValueError."""
        with pytest.raises(ValueError, match="title must not be empty"):
            SkillProposal(id="sp-1", title="")

    def test_invalid_status_raises(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            SkillProposal(id="sp-1", title="Test", status="invalid")

    def test_invalid_estimated_effort_raises(self):
        """Test that invalid estimated_effort raises ValueError."""
        with pytest.raises(ValueError, match="Invalid estimated_effort"):
            SkillProposal(id="sp-1", title="Test", estimated_effort="invalid")

    def test_status_values(self):
        """Test all status values."""
        for status in ProposalStatus:
            sp = SkillProposal(id="sp-1", title="Test", status=status)
            assert sp.status == status

    def test_to_dict(self):
        """Test serialization to dict."""
        sp = SkillProposal(id="sp-1", title="Test")
        d = sp.to_dict()
        assert d["id"] == "sp-1"
        assert d["title"] == "Test"
        assert d["status"] == "proposed"
        assert "proposed_at" in d
