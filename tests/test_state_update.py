"""Tests for the State Update module (Stage 7 of the closed loop).

Covers:
- ``apply_verification_result`` — PASS dispatches evidence, FAIL does not
- ``evaluate_plan_impact`` — produces PlanRevisionSignal when state changes
- ``close_loop`` — end-to-end: verification → state update → planner feedback
- Idempotency — re-applying same result does not double-update
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from janus.services.execution_feedback import (
    EvidencePackage,
    JanusDomainMetadata,
)
from janus.services.state_update import (
    PlanRevisionSignal,
    StateUpdateResult,
    apply_verification_result,
    close_loop,
    evaluate_plan_impact,
)
from janus.verification import CheckResult, VerificationReport


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_pass_report(task_id: str = "t_test") -> VerificationReport:
    """Create a minimal PASS verification report."""
    return VerificationReport(
        task_id=task_id,
        overall="PASS",
        checks={
            "files_create": CheckResult(check_name="files_create", passed=True),
        },
        summary="PASS: 1 checks, 0 items, 0 failures",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _make_fail_report(task_id: str = "t_test") -> VerificationReport:
    """Create a minimal FAIL verification report."""
    return VerificationReport(
        task_id=task_id,
        overall="FAIL",
        checks={
            "files_create": CheckResult(
                check_name="files_create",
                passed=False,
                details=[{"item": "src/x.py", "passed": False, "message": "missing"}],
            ),
        },
        summary="FAIL: 1 checks, 1 items, 1 failures",
        failures=[{"check": "files_create", "item": "src/x.py", "message": "missing"}],
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _setup_goals(tmp_path, monkeypatch, content="# Goals\n"):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    return goals_file


def _setup_tasks(tmp_path, monkeypatch, content="- [ ] Placeholder\n"):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
    return tasks_file


def _load_goals():
    from janus.integrations.markdown_goals import load_goals
    return load_goals()


# ── apply_verification_result ─────────────────────────────────────────────────


class TestApplyVerificationResult:
    """apply_verification_result dispatches evidence on PASS, skips on FAIL."""

    def test_pass_dispatches_evidence_to_goal(self, tmp_path, monkeypatch):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Test goal\nStatus: active\n",
        )
        report = _make_pass_report("t_abc")
        md = JanusDomainMetadata(object="goal", title="Test goal")
        ev = EvidencePackage(
            task_id="t_abc",
            summary="Implement X",
            completed_at="2026-09-09T10:00:00Z",
            changed_files=["src/foo.py"],
            tests_passed=True,
            pr_url="https://example.com/pr/1",
        )
        result = apply_verification_result(report, md, ev)
        assert result.verification_passed is True
        assert result.task_id == "t_abc"
        assert result.updated_goals == ["Test goal"]
        assert result.errors == []
        assert result.has_changes is True
        # Verify state was actually updated
        goals = _load_goals()
        assert len(goals) == 1
        assert len(goals[0].recent_activity or []) == 1

    def test_fail_does_not_dispatch(self, tmp_path, monkeypatch):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Test goal\nStatus: active\n",
        )
        report = _make_fail_report("t_abc")
        md = JanusDomainMetadata(object="goal", title="Test goal")
        ev = EvidencePackage(task_id="t_abc", summary="Implement X")
        result = apply_verification_result(report, md, ev)
        assert result.verification_passed is False
        assert result.has_changes is False
        assert len(result.errors) == 1
        assert "Verification failed" in result.errors[0]
        # Verify state was NOT updated
        goals = _load_goals()
        assert len(goals[0].recent_activity or []) == 0

    def test_pass_dispatches_to_task(self, tmp_path, monkeypatch):
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature\n")
        report = _make_pass_report("t_task")
        md = JanusDomainMetadata(object="task", title="Build feature")
        ev = EvidencePackage(
            task_id="t_task",
            summary="Build feature",
            tests_passed=True,
        )
        result = apply_verification_result(report, md, ev)
        assert result.verification_passed is True
        assert result.updated_tasks == ["Build feature"]

    def test_pass_dispatches_to_milestone(self, tmp_path, monkeypatch):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n"
            "## Goal: G\nStatus: active\n"
            "Related tasks:\n- Task A\n\n"
            "## Milestones\n\n"
            "### Milestone: M1  (order: 0)\nStatus: open\n",
        )
        _setup_tasks(tmp_path, monkeypatch, "- [x] Task A\n")
        report = _make_pass_report("t_ms")
        md = JanusDomainMetadata(object="milestone", title="M1")
        ev = EvidencePackage(
            task_id="t_ms",
            summary="Task A",
            completed_at="2026-09-09",
        )
        result = apply_verification_result(report, md, ev)
        assert result.verification_passed is True
        assert result.updated_milestones == ["M1"]

    def test_idempotent_reapply_does_not_double_update(self, tmp_path, monkeypatch):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Test goal\nStatus: active\n",
        )
        report = _make_pass_report("t_idem")
        md = JanusDomainMetadata(object="goal", title="Test goal")
        ev = EvidencePackage(
            task_id="t_idem",
            summary="Implement X",
            completed_at="2026-09-09T10:00:00Z",
        )
        # Apply twice
        result1 = apply_verification_result(report, md, ev)
        result2 = apply_verification_result(report, md, ev)
        assert result1.has_changes is True
        assert result2.has_changes is True
        # But only one activity entry
        goals = _load_goals()
        assert len(goals[0].recent_activity or []) == 1

    def test_to_dict_serializes(self, tmp_path, monkeypatch):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n",
        )
        report = _make_pass_report("t_ser")
        md = JanusDomainMetadata(object="goal", title="G")
        ev = EvidencePackage(task_id="t_ser", summary="s")
        result = apply_verification_result(report, md, ev)
        d = result.to_dict()
        assert d["task_id"] == "t_ser"
        assert d["verification_passed"] is True
        assert "updated_goals" in d
        assert "state_changes" in d
        assert "timestamp" in d


# ── evaluate_plan_impact ──────────────────────────────────────────────────────


class TestEvaluatePlanImpact:
    """evaluate_plan_impact produces signals when state changes affect planning."""

    def test_no_changes_returns_none(self):
        result = StateUpdateResult(
            task_id="t_1",
            verification_passed=True,
            state_changes=[],
        )
        assert evaluate_plan_impact(result) is None

    def test_failed_verification_returns_none(self):
        result = StateUpdateResult(
            task_id="t_1",
            verification_passed=False,
            state_changes=["verification_failed"],
        )
        assert evaluate_plan_impact(result) is None

    def test_goal_update_produces_signal(self):
        result = StateUpdateResult(
            task_id="t_1",
            verification_passed=True,
            state_changes=["appended recent_activity entry to goal 'G'"],
            updated_goals=["G"],
        )
        signal = evaluate_plan_impact(result)
        assert signal is not None
        assert signal.goal_title == "G"
        assert signal.priority == 1
        assert "goals updated" in signal.reason

    def test_task_update_produces_higher_priority_signal(self):
        result = StateUpdateResult(
            task_id="t_1",
            verification_passed=True,
            state_changes=["marked Janus task 'T' completed"],
            updated_tasks=["T"],
        )
        signal = evaluate_plan_impact(result, goal_title="My Goal")
        assert signal is not None
        assert signal.goal_title == "My Goal"
        assert signal.priority == 2
        assert "tasks updated" in signal.reason
        assert signal.affected_tasks == ["T"]

    def test_milestone_update_produces_highest_priority_signal(self):
        result = StateUpdateResult(
            task_id="t_1",
            verification_passed=True,
            state_changes=["milestone 'M1' auto-completed"],
            updated_milestones=["M1"],
        )
        signal = evaluate_plan_impact(result, goal_title="G")
        assert signal is not None
        assert signal.priority == 3
        assert "milestones updated" in signal.reason

    def test_explicit_goal_title_overrides_updated_goals(self):
        result = StateUpdateResult(
            task_id="t_1",
            verification_passed=True,
            state_changes=["appended recent_activity entry to goal 'G'"],
            updated_goals=["G"],
        )
        signal = evaluate_plan_impact(result, goal_title="Other Goal")
        assert signal is not None
        assert signal.goal_title == "Other Goal"

    def test_no_goal_title_and_no_updated_goals_returns_none(self):
        result = StateUpdateResult(
            task_id="t_1",
            verification_passed=True,
            state_changes=["something happened"],
        )
        assert evaluate_plan_impact(result) is None

    def test_signal_to_dict(self):
        signal = PlanRevisionSignal(
            goal_title="G",
            reason="tasks updated: T1",
            priority=2,
            affected_tasks=["T1"],
        )
        d = signal.to_dict()
        assert d["goal_title"] == "G"
        assert d["priority"] == 2
        assert d["affected_tasks"] == ["T1"]


# ── close_loop (end-to-end) ──────────────────────────────────────────────────


class TestCloseLoop:
    """close_loop: verification → state update → planner feedback."""

    def test_pass_closes_loop_with_plan_signal(self, tmp_path, monkeypatch):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Test goal\nStatus: active\n",
        )
        report = _make_pass_report("t_loop")
        md = JanusDomainMetadata(object="goal", title="Test goal")
        ev = EvidencePackage(
            task_id="t_loop",
            summary="Implement X",
            tests_passed=True,
        )
        state_result, plan_signal = close_loop(report, md, ev)
        assert state_result.verification_passed is True
        assert state_result.has_changes is True
        assert plan_signal is not None
        assert plan_signal.goal_title == "Test goal"

    def test_fail_closes_loop_without_plan_signal(self, tmp_path, monkeypatch):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Test goal\nStatus: active\n",
        )
        report = _make_fail_report("t_loop")
        md = JanusDomainMetadata(object="goal", title="Test goal")
        ev = EvidencePackage(task_id="t_loop", summary="Implement X")
        state_result, plan_signal = close_loop(report, md, ev)
        assert state_result.verification_passed is False
        assert state_result.has_changes is False
        assert plan_signal is None

    def test_task_completion_closes_loop(self, tmp_path, monkeypatch):
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature\n")
        report = _make_pass_report("t_task")
        md = JanusDomainMetadata(object="task", title="Build feature")
        ev = EvidencePackage(
            task_id="t_task",
            summary="Build feature",
            tests_passed=True,
        )
        state_result, plan_signal = close_loop(
            report, md, ev, goal_title="My Goal"
        )
        assert state_result.verification_passed is True
        assert state_result.updated_tasks == ["Build feature"]
        assert plan_signal is not None
        assert plan_signal.goal_title == "My Goal"
        assert plan_signal.priority == 2


# ── StateUpdateResult edge cases ─────────────────────────────────────────────


class TestStateUpdateResultEdgeCases:
    """Edge cases for StateUpdateResult."""

    def test_empty_result_has_no_changes(self):
        result = StateUpdateResult(task_id="t_1", verification_passed=True)
        assert result.has_changes is False

    def test_result_with_only_state_changes_has_changes(self):
        result = StateUpdateResult(
            task_id="t_1",
            verification_passed=True,
            state_changes=["something"],
        )
        assert result.has_changes is True

    def test_result_with_only_errors_has_no_changes(self):
        result = StateUpdateResult(
            task_id="t_1",
            verification_passed=False,
            errors=["Verification failed: bad"],
        )
        assert result.has_changes is False

    def test_timestamp_is_iso8601(self):
        result = StateUpdateResult(
            task_id="t_1",
            verification_passed=True,
            timestamp="2026-09-09T10:00:00+00:00",
        )
        assert "2026" in result.timestamp


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
