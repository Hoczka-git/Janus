"""Tests for the Action Proposal Engine interface and domain models."""

from __future__ import annotations

from datetime import datetime

import pytest

from janus.models.policy import RiskLevel
from janus.planner.models import (
    PlannedTask,
    PlanningContext,
    PlanningRisk,
    PlanningSignals,
    Priority,
    PriorityEntry,
    RiskSeverity,
    WeeklyPlan,
)
from janus.proposal import (
    ActionProposal,
    ActionProposalEngine,
    ActionType,
    ProposalStatus,
)


# ── ActionType enum ──────────────────────────────────────────────────────────


class TestActionType:
    def test_values(self) -> None:
        assert ActionType.CREATE_TASK == "CREATE_TASK"
        assert ActionType.UPDATE_TASK == "UPDATE_TASK"
        assert ActionType.RESCHEDULE_TASK == "RESCHEDULE_TASK"
        assert ActionType.CHANGE_PRIORITY == "CHANGE_PRIORITY"
        assert ActionType.CREATE_CALENDAR_EVENT == "CREATE_CALENDAR_EVENT"

    def test_membership(self) -> None:
        assert len(ActionType) == 5

    def test_no_mutation_types(self) -> None:
        """V1 proposal engine must not expose mutation action types."""
        # These are the only allowed action types in V1
        allowed = {at.value for at in ActionType}
        assert "DELETE_TASK" not in allowed
        assert "DELETE_GOAL" not in allowed
        assert "DELETE_CALENDAR_EVENT" not in allowed
        assert "EXECUTE" not in allowed


# ── ProposalStatus enum ─────────────────────────────────────────────────────


class TestProposalStatus:
    def test_values(self) -> None:
        assert ProposalStatus.PROPOSED == "PROPOSED"
        assert ProposalStatus.APPROVED == "APPROVED"
        assert ProposalStatus.REJECTED == "REJECTED"
        assert ProposalStatus.EXECUTED == "EXECUTED"

    def test_membership(self) -> None:
        assert len(ProposalStatus) == 4


# ── ActionProposal model ─────────────────────────────────────────────────────


class TestActionProposal:
    def test_minimal_construct(self) -> None:
        ap = ActionProposal(
            reason="Test proposal",
        )
        assert ap.proposal_id == ""
        assert ap.action_type == ActionType.CREATE_TASK
        assert ap.target_id is None
        assert ap.parameters == {}
        assert ap.reason == "Test proposal"
        assert ap.source == ""
        assert ap.risk == RiskLevel.LOW
        assert ap.status == ProposalStatus.PROPOSED
        assert ap.is_actionable is True

    def test_full_construct(self) -> None:
        ap = ActionProposal(
            proposal_id="AP-abc123",
            action_type=ActionType.RESCHEDULE_TASK,
            target_id="task-123",
            parameters={"new_due_date": "2026-10-10"},
            reason="Task is overdue",
            source="rule:overdue",
            risk=RiskLevel.MEDIUM,
            status=ProposalStatus.PROPOSED,
        )
        assert ap.proposal_id == "AP-abc123"
        assert ap.action_type == ActionType.RESCHEDULE_TASK
        assert ap.target_id == "task-123"
        assert ap.parameters == {"new_due_date": "2026-10-10"}
        assert ap.reason == "Task is overdue"
        assert ap.source == "rule:overdue"
        assert ap.risk == RiskLevel.MEDIUM
        assert ap.status == ProposalStatus.PROPOSED

    def test_empty_reason_raises(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            ActionProposal(reason="")

    def test_whitespace_proposal_id_raises(self) -> None:
        with pytest.raises(ValueError, match="proposal_id"):
            ActionProposal(proposal_id="   ", reason="test")

    def test_timestamps_auto_set(self) -> None:
        ap = ActionProposal(reason="test")
        assert ap.created_at is not None
        assert ap.updated_at is not None
        assert ap.updated_at == ap.created_at

    def test_is_actionable_only_when_proposed(self) -> None:
        ap = ActionProposal(reason="test", status=ProposalStatus.PROPOSED)
        assert ap.is_actionable is True

        ap.status = ProposalStatus.APPROVED
        assert ap.is_actionable is False

        ap.status = ProposalStatus.REJECTED
        assert ap.is_actionable is False

        ap.status = ProposalStatus.EXECUTED
        assert ap.is_actionable is False

    def test_to_dict(self) -> None:
        ap = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            reason="Test",
            source="test",
            risk=RiskLevel.LOW,
        )
        d = ap.to_dict()
        assert d["proposal_id"] == "AP-001"
        assert d["action_type"] == "CREATE_TASK"
        assert d["reason"] == "Test"
        assert d["source"] == "test"
        assert d["risk"] == "low"
        assert d["status"] == "PROPOSED"
        assert "created_at" in d
        assert "updated_at" in d

    def test_from_dict(self) -> None:
        ap = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.RESCHEDULE_TASK,
            target_id="task-1",
            parameters={"new_due_date": "2026-10-10"},
            reason="Overdue",
            source="rule:overdue",
            risk=RiskLevel.MEDIUM,
        )
        d = ap.to_dict()
        ap2 = ActionProposal.from_dict(d)
        assert ap2.proposal_id == ap.proposal_id
        assert ap2.action_type == ap.action_type
        assert ap2.target_id == ap.target_id
        assert ap2.parameters == ap.parameters
        assert ap2.reason == ap.reason
        assert ap2.source == ap.source
        assert ap2.risk == ap.risk
        assert ap2.status == ap.status

    def test_serialization_roundtrip(self) -> None:
        ap = ActionProposal(
            proposal_id="AP-roundtrip",
            action_type=ActionType.CHANGE_PRIORITY,
            target_id="task-42",
            parameters={"new_priority": 1},
            reason="High priority goal",
            source="rule:priority",
            risk=RiskLevel.LOW,
            metadata={"goal_id": "career"},
        )
        d = ap.to_dict()
        ap2 = ActionProposal.from_dict(d)
        assert ap2.to_dict() == d


