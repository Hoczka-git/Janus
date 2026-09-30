"""Unit tests for SupportMode enum.

Covers enum values, string comparison, construction from string,
and the SUPPORT_MODE_ORDER tuple.
"""

import pytest

from janus.models.support_mode import SUPPORT_MODE_ORDER, SupportMode


class TestSupportModeValues:
    def test_explain_value(self):
        assert SupportMode.EXPLAIN == "explain"

    def test_coach_value(self):
        assert SupportMode.COACH == "coach"

    def test_scaffold_value(self):
        assert SupportMode.SCAFFOLD == "scaffold"

    def test_review_value(self):
        assert SupportMode.REVIEW == "review"

    def test_execute_value(self):
        assert SupportMode.EXECUTE == "execute"

    def test_member_count(self):
        assert len(SupportMode) == 5


class TestSupportModeConstruction:
    def test_from_string_explain(self):
        assert SupportMode("explain") is SupportMode.EXPLAIN

    def test_from_string_coach(self):
        assert SupportMode("coach") is SupportMode.COACH

    def test_from_string_scaffold(self):
        assert SupportMode("scaffold") is SupportMode.SCAFFOLD

    def test_from_string_review(self):
        assert SupportMode("review") is SupportMode.REVIEW

    def test_from_string_execute(self):
        assert SupportMode("execute") is SupportMode.EXECUTE

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            SupportMode("invalid")

    def test_str_comparison(self):
        """StrEnum members compare equal to their string values."""
        assert SupportMode.EXPLAIN == "explain"
        assert SupportMode.COACH == "coach"
        assert SupportMode.SCAFFOLD == "scaffold"
        assert SupportMode.REVIEW == "review"
        assert SupportMode.EXECUTE == "execute"

    def test_str_method(self):
        assert str(SupportMode.EXPLAIN) == "explain"
        assert str(SupportMode.COACH) == "coach"
        assert str(SupportMode.SCAFFOLD) == "scaffold"
        assert str(SupportMode.REVIEW) == "review"
        assert str(SupportMode.EXECUTE) == "execute"


class TestSupportModeOrder:
    def test_order_length(self):
        assert len(SUPPORT_MODE_ORDER) == 5

    def test_order_contains_all_members(self):
        for mode in SupportMode:
            assert mode in SUPPORT_MODE_ORDER

    def test_order_least_to_most_substitutive(self):
        """EXPLAIN is least substitutive, EXECUTE is most."""
        assert SUPPORT_MODE_ORDER[0] is SupportMode.EXPLAIN
        assert SUPPORT_MODE_ORDER[1] is SupportMode.COACH
        assert SUPPORT_MODE_ORDER[2] is SupportMode.SCAFFOLD
        assert SUPPORT_MODE_ORDER[3] is SupportMode.REVIEW
        assert SUPPORT_MODE_ORDER[4] is SupportMode.EXECUTE

    def test_order_is_tuple(self):
        assert isinstance(SUPPORT_MODE_ORDER, tuple)


class TestSupportModeExport:
    def test_importable_from_models_package(self):
        from janus.models import SupportMode as ExportedSupportMode
        assert ExportedSupportMode is SupportMode

    def test_in_models_all(self):
        import janus.models
        assert "SupportMode" in janus.models.__all__
