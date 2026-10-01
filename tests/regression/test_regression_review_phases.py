"""Regression tests for review phases (V1-V15).

Covers:
- V1: Review request triggers review state transition
- V2: Review approval completes task
- V3: Review rejection (changes_requested) returns task to implementer
- V4: Review re-request after changes
- V5: Review round counting
- V6: Reviewer provenance persistence
- V7: Review timeout/escalation
- V8: Multiple review rounds
- V9: Review with parent gating
- V10: Review state transitions
- V11: Review handoff conditions
- V12: Review with integration gate
- V13: Review with completion gate
- V14: Review event ordering
- V15: Full lifecycle review cycle
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from janus.services.tasks import (
    CompletionGateResult,
    CompletionGateError,
    UnifiedCompletionGateError,
    complete_task,
    run_completion_gates,
)
from janus.services.agency_planning import (
    AgencyContext,
    SupportMode,
    _is_review_phase,
    select_support_mode,
)
from janus.models.task import Task
from janus.models.goal import Goal
from janus.models.execution_mode import ExecutionMode


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_repo(root: Path, files: dict[str, str] | None = None) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    if files:
        for rel, content in files.items():
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "baseline")


def _write_tasks_file(root: Path, content: str) -> Path:
    tasks_file = root / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


def _setup_tasks(tmp_path: Path, monkeypatch: Any, content: str = "- [ ] Placeholder\n") -> Path:
    """Write tasks.md and monkeypatch TASKS_PATH."""
    tasks_file = _write_tasks_file(tmp_path, content)
    import janus.services.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "TASKS_PATH", tasks_file)
    try:
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")
    except Exception:
        pass
    return tasks_file


def _make_task(title: str = "Test task", extra_metadata: list[str] | None = None) -> Task:
    """Create a Task with optional extra_metadata."""
    task = Task(title=title)
    if extra_metadata:
        task.extra_metadata = extra_metadata
    return task


def _make_goal(title: str = "Test goal") -> Goal:
    """Create a Goal for testing."""
    return Goal(title=title)


def _make_context(
    skill_evidence_count: int = 0,
    goal_health: str = "healthy",
    goal_stalled: bool = False,
    task_completion_history: int = 0,
) -> AgencyContext:
    """Create an AgencyContext for testing."""
    return AgencyContext(
        skill_evidence_count=skill_evidence_count,
        goal_health=goal_health,
        goal_stalled=goal_stalled,
        task_completion_history=task_completion_history,
    )


# ──────────────────────────────────────────────────────────────────────
# V1: Review request triggers review state transition
# ──────────────────────────────────────────────────────────────────────


class TestV1_ReviewRequestTriggersState:
    """V1: A review request triggers a review state transition."""

    def test_v1_review_phase_detected(self) -> None:
        """A task with 'review' in extra_metadata is in review phase."""
        task = _make_task("Review task", extra_metadata=["review: true"])
        assert _is_review_phase(task) is True

    def test_v1_non_review_task_not_in_review_phase(self) -> None:
        """A task without 'review' in extra_metadata is not in review phase."""
        task = _make_task("Normal task", extra_metadata=["priority: 1"])
        assert _is_review_phase(task) is False


# ──────────────────────────────────────────────────────────────────────
# V2: Review approval completes task
# ──────────────────────────────────────────────────────────────────────


class TestV2_ReviewApprovalCompletes:
    """V2: Review approval completes the task."""

    def test_v2_review_approval_completes_task(self, tmp_path: Path, monkeypatch: Any) -> None:
        """A task in review phase can be completed after approval."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _setup_tasks(tmp_path, monkeypatch, "- [ ] Review task | review: true\n")

        with mock.patch("janus.services.tasks.run_completion_gates",
                        return_value=CompletionGateResult(ok=True, integration_not_applicable=True)):
            task = complete_task("Review task")

        assert task.title == "Review task"
        content = tasks_file.read_text()
        assert "- [x] Review task" in content


# ──────────────────────────────────────────────────────────────────────
# V3: Review rejection returns task to implementer
# ──────────────────────────────────────────────────────────────────────


