"""Connector ABC — the Phase F integration protocol.

Every integration (Google Calendar, Telegram, GitHub, Email, Fitness, AWS)
must implement this interface. The 7 required components are:

1. source          — unique identifier string
2. capabilities    — set of ConnectorCapability values
3. permissions     — set of ConnectorPermission values
4. read()          — fetch data from the external system
5. propose()       — propose an action (returns ConnectorProposal)
6. execute()       — execute a proposal (returns ConnectorResult)
7. evidence()      — produce evidence after execution (returns ConnectorEvidence)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from janus.models.connector import (
    ConnectorCapability,
    ConnectorEvidence,
    ConnectorPermission,
    ConnectorProposal,
    ConnectorResult,
)


class Connector(ABC):
    """Abstract base class for all Janus integrations.

    Subclasses must implement all 7 components. The default implementations
    of ``propose``, ``execute``, and ``evidence`` raise ``NotImplementedError``
    so that read-only connectors (e.g. Google Calendar) only need to implement
    ``read``.
    """

    @property
    @abstractmethod
    def source(self) -> str:
        """Unique identifier for this connector (e.g. ``"google_calendar"``)."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> set[ConnectorCapability]:
        """Set of capabilities this connector provides."""
        ...

    @property
    @abstractmethod
    def permissions(self) -> set[ConnectorPermission]:
        """Set of permissions this connector requires."""
        ...

    @abstractmethod
    def read(self, **kwargs: Any) -> list[Any]:
        """Fetch data from the external system.

        Returns a list of domain objects (e.g. ``Event``, ``Task``).
        """
        ...

    def propose(self, **kwargs: Any) -> ConnectorProposal:
        """Propose an action to be executed later.

        Read-only connectors may leave this unimplemented.
        """
        raise NotImplementedError(
            f"Connector '{self.source}' does not support propose()"
        )

    def execute(
        self, proposal: ConnectorProposal, **kwargs: Any
    ) -> ConnectorResult:
        """Execute a previously proposed action.

        Read-only connectors may leave this unimplemented.
        """
        raise NotImplementedError(
            f"Connector '{self.source}' does not support execute()"
        )

    def evidence(
        self, result: ConnectorResult, **kwargs: Any
    ) -> ConnectorEvidence:
        """Produce evidence after executing a proposal.

        Read-only connectors may leave this unimplemented.
        """
        raise NotImplementedError(
            f"Connector '{self.source}' does not support evidence()"
        )
