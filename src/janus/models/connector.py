"""Connector protocol data models.

These types define the contract that every integration must fulfill
to participate in the Janus connector framework (Phase F).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ConnectorCapability(str, Enum):
    """What a connector can do."""

    READ = "read"
    WRITE = "write"
    NOTIFY = "notify"
    PROPOSE = "propose"
    EXECUTE = "execute"


class ConnectorPermission(str, Enum):
    """What permissions a connector requires."""

    CALENDAR_READ = "calendar.read"
    CALENDAR_WRITE = "calendar.write"
    TELEGRAM_SEND = "telegram.send"
    TELEGRAM_READ = "telegram.read"
    GITHUB_READ = "github.read"
    GITHUB_WRITE = "github.write"
    EMAIL_READ = "email.read"
    EMAIL_SEND = "email.send"
    FITNESS_READ = "fitness.read"
    AWS_READ = "aws.read"
    AWS_WRITE = "aws.write"


@dataclass
class ConnectorProposal:
    """A proposed action from a connector."""

    connector_source: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class ConnectorResult:
    """Result of executing a connector proposal."""

    success: bool
    connector_source: str
    action: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ConnectorEvidence:
    """Evidence produced after executing a connector proposal."""

    connector_source: str
    action: str
    timestamp: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat()
    )
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
