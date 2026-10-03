"""Integration tests for the execution loop.

Exercises the full flow:
    ActionProposal -> Execution -> Evidence Collection -> Outcome Verification

Covers:
- Happy path: execution succeeds, evidence matches, verification VERIFIED
- Execution succeeds but evidence doesn't match -> UNVERIFIED
- Execution fails -> INCONCLUSIVE
- No intended state -> INCONCLUSIVE
- Partial evidence -> INCONCLUSIVE or UNVERIFIED
- derive_intended_state from proposal metadata
- _build_result_message from ExecutionResult
- ExecutionLoopResult serialization
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from janus.execution.loop import (
    ExecutionLoopResult,
    _build_result_message,
    derive_intended_state,
    run_execution_loop,
)
from janus.execution.models import ExecutionResult, ExecutionStatus
from janus.execution.service import ExecutionService
from janus.models.policy import RiskLevel
from janus.proposal.models import ActionProposal, ActionType, ProposalStatus
from janus.services.evidence import EvidenceStatus
from janus.services.evidence_collection import EvidenceCollector
from janus.services.execution_feedback import (
    EvidencePackage,
    ExecutionResultMessage,
    JanusDomainMetadata,
)
from janus.services.outcome_verification import (
    IntendedState,
    VerificationStatus,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_tasks_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temporary tasks.md path and monkeypatch TASKS_PATH."""
    tasks_path = tmp_path / "tasks.md"
    tasks_path.write_text("", encoding="utf-8")
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_path)
    return tasks_path


@pytest.fixture
def tmp_executions_path(tmp_path: Path) -> Path:
    """Provide a temporary executions.jsonl path."""
    return tmp_path / "executions.jsonl"


@pytest.fixture
def approved_create_proposal() -> ActionProposal:
    """A sample approved CREATE_TASK proposal."""
    return ActionProposal(
        proposal_id="AP-001",
        action_type=ActionType.CREATE_TASK,
        parameters={"title": "Test task", "due_date": "2026-10-15", "priority": 2},
        reason="Test proposal",
        source="test",
        risk=RiskLevel.LOW,
        status=ProposalStatus.APPROVED,
    )


@pytest.fixture
def approved_update_proposal() -> ActionProposal:
    """A sample approved UPDATE_TASK proposal."""
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
def approved_reschedule_proposal() -> ActionProposal:
    """A sample approved RESCHEDULE_TASK proposal."""
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


@pytest.fixture
def full_intended_state() -> IntendedState:
    """An intended state with all fields populated."""
    return IntendedState(
        expected_changed_files=["src/foo.py", "tests/test_foo.py"],
        expected_tests_passed=True,
        expected_pr_url="https://github.com/example/repo/pull/42",
        expected_summary_contains=["Test task"],
        expected_body_contains=["test"],
        expected_metric_updates=[{"metric_name": "X", "value": 1.0}],
    )


@pytest.fixture
def minimal_intended_state() -> IntendedState:
    """An intended state with only tests_passed check."""
    return IntendedState(expected_tests_passed=True)


def _make_mock_executor(
    *,
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
    result_details: dict | None = None,
    error: str | None = None,
) -> MagicMock:
    """Create a mock executor that returns a controlled ExecutionResult."""
    mock = MagicMock()
    mock.execute.return_value = ExecutionResult(
        execution_id="EX-mock",
        proposal_id="AP-001",
        status=status,
        action_type=ActionType.CREATE_TASK,
        target_id="Test task",
        result_details=result_details or {"task_title": "Test task"},
        error=error,
    )
    return mock


# ── _build_result_message tests ──────────────────────────────────────────────


