"""Custom pytest markers for regression tests."""

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "scenario(id): marks a test as covering a specific coverage matrix scenario",
    )
    config.addinivalue_line(
        "markers",
        "no_parallel: marks a test as unsafe for parallel execution",
    )
    config.addinivalue_line(
        "markers",
        "slow: marks a test as slow (excluded from quick runs)",
    )
