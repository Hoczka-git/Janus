"""Tests for the Execution Engine V1 — models, policy gate, executor, and service.

Covers:
- ExecutionResult model (serialization, properties)
- ExecutionStatus enum
- PolicyDecision model
- PolicyGate (all 7 validation checks)
- TaskExecutor (CREATE_TASK, UPDATE_TASK, RESCHEDULE_TASK, failure cases)
- ExecutionService (persistence, idempotency)
- ProposalService (persistence, status updates)
- End-to-end flow
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from janus.execution import (
    ActionExecutor,
    ExecutionResult,
    ExecutionService,
    ExecutionStatus,
    PolicyDecision,
    PolicyGate,
    TaskExecutor,
)
from janus.execution.models import ExecutionResult, ExecutionStatus, PolicyDecision
from janus.execution.policy import (
    REQUIRED_PARAMETERS,
    SUPPORTED_ACTION_TYPES,
    PolicyGate,
)
from janus.execution.executor import TaskExecutor
from janus.execution.service import ExecutionService
from janus.execution.proposal_service import ProposalService
from janus.execution.protocol import ActionExecutor
from janus.models.policy import RiskLevel
from janus.proposal.models import ActionProposal, ActionType, ProposalStatus


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_tasks_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temporary tasks.md path and monkeypatch TASKS_PATH."""
    tasks_path = tmp_path / "tasks.md"
    tasks_path.write_text("", encoding="utf-8")
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_path)
    return tasks_path


@pytest.fixture
def tmp_proposals_path(tmp_path: Path) -> Path:
    """Provide a temporary proposals.jsonl path."""
    return tmp_path / "proposals.jsonl"


@pytest.fixture
def tmp_executions_path(tmp_path: Path) -> Path:
    """Provide a temporary executions.jsonl path."""
    return tmp_path / "executions.jsonl"


@pytest.fixture
def sample_create_proposal() -> ActionProposal:
    """A sample CREATE_TASK proposal in PROPOSED status."""
    return ActionProposal(
        proposal_id="AP-001",
        action_type=ActionType.CREATE_TASK,
        parameters={"title": "Test task", "due_date": "2026-10-15", "priority": 2},
        reason="Test proposal",
        source="test",
        risk=RiskLevel.LOW,
        status=ProposalStatus.PROPOSED,
    )


@pytest.fixture
def approved_create_proposal(sample_create_proposal: ActionProposal) -> ActionProposal:
    """A sample CREATE_TASK proposal in APPROVED status."""
    sample_create_proposal.status = ProposalStatus.APPROVED
    return sample_create_proposal


@pytest.fixture
def sample_update_proposal() -> ActionProposal:
    """A sample UPDATE_TASK proposal."""
    return ActionProposal(
        proposal_id="AP-002",
        action_type=ActionType.UPDATE_TASK,
        target_id="Existing task",
        parameters={"new_state": "in_progress", "risk_description": "Test update"},
        reason="Update task state",
        source="test",
        risk=RiskLevel.LOW,
        status=ProposalStatus.APPROVED,
    )


@pytest.fixture
def sample_reschedule_proposal() -> ActionProposal:
    """A sample RESCHEDULE_TASK proposal."""
    return ActionProposal(
        proposal_id="AP-003",
        action_type=ActionType.RESCHEDULE_TASK,
        target_id="Existing task",
        parameters={"new_due_date": "2026-10-20"},
        reason="Reschedule task",
        source="test",
        risk=RiskLevel.LOW,
        status=ProposalStatus.APPROVED,
    )


# ── ExecutionStatus enum ────────────────────────────────────────────────────


class TestExecutionStatus:
    def test_values(self) -> None:
        assert ExecutionStatus.SUCCESS == "SUCCESS"
        assert ExecutionStatus.FAILED == "FAILED"
        assert ExecutionStatus.SKIPPED == "SKIPPED"

    def test_membership(self) -> None:
        assert len(ExecutionStatus) == 3


# ── ExecutionResult model ───────────────────────────────────────────────────


