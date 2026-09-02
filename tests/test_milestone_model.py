"""Tests for the Milestone dataclass validation.

Task-to-milestone membership is NOT stored on the Milestone model — it is
derived dynamically at query/planning time (see services/next_action.py,
``derive_milestone_tasks``).
"""

import pytest

from janus.models.milestone import Milestone


class TestMilestoneModel:
    def test_default_fields(self):
        m = Milestone(title="Register", goal_title="My Goal")
        assert m.title == "Register"
        assert m.goal_title == "My Goal"
        assert m.description == ""
        assert m.deadline is None
        assert m.status == "open"
        assert m.order == 0

    def test_all_fields(self):
        m = Milestone(
            title="Register",
            goal_title="My Goal",
            description="Sign up for event",
            deadline="2026-09-30",
            status="in_progress",
            order=1,
        )
        assert m.description == "Sign up for event"
        assert m.deadline == "2026-09-30"
        assert m.status == "in_progress"
        assert m.order == 1

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="Milestone title must not be empty"):
            Milestone(title="", goal_title="My Goal")

    def test_whitespace_title_raises(self):
        with pytest.raises(ValueError, match="Milestone title must not be empty"):
            Milestone(title="  ", goal_title="My Goal")

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid milestone status"):
            Milestone(title="X", goal_title="G", status="pending")

    def test_valid_statuses(self):
        for s in ("open", "in_progress", "completed", "skipped"):
            m = Milestone(title="X", goal_title="G", status=s)
            assert m.status == s

    def test_order_defaults_to_zero(self):
        m = Milestone(title="X", goal_title="G")
        assert m.order == 0
