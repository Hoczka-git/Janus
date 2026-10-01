"""Tests for Preference model — Phase C (Personal State)."""

from datetime import datetime

import pytest

from janus.models.preference import Preference, PreferenceCategory


class TestPreference:
    """Tests for the Preference model."""

    def test_create_minimal(self):
        """Test creating a minimal Preference."""
        pf = Preference(id="pf-1", title="Test preference")
        assert pf.id == "pf-1"
        assert pf.title == "Test preference"
        assert pf.category == PreferenceCategory.OTHER
        assert pf.value == ""
        assert pf.priority == 3
        assert pf.active is True
        assert pf.created_at is not None
        assert pf.notes == ""

    def test_create_full(self):
        """Test creating a full Preference."""
        now = datetime.now()
        pf = Preference(
            id="pf-2",
            title="Full preference",
            category=PreferenceCategory.COMMUNICATION,
            value="email",
            priority=5,
            active=False,
            created_at=now,
            notes="Some notes",
        )
        assert pf.id == "pf-2"
        assert pf.title == "Full preference"
        assert pf.category == PreferenceCategory.COMMUNICATION
        assert pf.value == "email"
        assert pf.priority == 5
        assert pf.active is False
        assert pf.created_at == now
        assert pf.notes == "Some notes"

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            Preference(id="", title="Test")

    def test_empty_title_raises(self):
        """Test that empty title raises ValueError."""
        with pytest.raises(ValueError, match="title must not be empty"):
            Preference(id="pf-1", title="")

    def test_invalid_category_raises(self):
        """Test that invalid category raises ValueError."""
        with pytest.raises(ValueError, match="Invalid category"):
            Preference(id="pf-1", title="Test", category="invalid")

    def test_invalid_priority_raises(self):
        """Test that invalid priority raises ValueError."""
        with pytest.raises(ValueError, match="Invalid priority"):
            Preference(id="pf-1", title="Test", priority=6)

    def test_category_values(self):
        """Test all category values."""
        for cat in PreferenceCategory:
            pf = Preference(id="pf-1", title="Test", category=cat)
            assert pf.category == cat

    def test_to_dict(self):
        """Test serialization to dict."""
        pf = Preference(id="pf-1", title="Test")
        d = pf.to_dict()
        assert d["id"] == "pf-1"
        assert d["title"] == "Test"
        assert d["category"] == "other"
        assert "created_at" in d