class TestExecutionResult:
    def test_creation_with_defaults(self) -> None:
        result = ExecutionResult()
        assert result.execution_id == ""
        assert result.proposal_id == ""
        assert result.status == ExecutionStatus.SKIPPED
        assert result.action_type == ActionType.CREATE_TASK
        assert result.target_id is None
        assert result.timestamp is not None
        assert result.result_details == {}
        assert result.error is None

    def test_creation_with_values(self) -> None:
        ts = datetime(2026, 10, 2, 12, 0, 0)
        result = ExecutionResult(
            execution_id="EX-abc123",
            proposal_id="AP-001",
            status=ExecutionStatus.SUCCESS,
            action_type=ActionType.CREATE_TASK,
            target_id="Test task",
            timestamp=ts,
            result_details={"task_title": "Test task"},
        )
        assert result.execution_id == "EX-abc123"
        assert result.proposal_id == "AP-001"
        assert result.status == ExecutionStatus.SUCCESS
        assert result.action_type == ActionType.CREATE_TASK
        assert result.target_id == "Test task"
        assert result.timestamp == ts
        assert result.result_details == {"task_title": "Test task"}
        assert result.error is None

    def test_is_success(self) -> None:
        result = ExecutionResult(status=ExecutionStatus.SUCCESS)
        assert result.is_success is True
        assert result.is_failed is False
        assert result.is_skipped is False

    def test_is_failed(self) -> None:
        result = ExecutionResult(status=ExecutionStatus.FAILED)
        assert result.is_success is False
        assert result.is_failed is True
        assert result.is_skipped is False

    def test_is_skipped(self) -> None:
        result = ExecutionResult(status=ExecutionStatus.SKIPPED)
        assert result.is_success is False
        assert result.is_failed is False
        assert result.is_skipped is True

    def test_to_dict(self) -> None:
        ts = datetime(2026, 10, 2, 12, 0, 0)
        result = ExecutionResult(
            execution_id="EX-abc123",
            proposal_id="AP-001",
            status=ExecutionStatus.SUCCESS,
            action_type=ActionType.CREATE_TASK,
            target_id="Test task",
            timestamp=ts,
            result_details={"key": "value"},
            error=None,
        )
        d = result.to_dict()
        assert d["execution_id"] == "EX-abc123"
        assert d["proposal_id"] == "AP-001"
        assert d["status"] == "SUCCESS"
        assert d["action_type"] == "CREATE_TASK"
        assert d["target_id"] == "Test task"
        assert d["timestamp"] == ts.isoformat()
        assert d["result_details"] == {"key": "value"}
        assert d["error"] is None

    def test_from_dict(self) -> None:
        ts = datetime(2026, 10, 2, 12, 0, 0)
        data = {
            "execution_id": "EX-abc123",
            "proposal_id": "AP-001",
            "status": "SUCCESS",
            "action_type": "CREATE_TASK",
            "target_id": "Test task",
            "timestamp": ts.isoformat(),
            "result_details": {"key": "value"},
            "error": None,
        }
        result = ExecutionResult.from_dict(data)
        assert result.execution_id == "EX-abc123"
        assert result.proposal_id == "AP-001"
        assert result.status == ExecutionStatus.SUCCESS
        assert result.action_type == ActionType.CREATE_TASK
        assert result.target_id == "Test task"
        assert result.timestamp == ts
        assert result.result_details == {"key": "value"}
        assert result.error is None

    def test_roundtrip_serialization(self) -> None:
        ts = datetime(2026, 10, 2, 12, 0, 0)
        original = ExecutionResult(
            execution_id="EX-abc123",
            proposal_id="AP-001",
            status=ExecutionStatus.FAILED,
            action_type=ActionType.UPDATE_TASK,
            target_id="Test task",
            timestamp=ts,
            result_details={"error_code": 42},
            error="Something went wrong",
        )
        d = original.to_dict()
        restored = ExecutionResult.from_dict(d)
        assert restored.execution_id == original.execution_id
        assert restored.proposal_id == original.proposal_id
        assert restored.status == original.status
        assert restored.action_type == original.action_type
        assert restored.target_id == original.target_id
        assert restored.timestamp == original.timestamp
        assert restored.result_details == original.result_details
        assert restored.error == original.error

    def test_empty_execution_id_raises(self) -> None:
        with pytest.raises(ValueError, match="execution_id must not be empty"):
            ExecutionResult(execution_id="   ")

    def test_from_dict_with_missing_fields(self) -> None:
        result = ExecutionResult.from_dict({})
        assert result.execution_id == ""
        assert result.proposal_id == ""
        assert result.status == ExecutionStatus.SKIPPED
        assert result.action_type == ActionType.CREATE_TASK


