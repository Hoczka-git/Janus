"""Google Calendar connector — implements the Connector ABC (Phase F).

Wraps the existing ad-hoc Google Calendar integration in the Connector
protocol. Read-only: supports ``read()`` but not ``propose()``/``execute()``.
"""
from __future__ import annotations

import logging
from typing import Any

from janus.integrations.connector import Connector
from janus.models.connector import (
    ConnectorCapability,
    ConnectorPermission,
)
from janus.models.event import Event

logger = logging.getLogger(__name__)


class GoogleCalendarConnector(Connector):
    """Connector for Google Calendar integration."""

    @property
    def source(self) -> str:
        return "google_calendar"

    @property
    def capabilities(self) -> set[ConnectorCapability]:
        return {ConnectorCapability.READ}

    @property
    def permissions(self) -> set[ConnectorPermission]:
        return {ConnectorPermission.CALENDAR_READ}

    def read(self, **kwargs: Any) -> list[Event]:
        """Fetch upcoming events from all configured calendars."""
        from janus.integrations.google_calendar import list_upcoming_events

        trace_id = kwargs.get("trace_id")
        return list_upcoming_events(trace_id=trace_id)
