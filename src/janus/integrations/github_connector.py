"""GitHub connector — implements the Connector ABC (Phase F).

Stub implementation: defines the interface and capabilities but
does not yet implement actual GitHub API calls. This establishes the
connector contract so that future implementation only needs to fill
in the ``read()`` method.
"""
from __future__ import annotations

import logging
from typing import Any

from janus.integrations.connector import Connector
from janus.models.connector import (
    ConnectorCapability,
    ConnectorPermission,
)

logger = logging.getLogger(__name__)


class GitHubConnector(Connector):
    """Connector for GitHub integration (stub)."""

    @property
    def source(self) -> str:
        return "github"

    @property
    def capabilities(self) -> set[ConnectorCapability]:
        return {ConnectorCapability.READ}

    @property
    def permissions(self) -> set[ConnectorPermission]:
        return {ConnectorPermission.GITHUB_READ}

    def read(self, **kwargs: Any) -> list[Any]:
        """Fetch data from GitHub (stub — returns empty list)."""
        logger.info("GitHubConnector.read() called (stub — no implementation)")
        return []
