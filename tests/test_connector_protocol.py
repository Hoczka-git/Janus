"""Tests for the Connector Protocol (Phase F).

Covers:
- Connector data models (capability, permission, proposal, result, evidence)
- Connector ABC (7 required components)
- ConnectorRegistry (lifecycle management)
- GoogleCalendarConnector (read-only)
- TelegramConnector (notify + execute)
- Stub connectors (GitHub, Email, Fitness, AWS)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from janus.integrations.aws_connector import AWSConnector
from janus.integrations.connector import Connector
from janus.integrations.email_connector import EmailConnector
from janus.integrations.fitness_connector import FitnessConnector
from janus.integrations.github_connector import GitHubConnector
from janus.integrations.google_calendar_connector import GoogleCalendarConnector
from janus.integrations.registry import ConnectorRegistry
from janus.integrations.telegram_connector import TelegramConnector
from janus.models.connector import (
    ConnectorCapability,
    ConnectorEvidence,
    ConnectorPermission,
    ConnectorProposal,
    ConnectorResult,
)
from janus.models.daily_briefing import DailyBriefing
from janus.models.event import Event


# ── Data model tests ─────────────────────────────────────────────────────────


class TestConnectorCapability:
    def test_values(self):
        assert ConnectorCapability.READ == "read"
        assert ConnectorCapability.WRITE == "write"
        assert ConnectorCapability.NOTIFY == "notify"
        assert ConnectorCapability.PROPOSE == "propose"
        assert ConnectorCapability.EXECUTE == "execute"

    def test_is_str_enum(self):
        assert isinstance(ConnectorCapability.READ, str)


class TestConnectorPermission:
    def test_values(self):
        assert ConnectorPermission.CALENDAR_READ == "calendar.read"
        assert ConnectorPermission.CALENDAR_WRITE == "calendar.write"
        assert ConnectorPermission.TELEGRAM_SEND == "telegram.send"
        assert ConnectorPermission.TELEGRAM_READ == "telegram.read"
        assert ConnectorPermission.GITHUB_READ == "github.read"
        assert ConnectorPermission.GITHUB_WRITE == "github.write"
        assert ConnectorPermission.EMAIL_READ == "email.read"
        assert ConnectorPermission.EMAIL_SEND == "email.send"
        assert ConnectorPermission.FITNESS_READ == "fitness.read"
        assert ConnectorPermission.AWS_READ == "aws.read"
        assert ConnectorPermission.AWS_WRITE == "aws.write"

    def test_is_str_enum(self):
        assert isinstance(ConnectorPermission.CALENDAR_READ, str)


class TestConnectorProposal:
    def test_creation(self):
        p = ConnectorProposal(
            connector_source="telegram",
            action="send_message",
            payload={"text": "hello"},
            reason="test",
        )
        assert p.connector_source == "telegram"
        assert p.action == "send_message"
        assert p.payload == {"text": "hello"}
        assert p.reason == "test"

    def test_default_payload(self):
        p = ConnectorProposal(connector_source="x", action="y")
        assert p.payload == {}
        assert p.reason == ""


class TestConnectorResult:
    def test_success(self):
        r = ConnectorResult(
            success=True,
            connector_source="telegram",
            action="send_message",
            data={"message_sent": True},
        )
        assert r.success is True
        assert r.error is None

    def test_failure(self):
        r = ConnectorResult(
            success=False,
            connector_source="telegram",
            action="send_message",
            error="timeout",
        )
        assert r.success is False
        assert r.error == "timeout"


class TestConnectorEvidence:
    def test_creation(self):
        e = ConnectorEvidence(
            connector_source="telegram",
            action="send_message",
            summary="Message sent",
            details={"success": True},
        )
        assert e.connector_source == "telegram"
        assert e.action == "send_message"
        assert e.summary == "Message sent"
        assert e.details == {"success": True}
        assert e.timestamp  # auto-generated


# ── Connector ABC tests ──────────────────────────────────────────────────────


class TestConnectorABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Connector()  # type: ignore[abstract]

    def test_read_only_connector_raises_on_propose(self):
        class ReadOnlyConnector(Connector):
            @property
            def source(self) -> str:
                return "test"

            @property
            def capabilities(self) -> set[ConnectorCapability]:
                return {ConnectorCapability.READ}

            @property
            def permissions(self) -> set[ConnectorPermission]:
                return set()

            def read(self, **kwargs):
                return []

        c = ReadOnlyConnector()
        with pytest.raises(NotImplementedError, match="does not support propose"):
            c.propose()

    def test_read_only_connector_raises_on_execute(self):
        class ReadOnlyConnector(Connector):
            @property
            def source(self) -> str:
                return "test"

            @property
            def capabilities(self) -> set[ConnectorCapability]:
                return {ConnectorCapability.READ}

            @property
            def permissions(self) -> set[ConnectorPermission]:
                return set()

            def read(self, **kwargs):
                return []

        c = ReadOnlyConnector()
        with pytest.raises(NotImplementedError, match="does not support execute"):
            c.execute(ConnectorProposal(connector_source="test", action="x"))

    def test_read_only_connector_raises_on_evidence(self):
        class ReadOnlyConnector(Connector):
            @property
            def source(self) -> str:
                return "test"

            @property
            def capabilities(self) -> set[ConnectorCapability]:
                return {ConnectorCapability.READ}

            @property
            def permissions(self) -> set[ConnectorPermission]:
                return set()

            def read(self, **kwargs):
                return []

        c = ReadOnlyConnector()
        with pytest.raises(NotImplementedError, match="does not support evidence"):
            c.evidence(ConnectorResult(success=True, connector_source="test", action="x"))


# ── ConnectorRegistry tests ──────────────────────────────────────────────────


class TestConnectorRegistry:
    def test_register_and_get(self):
        registry = ConnectorRegistry()
        gc = GoogleCalendarConnector()
        registry.register(gc)
        assert registry.get("google_calendar") is gc

    def test_register_replaces_existing(self):
        registry = ConnectorRegistry()
        gc1 = GoogleCalendarConnector()
        gc2 = GoogleCalendarConnector()
        registry.register(gc1)
        registry.register(gc2)
        assert registry.get("google_calendar") is gc2
        assert len(registry) == 1

    def test_unregister(self):
        registry = ConnectorRegistry()
        gc = GoogleCalendarConnector()
        registry.register(gc)
        removed = registry.unregister("google_calendar")
        assert removed is gc
        assert registry.get("google_calendar") is None
        assert len(registry) == 0

    def test_unregister_nonexistent(self):
        registry = ConnectorRegistry()
        assert registry.unregister("nonexistent") is None

    def test_all(self):
        registry = ConnectorRegistry()
        registry.register(GoogleCalendarConnector())
        registry.register(TelegramConnector())
        all_connectors = registry.all()
        assert len(all_connectors) == 2
        sources = {c.source for c in all_connectors}
        assert sources == {"google_calendar", "telegram"}

    def test_with_capability(self):
        registry = ConnectorRegistry()
        registry.register(GoogleCalendarConnector())
        registry.register(TelegramConnector())
        read_connectors = registry.with_capability(ConnectorCapability.READ)
        assert len(read_connectors) == 1
        assert read_connectors[0].source == "google_calendar"

    def test_with_permission(self):
        registry = ConnectorRegistry()
        registry.register(GoogleCalendarConnector())
        registry.register(TelegramConnector())
        cal_connectors = registry.with_permission(ConnectorPermission.CALENDAR_READ)
        assert len(cal_connectors) == 1
        assert cal_connectors[0].source == "google_calendar"

    def test_iteration(self):
        registry = ConnectorRegistry()
        registry.register(GoogleCalendarConnector())
        registry.register(TelegramConnector())
        sources = [c.source for c in registry]
        assert set(sources) == {"google_calendar", "telegram"}

    def test_len(self):
        registry = ConnectorRegistry()
        assert len(registry) == 0
        registry.register(GoogleCalendarConnector())
        assert len(registry) == 1

    def test_contains(self):
        registry = ConnectorRegistry()
        registry.register(GoogleCalendarConnector())
        assert "google_calendar" in registry
        assert "telegram" not in registry


# ── GoogleCalendarConnector tests ─────────────────────────────────────────────


class TestGoogleCalendarConnector:
    def test_source(self):
        c = GoogleCalendarConnector()
        assert c.source == "google_calendar"

    def test_capabilities(self):
        c = GoogleCalendarConnector()
        assert c.capabilities == {ConnectorCapability.READ}

    def test_permissions(self):
        c = GoogleCalendarConnector()
        assert c.permissions == {ConnectorPermission.CALENDAR_READ}

    def test_read_returns_events(self):
        c = GoogleCalendarConnector()
        with patch(
            "janus.integrations.google_calendar.list_upcoming_events",
            return_value=[],
        ):
            result = c.read()
        assert result == []

    def test_read_with_trace_id(self):
        c = GoogleCalendarConnector()
        with patch(
            "janus.integrations.google_calendar.list_upcoming_events",
            return_value=[],
        ) as mock:
            c.read(trace_id="test-trace")
        mock.assert_called_once_with(trace_id="test-trace")


# ── TelegramConnector tests ──────────────────────────────────────────────────


class TestTelegramConnector:
    def test_source(self):
        c = TelegramConnector()
        assert c.source == "telegram"

    def test_capabilities(self):
        c = TelegramConnector()
        assert ConnectorCapability.NOTIFY in c.capabilities
        assert ConnectorCapability.EXECUTE in c.capabilities

    def test_permissions(self):
        c = TelegramConnector()
        assert c.permissions == {ConnectorPermission.TELEGRAM_SEND}

    def test_read_returns_empty(self):
        c = TelegramConnector()
        assert c.read() == []

    def test_propose(self):
        c = TelegramConnector()
        briefing = DailyBriefing(events=[], has_calendar=False)
        proposal = c.propose(briefing=briefing)
        assert proposal.connector_source == "telegram"
        assert proposal.action == "send_message"
        assert "text" in proposal.payload

    def test_propose_requires_briefing(self):
        c = TelegramConnector()
        with pytest.raises(ValueError, match="briefing is required"):
            c.propose()

    def test_execute_success(self):
        c = TelegramConnector()
        briefing = DailyBriefing(events=[], has_calendar=False)
        proposal = ConnectorProposal(
            connector_source="telegram",
            action="send_message",
            payload={"text": "test"},
        )
        with patch(
            "janus.integrations.telegram.send_briefing"
        ) as mock_send:
            result = c.execute(proposal, briefing=briefing)
        assert result.success is True
        assert result.connector_source == "telegram"
        mock_send.assert_called_once()

    def test_execute_failure(self):
        c = TelegramConnector()
        briefing = DailyBriefing(events=[], has_calendar=False)
        proposal = ConnectorProposal(
            connector_source="telegram",
            action="send_message",
        )
        with patch(
            "janus.integrations.telegram.send_briefing",
            side_effect=RuntimeError("API error"),
        ):
            result = c.execute(proposal, briefing=briefing)
        assert result.success is False
        assert "API error" in result.error

    def test_execute_requires_briefing(self):
        c = TelegramConnector()
        proposal = ConnectorProposal(
            connector_source="telegram",
            action="send_message",
        )
        result = c.execute(proposal)
        assert result.success is False
        assert "briefing is required" in result.error

    def test_evidence(self):
        c = TelegramConnector()
        result = ConnectorResult(
            success=True,
            connector_source="telegram",
            action="send_message",
        )
        evidence = c.evidence(result)
        assert evidence.connector_source == "telegram"
        assert evidence.action == "send_message"
        assert "sent" in evidence.summary


# ── Stub connector tests ─────────────────────────────────────────────────────


class TestGitHubConnector:
    def test_source(self):
        assert GitHubConnector().source == "github"

    def test_capabilities(self):
        assert GitHubConnector().capabilities == {ConnectorCapability.READ}

    def test_permissions(self):
        assert GitHubConnector().permissions == {ConnectorPermission.GITHUB_READ}

    def test_read_returns_empty(self):
        assert GitHubConnector().read() == []


class TestEmailConnector:
    def test_source(self):
        assert EmailConnector().source == "email"

    def test_capabilities(self):
        assert EmailConnector().capabilities == {ConnectorCapability.READ}

    def test_permissions(self):
        assert EmailConnector().permissions == {ConnectorPermission.EMAIL_READ}

    def test_read_returns_empty(self):
        assert EmailConnector().read() == []


class TestFitnessConnector:
    def test_source(self):
        assert FitnessConnector().source == "fitness"

    def test_capabilities(self):
        assert FitnessConnector().capabilities == {ConnectorCapability.READ}

    def test_permissions(self):
        assert FitnessConnector().permissions == {ConnectorPermission.FITNESS_READ}

    def test_read_returns_empty(self):
        assert FitnessConnector().read() == []


class TestAWSConnector:
    def test_source(self):
        assert AWSConnector().source == "aws"

    def test_capabilities(self):
        assert AWSConnector().capabilities == {ConnectorCapability.READ}

    def test_permissions(self):
        assert AWSConnector().permissions == {ConnectorPermission.AWS_READ}

    def test_read_returns_empty(self):
        assert AWSConnector().read() == []


# ── Integration: registry with all connectors ────────────────────────────────


class TestFullRegistry:
    def test_register_all_connectors(self):
        registry = ConnectorRegistry()
        registry.register(GoogleCalendarConnector())
        registry.register(TelegramConnector())
        registry.register(GitHubConnector())
        registry.register(EmailConnector())
        registry.register(FitnessConnector())
        registry.register(AWSConnector())
        assert len(registry) == 6

    def test_all_sources_unique(self):
        registry = ConnectorRegistry()
        registry.register(GoogleCalendarConnector())
        registry.register(TelegramConnector())
        registry.register(GitHubConnector())
        registry.register(EmailConnector())
        registry.register(FitnessConnector())
        registry.register(AWSConnector())
        sources = [c.source for c in registry]
        assert len(sources) == len(set(sources))

    def test_all_implement_connector_abc(self):
        registry = ConnectorRegistry()
        registry.register(GoogleCalendarConnector())
        registry.register(TelegramConnector())
        registry.register(GitHubConnector())
        registry.register(EmailConnector())
        registry.register(FitnessConnector())
        registry.register(AWSConnector())
        for c in registry:
            assert isinstance(c, Connector)
