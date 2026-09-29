"""Tests for ``janus inbox triage`` title derivation.

Covers the ``[plan]`` replenishment-marker preservation in
``_derive_title()`` — the triage path must not drop the marker that
the replenishment plugin uses to identify eligible tasks.
"""

from __future__ import annotations

import pytest

from janus.inbox_cli import _derive_title


class TestDeriveTitlePlanMarker:
    """``[plan]`` marker must survive title derivation."""

    def test_plan_marker_at_start_preserved(self):
        result = _derive_title("[plan] Do the thing")
        assert result == "[plan] Do the thing"

    def test_plan_marker_with_long_text_preserved(self):
        """Even when the body text exceeds 80 chars, [plan] must survive."""
        long_text = "[plan] " + "x" * 100
        result = _derive_title(long_text)
        assert result.startswith("[plan] ")
        assert len(result) <= 87  # "[plan] " (7) + 77 + "..." (3) = 87 max

    def test_plan_marker_after_prefix_preserved(self):
        """[plan] may appear after a common prefix like 'remember to'."""
        result = _derive_title("remember to [plan] do the thing")
        assert result == "[plan] do the thing"

    def test_plan_marker_after_long_prefix_preserved(self):
        """[plan] after a long prefix that would trigger truncation."""
        long_text = "remember to " + "x" * 100 + " [plan] do the thing"
        result = _derive_title(long_text)
        assert result.startswith("[plan] ")

    def test_no_plan_marker_unchanged(self):
        """Text without [plan] should not gain a marker."""
        result = _derive_title("Do the thing")
        assert result == "Do the thing"

    def test_no_plan_marker_truncation_unchanged(self):
        """Long text without [plan] should truncate as before."""
        long_text = "x" * 100
        result = _derive_title(long_text)
        assert result == "x" * 77 + "..."

    def test_plan_marker_only(self):
        """Edge case: text is just '[plan]'."""
        result = _derive_title("[plan]")
        assert result == "[plan]"

    def test_plan_marker_with_trailing_space(self):
        """Edge case: '[plan] ' with trailing space."""
        result = _derive_title("[plan]   Do the thing")
        assert result == "[plan] Do the thing"

    def test_plan_marker_case_sensitive(self):
        """[Plan] or [PLAN] should NOT be treated as the marker."""
        result = _derive_title("[Plan] Do the thing")
        assert result == "[Plan] Do the thing"

    def test_plan_marker_in_middle_of_long_text(self):
        """[plan] in the middle of a long text should be extracted."""
        long_text = "x" * 50 + " [plan] " + "y" * 50
        result = _derive_title(long_text)
        assert result.startswith("[plan] ")
        # The text after [plan] should be truncated
        assert len(result) <= 87
