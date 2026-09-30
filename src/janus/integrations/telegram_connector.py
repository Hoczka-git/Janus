"""Telegram connector — implements the Connector ABC (Phase F).

Wraps the existing ad-hoc Telegram integration in the Connector protocol.
Supports NOTIFY capability: can propose and execute message sends.
"""
from __future__ import annotations

import logging
from typing import Any

from janus.integrations.connector import Connector
from janus.models.connector import (
    ConnectorCapability,
    ConnectorEvidence,
    ConnectorPermission,
    ConnectorProposal,
    ConnectorResult,
)

logger = logging.getLogger(__name__)


class TelegramConnector(Connector):
    """Connector for Telegram delivery integration."""

    @property
    def source(self) -> str:
        return "telegram"

    @property
    def capabilities(self) -> set[ConnectorCapability]:
        return {ConnectorCapability.NOTIFY, ConnectorCapability.EXECUTE}

    @property
    def permissions(self) -> set[ConnectorPermission]:
        return {ConnectorPermission.TELEGRAM_SEND}

    def read(self, **kwargs: Any) -> list[Any]:
        """Telegram does not support reading messages in this integration."""
        return []

    def propose(self, **kwargs: Any) -> ConnectorProposal:
        """Propose sending a message via Telegram."""
        from janus.integrations.telegram import format_telegram_message

        briefing = kwargs.get("briefing")
        if briefing is None:
            raise ValueError("briefing is required to propose a Telegram message")

        text = format_telegram_message(briefing)
        return ConnectorProposal(
            connector_source=self.source,
            action="send_message",
            payload={"text": text},
            reason="Deliver daily briefing to Telegram",
        )

    def execute(
        self, proposal: ConnectorProposal, **kwargs: Any
    ) -> ConnectorResult:
        """Execute a Telegram message send proposal."""
        from janus.integrations.telegram import send_briefing

        briefing = kwargs.get("briefing")
        if briefing is None:
            return ConnectorResult(
                success=False,
                connector_source=self.source,
                action=proposal.action,
                error="briefing is required to execute a Telegram message",
            )

        trace_id = kwargs.get("trace_id")
        try:
            send_briefing(briefing, trace_id=trace_id)
            return ConnectorResult(
                success=True,
                connector_source=self.source,
                action=proposal.action,
                data={"message_sent": True},
            )
        except Exception as exc:
            return ConnectorResult(
                success=False,
                connector_source=self.source,
                action=proposal.action,
                error=str(exc),
            )

    def evidence(
        self, result: ConnectorResult, **kwargs: Any
    ) -> ConnectorEvidence:
        """Produce evidence after executing a Telegram proposal."""
        return ConnectorEvidence(
            connector_source=self.source,
            action=result.action,
            summary=(
                f"Telegram message "
                f"{'sent' if result.success else 'failed'}"
            ),
            details={
                "success": result.success,
                "error": result.error,
            },
        )
