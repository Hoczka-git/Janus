"""Tests for Recommendation serialization and validation.

Covers:
- __post_init__ validation (type checks, kind bounds)
- to_dict serialization
- from_dict deserialization
- Round-trip (to_dict → from_dict)
- Default values in from_dict
- Agency field serialization
"""

import pytest

from janus.models.execution_mode import ExecutionMode
from janus.models.support_mode import SupportMode
from janus.models.task_agency import TaskAgency
from janus.services.recommendations import Recommendation


class TestRecommendationValidation:
    """Tests for __post_init__ validation."""

    def test_valid_construction(self):
        rec = Recommendation(
            title="Test Task",
            kind="task",
            goal_title="Test Goal",
            score=10,
            reason="Test reason",
        )
        assert rec.title == "Test Task"
        assert rec.kind == "task"
        assert rec.goal_title == "Test Goal"
        assert rec.score == 10
        assert rec.reason == "Test reason"
        assert rec.agency is None

    def test_invalid_title_type(self):
        with pytest.raises(TypeError, match="title must be a str"):
            Recommendation(
                title=123,  # type: ignore[arg-type]
                kind="task",
                goal_title="Goal",
            )

    def test_invalid_kind_type(self):
        with pytest.raises(TypeError, match="kind must be a str"):
            Recommendation(
                title="Test",
                kind=123,  # type: ignore[arg-type]
                goal_title="Goal",
            )

    def test_invalid_kind_value(self):
        with pytest.raises(ValueError, match="kind must be 'task', 'project', or 'milestone'"):
            Recommendation(
                title="Test",
                kind="invalid",  # type: ignore[arg-type]
                goal_title="Goal",
            )

    def test_invalid_goal_title_type(self):
        with pytest.raises(TypeError, match="goal_title must be a str"):
            Recommendation(
                title="Test",
                kind="task",
                goal_title=123,  # type: ignore[arg-type]
            )

    def test_invalid_score_type(self):
        with pytest.raises(TypeError, match="score must be an int"):
            Recommendation(
                title="Test",
                kind="task",
                goal_title="Goal",
                score="high",  # type: ignore[arg-type]
            )

    def test_invalid_reason_type(self):
        with pytest.raises(TypeError, match="reason must be a str"):
            Recommendation(
                title="Test",
                kind="task",
                goal_title="Goal",
                reason=123,  # type: ignore[arg-type]
            )

    def test_invalid_agency_type(self):
        with pytest.raises(TypeError, match="agency must be a TaskAgency or None"):
            Recommendation(
                title="Test",
                kind="task",
                goal_title="Goal",
                agency="agency",  # type: ignore[arg-type]
            )

    def test_valid_kinds(self):
        for kind in ("task", "project", "milestone"):
            rec = Recommendation(
                title="Test",
                kind=kind,  # type: ignore[arg-type]
                goal_title="Goal",
            )
            assert rec.kind == kind

    def test_default_score(self):
        rec = Recommendation(
            title="Test",
            kind="task",
            goal_title="Goal",
        )
        assert rec.score == 0

    def test_default_reason(self):
        rec = Recommendation(
            title="Test",
            kind="task",
            goal_title="Goal",
        )
        assert rec.reason == ""

    def test_default_agency(self):
        rec = Recommendation(
            title="Test",
            kind="task",
            goal_title="Goal",
        )
        assert rec.agency is None

    def test_default_optional_fields(self):
        rec = Recommendation(
            title="Test",
            kind="task",
            goal_title="Goal",
        )
        assert rec.project_title is None
        assert rec.milestone_title is None
        assert rec.due_date is None
        assert rec.priority is None