class TestBuildResultMessage:
    """Tests for _build_result_message bridge function."""

    def test_builds_message_from_success_result(
        self, approved_create_proposal: ActionProposal
    ) -> None:
        result = ExecutionResult(
            execution_id="EX-abc123",
            proposal_id="AP-001",
            status=ExecutionStatus.SUCCESS,
            action_type=ActionType.CREATE_TASK,
            target_id="Test task",
            result_details={
                "task_title": "Test task",
                "changed_files": ["src/foo.py"],
                "tests_passed": True,
                "pr_url": "https://github.com/example/repo/pull/42",
            },
        )
        msg = _build_result_message(result, approved_create_proposal)
        assert isinstance(msg, ExecutionResultMessage)
        assert msg.metadata.object == "task"
        assert msg.metadata.title == "Test task"
        assert msg.evidence.task_id == "AP-001"
        assert msg.evidence.changed_files == ["src/foo.py"]
        assert msg.evidence.tests_passed is True
        assert msg.evidence.pr_url == "https://github.com/example/repo/pull/42"

    def test_builds_message_from_failed_result(
        self, approved_create_proposal: ActionProposal
    ) -> None:
        result = ExecutionResult(
            execution_id="EX-abc123",
            proposal_id="AP-001",
            status=ExecutionStatus.FAILED,
            action_type=ActionType.CREATE_TASK,
            target_id="Test task",
            error="Something went wrong",
        )
        msg = _build_result_message(result, approved_create_proposal)
        assert msg.evidence.summary == "Something went wrong"
        assert msg.evidence.changed_files == []
        assert msg.evidence.tests_passed is None

    def test_builds_message_with_no_result_details(
        self, approved_create_proposal: ActionProposal
    ) -> None:
        result = ExecutionResult(
            execution_id="EX-abc123",
            proposal_id="AP-001",
            status=ExecutionStatus.SUCCESS,
            action_type=ActionType.CREATE_TASK,
            target_id="Test task",
        )
        msg = _build_result_message(result, approved_create_proposal)
        assert msg.evidence.changed_files == []
        assert msg.evidence.tests_passed is None
        assert msg.evidence.pr_url is None

    def test_builds_message_uses_proposal_title_when_no_target(
        self, approved_create_proposal: ActionProposal
    ) -> None:
        """When target_id is None, falls back to proposal parameters title."""
        approved_create_proposal.target_id = None
        result = ExecutionResult(
            execution_id="EX-abc123",
            proposal_id="AP-001",
            status=ExecutionStatus.SUCCESS,
            action_type=ActionType.CREATE_TASK,
            result_details={"task_title": "Test task"},
        )
        msg = _build_result_message(result, approved_create_proposal)
        assert msg.metadata.title == "Test task"


# ── derive_intended_state tests ──────────────────────────────────────────────


class TestDeriveIntendedState:
    """Tests for derive_intended_state function."""

    def test_returns_empty_intended_state_when_no_metadata(
        self, approved_create_proposal: ActionProposal
    ) -> None:
        state = derive_intended_state(approved_create_proposal)
        assert state.expected_changed_files is None
        assert state.expected_tests_passed is None
        assert state.expected_pr_url is None
        assert state.expected_summary_contains is None
        assert state.expected_body_contains is None
        assert state.expected_metric_updates is None
        assert state.require_all_changed_files is True

    def test_extracts_expected_tests_passed(
        self, approved_create_proposal: ActionProposal
    ) -> None:
        approved_create_proposal.metadata["expected_tests_passed"] = True
        state = derive_intended_state(approved_create_proposal)
        assert state.expected_tests_passed is True

    def test_extracts_expected_changed_files(
        self, approved_create_proposal: ActionProposal
    ) -> None:
        approved_create_proposal.metadata["expected_changed_files"] = ["a.py", "b.py"]
        state = derive_intended_state(approved_create_proposal)
        assert state.expected_changed_files == ["a.py", "b.py"]

    def test_extracts_expected_pr_url(
        self, approved_create_proposal: ActionProposal
    ) -> None:
        approved_create_proposal.metadata["expected_pr_url"] = "https://example.com/pr/1"
        state = derive_intended_state(approved_create_proposal)
        assert state.expected_pr_url == "https://example.com/pr/1"

    def test_extracts_require_all_changed_files(
        self, approved_create_proposal: ActionProposal
    ) -> None:
        approved_create_proposal.metadata["require_all_changed_files"] = False
        state = derive_intended_state(approved_create_proposal)
        assert state.require_all_changed_files is False

    def test_extracts_all_fields(
        self, approved_create_proposal: ActionProposal
    ) -> None:
        approved_create_proposal.metadata = {
            "expected_changed_files": ["src/foo.py"],
            "expected_tests_passed": True,
            "expected_pr_url": "https://example.com/pr/1",
            "expected_summary_contains": ["foo"],
            "expected_body_contains": ["bar"],
            "expected_metric_updates": [{"metric_name": "X", "value": 1.0}],
            "require_all_changed_files": False,
        }
        state = derive_intended_state(approved_create_proposal)
        assert state.expected_changed_files == ["src/foo.py"]
        assert state.expected_tests_passed is True
        assert state.expected_pr_url == "https://example.com/pr/1"
        assert state.expected_summary_contains == ["foo"]
        assert state.expected_body_contains == ["bar"]
        assert state.expected_metric_updates == [{"metric_name": "X", "value": 1.0}]
        assert state.require_all_changed_files is False


