"""Tests for GeneratedCapability model — Phase G (Self-Extending Skills)."""

from datetime import datetime

import pytest

from janus.models.generated_capability import GeneratedCapability, CapabilityStatus


class TestGeneratedCapability:
    """Tests for the GeneratedCapability model."""

    def test_create_minimal(self):
        """Test creating a minimal GeneratedCapability."""
        gc = GeneratedCapability(id="gc-1", name="test_capability")
        assert gc.id == "gc-1"
        assert gc.name == "test_capability"
        assert gc.description == ""
        assert gc.status == CapabilityStatus.GENERATING
        assert gc.created_at is not None
        assert gc.updated_at is not None
        assert gc.proposal_id == ""
        assert gc.code == ""
        assert gc.tests == ""
        assert gc.sandbox_results == {}
        assert gc.verification_results == {}
        assert gc.trust_level == "untrusted"
        assert gc.notes == ""

    def test_create_full(self):
        """Test creating a full GeneratedCapability."""
        now = datetime.now()
        gc = GeneratedCapability(
            id="gc-2",
            name="full_capability",
            description="A full capability",
            status=CapabilityStatus.INSTALLED,
            created_at=now,
            updated_at=now,
            proposal_id="sp-1",
            code="print('hello')",
            tests="def test(): pass",
            sandbox_results={"passed": True},
            verification_results={"passed": True},
            trust_level="high",
            notes="Some notes",
        )
        assert gc.id == "gc-2"
        assert gc.name == "full_capability"
        assert gc.description == "A full capability"
        assert gc.status == CapabilityStatus.INSTALLED
        assert gc.created_at == now
        assert gc.updated_at == now
        assert gc.proposal_id == "sp-1"
        assert gc.code == "print('hello')"
        assert gc.tests == "def test(): pass"
        assert gc.sandbox_results == {"passed": True}
        assert gc.verification_results == {"passed": True}
        assert gc.trust_level == "high"
        assert gc.notes == "Some notes"

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            GeneratedCapability(id="", name="test")

    def test_empty_name_raises(self):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="name must not be empty"):
            GeneratedCapability(id="gc-1", name="")

    def test_invalid_status_raises(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            GeneratedCapability(id="gc-1", name="test", status="invalid")

    def test_invalid_trust_level_raises(self):
        """Test that invalid trust_level raises ValueError."""
        with pytest.raises(ValueError, match="Invalid trust_level"):
            GeneratedCapability(id="gc-1", name="test", trust_level="invalid")

    def test_status_values(self):
        """Test all status values."""
        for status in CapabilityStatus:
            gc = GeneratedCapability(id="gc-1", name="test", status=status)
            assert gc.status == status

    def test_to_dict(self):
        """Test serialization to dict."""
        gc = GeneratedCapability(id="gc-1", name="test")
        d = gc.to_dict()
        assert d["id"] == "gc-1"
        assert d["name"] == "test"
        assert d["status"] == "generating"
        assert "created_at" in d
        assert "updated_at" in d
