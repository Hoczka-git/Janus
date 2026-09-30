"""Connector registry — lifecycle management for all connectors.

Provides registration, lookup, and iteration over all active connectors.
"""
from __future__ import annotations

import logging
from typing import Iterator

from janus.integrations.connector import Connector
from janus.models.connector import ConnectorCapability, ConnectorPermission

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """Registry for all active connectors.

    Usage::

        registry = ConnectorRegistry()
        registry.register(GoogleCalendarConnector())
        registry.register(TelegramConnector())

        for connector in registry:
            print(connector.source, connector.capabilities)
    """

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        """Register a connector. Replaces any existing connector with the same source."""
        source = connector.source
        if source in self._connectors:
            logger.warning(
                "Replacing existing connector '%s'", source
            )
        self._connectors[source] = connector
        logger.info(
            "Registered connector '%s' with capabilities=%s permissions=%s",
            source,
            connector.capabilities,
            connector.permissions,
        )

    def unregister(self, source: str) -> Connector | None:
        """Remove a connector by source. Returns the removed connector or None."""
        return self._connectors.pop(source, None)

    def get(self, source: str) -> Connector | None:
        """Get a connector by source identifier."""
        return self._connectors.get(source)

    def all(self) -> list[Connector]:
        """Return all registered connectors."""
        return list(self._connectors.values())

    def with_capability(
        self, capability: ConnectorCapability
    ) -> list[Connector]:
        """Return all connectors that have the given capability."""
        return [
            c for c in self._connectors.values()
            if capability in c.capabilities
        ]

    def with_permission(
        self, permission: ConnectorPermission
    ) -> list[Connector]:
        """Return all connectors that require the given permission."""
        return [
            c for c in self._connectors.values()
            if permission in c.permissions
        ]

    def __iter__(self) -> Iterator[Connector]:
        return iter(self._connectors.values())

    def __len__(self) -> int:
        return len(self._connectors)

    def __contains__(self, source: str) -> bool:
        return source in self._connectors
