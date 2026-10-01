"""Tests for approval request handling in Hermes execution.

Covers:
- _build_approval_request: constructs ApprovalRequest from EnforcementGateError
- _present_approval_request: presents request and captures user response
- dispatch_completion: enforcement gate integration with approval flow
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from janus.models.policy import ClassificationCategory, RiskLevel
from janus.models.policy_p1 import ApprovalResponse, PolicyVerdict
from janus.services.enforcement_gate import (
    EnforcementAction,
    EnforcementGateError,
    EnforcementResult,
)
from janus.services.execution_feedback import (
    EvidencePackage,
    JanusDomainMetadata,
    _build_approval_request,
    _present_approval_request,
    dispatch_completion,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_metadata(object_type: str = "task", title: str = "Test task"):
    """Helper to create JanusDomainMetadata with correct fields."""
    return JanusDomainMetadata(object=object_type, title=title)


def _make_evidence(task_id: str = "t-123", summary: str = "Test task"):
    """Helper to create EvidencePackage with required fields."""
    return EvidencePackage(task_id=task_id, summary=summary)


def _make_gate_error(
    action: str = "task_completion",
    category: ClassificationCategory = ClassificationCategory.APPROVAL_REQUIRED,
    message: str = "Action requires approval",
    context: str = "hermes_sync",
):
    """Helper to create an EnforcementGateError."""
    result = EnforcementResult(
        allowed=False,
        category=category,
        action=action,
        message=message,
        context=context,
    )
    return EnforcementGateError(result)


# ── _build_approval_request ──────────────────────────────────────────────────


class TestBuildApprovalRequest:
    """Test _build_approval_request constructs correct ApprovalRequest."""

    def test_builds_request_for_task_completion(self):
        metadata = _make_metadata("task", "My task")
        evidence = _make_evidence()
        error = _make_gate_error("task_completion")

        request = _build_approval_request(metadata, evidence, error)

        assert request.action == "task_completion"
        assert request.context == "task: My task"
        assert request.risk_level == RiskLevel.HIGH
        assert request.policy_rule == "approval_required"
        assert "My task" in request.what_approval_entails
        assert "completion gates" in request.what_approval_entails
        assert "remains open" in request.alternative

    def test_builds_request_for_goal_completion(self):
        metadata = _make_metadata("goal", "My goal")
        evidence = _make_evidence()
        error = _make_gate_error("goal_completion")

        request = _build_approval_request(metadata, evidence, error)

        assert request.action == "goal_completion"
        assert request.context == "goal: My goal"
        assert "My goal" in request.what_approval_entails
        assert "remains active" in request.alternative

    def test_builds_request_for_knowledge_ingestion(self):
        metadata = _make_metadata("research", "My research")
        evidence = _make_evidence()
        error = _make_gate_error("knowledge_ingestion")

        request = _build_approval_request(metadata, evidence, error)

        assert request.action == "knowledge_ingestion"
        assert request.context == "research: My research"
        assert "ingesting" in request.what_approval_entails.lower()

    def test_builds_request_for_external_write(self):
        metadata = _make_metadata("task", "External task")
        evidence = _make_evidence()
        error = _make_gate_error("external_write")

        request = _build_approval_request(metadata, evidence, error)

        assert request.action == "external_write"
        assert "external write" in request.what_approval_entails.lower()

    def test_builds_request_for_bulk_operation(self):
        metadata = _make_metadata("task", "Bulk task")
        evidence = _make_evidence()
        error = _make_gate_error("bulk_operation")

        request = _build_approval_request(metadata, evidence, error)

        assert request.action == "bulk_operation"
        assert "bulk" in request.what_approval_entails.lower()

    def test_builds_request_for_config_change(self):
        metadata = _make_metadata("task", "Config task")
        evidence = _make_evidence()
        error = _make_gate_error("config_change")

        request = _build_approval_request(metadata, evidence, error)

        assert request.action == "config_change"
        assert "configuration" in request.what_approval_entails.lower()

    def test_builds_request_for_goal_deletion(self):
        metadata = _make_metadata("goal", "Delete me")
        evidence = _make_evidence()
        error = _make_gate_error("goal_deletion")

        request = _build_approval_request(metadata, evidence, error)

        assert request.action == "goal_deletion"
        assert "Delete me" in request.what_approval_entails
        assert "deleting" in request.what_approval_entails.lower()

    def test_builds_request_for_unknown_action(self):
        metadata = _make_metadata("task", "Unknown task")
        evidence = _make_evidence()
        error = _make_gate_error("some_unknown_action")

        request = _build_approval_request(metadata, evidence, error)

        assert request.action == "some_unknown_action"
        assert "some_unknown_action" in request.what_approval_entails

    def test_request_contains_rationale_from_error(self):
        metadata = _make_metadata("task", "Test")
        evidence = _make_evidence()
        error = _make_gate_error(
            "task_completion",
            message="Custom rationale message",
        )

        request = _build_approval_request(metadata, evidence, error)

        assert request.rationale == "Custom rationale message"

    def test_request_has_gate_id_none(self):
        metadata = _make_metadata("task", "Test")
        evidence = _make_evidence()
        error = _make_gate_error()

        request = _build_approval_request(metadata, evidence, error)

        assert request.gate_id is None


# ── _present_approval_request ────────────────────────────────────────────────


class TestPresentApprovalRequest:
    """Test _present_approval_request displays prompt and captures response."""

    def test_approve_response(self):
        from janus.models.policy_p1 import ApprovalRequest

        request = ApprovalRequest(
            action="task_completion",
            context="task: Test",
            risk_level=RiskLevel.HIGH,
            policy_rule="approval_required",
            rationale="Test rationale",
            what_approval_entails="Test entails",
            alternative="Test alternative",
        )

        with patch("builtins.input", return_value="y"):
            record = _present_approval_request(request)

        assert record.response == ApprovalResponse.APPROVE
        assert record.request is request

    def test_deny_response(self):
        from janus.models.policy_p1 import ApprovalRequest

        request = ApprovalRequest(
            action="task_completion",
            context="task: Test",
            risk_level=RiskLevel.HIGH,
            policy_rule="approval_required",
            rationale="Test rationale",
            what_approval_entails="Test entails",
            alternative="Test alternative",
        )

        with patch("builtins.input", return_value="n"):
            record = _present_approval_request(request)

        assert record.response == ApprovalResponse.DENY

    def test_defer_response(self):
        from janus.models.policy_p1 import ApprovalRequest

        request = ApprovalRequest(
            action="task_completion",
            context="task: Test",
            risk_level=RiskLevel.HIGH,
            policy_rule="approval_required",
            rationale="Test rationale",
            what_approval_entails="Test entails",
            alternative="Test alternative",
        )

        with patch("builtins.input", return_value="d"):
            record = _present_approval_request(request)

        assert record.response == ApprovalResponse.DEFER

    def test_approve_full_word(self):
        from janus.models.policy_p1 import ApprovalRequest

        request = ApprovalRequest(
            action="task_completion",
            context="task: Test",
            risk_level=RiskLevel.HIGH,
            policy_rule="approval_required",
            rationale="Test rationale",
            what_approval_entails="Test entails",
            alternative="Test alternative",
        )

        with patch("builtins.input", return_value="yes"):
            record = _present_approval_request(request)

        assert record.response == ApprovalResponse.APPROVE

    def test_deny_full_word(self):
        from janus.models.policy_p1 import ApprovalRequest

        request = ApprovalRequest(
            action="task_completion",
            context="task: Test",
            risk_level=RiskLevel.HIGH,
            policy_rule="approval_required",
            rationale="Test rationale",
            what_approval_entails="Test entails",
            alternative="Test alternative",
        )

        with patch("builtins.input", return_value="no"):
            record = _present_approval_request(request)

        assert record.response == ApprovalResponse.DENY

    def test_defer_full_word(self):
        from janus.models.policy_p1 import ApprovalRequest

        request = ApprovalRequest(
            action="task_completion",
            context="task: Test",
            risk_level=RiskLevel.HIGH,
            policy_rule="approval_required",
            rationale="Test rationale",
            what_approval_entails="Test entails",
            alternative="Test alternative",
        )

        with patch("builtins.input", return_value="defer"):
            record = _present_approval_request(request)

        assert record.response == ApprovalResponse.DEFER

    def test_invalid_then_valid_response(self):
        from janus.models.policy_p1 import ApprovalRequest

        request = ApprovalRequest(
            action="task_completion",
            context="task: Test",
            risk_level=RiskLevel.HIGH,
            policy_rule="approval_required",
            rationale="Test rationale",
            what_approval_entails="Test entails",
            alternative="Test alternative",
        )

        # First invalid, then valid
        with patch("builtins.input", side_effect=["invalid", "y"]):
            record = _present_approval_request(request)

        assert record.response == ApprovalResponse.APPROVE

    def test_eof_error_auto_deny(self):
        """Non-interactive mode (EOFError) should auto-deny for safety."""
        from janus.models.policy_p1 import ApprovalRequest

        request = ApprovalRequest(
            action="task_completion",
            context="task: Test",
            risk_level=RiskLevel.HIGH,
            policy_rule="approval_required",
            rationale="Test rationale",
            what_approval_entails="Test entails",
            alternative="Test alternative",
        )

        with patch("builtins.input", side_effect=EOFError):
            record = _present_approval_request(request)

        assert record.response == ApprovalResponse.DENY

    def test_prompt_is_printed(self):
        from janus.models.policy_p1 import ApprovalRequest

        request = ApprovalRequest(
            action="task_completion",
            context="task: Test",
            risk_level=RiskLevel.HIGH,
            policy_rule="approval_required",
            rationale="Test rationale",
            what_approval_entails="Test entails",
            alternative="Test alternative",
        )

        with patch("builtins.input", return_value="y"), \
             patch("builtins.print") as mock_print:
            _present_approval_request(request)

        # Should have printed the prompt
        assert mock_print.called


# ── dispatch_completion with enforcement gate ─────────────────────────────────


class TestDispatchCompletionWithEnforcementGate:
    """Test dispatch_completion integrates enforcement gate with approval flow."""

    @pytest.fixture(autouse=True)
    def _bypass_enforcement_gate(self, monkeypatch):
        """Bypass the enforcement gate by default."""
        monkeypatch.setattr(
            "janus.services.enforcement_gate.enforce_or_raise",
            lambda *a, **kw: MagicMock(allowed=True),
        )

    def test_allowed_action_proceeds(self, tmp_path, monkeypatch):
        """Allowed actions should proceed to normal dispatch."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        metadata = _make_metadata("goal", "My goal")
        evidence = _make_evidence()

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise"
        ) as mock_enforce:
            mock_result = MagicMock()
            mock_result.allowed = True
            mock_enforce.return_value = mock_result

            results = dispatch_completion(metadata, evidence)

        assert "goal" in results
        mock_enforce.assert_called_once()

    def test_approval_required_blocks_without_approval(self, tmp_path, monkeypatch):
        """APPROVAL_REQUIRED should block when user denies."""
        metadata = _make_metadata("task", "Test task")
        evidence = _make_evidence()

        def blocking_gate(*a, **kw):
            result = EnforcementResult(
                allowed=False,
                category=ClassificationCategory.APPROVAL_REQUIRED,
                action="task_completion",
                message="Requires approval",
            )
            raise EnforcementGateError(result)

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise",
            side_effect=blocking_gate,
        ), patch(
            "janus.services.execution_feedback._present_approval_request"
        ) as mock_present:
            mock_record = MagicMock()
            mock_record.response = ApprovalResponse.DENY
            mock_record.request.alternative = "Task remains open."
            mock_present.return_value = mock_record

            results = dispatch_completion(metadata, evidence)

        assert results["blocked"] == "task"
        assert "denied" in results["reason"].lower()
        assert results["category"] == "approval_required"

    def test_approval_required_resumes_on_approve(self, tmp_path, monkeypatch):
        """APPROVAL_REQUIRED should resume dispatch when user approves."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        metadata = _make_metadata("goal", "My goal")
        evidence = _make_evidence()

        def blocking_gate(*a, **kw):
            result = EnforcementResult(
                allowed=False,
                category=ClassificationCategory.APPROVAL_REQUIRED,
                action="goal_completion",
                message="Requires approval",
            )
            raise EnforcementGateError(result)

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise",
            side_effect=blocking_gate,
        ), patch(
            "janus.services.execution_feedback._present_approval_request"
        ) as mock_present:
            mock_record = MagicMock()
            mock_record.response = ApprovalResponse.APPROVE
            mock_present.return_value = mock_record

            results = dispatch_completion(metadata, evidence)

        # Should have proceeded to dispatch
        assert "goal" in results
        assert "blocked" not in results

    def test_approval_required_defer_blocks(self, tmp_path, monkeypatch):
        """APPROVAL_REQUIRED should block when user defers."""
        metadata = _make_metadata("task", "Test task")
        evidence = _make_evidence()

        def blocking_gate(*a, **kw):
            result = EnforcementResult(
                allowed=False,
                category=ClassificationCategory.APPROVAL_REQUIRED,
                action="task_completion",
                message="Requires approval",
            )
            raise EnforcementGateError(result)

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise",
            side_effect=blocking_gate,
        ), patch(
            "janus.services.execution_feedback._present_approval_request"
        ) as mock_present:
            mock_record = MagicMock()
            mock_record.response = ApprovalResponse.DEFER
            mock_record.request.alternative = "Task remains open."
            mock_present.return_value = mock_record

            results = dispatch_completion(metadata, evidence)

        assert results["blocked"] == "task"
        assert "defer" in results["reason"].lower()

    def test_user_only_blocks_immediately(self, tmp_path, monkeypatch):
        """USER_ONLY category should block immediately without approval prompt."""
        metadata = _make_metadata("task", "Test task")
        evidence = _make_evidence()

        def blocking_gate(*a, **kw):
            result = EnforcementResult(
                allowed=False,
                category=ClassificationCategory.USER_ONLY,
                action="task_completion",
                message="User only action",
            )
            raise EnforcementGateError(result)

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise",
            side_effect=blocking_gate,
        ), patch(
            "janus.services.execution_feedback._present_approval_request"
        ) as mock_present:
            results = dispatch_completion(metadata, evidence)

        assert results["blocked"] == "task"
        assert results["category"] == "user_only"
        # Should NOT have presented approval request
        mock_present.assert_not_called()

    def test_unknown_object_skips_enforcement(self, tmp_path, monkeypatch):
        """Unknown object types should skip enforcement gate."""
        metadata = _make_metadata("widget", "Test widget")
        evidence = _make_evidence()

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise"
        ) as mock_enforce:
            results = dispatch_completion(metadata, evidence)

        assert "skipped" in results
        mock_enforce.assert_not_called()

    def test_approval_request_built_with_correct_context(self, tmp_path, monkeypatch):
        """Approval request should contain correct context from metadata."""
        metadata = _make_metadata("goal", "My important goal")
        evidence = _make_evidence()

        def blocking_gate(*a, **kw):
            result = EnforcementResult(
                allowed=False,
                category=ClassificationCategory.APPROVAL_REQUIRED,
                action="goal_completion",
                message="Requires approval",
            )
            raise EnforcementGateError(result)

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise",
            side_effect=blocking_gate,
        ), patch(
            "janus.services.execution_feedback._present_approval_request"
        ) as mock_present:
            mock_record = MagicMock()
            mock_record.response = ApprovalResponse.DENY
            mock_record.request.alternative = "Goal remains active."
            mock_present.return_value = mock_record

            dispatch_completion(metadata, evidence)

        # Check that the request was built with correct context
        call_args = mock_present.call_args
        request = call_args[0][0]
        assert request.context == "goal: My important goal"
        assert request.action == "goal_completion"


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _setup_goals(tmp_path, monkeypatch, content):
    """Setup goals file for testing."""
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        "janus.integrations.markdown_goals.GOALS_PATH",
        goals_file,
    )
    monkeypatch.setattr(
        "janus.services.goals.GOALS_PATH",
        goals_file,
    )