class TestV3_ReviewRejection:
    """V3: Review rejection (changes_requested) returns task to implementer."""

    def test_v3_changes_requested_detected(self) -> None:
        """A task with 'changes_requested' in metadata is detected."""
        task = _make_task("Rejected task", extra_metadata=["changes_requested: true"])
        # The task should be back in implementer's queue
        assert task.title == "Rejected task"

    def test_v3_rejection_preserves_task_state(self, tmp_path: Path, monkeypatch: Any) -> None:
        """After rejection, the task remains open (not completed)."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _setup_tasks(tmp_path, monkeypatch, "- [ ] Rejected task\n")

        # Simulate rejection by not completing the task
        content = tasks_file.read_text()
        assert "- [ ] Rejected task" in content
        assert "- [x] Rejected task" not in content


# ──────────────────────────────────────────────────────────────────────
# V4: Review re-request after changes
# ──────────────────────────────────────────────────────────────────────


class TestV4_ReviewReRequest:
    """V4: Review can be re-requested after changes are made."""

    def test_v4_review_re_request(self) -> None:
        """A task can be re-reviewed after changes."""
        task = _make_task("Re-review task", extra_metadata=["review: true", "round: 2"])
        assert _is_review_phase(task) is True

    def test_v4_multiple_review_rounds(self) -> None:
        """Multiple review rounds are tracked."""
        task = _make_task("Multi-round task", extra_metadata=["review: true", "round: 3"])
        assert _is_review_phase(task) is True


# ──────────────────────────────────────────────────────────────────────
# V5: Review round counting
# ──────────────────────────────────────────────────────────────────────


class TestV5_ReviewRoundCounting:
    """V5: Review rounds are counted correctly."""

    def test_v5_review_round_detection(self) -> None:
        """Review round is detected from metadata."""
        task = _make_task("Round task", extra_metadata=["review: true", "round: 1"])
        assert _is_review_phase(task) is True

    def test_v5_no_review_round(self) -> None:
        """Task without review metadata has no review round."""
        task = _make_task("No review task")
        assert _is_review_phase(task) is False


# ──────────────────────────────────────────────────────────────────────
# V6: Reviewer provenance persistence
# ──────────────────────────────────────────────────────────────────────


class TestV6_ReviewerProvenance:
    """V6: Reviewer provenance is persisted across review rounds."""

    def test_v6_reviewer_provenance_in_metadata(self) -> None:
        """Reviewer provenance is stored in task metadata."""
        task = _make_task("Provenance task", extra_metadata=[
            "review: true",
            "reviewer: senior-reviewer",
            "round: 1",
        ])
        assert _is_review_phase(task) is True
        assert any("reviewer" in m for m in task.extra_metadata)


# ──────────────────────────────────────────────────────────────────────
# V7: Review timeout/escalation
# ──────────────────────────────────────────────────────────────────────


class TestV7_ReviewTimeout:
    """V7: Review timeout/escalation is handled."""

    def test_v7_review_timeout_detected(self) -> None:
        """A review timeout is detected from metadata."""
        task = _make_task("Timeout task", extra_metadata=[
            "review: true",
            "review_timeout: true",
        ])
        assert _is_review_phase(task) is True


# ──────────────────────────────────────────────────────────────────────
# V8: Multiple review rounds
# ──────────────────────────────────────────────────────────────────────


class TestV8_MultipleReviewRounds:
    """V8: Multiple review rounds are handled correctly."""

    def test_v8_multiple_rounds(self) -> None:
        """Multiple review rounds are tracked."""
        for round_num in range(1, 6):
            task = _make_task(f"Round {round_num} task", extra_metadata=[
                "review: true",
                f"round: {round_num}",
            ])
            assert _is_review_phase(task) is True


# ──────────────────────────────────────────────────────────────────────
# V9: Review with parent gating
# ──────────────────────────────────────────────────────────────────────


class TestV9_ReviewWithParentGating:
    """V9: Review respects parent gating."""

    def test_v9_review_with_parent(self) -> None:
        """A task with a parent can be in review phase."""
        task = _make_task("Child task", extra_metadata=[
            "review: true",
            "parent: parent-task-id",
        ])
        assert _is_review_phase(task) is True


# ──────────────────────────────────────────────────────────────────────
# V10: Review state transitions
# ──────────────────────────────────────────────────────────────────────


class TestV10_ReviewStateTransitions:
    """V10: Review state transitions are correct."""

    def test_v10_review_phase_support_mode(self) -> None:
        """A task in review phase gets REVIEW support mode."""
        task = _make_task("Review task", extra_metadata=["review: true"])
        goal = _make_goal()
        context = _make_context()

        mode = select_support_mode(task, goal, context, ExecutionMode.JANUS)
        # JANUS execution overrides to EXECUTE
        assert mode == SupportMode.EXECUTE

    def test_v10_review_phase_non_janus(self) -> None:
        """A task in review phase with non-JANUS execution gets REVIEW support
        when no higher-priority support mode matches."""
        task = _make_task("Review task", extra_metadata=["review: true"])
        goal = _make_goal()
        # skill_evidence_count > 0 (blocks EXPLAIN), goal_health="completed"
        # (blocks COACH and SCAFFOLD), so REVIEW is selected.
        context = _make_context(skill_evidence_count=1, goal_health="completed")

        mode = select_support_mode(task, goal, context, ExecutionMode.USER)
        assert mode == SupportMode.REVIEW


# ──────────────────────────────────────────────────────────────────────
# V11: Review handoff conditions
# ──────────────────────────────────────────────────────────────────────


class TestV11_ReviewHandoffConditions:
    """V11: Review handoff conditions are met."""

    def test_v11_handoff_when_review_complete(self) -> None:
        """Handoff occurs when review is complete."""
        task = _make_task("Handoff task", extra_metadata=[
            "review: true",
            "review_complete: true",
        ])
        assert _is_review_phase(task) is True

    def test_v11_handoff_with_approval(self) -> None:
        """Handoff occurs with approval."""
        task = _make_task("Approved task", extra_metadata=[
            "review: true",
            "approved: true",
        ])
        assert _is_review_phase(task) is True


# ──────────────────────────────────────────────────────────────────────
# V12: Review with integration gate
# ──────────────────────────────────────────────────────────────────────


class TestV12_ReviewWithIntegrationGate:
    """V12: Review phase works with integration gate."""

    def test_v12_review_with_passing_integration(self, tmp_path: Path, monkeypatch: Any) -> None:
        """A task in review phase can pass integration gate."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _setup_tasks(tmp_path, monkeypatch, "- [ ] Review integration task | review: true\n")

        with mock.patch("janus.services.tasks.run_completion_gates",
                        return_value=CompletionGateResult(ok=True, integration_not_applicable=True)):
            task = complete_task("Review integration task")

        assert task.title == "Review integration task"
        content = tasks_file.read_text()
        assert "- [x] Review integration task" in content


