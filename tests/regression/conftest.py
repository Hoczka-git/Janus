"""Regression-specific pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.regression.harness import TestHarness


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestHarness:
    """Provide a TestHarness instance for regression tests."""
    return TestHarness(tmp_path, monkeypatch)
