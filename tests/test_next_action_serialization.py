"""Tests for NextAction serialization and validation.

Covers:
- __post_init__ validation (type checks, kind bounds)
- to_dict serialization
- from_dict deserialization
- Round-trip (to_dict → from_dict)
- Default values in from_dict
- Agency field serialization
"""

import pytest

from janus.domain.planning import NextAction
from janus.models.execution_mode import ExecutionMode
from janus.models.support_mode import SupportMode
from janus.models.task_agency import TaskAgency


class TestNextActionValidation:
    """Tests for __post_init__ validation."""

    def test_valid_construction(self):
        action = NextAction(
            title="Test Task",
            kind="task",
            reason="Test reason",
            goal_title="Test Goal",
            score=10,
        )
        assert action.title == "Test Task"
        assert action.kind == "task"
        assert action.reason == "Test reason"
        assert action.goal_title == "Test Goal"
        assert action.score == 10
        assert action.agency is None

    def test_invalid_title_type(self):
        with pytest.raises(TypeError, match="title must be a str"):
            NextAction(
                title=123,  # type: ignore[arg-type]
                kind="task",
                reason="Test",
                goal_title="Goal",
            )

    def test_invalid_kind_type(self):
        with pytest.raises(TypeError, match="kind must be a str"):
            NextAction(
                title="Test",
                kind=123,  # type: ignore[arg-type]
                reason="Test",
                goal_title="Goal",
            )

    def test_kind_not_value_restricted(self):
        """NextAction does not validate kind values — consumers are responsible."""
        action = NextAction(
            title="Test",
            kind="anything",
            reason="Test",
            goal_title="Goal",
        )
        assert action.kind == "anything"

    def test_invalid_reason_type(self):
        with pytest.raises(TypeError, match="reason must be a str"):
            NextAction(
                title="Test",
                kind="task",
                reason=123,  # type: ignore[arg-type]
                goal_title="Goal",
            )

    def test_invalid_goal_title_type(self):
        with pytest.raises(TypeError, match="goal_title must be a str"):
            NextAction(
                title="Test",
                kind="task",
                reason="Test",
                goal_title=123,  # type: ignore[arg-type]
            )

    def test_invalid_score_type(self):
        with pytest.raises(TypeError, match="score must be an int"):
            NextAction(
                title="Test",
                kind="task",
                reason="Test",
                goal_title="Goal",
                score="high",  # type: ignore[arg-type]
            )

    def test_invalid_agency_type(self):
        with pytest.raises(TypeError, match="agency must be a TaskAgency or None"):
            NextAction(
                title="Test",
                kind="task",
                reason="Test",
                goal_title="Goal",
                agency="agency",  # type: ignore[arg-type]
            )

    def test_valid_kinds(self):
        for kind in ("task", "milestone", "project"):
            action = NextAction(
                title="Test",
                kind=kind,  # type: ignore[arg-type]
                reason="Test",
                goal_title="Goal",
            )
            assert action.kind == kind

    def test_default_score(self):
        action = NextAction(
            title="Test",
            kind="task",
            reason="Test",
            goal_title="Goal",
        )
        assert action.score == 0

    def test_default_agency(self):
        action = NextAction(
            title="Test",
            kind="task",
            reason="Test",
            goal_title="Goal",
        )
        assert action.agency is None


class TestNextActionSerialization:
    """Tests for to_dict and from_dict."""

    def test_to_dict_full(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.JANUS,
            support_mode=SupportMode.EXECUTE,
            reason="Admin task",
            confidence=0.8,
        )
        action = NextAction(
            title="Sync data",
            kind="task",
            reason="Next task in milestone",
            goal_title="Test Goal",
            score=50,
            agency=agency,
        )
        d = action.to_dict()
        assert d == {
            "title": "Sync data",
            "kind": "task",
            "reason": "Next task in milestone",
            "goal_title": "Test Goal",
            "score": 50,
            "agency": {
                "execution_mode": "janus",
                "support_mode": "execute",
                "reason": "Admin task",
                "confidence": 0.8,
            },
        }

    def test_to_dict_without_agency(self):
        action = NextAction(
            title="Test Task",
            kind="task",
            reason="Test reason",
            goal_title="Test Goal",
        )
        d = action.to_dict()
        assert d["agency"] is None

    def test_from_dict_full(self):
        data = {
            "title": "Sync data",
            "kind": "task",
            "reason": "Next task",
            "goal_title": "Test Goal",
            "score": 50,
            "agency": {
                "execution_mode": "janus",
                "support_mode": "execute",
                "reason": "Admin task",
                "confidence": 0.8,
            },
        }
        action = NextAction.from_dict(data)
        assert action.title == "Sync data"
        assert action.kind == "task"
        assert action.reason == "Next task"
        assert action.goal_title == "Test Goal"
        assert action.score == 50
        assert action.agency is not None
        assert action.agency.execution_mode == ExecutionMode.JANUS
        assert action.agency.support_mode == SupportMode.EXECUTE

    def test_from_dict_defaults(self):
        action = NextAction.from_dict({})
        assert action.title == ""
        assert action.kind == "task"
        assert action.reason == ""
        assert action.goal_title == ""
        assert action.score == 0
        assert action.agency is None

    def test_from_dict_partial(self):
        action = NextAction.from_dict({"title": "Test", "kind": "milestone"})
        assert action.title == "Test"
        assert action.kind == "milestone"
        assert action.reason == ""  # default
        assert action.goal_title == ""  # default
        assert action.score == 0  # default
        assert action.agency is None  # default

    def test_from_dict_without_agency(self):
        action = NextAction.from_dict({"title": "Test", "agency": None})
        assert action.agency is None

    def test_round_trip(self):
        original = NextAction(
            title="Design system",
            kind="task",
            reason="Complex task",
            goal_title="Build Product",
            score=75,
            agency=TaskAgency(
                execution_mode=ExecutionMode.COLLABORATIVE,
                support_mode=SupportMode.SCAFFOLD,
                reason="High complexity",
                confidence=0.7,
            ),
        )
        d = original.to_dict()
        restored = NextAction.from_dict(d)
        assert restored.title == original.title
        assert restored.kind == original.kind
        assert restored.reason == original.reason
        assert restored.goal_title == original.goal_title
        assert restored.score == original.score
        if original.agency is None or restored.agency is None:
            pytest.fail("agency should not be None")
        original_agency = original.agency
        restored_agency = restored.agency
        assert restored_agency.execution_mode == original_agency.execution_mode
        assert restored_agency.support_mode == original_agency.support_mode
        assert restored_agency.reason == original_agency.reason
        assert restored_agency.confidence == original_agency.confidence

    def test_to_dict_returns_dict(self):
        action = NextAction(
            title="Test",
            kind="task",
            reason="Test",
            goal_title="Goal",
        )
        d = action.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_values_are_strings(self):
        action = NextAction(
            title="Test",
            kind="task",
            reason="Test",
            goal_title="Goal",
        )
        d = action.to_dict()
        assert isinstance(d["title"], str)
        assert isinstance(d["kind"], str)
        assert isinstance(d["reason"], str)
        assert isinstance(d["goal_title"], str)
        assert isinstance(d["score"], int)

    def test_from_dict_kind_not_validated(self):
        """NextAction.from_dict does not validate kind values."""
        action = NextAction.from_dict({"kind": "anything"})
        assert action.kind == "anything"
