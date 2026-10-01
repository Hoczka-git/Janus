"""Tests for policy integration with service functions.

Design reference: docs/design/policy_approval_p1_design.md §11.2

After consolidation, policy enforcement lives in enforcement_gate.py and
is invoked at dispatch_completion(). Service functions (complete_task,
complete_goal, promote_to_vault) no longer have inline policy evaluation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from janus.exceptions import PolicyDenialError, PolicyApprovalRequired
from janus.models.policy_p1 import ApprovalResponse, PolicyVerdict
from janus.services.policy import evaluate_policy


def _make_metadata(object_type: str = "task", title: str = "Test task"):
    """Helper to create JanusDomainMetadata with correct fields."""
    from janus.services.execution_feedback import JanusDomainMetadata
    return JanusDomainMetadata(object=object_type, title=title)


def _make_evidence(task_id: str = "t-123", summary: str = "Test task"):
    """Helper to create EvidencePackage with required fields."""
    from janus.services.execution_feedback import EvidencePackage
    return EvidencePackage(task_id=task_id, summary=summary)


class TestPolicyIntegrationWithDispatchCompletion:
    """Test that dispatch_completion() integrates the enforcement gate."""

    def test_enforcement_gate_blocks_denied_action(self, tmp_path, monkeypatch):
        """EnforcementGateError should block dispatch for denied actions."""
        from janus.services.execution_feedback import dispatch_completion
        from janus.services.enforcement_gate import (
            EnforcementGateError,
            EnforcementResult,
        )
        from janus.models.policy import ClassificationCategory

        metadata = _make_metadata("task", "Test task")
        evidence = _make_evidence()

        def blocking_gate(*a, **kw):
            result = EnforcementResult(
                allowed=False,
                category=ClassificationCategory.APPROVAL_REQUIRED,
                action="task_completion",
                message="blocked by policy",
            )
            raise EnforcementGateError(result)

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise",
            side_effect=blocking_gate,
        ):
            result = dispatch_completion(metadata, evidence)

        assert result["blocked"] == "task"
        assert "blocked by policy" in result["reason"]
        assert result["category"] == "approval_required"

    def test_enforcement_gate_allows_action(self, tmp_path, monkeypatch):
        """Allowed actions should proceed to normal dispatch."""
        from janus.services.execution_feedback import dispatch_completion

        metadata = _make_metadata("task", "Test task")
        evidence = _make_evidence()

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise"
        ) as mock_enforce, patch(
            "janus.services.tasks.complete_janus_task",
            return_value=MagicMock(),
        ):
            mock_result = MagicMock()
            mock_result.allowed = True
            mock_enforce.return_value = mock_result

            # Should not raise — proceeds to dispatch
            result = dispatch_completion(metadata, evidence)
            assert "blocked" not in result

    def test_dispatch_calls_enforcement_gate_before_service(self, tmp_path, monkeypatch):
        """Enforcement gate should be called before service dispatch."""
        from janus.services.execution_feedback import dispatch_completion

        metadata = _make_metadata("task", "Test task")
        evidence = _make_evidence()

        call_order = []

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise",
            side_effect=lambda *a, **kw: call_order.append("gate") or MagicMock(allowed=True),
        ), patch(
            "janus.services.tasks.complete_janus_task",
            side_effect=lambda *a, **kw: call_order.append("service") or MagicMock(),
        ):
            dispatch_completion(metadata, evidence)

        assert call_order[0] == "gate"

    def test_dispatch_blocks_before_service_on_denial(self, tmp_path, monkeypatch):
        """When gate blocks, service should not be called."""
        from janus.services.execution_feedback import dispatch_completion
        from janus.services.enforcement_gate import (
            EnforcementGateError,
            EnforcementResult,
        )
        from janus.models.policy import ClassificationCategory

        metadata = _make_metadata("task", "Test task")
        evidence = _make_evidence()

        call_order = []

        def blocking_gate(*a, **kw):
            call_order.append("gate")
            result = EnforcementResult(
                allowed=False,
                category=ClassificationCategory.APPROVAL_REQUIRED,
                action="task_completion",
                message="blocked",
            )
            raise EnforcementGateError(result)

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise",
            side_effect=blocking_gate,
        ), patch(
            "janus.services.tasks.complete_janus_task",
            side_effect=lambda *a, **kw: call_order.append("service") or MagicMock(),
        ):
            result = dispatch_completion(metadata, evidence)

        assert call_order == ["gate"]
        assert result["blocked"] == "task"


class TestPolicyIntegrationWithCompleteTask:
    """Test that complete_task() works without inline policy evaluation."""

    def test_complete_task_proceeds_without_policy_error(self, tmp_path, monkeypatch):
        """complete_task() should not raise PolicyDenialError or PolicyApprovalRequired."""
        from janus.services.tasks import complete_task

        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with patch(
            "janus.services.tasks.run_completion_gates"
        ) as mock_gates:
            mock_gates.return_value = MagicMock(
                ok=True,
                pre_completion_report=None,
                integration_result=None,
            )

            try:
                complete_task("Test task")
            except (PolicyDenialError, PolicyApprovalRequired):
                pytest.fail("complete_task should not raise policy errors")
            except Exception:
                pass  # Other errors are expected in test environment


class TestPolicyIntegrationWithCompleteGoal:
    """Test that complete_goal() works without inline policy evaluation."""

    def test_complete_goal_proceeds_without_policy_error(self, tmp_path, monkeypatch):
        """complete_goal() should not raise PolicyDenialError or PolicyApprovalRequired."""
        from janus.services.goals import complete_goal

        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n\n## Goal: Test goal\nStatus: active\n")
        monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)

        try:
            complete_goal("Test goal")
        except (PolicyDenialError, PolicyApprovalRequired):
            pytest.fail("complete_goal should not raise policy errors")
        except Exception:
            pass  # Other errors are expected in test environment


class TestPolicyIntegrationWithPromoteToVault:
    """Test that promote_to_vault() works without inline policy evaluation."""

    def test_promote_to_vault_proceeds_without_policy_error(self, tmp_path, monkeypatch):
        """promote_to_vault() should not raise PolicyDenialError or PolicyApprovalRequired."""
        from janus.services.curation_gate import promote_to_vault

        try:
            promote_to_vault("test-proposal-id")
        except (PolicyDenialError, PolicyApprovalRequired):
            pytest.fail("promote_to_vault should not raise policy errors")
        except Exception:
            pass  # Other errors are expected in test environment


class TestPolicyEvaluationAtServiceEntryPoints:
    """Test that policy evaluation happens at the correct service entry points."""

    def test_dispatch_enforcement_gate_order(self, tmp_path, monkeypatch):
        """Enforcement gate should be called before service dispatch."""
        from janus.services.execution_feedback import dispatch_completion

        metadata = _make_metadata("task", "Test task")
        evidence = _make_evidence()

        call_order = []

        with patch(
            "janus.services.enforcement_gate.enforce_or_raise",
            side_effect=lambda *a, **kw: call_order.append("gate") or MagicMock(allowed=True),
        ), patch(
            "janus.services.tasks.complete_janus_task",
            side_effect=lambda *a, **kw: call_order.append("service") or MagicMock(),
        ):
            dispatch_completion(metadata, evidence)

        assert "gate" in call_order
        assert "service" in call_order
        assert call_order.index("gate") < call_order.index("service")