# ── ActionProposalEngine protocol ────────────────────────────────────────────


class TestActionProposalEngineProtocol:
    def test_is_protocol(self) -> None:
        assert hasattr(ActionProposalEngine, "_is_protocol")
        assert getattr(ActionProposalEngine, "_is_protocol") is True

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            ActionProposalEngine()  # type: ignore[abstract]

    def test_concrete_implementation(self) -> None:
        """A concrete class implementing the protocol can be instantiated."""

        class MockProposalEngine:
            def generate(
                self,
                plan: WeeklyPlan,
                context: PlanningContext,
            ) -> list[ActionProposal]:
                return []

        engine: ActionProposalEngine = MockProposalEngine()  # type: ignore[assignment]
        plan = WeeklyPlan(week_summary="test")
        ctx = PlanningContext(goals=[], tasks=[], calendar=[])
        proposals = engine.generate(plan, ctx)
        assert proposals == []

    def test_generate_returns_list(self) -> None:
        """Generate must return a list (possibly empty)."""

        class MockProposalEngine:
            def generate(
                self,
                plan: WeeklyPlan,
                context: PlanningContext,
            ) -> list[ActionProposal]:
                return [
                    ActionProposal(reason="test1"),
                    ActionProposal(reason="test2"),
                ]

        engine: ActionProposalEngine = MockProposalEngine()  # type: ignore[assignment]
        plan = WeeklyPlan(week_summary="test")
        ctx = PlanningContext(goals=[], tasks=[], calendar=[])
        proposals = engine.generate(plan, ctx)
        assert isinstance(proposals, list)
        assert len(proposals) == 2
        assert all(isinstance(p, ActionProposal) for p in proposals)


# ── No mutation methods guarantee ────────────────────────────────────────────


class TestNoMutationMethods:
    def test_proposal_model_has_no_mutation_methods(self) -> None:
        """ActionProposal must not expose any mutation methods."""
        ap = ActionProposal(reason="test")
        # These methods must NOT exist on ActionProposal
        assert not hasattr(ap, "execute")
        assert not hasattr(ap, "apply")
        assert not hasattr(ap, "mutate")
        assert not hasattr(ap, "create_task")
        assert not hasattr(ap, "update_task")
        assert not hasattr(ap, "delete_task")
        assert not hasattr(ap, "modify_goal")
        assert not hasattr(ap, "create_calendar_event")
        assert not hasattr(ap, "write")

    def test_engine_protocol_has_no_mutation_methods(self) -> None:
        """ActionProposalEngine protocol must not expose mutation methods."""
        # The protocol only has 'generate'
        assert hasattr(ActionProposalEngine, "generate")
        assert not hasattr(ActionProposalEngine, "execute")
        assert not hasattr(ActionProposalEngine, "apply")
        assert not hasattr(ActionProposalEngine, "mutate")
        assert not hasattr(ActionProposalEngine, "create_task")
        assert not hasattr(ActionProposalEngine, "update_task")
        assert not hasattr(ActionProposalEngine, "delete_task")
        assert not hasattr(ActionProposalEngine, "modify_goal")
        assert not hasattr(ActionProposalEngine, "create_calendar_event")
        assert not hasattr(ActionProposalEngine, "write")

    def test_proposal_status_transitions_not_mutations(self) -> None:
        """Status field is data, not a mutation method."""
        ap = ActionProposal(reason="test")
        # Status is a field, not a method
        assert isinstance(ap.status, ProposalStatus)
        # Changing status is just setting a field — not executing the action
        ap.status = ProposalStatus.APPROVED
        assert ap.status == ProposalStatus.APPROVED
