"""Tests for VerificationResult model — Phase B (Evidence & Audit)."""

from datetime import datetime

import pytest

from janus.models.verification_result import VerificationResult, VerificationStatus


class TestVerificationResult:
    """Tests for the VerificationResult model."""

    def test_create_minimal(self):
        """Test creating a minimal VerificationResult."""
        result = VerificationResult(id="vr-1", check_name="test_check")
        assert result.id == "vr-1"
        assert result.check_name == "test_check"
        assert result.status == VerificationStatus.PASS
        assert result.expected == ""
        assert result.actual == ""
        assert result.severity == "info"
        assert result.linked_task_title == ""
        assert result.linked_goal_title == ""
        assert result.linked_contract == ""
        assert result.details == {}
        assert result.created_at is not None

    def test_create_full(self):
        """Test creating a full VerificationResult."""
        now = datetime.now()
        result = VerificationResult(
            id="vr-2",
            check_name="full_check",
            status=VerificationStatus.FAIL,
            expected="All tests pass",
            actual="3 tests failed",
            severity="error",
            linked_task_title="Task 1",
            linked_goal_title="Goal 1",
            linked_contract="contract-1",
            created_at=now,
            details={"failed_tests": ["test_a", "test_b"]},
        )
        assert result.id == "vr-2"
        assert result.check_name == "full_check"
        assert result.status == VerificationStatus.FAIL
        assert result.expected == "All tests pass"
        assert result.actual == "3 tests failed"
        assert result.severity == "error"
        assert result.linked_task_title == "Task 1"
        assert result.linked_goal_title == "Goal 1"
        assert result.linked_contract == "contract-1"
        assert result.created_at == now
        assert result.details == {"failed_tests": ["test_a", "test_b"]}

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            VerificationResult(id="", check_name="test")

    def test_empty_check_name_raises(self):
        """Test that empty check_name raises ValueError."""
        with pytest.raises(ValueError, match="check_name must not be empty"):
            VerificationResult(id="vr-1", check_name="")

    def test_invalid_status_raises(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            VerificationResult(id="vr-1", check_name="test", status="invalid")

    def test_invalid_severity_raises(self):
        """Test that invalid severity raises ValueError."""
        with pytest.raises(ValueError, match="Invalid severity"):
            VerificationResult(id="vr-1", check_name="test", severity="invalid")

    def test_status_values(self):
        """Test all status values."""
        for status in VerificationStatus:
            result = VerificationResult(id="vr-1", check_name="test", status=status)
            assert result.status == status

    def test_to_dict(self):
        """Test serialization to dict."""
        result = VerificationResult(
            id="vr-1",
            check_name="test",
            status=VerificationStatus.PASS,
        )
        d = result.to_dict()
        assert d["id"] == "vr-1"
        assert d["check_name"] == "test"
        assert d["status"] == "pass"
        assert "created_at" in d
