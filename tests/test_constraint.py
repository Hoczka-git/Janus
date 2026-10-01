"""Tests for Constraint model — Phase C (Personal State)."""

from datetime import date, datetime

import pytest

from janus.models.constraint import Constraint, ConstraintType


class TestConstraint:
    """Tests for the Constraint model."""

    def test_create_minimal(self):
        """Test creating a minimal Constraint."""
        ct = Constraint(id="ct-1", title="Test constraint")
        assert ct.id == "ct-1"
        assert ct.title == "Test constraint"
        assert ct.constraint_type == ConstraintType.OTHER
        assert ct.severity == "medium"
        assert ct.active is True
        assert ct.created_at is not None
        assert ct.expires_at is None
        assert ct.linked_goal_title == ""
        assert ct.notes == ""

    def test_create_full(self):
        """Test creating a full Constraint."""
        now = datetime.now()
        expires = date(2026, 12, 31)
        ct = Constraint(
            id="ct-2",
            title="Full constraint",
            constraint_type=ConstraintType.TIME,
            severity="high",
            active=False,
            created_at=now,
            expires_at=expires,
            linked_goal_title="Goal 1",
            notes="Some notes",
        )
        assert ct.id == "ct-2"
        assert ct.title == "Full constraint"
        assert ct.constraint_type == ConstraintType.TIME
        assert ct.severity == "high"
        assert ct.active is False
        assert ct.created_at == now
        assert ct.expires_at == expires
        assert ct.linked_goal_title == "Goal 1"
        assert ct.notes == "Some notes"

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            Constraint(id="", title="Test")

    def test_empty_title_raises(self):
        """Test that empty title raises ValueError."""
        with pytest.raises(ValueError, match="title must not be empty"):
            Constraint(id="ct-1", title="")

    def test_invalid_constraint_type_raises(self):
        """Test that invalid constraint_type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid constraint_type"):
            Constraint(id="ct-1", title="Test", constraint_type="invalid")

    def test_invalid_severity_raises(self):
        """Test that invalid severity raises ValueError."""
        with pytest.raises(ValueError, match="Invalid severity"):
            Constraint(id="ct-1", title="Test", severity="invalid")

    def test_constraint_type_values(self):
        """Test all constraint type values."""
        for ct_type in ConstraintType:
            ct = Constraint(id="ct-1", title="Test", constraint_type=ct_type)
            assert ct.constraint_type == ct_type

    def test_to_dict(self):
        """Test serialization to dict."""
        ct = Constraint(id="ct-1", title="Test")
        d = ct.to_dict()
        assert d["id"] == "ct-1"
        assert d["title"] == "Test"
        assert d["constraint_type"] == "other"
        assert "created_at" in d
