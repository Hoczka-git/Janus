"""Tests for Resource model — Phase C (Personal State)."""

from datetime import date

import pytest

from janus.models.resource import Resource, ResourceType


class TestResource:
    """Tests for the Resource model."""

    def test_create_minimal(self):
        """Test creating a minimal Resource."""
        rs = Resource(id="rs-1", title="Test resource")
        assert rs.id == "rs-1"
        assert rs.title == "Test resource"
        assert rs.resource_type == ResourceType.OTHER
        assert rs.capacity == 0.0
        assert rs.used == 0.0
        assert rs.unit == ""
        assert rs.available_from is None
        assert rs.available_until is None
        assert rs.linked_goal_title == ""
        assert rs.notes == ""

    def test_create_full(self):
        """Test creating a full Resource."""
        rs = Resource(
            id="rs-2",
            title="Full resource",
            resource_type=ResourceType.TIME,
            capacity=40.0,
            used=10.0,
            unit="hours",
            available_from=date(2026, 1, 1),
            available_until=date(2026, 12, 31),
            linked_goal_title="Goal 1",
            notes="Some notes",
        )
        assert rs.id == "rs-2"
        assert rs.title == "Full resource"
        assert rs.resource_type == ResourceType.TIME
        assert rs.capacity == 40.0
        assert rs.used == 10.0
        assert rs.unit == "hours"
        assert rs.available_from == date(2026, 1, 1)
        assert rs.available_until == date(2026, 12, 31)
        assert rs.linked_goal_title == "Goal 1"
        assert rs.notes == "Some notes"

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            Resource(id="", title="Test")

    def test_empty_title_raises(self):
        """Test that empty title raises ValueError."""
        with pytest.raises(ValueError, match="title must not be empty"):
            Resource(id="rs-1", title="")

    def test_invalid_resource_type_raises(self):
        """Test that invalid resource_type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid resource_type"):
            Resource(id="rs-1", title="Test", resource_type="invalid")

    def test_negative_capacity_raises(self):
        """Test that negative capacity raises ValueError."""
        with pytest.raises(ValueError, match="capacity must be non-negative"):
            Resource(id="rs-1", title="Test", capacity=-1.0)

    def test_negative_used_raises(self):
        """Test that negative used raises ValueError."""
        with pytest.raises(ValueError, match="used must be non-negative"):
            Resource(id="rs-1", title="Test", used=-1.0)

    def test_used_exceeds_capacity_raises(self):
        """Test that used > capacity raises ValueError."""
        with pytest.raises(ValueError, match="used must not exceed capacity"):
            Resource(id="rs-1", title="Test", capacity=10.0, used=20.0)

    def test_available_property(self):
        """Test the available property."""
        rs = Resource(id="rs-1", title="Test", capacity=40.0, used=10.0)
        assert rs.available == 30.0

    def test_utilization_property(self):
        """Test the utilization property."""
        rs = Resource(id="rs-1", title="Test", capacity=40.0, used=10.0)
        assert rs.utilization == 0.25

    def test_utilization_zero_capacity(self):
        """Test utilization with zero capacity."""
        rs = Resource(id="rs-1", title="Test", capacity=0.0, used=0.0)
        assert rs.utilization == 0.0

    def test_resource_type_values(self):
        """Test all resource type values."""
        for rs_type in ResourceType:
            rs = Resource(id="rs-1", title="Test", resource_type=rs_type)
            assert rs.resource_type == rs_type

    def test_to_dict(self):
        """Test serialization to dict."""
        rs = Resource(id="rs-1", title="Test", capacity=40.0, used=10.0)
        d = rs.to_dict()
        assert d["id"] == "rs-1"
        assert d["title"] == "Test"
        assert d["resource_type"] == "other"
        assert d["available"] == 30.0
        assert d["utilization"] == 0.25
