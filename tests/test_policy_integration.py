"""Tests for policy integration with service functions.

Design reference: docs/design/policy_approval_p1_design.md §11.2
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from janus.exceptions import PolicyDenialError, PolicyApprovalRequired
from janus.models.policy import ApprovalResponse, PolicyVerdict
from janus.services.policy import evaluate_policy


class TestPolicyIntegrationWithCompleteTask:
    """Test that complete_task() integrates policy evaluation."""

    def test_policy_deny_blocks_completion(self, tmp_path, monkeypatch):
        """PolicyDenialError should block task completion."""
        from janus.services.tasks import complete_task

        # Create a minimal tasks.md
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        # Mock evaluate_policy to return DENY
        with patch(
            "janus.services.policy.evaluate_policy"
        ) as mock_evaluate:
            mock_evaluate.return_value = MagicMock(
                verdict=PolicyVerdict.DENY,
                rationale="Test denial",
                gate_id="G-1",
            )
            with pytest.raises(PolicyDenialError) as exc_info:
                complete_task("Test task")
            assert "Test denial" in str(exc_info.value)

    def test_policy_ask_triggers_approval(self, tmp_path, monkeypatch):
        """PolicyApprovalRequired should be raised when user denies."""
        from janus.services.tasks import complete_task

        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with patch(
            "janus.services.policy.evaluate_policy"
        ) as mock_evaluate, patch(
            "janus.services.policy.present_approval_request"
        ) as mock_present:
            mock_evaluate.return_value = MagicMock(
                verdict=PolicyVerdict.ASK,
                rationale="Test approval",
                gate_id="G-1",
            )
            mock_present.return_value = ApprovalResponse.DENY

            with pytest.raises(PolicyApprovalRequired):
                complete_task("Test task")

    def test_policy_allow_proceeds(self, tmp_path, monkeypatch):
        """ALLOW verdict should proceed to normal completion flow."""
        from janus.services.tasks import complete_task

        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with patch(
            "janus.services.policy.evaluate_policy"
        ) as mock_evaluate, patch(
            "janus.services.tasks.run_completion_gates"
        ) as mock_gates:
            mock_evaluate.return_value = MagicMock(
                verdict=PolicyVerdict.ALLOW,
                rationale="Test allow",
                gate_id=None,
            )
            mock_gates.return_value = MagicMock(
                ok=True,
                pre_completion_report=None,
                integration_result=None,
            )

            # Should not raise PolicyDenialError or PolicyApprovalRequired
            # (may raise other errors due to missing git repo, etc.)
            try:
                complete_task("Test task")
            except (PolicyDenialError, PolicyApprovalRequired):
                pytest.fail("ALLOW verdict should not raise policy errors")
            except Exception:
                pass  # Other errors are expected in test environment


class TestPolicyIntegrationWithCompleteGoal:
    """Test that complete_goal() integrates policy evaluation."""

    def test_policy_deny_blocks_goal_completion(self, tmp_path, monkeypatch):
        """PolicyDenialError should block goal completion."""
        from janus.services.goals import complete_goal

        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n\n## Goal: Test goal\nStatus: active\n")
        monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)

        with patch(
            "janus.services.policy.evaluate_policy"
        ) as mock_evaluate:
            mock_evaluate.return_value = MagicMock(
                verdict=PolicyVerdict.DENY,
                rationale="Test denial",
                gate_id="G-2",
            )
            with pytest.raises(PolicyDenialError) as exc_info:
                complete_goal("Test goal")
            assert "Test denial" in str(exc_info.value)

    def test_policy_ask_triggers_approval(self, tmp_path, monkeypatch):
        """PolicyApprovalRequired should be raised when user denies."""
        from janus.services.goals import complete_goal

        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n\n## Goal: Test goal\nStatus: active\n")
        monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)

        with patch(
            "janus.services.policy.evaluate_policy"
        ) as mock_evaluate, patch(
            "janus.services.policy.present_approval_request"
        ) as mock_present:
            mock_evaluate.return_value = MagicMock(
                verdict=PolicyVerdict.ASK,
                rationale="Test approval",
                gate_id="G-2",
            )
            mock_present.return_value = ApprovalResponse.DENY

            with pytest.raises(PolicyApprovalRequired):
                complete_goal("Test goal")


class TestPolicyIntegrationWithPromoteToVault:
    """Test that promote_to_vault() integrates policy evaluation."""

    def test_policy_deny_blocks_promotion(self, tmp_path, monkeypatch):
        """PolicyDenialError should block vault promotion."""
        from janus.services.curation_gate import promote_to_vault

        with patch(
            "janus.services.policy.evaluate_policy"
        ) as mock_evaluate:
            mock_evaluate.return_value = MagicMock(
                verdict=PolicyVerdict.DENY,
                rationale="Test denial",
                gate_id="G-3",
            )
            with pytest.raises(PolicyDenialError) as exc_info:
                promote_to_vault("test-proposal-id")
            assert "Test denial" in str(exc_info.value)

    def test_policy_ask_triggers_approval(self, tmp_path, monkeypatch):
        """PolicyApprovalRequired should be raised when user denies."""
        from janus.services.curation_gate import promote_to_vault

        with patch(
            "janus.services.policy.evaluate_policy"
        ) as mock_evaluate, patch(
            "janus.services.policy.present_approval_request"
        ) as mock_present:
            mock_evaluate.return_value = MagicMock(
                verdict=PolicyVerdict.ASK,
                rationale="Test approval",
                gate_id="G-3",
            )
            mock_present.return_value = ApprovalResponse.DENY

            with pytest.raises(PolicyApprovalRequired):
                promote_to_vault("test-proposal-id")


class TestPolicyEvaluationAtServiceEntryPoints:
    """Test that policy evaluation happens at the correct service entry points."""

    def test_complete_task_evaluates_policy_before_gates(self, tmp_path, monkeypatch):
        """Policy evaluation should happen before ADR-004 gates."""
        from janus.services.tasks import complete_task

        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [ ] Test task\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        call_order = []

        with patch(
            "janus.services.policy.evaluate_policy",
            side_effect=lambda **kwargs: call_order.append("policy") or MagicMock(
                verdict=PolicyVerdict.ALLOW,
                rationale="Test",
                gate_id=None,
            ),
        ), patch(
            "janus.services.tasks.run_completion_gates",
            side_effect=lambda **kwargs: call_order.append("gates") or MagicMock(
                ok=True,
                pre_completion_report=None,
                integration_result=None,
            ),
        ):
            try:
                complete_task("Test task")
            except Exception:
                pass

        assert call_order == ["policy", "gates"]

    def test_complete_goal_evaluates_policy_before_gates(self, tmp_path, monkeypatch):
        """Policy evaluation should happen before structural gates."""
        from janus.services.goals import complete_goal
        from janus.models.goal import Goal

        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n\n## Goal: Test goal\nStatus: active\n")
        monkeypatch.setattr("janus.services.goals.GOALS_PATH", goals_file)

        call_order = []

        with patch(
            "janus.services.policy.evaluate_policy",
            side_effect=lambda **kwargs: call_order.append("policy") or MagicMock(
                verdict=PolicyVerdict.ALLOW,
                rationale="Test",
                gate_id=None,
            ),
        ), patch(
            "janus.services.goals.get_goal",
            return_value=Goal(title="Test goal", status="active"),
        ), patch(
            "janus.services.goal_gates.run_goal_completion_gates",
            side_effect=lambda goal: call_order.append("gates") or MagicMock(ok=True),
        ):
            try:
                complete_goal("Test goal")
            except Exception:
                pass

        assert call_order == ["policy", "gates"]