class TestRecommendationSerialization:
    """Tests for to_dict and from_dict."""

    def test_to_dict_full(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="Learning task",
            confidence=0.6,
        )
        rec = Recommendation(
            title="Learn Python",
            kind="task",
            goal_title="Career Goal",
            score=50,
            reason="Next task in milestone",
            project_title="Skill Building",
            milestone_title="Q1",
            due_date="2024-03-15",
            priority=2,
            agency=agency,
        )
        d = rec.to_dict()
        assert d == {
            "title": "Learn Python",
            "kind": "task",
            "goal_title": "Career Goal",
            "score": 50,
            "reason": "Next task in milestone",
            "project_title": "Skill Building",
            "milestone_title": "Q1",
            "due_date": "2024-03-15",
            "priority": 2,
            "agency": {
                "execution_mode": "user",
                "support_mode": "explain",
                "reason": "Learning task",
                "confidence": 0.6,
            },
        }

    def test_to_dict_minimal(self):
        rec = Recommendation(
            title="Test Task",
            kind="task",
            goal_title="Test Goal",
        )
        d = rec.to_dict()
        assert d == {
            "title": "Test Task",
            "kind": "task",
            "goal_title": "Test Goal",
            "score": 0,
            "reason": "",
            "project_title": None,
            "milestone_title": None,
            "due_date": None,
            "priority": None,
            "agency": None,
        }

    def test_from_dict_full(self):
        data = {
            "title": "Learn Python",
            "kind": "task",
            "goal_title": "Career Goal",
            "score": 50,
            "reason": "Next task",
            "project_title": "Skills",
            "milestone_title": "Q1",
            "due_date": "2024-03-15",
            "priority": 2,
            "agency": {
                "execution_mode": "user",
                "support_mode": "explain",
                "reason": "Learning task",
                "confidence": 0.6,
            },
        }
        rec = Recommendation.from_dict(data)
        assert rec.title == "Learn Python"
        assert rec.kind == "task"
        assert rec.goal_title == "Career Goal"
        assert rec.score == 50
        assert rec.reason == "Next task"
        assert rec.project_title == "Skills"
        assert rec.milestone_title == "Q1"
        assert rec.due_date == "2024-03-15"
        assert rec.priority == 2
        assert rec.agency is not None
        assert rec.agency.execution_mode == ExecutionMode.USER
        assert rec.agency.support_mode == SupportMode.EXPLAIN

    def test_from_dict_defaults(self):
        rec = Recommendation.from_dict({})
        assert rec.title == ""
        assert rec.kind == "task"
        assert rec.goal_title == ""
        assert rec.score == 0
        assert rec.reason == ""
        assert rec.project_title is None
        assert rec.milestone_title is None
        assert rec.due_date is None
        assert rec.priority is None
        assert rec.agency is None

    def test_from_dict_partial(self):
        rec = Recommendation.from_dict({"title": "Test", "kind": "project"})
        assert rec.title == "Test"
        assert rec.kind == "project"
        assert rec.goal_title == ""  # default
        assert rec.score == 0  # default
        assert rec.reason == ""  # default
        assert rec.project_title is None  # default
        assert rec.milestone_title is None  # default
        assert rec.due_date is None  # default
        assert rec.priority is None  # default
        assert rec.agency is None  # default

    def test_from_dict_without_agency(self):
        rec = Recommendation.from_dict({"title": "Test", "agency": None})
        assert rec.agency is None

    def test_round_trip(self):
        original = Recommendation(
            title="Design system",
            kind="task",
            goal_title="Build Product",
            score=75,
            reason="Complex task",
            project_title="Architecture",
            milestone_title="Sprint 1",
            due_date="2024-06-30",
            priority=3,
            agency=TaskAgency(
                execution_mode=ExecutionMode.COLLABORATIVE,
                support_mode=SupportMode.SCAFFOLD,
                reason="High complexity",
                confidence=0.7,
            ),
        )
        d = original.to_dict()
        restored = Recommendation.from_dict(d)
        assert restored.title == original.title
        assert restored.kind == original.kind
        assert restored.goal_title == original.goal_title
        assert restored.score == original.score
        assert restored.reason == original.reason
        assert restored.project_title == original.project_title
        assert restored.milestone_title == original.milestone_title
        assert restored.due_date == original.due_date
        assert restored.priority == original.priority
        if original.agency is None or restored.agency is None:
            pytest.fail("agency should not be None")
        original_agency = original.agency
        restored_agency = restored.agency
        assert restored_agency.execution_mode == original_agency.execution_mode
        assert restored_agency.support_mode == original_agency.support_mode
        assert restored_agency.reason == original_agency.reason
        assert restored_agency.confidence == original_agency.confidence

    def test_to_dict_returns_dict(self):
        rec = Recommendation(
            title="Test",
            kind="task",
            goal_title="Goal",
        )
        d = rec.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_values_are_strings(self):
        rec = Recommendation(
            title="Test",
            kind="task",
            goal_title="Goal",
        )
        d = rec.to_dict()
        assert isinstance(d["title"], str)
        assert isinstance(d["kind"], str)
        assert isinstance(d["goal_title"], str)
        assert isinstance(d["score"], int)
        assert isinstance(d["reason"], str)

    def test_from_dict_invalid_kind(self):
        with pytest.raises(ValueError, match="kind must be 'task', 'project', or 'milestone'"):
            Recommendation.from_dict({"kind": "invalid"})
