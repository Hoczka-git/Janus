"""TestHarness — orchestrates setup/teardown for lifecycle regression tests.

Adapted from the design spec (t_7062733e) to Janus's markdown-based task
system.  The harness provides:

- Temporary directory management (git repos, workspace dirs).
- Lifecycle state construction (tasks in specific states).
- Mock/stub installation and verification.
- Cleanup orchestration.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable
from unittest import mock

import pytest


class TestHarness:
    """Orchestrates setup/teardown for lifecycle regression tests."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._tmp_path = tmp_path
        self._monkeypatch = monkeypatch
        self._cleanup_stack: list[Callable[[], None]] = []

    # ── Lifecycle state fixtures ──

    def create_task(
        self,
        title: str,
        status: str = "todo",
        parents: list[str] | None = None,
        assignee: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Create a task in the tasks.md file with the given state."""
        tasks_file = self._tmp_path / "tasks.md"
        if not tasks_file.exists():
            tasks_file.write_text("")

        line = f"- [ ] {title}"
        if status and status != "todo":
            line += f" | state: {status}"
        if metadata:
            for k, v in metadata.items():
                line += f" | {k}: {v}"

        content = tasks_file.read_text()
        if content and not content.endswith("\n"):
            content += "\n"
        content += line + "\n"
        tasks_file.write_text(content)

        return {
            "title": title,
            "status": status,
            "parents": parents or [],
            "assignee": assignee,
            "metadata": metadata or {},
        }

    def transition_task(self, task_id: str, new_status: str) -> dict:
        """Transition a task to a new lifecycle state."""
        tasks_file = self._tmp_path / "tasks.md"
        content = tasks_file.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if task_id in line and line.startswith("- ["):
                if new_status == "done":
                    lines[i] = line.replace("- [ ]", "- [x]", 1)
                elif new_status == "todo":
                    lines[i] = line.replace("- [x]", "- [ ]", 1)
                break
        tasks_file.write_text("\n".join(lines) + "\n")
        return {"title": task_id, "status": new_status}

    def create_swarm_root(
        self,
        title: str = "Swarm: Test root",
        children: list[dict] | None = None,
    ) -> dict:
        """Create a swarm root task with optional children."""
        root = self.create_task(title, status="todo")
        if children:
            for child in children:
                self.create_task(
                    child["title"],
                    status=child.get("status", "todo"),
                    parents=[title],
                )
        return root

    # ── Gate mocks ──

    def mock_integration_gate(
        self,
        result: str = "pass",
        reason: str | None = None,
    ) -> mock.MagicMock:
        """Install a mock for the integration gate."""
        from janus.services.tasks import CompletionGateResult

        if result == "pass":
            gate_result = CompletionGateResult(ok=True, integration_not_applicable=True)
        elif result == "fail":
            gate_result = CompletionGateResult(
                ok=False,
                blocked_reason=reason or "integration_failed",
                blocked_message="Integration gate failed (mocked)",
            )
        elif result == "skip":
            gate_result = CompletionGateResult(ok=True, integration_not_applicable=True)
        else:
            gate_result = CompletionGateResult(
                ok=False,
                blocked_reason="error",
                blocked_message="Integration gate error (mocked)",
            )

        m = mock.MagicMock(return_value=gate_result)
        self._monkeypatch.setattr("janus.services.tasks.run_completion_gates", m)
        return m

    def mock_completion_gate(
        self,
        result: str = "pass",
        blocked_reason: str | None = None,
    ) -> mock.MagicMock:
        """Install a mock for the completion gate."""
        from janus.services.tasks import CompletionGateResult

        if result == "pass":
            gate_result = CompletionGateResult(ok=True)
        elif result == "fail":
            gate_result = CompletionGateResult(
                ok=False,
                blocked_reason=blocked_reason or "completion_failed",
                blocked_message="Completion gate failed (mocked)",
            )
        else:
            gate_result = CompletionGateResult(ok=True, integration_not_applicable=True)

        m = mock.MagicMock(return_value=gate_result)
        self._monkeypatch.setattr("janus.services.tasks.run_completion_gates", m)
        return m

    def mock_hook(self, hook_name: str, side_effect: Exception | None = None) -> mock.MagicMock:
        """Install a mock for a lifecycle hook."""
        m = mock.MagicMock()
        if side_effect:
            m.side_effect = side_effect
        self._monkeypatch.setattr(f"janus.services.tasks.{hook_name}", m)
        return m

    # ── Failure injection ──

    def inject_claim_timeout(self, task_id: str) -> None:
        """Simulate a claim timeout by expiring the claim lock."""
        pass  # No-op in markdown-based system

    def inject_claim_conflict(self, task_id: str) -> None:
        """Simulate a concurrent claim conflict."""
        pass  # No-op in markdown-based system

    def inject_gate_failure(self, gate: str, error: Exception) -> None:
        """Inject a failure into a specific gate."""
        m = mock.MagicMock(side_effect=error)
        self._monkeypatch.setattr(f"janus.services.tasks.run_completion_gates", m)

    def inject_hook_error(self, hook_name: str, error: Exception) -> None:
        """Inject an error into a lifecycle hook."""
        m = mock.MagicMock(side_effect=error)
        self._monkeypatch.setattr(f"janus.services.tasks.{hook_name}", m)

    # ── Cleanup ──

    def cleanup(self) -> None:
        """Run all registered cleanup functions in reverse order."""
        while self._cleanup_stack:
            fn = self._cleanup_stack.pop()
            try:
                fn()
            except Exception:
                pass

    def __enter__(self) -> TestHarness:
        return self

    def __exit__(self, *args: Any) -> None:
        self.cleanup()
