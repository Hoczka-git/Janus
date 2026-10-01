"""Failure injection fixtures for lifecycle regression tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from tests.regression.harness import TestHarness


@pytest.fixture
def inject_claim_timeout(harness: TestHarness, task_running: dict) -> None:
    """Simulate a claim timeout by expiring the claim lock."""
    harness.inject_claim_timeout(task_running["title"])


@pytest.fixture
def inject_claim_conflict(harness: TestHarness, task_todo: dict) -> None:
    """Simulate a concurrent claim conflict."""
    harness.inject_claim_conflict(task_todo["title"])


@pytest.fixture
def inject_gate_failure(harness: TestHarness) -> None:
    """Inject a failure into the integration gate."""
    from janus.services.tasks import CompletionGateError
    harness.inject_gate_failure(
        "integration", CompletionGateError("test", "injected failure")
    )


@pytest.fixture
def inject_hook_error(harness: TestHarness) -> None:
    """Inject an error into a lifecycle hook."""
    harness.inject_hook_error(
        "kanban_task_completed", RuntimeError("hook exploded")
    )
