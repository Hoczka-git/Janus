"""Unit tests for ExecutionMode enum.

Covers enum values, string comparison, construction from string,
and the EXECUTION_MODE_ORDER tuple.
"""

import pytest

from janus.models.execution_mode import EXECUTION_MODE_ORDER, ExecutionMode


class TestExecutionModeValues:
    def test_user_value(self):
        assert ExecutionMode.USER == "user"

    def test_janus_value(self):
        assert ExecutionMode.JANUS == "janus"

    def test_collaborative_value(self):
        assert ExecutionMode.COLLABORATIVE == "collaborative"

    def test_member_count(self):
        assert len(ExecutionMode) == 3


class TestExecutionModeConstruction:
    def test_from_string_user(self):
        assert ExecutionMode("user") is ExecutionMode.USER

    def test_from_string_janus(self):
        assert ExecutionMode("janus") is ExecutionMode.JANUS

    def test_from_string_collaborative(self):
        assert ExecutionMode("collaborative") is ExecutionMode.COLLABORATIVE

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            ExecutionMode("invalid")

    def test_str_comparison(self):
        """StrEnum members compare equal to their string values."""
        assert ExecutionMode.USER == "user"
        assert ExecutionMode.JANUS == "janus"
        assert ExecutionMode.COLLABORATIVE == "collaborative"

    def test_str_method(self):
        assert str(ExecutionMode.USER) == "user"
        assert str(ExecutionMode.JANUS) == "janus"
        assert str(ExecutionMode.COLLABORATIVE) == "collaborative"


class TestExecutionModeOrder:
    def test_order_length(self):
        assert len(EXECUTION_MODE_ORDER) == 3

    def test_order_contains_all_members(self):
        for mode in ExecutionMode:
            assert mode in EXECUTION_MODE_ORDER

    def test_order_least_to_most_substitutive(self):
        """USER is least substitutive, COLLABORATIVE is most."""
        assert EXECUTION_MODE_ORDER[0] is ExecutionMode.USER
        assert EXECUTION_MODE_ORDER[1] is ExecutionMode.JANUS
        assert EXECUTION_MODE_ORDER[2] is ExecutionMode.COLLABORATIVE

    def test_order_is_tuple(self):
        assert isinstance(EXECUTION_MODE_ORDER, tuple)


class TestExecutionModeExport:
    def test_importable_from_models_package(self):
        from janus.models import ExecutionMode as ExportedExecutionMode
        assert ExportedExecutionMode is ExecutionMode

    def test_in_models_all(self):
        import janus.models
        assert "ExecutionMode" in janus.models.__all__
