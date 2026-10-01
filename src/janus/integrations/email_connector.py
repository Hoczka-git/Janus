"""Email connector — implements the Connector ABC (Phase F).

Stub implementation: defines the interface and capabilities but
does not yet implement actual email API calls.
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


class EmailConnector(Connector):
    """Connector for Email integration (stub)."""

    @property
    def source(self) -> str:
        return "email"

    @property
    def capabilities(self) -> set[ConnectorCapability]:
        return {ConnectorCapability.READ}

    @property
    def permissions(self) -> set[ConnectorPermission]:
        return {ConnectorPermission.EMAIL_READ}

    def read(self, **kwargs: Any) -> list[Any]:
        """Fetch emails (stub — returns empty list)."""
        logger.info("EmailConnector.read() called (stub — no implementation)")
        return []