# ── run_execution_loop: happy path ───────────────────────────────────────────


class TestExecutionLoopHappyPath:
    """Tests for the full execution loop when everything succeeds."""

    def test_full_loop_success(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
        minimal_intended_state: IntendedState,
    ) -> None:
        """Execution succeeds, evidence collected, verification VERIFIED."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
        )
        assert isinstance(result, ExecutionLoopResult)
        assert result.execution.is_success
        assert result.execution_succeeded
        assert result.verification.status == VerificationStatus.VERIFIED
        assert result.outcome_verified
        assert result.success

    def test_full_loop_returns_evidence_artifact(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
        minimal_intended_state: IntendedState,
    ) -> None:
        """The loop returns a structured Evidence artifact."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
        )
        assert result.evidence.task_id == "AP-001"
        assert result.evidence.domain_object == "task"
        assert result.evidence.domain_title == "Test task"
        assert result.evidence.status in (
            EvidenceStatus.SUCCESS,
            EvidenceStatus.PARTIAL,
            EvidenceStatus.EMPTY,
        )

    def test_full_loop_persists_execution(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
        minimal_intended_state: IntendedState,
    ) -> None:
        """The execution result is persisted to the executions file."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        run_execution_loop(
            approved_create_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
        )
        assert tmp_executions_path.exists()
        content = tmp_executions_path.read_text(encoding="utf-8")
        assert "AP-001" in content

    def test_full_loop_with_update_task(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_update_proposal: ActionProposal,
        minimal_intended_state: IntendedState,
    ) -> None:
        """Full loop works for UPDATE_TASK proposals."""
        # First create the task so it exists
        from janus.services.tasks import add_task
        add_task("Existing task", None, 1)

        service = ExecutionService(executions_path=tmp_executions_path)
        result = run_execution_loop(
            approved_update_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
        )
        assert result.execution.is_success
        assert result.execution.action_type == ActionType.UPDATE_TASK

    def test_full_loop_with_reschedule_task(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_reschedule_proposal: ActionProposal,
        minimal_intended_state: IntendedState,
    ) -> None:
        """Full loop works for RESCHEDULE_TASK proposals."""
        # First create the task so it exists
        from janus.services.tasks import add_task
        add_task("Existing task", None, 1)

        service = ExecutionService(executions_path=tmp_executions_path)
        result = run_execution_loop(
            approved_reschedule_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
        )
        assert result.execution.is_success
        assert result.execution.action_type == ActionType.RESCHEDULE_TASK


# ── run_execution_loop: verification failures ────────────────────────────────


class TestExecutionLoopVerificationFailures:
    """Tests for when verification fails or is inconclusive."""

    def test_unverified_when_evidence_doesnt_match(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
    ) -> None:
        """Execution succeeds but evidence doesn't match intended state."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": False,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        intended = IntendedState(expected_tests_passed=True)
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=intended,
            execution_service=service,
        )
        assert result.execution.is_success
        assert result.verification.status == VerificationStatus.UNVERIFIED
        assert not result.outcome_verified
        assert not result.success

    def test_inconclusive_when_no_intended_state(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
    ) -> None:
        """When no intended state is provided, verification is INCONCLUSIVE."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=IntendedState(),
            execution_service=service,
        )
        assert result.execution.is_success
        assert result.verification.status == VerificationStatus.INCONCLUSIVE
        assert not result.success

    def test_inconclusive_when_execution_fails(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        """When execution fails, verification is INCONCLUSIVE."""
        mock_executor = _make_mock_executor(
            status=ExecutionStatus.FAILED,
            error="Something went wrong",
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        proposal = ActionProposal(
            proposal_id="AP-fail",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": ""},
            reason="Test failure",
            source="test",
            risk=RiskLevel.LOW,
            status=ProposalStatus.APPROVED,
        )
        intended = IntendedState(expected_tests_passed=True)
        result = run_execution_loop(
            proposal,
            intended_state=intended,
            execution_service=service,
        )
        assert result.execution.is_failed
        assert result.verification.status == VerificationStatus.INCONCLUSIVE
        assert result.verification.execution_succeeded is False
        assert not result.success

    def test_unverified_when_tests_failed(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        """When tests fail in evidence, verification is UNVERIFIED."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": False,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test task"},
            reason="Test",
            source="test",
            risk=RiskLevel.LOW,
            status=ProposalStatus.APPROVED,
        )
        intended = IntendedState(expected_tests_passed=True)
        result = run_execution_loop(
            proposal,
            intended_state=intended,
            execution_service=service,
        )
        assert result.execution.is_success
        assert result.verification.status == VerificationStatus.UNVERIFIED
        assert not result.outcome_verified
        assert not result.success


