"""Tests for TrustModel — Phase G (Self-Extending Skills)."""

from datetime import datetime

import pytest

from janus.models.trust_model import (
    TrustModel,
    TrustLevel,
    TRUST_LEVEL_TRANSITIONS,
    is_valid_trust_transition,
)


class TestTrustLevel:
    """Tests for the TrustLevel enum."""

    def test_enum_values(self):
        """Test all enum values."""
        assert TrustLevel.UNTRUSTED == "untrusted"
        assert TrustLevel.LOW == "low"
        assert TrustLevel.MEDIUM == "medium"
        assert TrustLevel.HIGH == "high"

    def test_transitions_exist(self):
        """Test that transitions dict has all levels."""
        assert "untrusted" in TRUST_LEVEL_TRANSITIONS
        assert "low" in TRUST_LEVEL_TRANSITIONS
        assert "medium" in TRUST_LEVEL_TRANSITIONS
        assert "high" in TRUST_LEVEL_TRANSITIONS

    def test_valid_transitions(self):
        """Test valid transitions."""
        assert is_valid_trust_transition("untrusted", "low") is True
        assert is_valid_trust_transition("low", "medium") is True
        assert is_valid_trust_transition("medium", "high") is True

    def test_invalid_transitions(self):
        """Test invalid transitions."""
        assert is_valid_trust_transition("high", "untrusted") is False
        assert is_valid_trust_transition("medium", "low") is False
        assert is_valid_trust_transition("low", "untrusted") is False

    def test_self_transition(self):
        """Test self transitions (should be invalid)."""
        assert is_valid_trust_transition("untrusted", "untrusted") is False
        assert is_valid_trust_transition("low", "low") is False
        assert is_valid_trust_transition("medium", "medium") is False
        assert is_valid_trust_transition("high", "high") is False


class TestTrustModel:
    """Tests for the TrustModel model."""

    def test_create_minimal(self):
        """Test creating a minimal TrustModel."""
        tm = TrustModel(id="tm-1", name="Test trust model")
        assert tm.id == "tm-1"
        assert tm.name == "Test trust model"
        assert tm.description == ""
        assert tm.rules == []
        assert tm.created_at is not None
        assert tm.updated_at is not None
        assert tm.active is True

    def test_create_full(self):
        """Test creating a full TrustModel."""
        now = datetime.now()
        tm = TrustModel(
            id="tm-2",
            name="Full trust model",
            description="A full trust model",
            rules=[{"rule": "test"}],
            created_at=now,
            updated_at=now,
            active=False,
        )
        assert tm.id == "tm-2"
        assert tm.name == "Full trust model"
        assert tm.description == "A full trust model"
        assert tm.rules == [{"rule": "test"}]
        assert tm.created_at == now
        assert tm.updated_at == now
        assert tm.active is False

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            TrustModel(id="", name="Test")

    def test_empty_name_raises(self):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="name must not be empty"):
            TrustModel(id="tm-1", name="")

    def test_to_dict(self):
        """Test serialization to dict."""
        tm = TrustModel(id="tm-1", name="Test")
        d = tm.to_dict()
        assert d["id"] == "tm-1"
        assert d["name"] == "Test"
        assert "created_at" in d
        assert "updated_at" in d
