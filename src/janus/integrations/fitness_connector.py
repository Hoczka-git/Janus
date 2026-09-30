"""Fitness/wearable connector — implements the Connector ABC (Phase F).

Stub implementation: defines the interface and capabilities but
does not yet implement actual fitness API calls.
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


class FitnessConnector(Connector):
    """Connector for fitness/wearable integration (stub)."""

    @property
    def source(self) -> str:
        return "fitness"

    @property
    def capabilities(self) -> set[ConnectorCapability]:
        return {ConnectorCapability.READ}

    @property
    def permissions(self) -> set[ConnectorPermission]:
        return {ConnectorPermission.FITNESS_READ}

    def read(self, **kwargs: Any) -> list[Any]:
        """Fetch fitness data (stub — returns empty list)."""
        logger.info("FitnessConnector.read() called (stub — no implementation)")
        return []
