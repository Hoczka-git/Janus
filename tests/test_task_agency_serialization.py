"""Tests for TaskAgency serialization and validation.

Covers:
- __post_init__ validation (type checks, confidence bounds)
- to_dict serialization
- from_dict deserialization
- Round-trip (to_dict → from_dict)
- Default values in from_dict
"""

import pytest

from janus.models.execution_mode import ExecutionMode
from janus.models.support_mode import SupportMode
from janus.models.task_agency import TaskAgency


class TestTaskAgencyValidation:
    """Tests for __post_init__ validation."""

    def test_valid_construction(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test reason",
            confidence=0.7,
        )
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.EXPLAIN
        assert agency.reason == "Test reason"
        assert agency.confidence == 0.7

    def test_invalid_execution_mode_type(self):
        with pytest.raises(TypeError, match="execution_mode must be an ExecutionMode"):
            TaskAgency(
                execution_mode="user",  # type: ignore[arg-type]
                support_mode=SupportMode.EXPLAIN,
                reason="Test",
            )

    def test_invalid_support_mode_type(self):
        with pytest.raises(TypeError, match="support_mode must be a SupportMode"):
            TaskAgency(
                execution_mode=ExecutionMode.USER,
                support_mode="explain",  # type: ignore[arg-type]
                reason="Test",
            )

    def test_invalid_reason_type(self):
        with pytest.raises(TypeError, match="reason must be a str"):
            TaskAgency(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                reason=123,  # type: ignore[arg-type]
            )

    def test_invalid_confidence_type(self):
        with pytest.raises(TypeError, match="confidence must be a number"):
            TaskAgency(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                reason="Test",
                confidence="high",  # type: ignore[arg-type]
            )

    def test_confidence_below_zero(self):
        with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
            TaskAgency(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                reason="Test",
                confidence=-0.1,
            )

    def test_confidence_above_one(self):
        with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
            TaskAgency(
                execution_mode=ExecutionMode.USER,
                support_mode=SupportMode.EXPLAIN,
                reason="Test",
                confidence=1.1,
            )

    def test_confidence_zero_valid(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test",
            confidence=0.0,
        )
        assert agency.confidence == 0.0

    def test_confidence_one_valid(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test",
            confidence=1.0,
        )
        assert agency.confidence == 1.0

    def test_default_confidence(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test",
        )
        assert agency.confidence == 0.5


class TestTaskAgencySerialization:
    """Tests for to_dict and from_dict."""

    def test_to_dict_full(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.JANUS,
            support_mode=SupportMode.EXECUTE,
            reason="Admin task",
            confidence=0.8,
        )
        d = agency.to_dict()
        assert d == {
            "execution_mode": "janus",
            "support_mode": "execute",
            "reason": "Admin task",
            "confidence": 0.8,
        }

    def test_to_dict_default_confidence(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Learning task",
        )
        d = agency.to_dict()
        assert d["confidence"] == 0.5

    def test_from_dict_full(self):
        data = {
            "execution_mode": "collaborative",
            "support_mode": "scaffold",
            "reason": "Complex task",
            "confidence": 0.6,
        }
        agency = TaskAgency.from_dict(data)
        assert agency.execution_mode == ExecutionMode.COLLABORATIVE
        assert agency.support_mode == SupportMode.SCAFFOLD
        assert agency.reason == "Complex task"
        assert agency.confidence == 0.6

    def test_from_dict_defaults(self):
        agency = TaskAgency.from_dict({})
        assert agency.execution_mode == ExecutionMode.USER
        assert agency.support_mode == SupportMode.EXPLAIN
        assert agency.reason == ""
        assert agency.confidence == 0.5

    def test_from_dict_partial(self):
        agency = TaskAgency.from_dict({"execution_mode": "janus"})
        assert agency.execution_mode == ExecutionMode.JANUS
        assert agency.support_mode == SupportMode.EXPLAIN  # default
        assert agency.reason == ""  # default
        assert agency.confidence == 0.5  # default

    def test_round_trip(self):
        original = TaskAgency(
            execution_mode=ExecutionMode.COLLABORATIVE,
            support_mode=SupportMode.COACH,
            reason="Stalled goal",
            confidence=0.7,
        )
        d = original.to_dict()
        restored = TaskAgency.from_dict(d)
        assert restored.execution_mode == original.execution_mode
        assert restored.support_mode == original.support_mode
        assert restored.reason == original.reason
        assert restored.confidence == original.confidence

    def test_to_dict_returns_dict(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Test",
        )
        d = agency.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_values_are_strings(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.JANUS,
            support_mode=SupportMode.EXECUTE,
            reason="Test",
        )
        d = agency.to_dict()
        assert isinstance(d["execution_mode"], str)
        assert isinstance(d["support_mode"], str)
        assert isinstance(d["reason"], str)
        assert isinstance(d["confidence"], float)

    def test_from_dict_invalid_execution_mode(self):
        with pytest.raises(ValueError):
            TaskAgency.from_dict({"execution_mode": "invalid"})

    def test_from_dict_invalid_support_mode(self):
        with pytest.raises(ValueError):
            TaskAgency.from_dict({"support_mode": "invalid"})
