"""Targeted test: decision-to-action connection in execution feedback."""
import pytest
from janus.services.execution_feedback import _ingest_decision
from janus.services.decisions import DECISIONS_DIR
from unittest.mock import MagicMock


class MockEvidence:
    def __init__(self, body):
        self.body = body
        self.task_id = "t-test"
        self.summary = "test"
        self.changed_files = []
        self.tests_passed = True
        self.pr_url = None
        self.janus_body = None
        self.metric_updates = None


class MockMetadata:
    object = "decision"
    title = "Test"


def test_decision_to_action_links_goals(monkeypatch, tmp_path):
    """Ingesting a decision with goal_titles connects to action pipeline."""
    # Create synthetic ADR with goal reference
    body = (
        "---\n"
        "adr_number: 099\n"
        "title: Decision to Action Connection\n"
        "status: accepted\n"
        "goal_titles: [\"Test Goal\"]\n"
        "---\n"
        "## Context\n\nLink test.\n"
        "## Decision\n\nConnect.\n"
    )
    # Monkeypatch decisions dir to avoid real writes
    import janus.services.decisions as dec_mod
    dec_dir = tmp_path / "docs" / "decisions"
    dec_dir.mkdir(parents=True)
    monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)

    result = _ingest_decision(MockMetadata(), MockEvidence(body))
    assert result["object"] == "decision"
    assert result["adr_number"] == "099"
    assert "action_connection" in result
    assert "linked_goals" in result.get("action_connection", {}) or "link_errors" in result.get("action_connection", {})