# ── run_execution_loop: derived intended state ───────────────────────────────


class TestExecutionLoopDerivedIntendedState:
    """Tests for when intended state is derived from proposal metadata."""

    def test_uses_derived_intended_state_when_none_provided(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
    ) -> None:
        """When intended_state is None, it's derived from proposal metadata."""
        approved_create_proposal.metadata["expected_tests_passed"] = True
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=None,
            execution_service=service,
        )
        # The derived intended state should have been used
        assert result.intended_state.expected_tests_passed is True

    def test_explicit_intended_state_overrides_derived(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
    ) -> None:
        """When intended_state is provided, it takes precedence over derived."""
        approved_create_proposal.metadata["expected_tests_passed"] = True
        explicit = IntendedState(expected_tests_passed=False)
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=explicit,
            execution_service=service,
        )
        assert result.intended_state.expected_tests_passed is False


# ── run_execution_loop: idempotency ──────────────────────────────────────────


class TestExecutionLoopIdempotency:
    """Tests for idempotent execution in the loop."""

    def test_already_executed_proposal_returns_skipped(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
        minimal_intended_state: IntendedState,
    ) -> None:
        """Running the loop twice on the same proposal returns SKIPPED on second run."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )

        # First run: succeeds
        result1 = run_execution_loop(
            approved_create_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
        )
        assert result1.execution.is_success

        # Second run: skipped (idempotent)
        result2 = run_execution_loop(
            approved_create_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
        )
        assert result2.execution.is_skipped
        assert not result2.success


# ── run_execution_loop: custom components ────────────────────────────────────


class TestExecutionLoopCustomComponents:
    """Tests for injecting custom execution service and evidence collector."""

    def test_custom_evidence_collector(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
        minimal_intended_state: IntendedState,
    ) -> None:
        """Custom evidence collector is used when provided."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        custom_collector = EvidenceCollector()
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
            evidence_collector=custom_collector,
        )
        assert result.execution.is_success
        assert result.evidence is not None

    def test_custom_execution_service(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
        minimal_intended_state: IntendedState,
    ) -> None:
        """Custom execution service is used when provided."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
        )
        assert result.execution.execution_id == "EX-mock"
        mock_executor.execute.assert_called_once()


# ── ExecutionLoopResult serialization ────────────────────────────────────────


class TestExecutionLoopResultSerialization:
    """Tests for ExecutionLoopResult.to_dict()."""

    def test_to_dict_is_json_serializable(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
        minimal_intended_state: IntendedState,
    ) -> None:
        """The loop result can be serialized to JSON."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
        )
        d = result.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        assert len(json_str) > 0

    def test_to_dict_contains_all_stages(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
        minimal_intended_state: IntendedState,
    ) -> None:
        """The serialized dict contains execution, evidence, and verification."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=minimal_intended_state,
            execution_service=service,
        )
        d = result.to_dict()
        assert "execution" in d
        assert "evidence" in d
        assert "verification" in d
        assert "success" in d
        assert "intended_state" in d
        assert d["execution"]["proposal_id"] == "AP-001"
        assert d["evidence"]["task_id"] == "AP-001"
        assert d["verification"]["status"] in ("VERIFIED", "UNVERIFIED", "INCONCLUSIVE")


# ── run_execution_loop: edge cases ───────────────────────────────────────────


class TestExecutionLoopEdgeCases:
    """Edge case tests for the execution loop."""

    def test_loop_never_raises_on_verification_failure(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        """The loop never raises, even when verification fails."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": False,
                "changed_files": ["src/other.py"],
                "pr_url": "https://other.com/pr/1",
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CREATE_TASK,
            parameters={"title": "Test task"},
            reason="Test",
            source="test",
            risk=RiskLevel.LOW,
            status=ProposalStatus.APPROVED,
        )
        # Intended state that will never match
        intended = IntendedState(
            expected_changed_files=["nonexistent.py"],
            expected_tests_passed=True,
            expected_pr_url="https://nonexistent.com/pr/1",
        )
        # Should not raise
        result = run_execution_loop(
            proposal,
            intended_state=intended,
            execution_service=service,
        )
        assert result.verification.status == VerificationStatus.UNVERIFIED
        assert not result.success

    def test_loop_handles_skipped_execution(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
    ) -> None:
        """When execution is skipped (e.g., policy denied), loop completes."""
        proposal = ActionProposal(
            proposal_id="AP-001",
            action_type=ActionType.CHANGE_PRIORITY,  # Not supported
            parameters={"new_priority": 1},
            reason="Test",
            source="test",
            risk=RiskLevel.LOW,
            status=ProposalStatus.APPROVED,
        )
        intended = IntendedState(expected_tests_passed=True)
        service = ExecutionService(executions_path=tmp_executions_path)
        result = run_execution_loop(
            proposal,
            intended_state=intended,
            execution_service=service,
        )
        assert result.execution.is_skipped
        assert result.verification.status == VerificationStatus.INCONCLUSIVE
        assert not result.success

    def test_loop_result_has_intended_state(
        self,
        tmp_tasks_path: Path,
        tmp_executions_path: Path,
        approved_create_proposal: ActionProposal,
        full_intended_state: IntendedState,
    ) -> None:
        """The loop result carries the intended state used for verification."""
        mock_executor = _make_mock_executor(
            result_details={
                "task_title": "Test task",
                "tests_passed": True,
                "changed_files": ["src/foo.py", "tests/test_foo.py"],
                "pr_url": "https://github.com/example/repo/pull/42",
            },
        )
        service = ExecutionService(
            executor=mock_executor,
            executions_path=tmp_executions_path,
        )
        result = run_execution_loop(
            approved_create_proposal,
            intended_state=full_intended_state,
            execution_service=service,
        )
        assert result.intended_state.expected_tests_passed is True
        assert result.intended_state.expected_changed_files == [
            "src/foo.py",
            "tests/test_foo.py",
        ]
