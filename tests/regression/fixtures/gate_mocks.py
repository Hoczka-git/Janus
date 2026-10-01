"""Mock/stub strategies for gates and failure injection."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from tests.regression.harness import TestHarness


HOOK_NAMES = [
    "kanban_task_claimed",
    "kanban_task_completed",
    "kanban_task_blocked",
    "kanban_task_unblocked",
    "review_requested",
    "changes_requested",
    "review_reopened",
]


@pytest.fixture
def mock_all_hooks(monkeypatch: pytest.MonkeyPatch) -> dict[str, mock.MagicMock]:
    """Install mocks for all lifecycle hooks. Returns dict of hook_name -> mock."""
    mocks: dict[str, mock.MagicMock] = {}
    for name in HOOK_NAMES:
        m = mock.MagicMock()
        monkeypatch.setattr(f"janus.services.tasks.{name}", m)
        mocks[name] = m
    return mocks


@pytest.fixture
def mock_integration_gate_pass(harness: TestHarness) -> mock.MagicMock:
    """Mock integration gate to pass."""
    return harness.mock_integration_gate("pass")


@pytest.fixture
def mock_integration_gate_fail(harness: TestHarness) -> mock.MagicMock:
    """Mock integration gate to fail."""
    return harness.mock_integration_gate("fail")


@pytest.fixture
def mock_completion_gate_pass(harness: TestHarness) -> mock.MagicMock:
    """Mock completion gate to pass."""
    return harness.mock_completion_gate("pass")


@pytest.fixture
def mock_completion_gate_fail(harness: TestHarness) -> mock.MagicMock:
    """Mock completion gate to fail."""
    return harness.mock_completion_gate("fail")


@pytest.fixture
def claim_timeout(harness: TestHarness, task_running: dict) -> None:
    """Simulate a claim timeout by expiring the claim lock."""
    harness.inject_claim_timeout(task_running["title"])


@pytest.fixture
def claim_conflict(harness: TestHarness, task_todo: dict) -> None:
    """Simulate a concurrent claim conflict."""
    harness.inject_claim_conflict(task_todo["title"])


@pytest.fixture
def gate_failure(harness: TestHarness) -> None:
    """Inject a failure into the integration gate."""
    from janus.services.tasks import CompletionGateError
    harness.inject_gate_failure("integration", CompletionGateError("test", "injected failure"))


@pytest.fixture
def hook_error(harness: TestHarness) -> None:
    """Inject an error into a lifecycle hook."""
    harness.inject_hook_error("kanban_task_completed", RuntimeError("hook exploded"))
