"""Tests for EvidenceType enum — Phase B (Evidence & Audit)."""

import pytest

from janus.models.evidence_type import (
    EvidenceType,
    EVIDENCE_TYPE_TRANSITIONS,
    is_valid_evidence_transition,
)


class TestEvidenceType:
    """Tests for the EvidenceType enum."""

    def test_enum_values(self):
        """Test all enum values."""
        assert EvidenceType.PLANNED == "planned"
        assert EvidenceType.CLAIMED == "claimed"
        assert EvidenceType.VERIFIED == "verified"
        assert EvidenceType.OUTCOME == "outcome"

    def test_transitions_exist(self):
        """Test that transitions dict has all types."""
        assert "planned" in EVIDENCE_TYPE_TRANSITIONS
        assert "claimed" in EVIDENCE_TYPE_TRANSITIONS
        assert "verified" in EVIDENCE_TYPE_TRANSITIONS
        assert "outcome" in EVIDENCE_TYPE_TRANSITIONS

    def test_valid_transitions(self):
        """Test valid transitions."""
        assert is_valid_evidence_transition("planned", "claimed") is True
        assert is_valid_evidence_transition("planned", "verified") is True
        assert is_valid_evidence_transition("claimed", "verified") is True
        assert is_valid_evidence_transition("claimed", "outcome") is True
        assert is_valid_evidence_transition("verified", "outcome") is True

    def test_invalid_transitions(self):
        """Test invalid transitions."""
        assert is_valid_evidence_transition("outcome", "planned") is False
        assert is_valid_evidence_transition("verified", "planned") is False
        assert is_valid_evidence_transition("claimed", "planned") is False
        assert is_valid_evidence_transition("planned", "outcome") is False

    def test_self_transition(self):
        """Test self transitions (should be invalid)."""
        assert is_valid_evidence_transition("planned", "planned") is False
        assert is_valid_evidence_transition("claimed", "claimed") is False
        assert is_valid_evidence_transition("verified", "verified") is False
        assert is_valid_evidence_transition("outcome", "outcome") is False