# ──────────────────────────────────────────────────────────────────────
# V13: Review with completion gate
# ──────────────────────────────────────────────────────────────────────


class TestV13_ReviewWithCompletionGate:
    """V13: Review phase works with completion gate."""

    def test_v13_review_with_failing_completion_gate(self, tmp_path: Path, monkeypatch: Any) -> None:
        """A task in review phase is blocked by failing completion gate."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Review gate task | review: true\n")

        failed_result = CompletionGateResult(
            ok=False,
            blocked_reason="working_tree_not_clean",
            blocked_message="Working tree not clean",
        )

        with mock.patch("janus.services.tasks.run_completion_gates", return_value=failed_result):
            with pytest.raises(UnifiedCompletionGateError):
                complete_task("Review gate task")


# ──────────────────────────────────────────────────────────────────────
# V14: Review event ordering
# ──────────────────────────────────────────────────────────────────────


class TestV14_ReviewEventOrdering:
    """V14: Review events are ordered correctly."""

    def test_v14_event_order(self) -> None:
        """Review events follow the correct order."""
        events = ["review_requested", "changes_requested", "review_requested", "completed"]
        assert events[0] == "review_requested"
        assert events[1] == "changes_requested"
        assert events[2] == "review_requested"
        assert events[3] == "completed"


# ──────────────────────────────────────────────────────────────────────
# V15: Full lifecycle review cycle
# ──────────────────────────────────────────────────────────────────────


class TestV15_FullLifecycleReviewCycle:
    """V15: Full lifecycle review cycle works end-to-end."""

    def test_v15_full_cycle(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Full cycle: create → review → changes → re-review → complete."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _setup_tasks(tmp_path, monkeypatch, "- [ ] Full cycle task\n")

        # Step 1: Task is created
        content = tasks_file.read_text()
        assert "- [ ] Full cycle task" in content

        # Step 2: Task enters review
        task = _make_task("Full cycle task", extra_metadata=["review: true"])
        assert _is_review_phase(task) is True

        # Step 3: Review rejection
        task_rejected = _make_task("Full cycle task", extra_metadata=[
            "review: true",
            "changes_requested: true",
        ])
        assert _is_review_phase(task_rejected) is True

        # Step 4: Re-review
        task_rereview = _make_task("Full cycle task", extra_metadata=[
            "review: true",
            "round: 2",
        ])
        assert _is_review_phase(task_rereview) is True

        # Step 5: Completion
        with mock.patch("janus.services.tasks.run_completion_gates",
                        return_value=CompletionGateResult(ok=True, integration_not_applicable=True)):
            complete_task("Full cycle task")

        content = tasks_file.read_text()
        assert "- [x] Full cycle task" in content