# ── PolicyDecision model ─────────────────────────────────────────────────────


class TestPolicyDecision:
    def test_creation(self) -> None:
        decision = PolicyDecision(allowed=True, reason="OK", proposal_id="AP-001")
        assert decision.allowed is True
        assert decision.reason == "OK"
        assert decision.proposal_id == "AP-001"

    def test_to_dict(self) -> None:
        decision = PolicyDecision(allowed=False, reason="Blocked", proposal_id="AP-001")
        d = decision.to_dict()
        assert d == {"allowed": False, "reason": "Blocked", "proposal_id": "AP-001"}


# ── PolicyGate ──────────────────────────────────────────────────────────────


class TestPolicyGate:
    def test_supported_action_types(self) -> None:
        assert ActionType.CREATE_TASK in SUPPORTED_ACTION_TYPES
        assert ActionType.UPDATE_TASK in SUPPORTED_ACTION_TYPES
        assert ActionType.RESCHEDULE_TASK in SUPPORTED_ACTION_TYPES
        assert ActionType.CHANGE_PRIORITY not in SUPPORTED_ACTION_TYPES
        assert ActionType.CREATE_CALENDAR_EVENT not in SUPPORTED_ACTION_TYPES

    def test_required_parameters(self) -> None:
        assert "title" in REQUIRED_PARAMETERS[ActionType.CREATE_TASK]
        assert "risk_description" in REQUIRED_PARAMETERS[ActionType.UPDATE_TASK]
        assert "new_due_date" in REQUIRED_PARAMETERS[ActionType.RESCHEDULE_TASK]

    def test_none_proposal_blocked(self) -> None:
        gate = PolicyGate()
        decision = gate.evaluate(None)  # type: ignore[arg-type]
        assert decision.allowed is False
        assert "None" in decision.reason

    def test_missing_proposal_id_blocked(self) -> None:
        gate = PolicyGate()
        proposal = ActionProposal(
            proposal_id="",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is False
        assert "no ID" in decision.reason

    def test_empty_reason_blocked_by_model(self) -> None:
        """ActionProposal model itself prevents empty reason."""
        with pytest.raises(ValueError, match="reason must not be empty"):
            ActionProposal(
                proposal_id="AP-001",
                action_type=ActionType.CREATE_TASK,
                parameters={"title": "Test"},
                reason="",
                status=ProposalStatus.APPROVED,
            )

    def test_unapproved_proposal_blocked(self) -> None:
        gate = PolicyGate()
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test"},
            reason="Test",
            status=ProposalStatus.PROPOSED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is False
        assert "not APPROVED" in decision.reason

    def test_rejected_proposal_blocked(self) -> None:
        gate = PolicyGate()
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test"},
            reason="Test",
            status=ProposalStatus.REJECTED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is False
        assert "not APPROVED" in decision.reason

    def test_already_executed_blocked(self) -> None:
        gate = PolicyGate(is_executed=lambda pid: True)
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is False
        assert "already been executed" in decision.reason

    def test_unsupported_action_type_blocked(self) -> None:
        gate = PolicyGate()
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CHANGE_PRIORITY,
            parameters={"new_priority": 1},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is False
        assert "not supported" in decision.reason

    def test_missing_required_parameters_blocked(self) -> None:
        gate = PolicyGate()
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is False
        assert "Missing required parameters" in decision.reason

    def test_update_task_missing_target_blocked(self) -> None:
        gate = PolicyGate()
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.UPDATE_TASK,
            target_id=None,
            parameters={"risk_description": "Test"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is False
        assert "requires a target_id" in decision.reason

    def test_reschedule_task_missing_target_blocked(self) -> None:
        gate = PolicyGate()
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.RESCHEDULE_TASK,
            target_id=None,
            parameters={"new_due_date": "2026-10-20"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is False
        assert "requires a target_id" in decision.reason

    def test_valid_proposal_passes(self) -> None:
        gate = PolicyGate()
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test task"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is True
        assert decision.reason == "Policy check passed"
        assert decision.proposal_id == "AP-001"

    def test_valid_update_task_passes(self) -> None:
        gate = PolicyGate()
        proposal = ActionProposal(
            proposal_id="AP-002",
            action_type=ActionType.UPDATE_TASK,
            target_id="Existing task",
            parameters={"risk_description": "Test"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is True

    def test_valid_reschedule_task_passes(self) -> None:
        gate = PolicyGate()
        proposal = ActionProposal(
            proposal_id="AP-003",
            action_type=ActionType.RESCHEDULE_TASK,
            target_id="Existing task",
            parameters={"new_due_date": "2026-10-20"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        decision = gate.evaluate(proposal)
        assert decision.allowed is True


# ── TaskExecutor ────────────────────────────────────────────────────────────


class TestTaskExecutor:
    def test_is_action_executor(self) -> None:
        executor = TaskExecutor()
        assert isinstance(executor, ActionExecutor)

    def test_execute_create_task_success(
        self, tmp_tasks_path: Path, approved_create_proposal: ActionProposal
    ) -> None:
        executor = TaskExecutor()
        result = executor.execute(approved_create_proposal)
        assert result.status == ExecutionStatus.SUCCESS
        assert result.proposal_id == "AP-001"
        assert result.action_type == ActionType.CREATE_TASK
        assert result.error is None
        assert result.result_details["task_title"] == "Test task"

    def test_execute_create_task_persists_to_file(
        self, tmp_tasks_path: Path, approved_create_proposal: ActionProposal
    ) -> None:
        executor = TaskExecutor()
        result = executor.execute(approved_create_proposal)
        assert result.status == ExecutionStatus.SUCCESS
        content = tmp_tasks_path.read_text(encoding="utf-8")
        assert "Test task" in content

    def test_execute_create_task_empty_title(
        self, tmp_tasks_path: Path
    ) -> None:
        """Empty title passes policy gate (key exists) but fails in executor."""
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": ""},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        executor = TaskExecutor()
        result = executor.execute(proposal)
        assert result.status == ExecutionStatus.FAILED
        assert result.error is not None
        assert "title" in result.error.lower()

    def test_execute_create_task_invalid_due_date(
        self, tmp_tasks_path: Path
    ) -> None:
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test", "due_date": "not-a-date"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        executor = TaskExecutor()
        result = executor.execute(proposal)
        assert result.status == ExecutionStatus.FAILED
        assert result.error is not None
        assert "Invalid due date" in result.error

    def test_execute_create_task_invalid_priority(
        self, tmp_tasks_path: Path
    ) -> None:
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test", "priority": "high"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        executor = TaskExecutor()
        result = executor.execute(proposal)
        assert result.status == ExecutionStatus.FAILED
        assert result.error is not None
        assert "Invalid priority" in result.error

    def test_execute_unapproved_proposal_skipped(
        self, tmp_tasks_path: Path, sample_create_proposal: ActionProposal
    ) -> None:
        executor = TaskExecutor()
        result = executor.execute(sample_create_proposal)
        assert result.status == ExecutionStatus.SKIPPED
        assert result.error is not None
        assert "not APPROVED" in result.error

    def test_execute_update_task_success(
        self, tmp_tasks_path: Path, sample_update_proposal: ActionProposal
    ) -> None:
        from janus.services.tasks import add_task

        add_task("Existing task", date(2026, 10, 10), 1)
        executor = TaskExecutor()
        result = executor.execute(sample_update_proposal)
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result_details["new_state"] == "in_progress"

    def test_execute_update_task_not_found(
        self, tmp_tasks_path: Path, sample_update_proposal: ActionProposal
    ) -> None:
        executor = TaskExecutor()
        result = executor.execute(sample_update_proposal)
        assert result.status == ExecutionStatus.FAILED
        assert result.error is not None

    def test_execute_update_task_invalid_state(
        self, tmp_tasks_path: Path
    ) -> None:
        from janus.services.tasks import add_task

        add_task("Existing task", date(2026, 10, 10), 1)
        proposal = ActionProposal(
            proposal_id="AP-002",
            action_type=ActionType.UPDATE_TASK,
            target_id="Existing task",
            parameters={"new_state": "invalid_state", "risk_description": "Test"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        executor = TaskExecutor()
        result = executor.execute(proposal)
        assert result.status == ExecutionStatus.FAILED
        assert result.error is not None
        assert "Invalid state" in result.error

    def test_execute_reschedule_task_success(
        self, tmp_tasks_path: Path, sample_reschedule_proposal: ActionProposal
    ) -> None:
        from janus.services.tasks import add_task

        add_task("Existing task", date(2026, 10, 10), 1)
        executor = TaskExecutor()
        result = executor.execute(sample_reschedule_proposal)
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result_details["new_due_date"] == "2026-10-20"

    def test_execute_reschedule_task_not_found(
        self, tmp_tasks_path: Path, sample_reschedule_proposal: ActionProposal
    ) -> None:
        executor = TaskExecutor()
        result = executor.execute(sample_reschedule_proposal)
        assert result.status == ExecutionStatus.FAILED
        assert result.error is not None

    def test_execute_reschedule_task_invalid_date(
        self, tmp_tasks_path: Path
    ) -> None:
        from janus.services.tasks import add_task

        add_task("Existing task", date(2026, 10, 10), 1)
        proposal = ActionProposal(
            proposal_id="AP-003",
            action_type=ActionType.RESCHEDULE_TASK,
            target_id="Existing task",
            parameters={"new_due_date": "not-a-date"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        executor = TaskExecutor()
        result = executor.execute(proposal)
        assert result.status == ExecutionStatus.FAILED
        assert result.error is not None
        assert "Invalid due date" in result.error

    def test_execute_unsupported_action_type(
        self, tmp_tasks_path: Path
    ) -> None:
        proposal = ActionProposal(
            proposal_id="AP-004",
            action_type=ActionType.CHANGE_PRIORITY,
            target_id="Existing task",
            parameters={"new_priority": 1},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        executor = TaskExecutor()
        result = executor.execute(proposal)
        assert result.status == ExecutionStatus.SKIPPED
        assert result.error is not None
        assert "not supported" in result.error


# ── ExecutionService ────────────────────────────────────────────────────────


class TestExecutionService:
    def test_execute_and_persist(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
    ) -> None:
        service = ExecutionService(executions_path=tmp_executions_path)
        result = service.execute(approved_create_proposal)
        assert result.status == ExecutionStatus.SUCCESS
        assert tmp_executions_path.exists()
        content = tmp_executions_path.read_text(encoding="utf-8")
        record = json.loads(content.strip())
        assert record["proposal_id"] == "AP-001"
        assert record["status"] == "SUCCESS"

    def test_idempotency_prevents_duplicate_execution(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
    ) -> None:
        service = ExecutionService(executions_path=tmp_executions_path)
        result1 = service.execute(approved_create_proposal)
        assert result1.status == ExecutionStatus.SUCCESS

        result2 = service.execute(approved_create_proposal)
        assert result2.status == ExecutionStatus.SKIPPED
        assert result2.error is not None
        assert "already been executed" in result2.error

        # Verify only one task was created
        content = tmp_tasks_path.read_text(encoding="utf-8")
        assert content.count("Test task") == 1

    def test_is_executed_returns_false_for_new_proposal(
        self, tmp_executions_path: Path
    ) -> None:
        service = ExecutionService(executions_path=tmp_executions_path)
        assert service.is_executed("AP-999") is False

    def test_is_executed_returns_true_after_execution(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
    ) -> None:
        service = ExecutionService(executions_path=tmp_executions_path)
        assert service.is_executed("AP-001") is False
        service.execute(approved_create_proposal)
        assert service.is_executed("AP-001") is True

    def test_get_execution_by_id(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
    ) -> None:
        service = ExecutionService(executions_path=tmp_executions_path)
        result = service.execute(approved_create_proposal)
        retrieved = service.get_execution(result.execution_id)
        assert retrieved is not None
        assert retrieved.execution_id == result.execution_id
        assert retrieved.proposal_id == "AP-001"
        assert retrieved.status == ExecutionStatus.SUCCESS

    def test_get_execution_not_found(self, tmp_executions_path: Path) -> None:
        service = ExecutionService(executions_path=tmp_executions_path)
        assert service.get_execution("EX-nonexistent") is None

    def test_list_executions(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
    ) -> None:
        service = ExecutionService(executions_path=tmp_executions_path)
        assert service.list_executions() == []
        service.execute(approved_create_proposal)
        executions = service.list_executions()
        assert len(executions) == 1
        assert executions[0].proposal_id == "AP-001"

    def test_list_executions_empty(self, tmp_executions_path: Path) -> None:
        service = ExecutionService(executions_path=tmp_executions_path)
        assert service.list_executions() == []

    def test_persists_failed_execution(
        self, tmp_tasks_path: Path, tmp_executions_path: Path
    ) -> None:
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": ""},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        service = ExecutionService(executions_path=tmp_executions_path)
        result = service.execute(proposal)
        assert result.status == ExecutionStatus.FAILED
        assert tmp_executions_path.exists()
        content = tmp_executions_path.read_text(encoding="utf-8")
        record = json.loads(content.strip())
        assert record["status"] == "FAILED"

    def test_persists_skipped_execution(
        self, tmp_tasks_path: Path, tmp_executions_path: Path
    ) -> None:
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test"},
            reason="Test",
            status=ProposalStatus.PROPOSED,
        )
        service = ExecutionService(executions_path=tmp_executions_path)
        result = service.execute(proposal)
        assert result.status == ExecutionStatus.SKIPPED
        assert tmp_executions_path.exists()


# ── ProposalService ─────────────────────────────────────────────────────────


class TestProposalService:
    def test_save_and_get_proposal(self, tmp_proposals_path: Path) -> None:
        service = ProposalService(proposals_path=tmp_proposals_path)
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test"},
            reason="Test",
            status=ProposalStatus.PROPOSED,
        )
        service.save_proposal(proposal)
        retrieved = service.get_proposal("AP-001")
        assert retrieved is not None
        assert retrieved.proposal_id == "AP-001"
        assert retrieved.action_type == ActionType.CREATE_TASK

    def test_get_proposal_not_found(self, tmp_proposals_path: Path) -> None:
        service = ProposalService(proposals_path=tmp_proposals_path)
        assert service.get_proposal("AP-999") is None

    def test_list_proposals(self, tmp_proposals_path: Path) -> None:
        service = ProposalService(proposals_path=tmp_proposals_path)
        assert service.list_proposals() == []
        for i in range(3):
            service.save_proposal(
                ActionProposal(
                    proposal_id=f"AP-{i:03d}",
                    action_type=ActionType.CREATE_TASK,
                    parameters={"title": f"Task {i}"},
                    reason="Test",
                )
            )
        proposals = service.list_proposals()
        assert len(proposals) == 3

    def test_update_status(self, tmp_proposals_path: Path) -> None:
        service = ProposalService(proposals_path=tmp_proposals_path)
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test"},
            reason="Test",
            status=ProposalStatus.PROPOSED,
        )
        service.save_proposal(proposal)
        updated = service.update_status("AP-001", ProposalStatus.APPROVED)
        assert updated is not None
        assert updated.status == ProposalStatus.APPROVED
        retrieved = service.get_proposal("AP-001")
        assert retrieved is not None
        assert retrieved.status == ProposalStatus.APPROVED

    def test_update_status_not_found(self, tmp_proposals_path: Path) -> None:
        service = ProposalService(proposals_path=tmp_proposals_path)
        assert service.update_status("AP-999", ProposalStatus.APPROVED) is None

    def test_save_proposal_updates_existing(self, tmp_proposals_path: Path) -> None:
        service = ProposalService(proposals_path=tmp_proposals_path)
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test"},
            reason="Test",
            status=ProposalStatus.PROPOSED,
        )
        service.save_proposal(proposal)
        proposal.status = ProposalStatus.APPROVED
        service.save_proposal(proposal)
        proposals = service.list_proposals()
        assert len(proposals) == 1
        assert proposals[0].status == ProposalStatus.APPROVED


# ── End-to-end flow ─────────────────────────────────────────────────────────


class TestEndToEnd:
    def test_full_flow_create_task(
        self,
        tmp_tasks_path: Path,
        tmp_proposals_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        """Proposal -> Approval -> Policy -> Execution -> Result."""
        proposal_service = ProposalService(proposals_path=tmp_proposals_path)
        execution_service = ExecutionService(executions_path=tmp_executions_path)

        # 1. Create proposal
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "E2E test task", "due_date": "2026-10-15"},
            reason="E2E test",
            status=ProposalStatus.PROPOSED,
        )
        proposal_service.save_proposal(proposal)

        # 2. Approve
        approved = proposal_service.update_status("AP-001", ProposalStatus.APPROVED)
        assert approved is not None
        assert approved.status == ProposalStatus.APPROVED

        # 3. Execute
        result = execution_service.execute(approved)
        assert result.status == ExecutionStatus.SUCCESS
        assert result.proposal_id == "AP-001"

        # 4. Verify task was created
        content = tmp_tasks_path.read_text(encoding="utf-8")
        assert "E2E test task" in content

        # 5. Verify execution was persisted
        executions = execution_service.list_executions()
        assert len(executions) == 1
        assert executions[0].status == ExecutionStatus.SUCCESS

    def test_full_flow_update_task(
        self,
        tmp_tasks_path: Path,
        tmp_proposals_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        from janus.services.tasks import add_task

        add_task("Existing task", date(2026, 10, 10), 1)
        proposal_service = ProposalService(proposals_path=tmp_proposals_path)
        execution_service = ExecutionService(executions_path=tmp_executions_path)

        proposal = ActionProposal(
            proposal_id="AP-002",
            action_type=ActionType.UPDATE_TASK,
            target_id="Existing task",
            parameters={"new_state": "in_progress", "risk_description": "Test"},
            reason="E2E test",
            status=ProposalStatus.APPROVED,
        )
        proposal_service.save_proposal(proposal)
        result = execution_service.execute(proposal)
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result_details["new_state"] == "in_progress"

    def test_full_flow_reschedule_task(
        self,
        tmp_tasks_path: Path,
        tmp_proposals_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        from janus.services.tasks import add_task

        add_task("Existing task", date(2026, 10, 10), 1)
        proposal_service = ProposalService(proposals_path=tmp_proposals_path)
        execution_service = ExecutionService(executions_path=tmp_executions_path)

        proposal = ActionProposal(
            proposal_id="AP-003",
            action_type=ActionType.RESCHEDULE_TASK,
            target_id="Existing task",
            parameters={"new_due_date": "2026-10-25"},
            reason="E2E test",
            status=ProposalStatus.APPROVED,
        )
        proposal_service.save_proposal(proposal)
        result = execution_service.execute(proposal)
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result_details["new_due_date"] == "2026-10-25"

    def test_unapproved_proposal_cannot_execute(
        self,
        tmp_tasks_path: Path,
        tmp_proposals_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        proposal_service = ProposalService(proposals_path=tmp_proposals_path)
        execution_service = ExecutionService(executions_path=tmp_executions_path)

        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Should not be created"},
            reason="Test",
            status=ProposalStatus.PROPOSED,
        )
        proposal_service.save_proposal(proposal)
        result = execution_service.execute(proposal)
        assert result.status == ExecutionStatus.SKIPPED
        content = tmp_tasks_path.read_text(encoding="utf-8")
        assert "Should not be created" not in content

    def test_rejected_proposal_cannot_execute(
        self,
        tmp_tasks_path: Path,
        tmp_proposals_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        proposal_service = ProposalService(proposals_path=tmp_proposals_path)
        execution_service = ExecutionService(executions_path=tmp_executions_path)

        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Should not be created"},
            reason="Test",
            status=ProposalStatus.REJECTED,
        )
        proposal_service.save_proposal(proposal)
        result = execution_service.execute(proposal)
        assert result.status == ExecutionStatus.SKIPPED
        content = tmp_tasks_path.read_text(encoding="utf-8")
        assert "Should not be created" not in content

    def test_duplicate_execution_prevented(
        self,
        tmp_tasks_path: Path,
        tmp_proposals_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        proposal_service = ProposalService(proposals_path=tmp_proposals_path)
        execution_service = ExecutionService(executions_path=tmp_executions_path)

        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Unique task"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        proposal_service.save_proposal(proposal)

        result1 = execution_service.execute(proposal)
        assert result1.status == ExecutionStatus.SUCCESS

        result2 = execution_service.execute(proposal)
        assert result2.status == ExecutionStatus.SKIPPED

        content = tmp_tasks_path.read_text(encoding="utf-8")
        assert content.count("Unique task") == 1

    def test_unsupported_action_blocked(
        self,
        tmp_tasks_path: Path,
        tmp_proposals_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        proposal_service = ProposalService(proposals_path=tmp_proposals_path)
        execution_service = ExecutionService(executions_path=tmp_executions_path)

        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_CALENDAR_EVENT,
            parameters={"title": "Meeting"},
            reason="Test",
            status=ProposalStatus.APPROVED,
        )
        proposal_service.save_proposal(proposal)
        result = execution_service.execute(proposal)
        assert result.status == ExecutionStatus.SKIPPED
        assert result.error is not None
        assert "not supported" in result.error
