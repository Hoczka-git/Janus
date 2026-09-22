"""Tests that verify formerly-bypassing write paths now route through the
canonical ADR-005 ingestion boundary (ingest_activities).

Two categories of tests:

1. ``TestWrappersConstructCorrectRecords`` — patches
   ``ingest_activities`` at the activity_ingest module and verifies each
   ``*_via_ingest`` wrapper builds the correct ``ActivityRecord`` with the
   right ``ActivityType``, ``source="cli"``, and evidence fields.

2. ``TestCLIRoutesThroughIngest`` — patches ``ingest_activities`` at the
   activity_ingest module and verifies that each CLI handler calls its
   ``*_via_ingest`` wrapper (and does NOT call the underlying service function
   directly).  For handlers that do display logic after ingest, the display
   calls are also patched so the assertion stays focused on routing.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from janus.services.activity_ingest import ActivityType, IngestResult


def _mock_ok_result(action: str = "created") -> IngestResult:
    """Return a mock IngestResult with action != 'rejected'."""
    return IngestResult(
        record_id="test", accepted=True, wrote=True,
        file_path="data/test.md", action=action,
    )


INGEST_PATCH = "janus.services.activity_ingest.ingest_activities"


# ── Wrapper tests: wrappers call ingest_activities with correct ActivityType ──

class TestWrappersConstructCorrectRecords:
    """Each *_via_ingest wrapper must call ingest_activities (the ADR-005 gate)
    with an ActivityRecord carrying the correct ActivityType and source."""

    def test_add_goal_via_ingest_record(self):
        with patch(INGEST_PATCH, return_value=[_mock_ok_result()]) as mock_ing:
            from janus.services.goals import add_goal_via_ingest
            result = add_goal_via_ingest(title="Test Goal", description="desc")

        mock_ing.assert_called_once()
        records = mock_ing.call_args.args[0]
        assert len(records) == 1
        assert records[0].type == ActivityType.GOAL_CREATED
        assert records[0].source == "cli"
        assert records[0].goal_title == "Test Goal"
        assert records[0].evidence.get("description") == "desc"
        assert result.action == "created"

    def test_update_goal_via_ingest_record(self):
        with patch(INGEST_PATCH, return_value=[_mock_ok_result("updated")]) as mock_ing:
            from janus.services.goals import update_goal_via_ingest
            update_goal_via_ingest(title="Test Goal", description="new desc")

        mock_ing.assert_called_once()
        records = mock_ing.call_args.args[0]
        assert records[0].type == ActivityType.GOAL_UPDATED
        assert records[0].source == "cli"
        assert records[0].goal_title == "Test Goal"
        assert records[0].evidence.get("description") == "new desc"

    def test_complete_goal_via_ingest_record(self):
        with patch(INGEST_PATCH, return_value=[_mock_ok_result("updated")]) as mock_ing:
            from janus.services.goals import complete_goal_via_ingest
            complete_goal_via_ingest(title="Test Goal")

        mock_ing.assert_called_once()
        records = mock_ing.call_args.args[0]
        assert records[0].type == ActivityType.GOAL_COMPLETED
        assert records[0].source == "cli"
        assert records[0].goal_title == "Test Goal"

    def test_complete_task_via_ingest_record(self):
        with patch(INGEST_PATCH, return_value=[_mock_ok_result("updated")]) as mock_ing:
            from janus.services.tasks import complete_task_via_ingest
            complete_task_via_ingest(title="Test Task")

        mock_ing.assert_called_once()
        records = mock_ing.call_args.args[0]
        assert records[0].type == ActivityType.TASK_COMPLETED
        assert records[0].source == "cli"
        assert records[0].task_title == "Test Task"

    def test_add_followup_via_ingest_record(self):
        with patch(INGEST_PATCH, return_value=[_mock_ok_result("appended")]) as mock_ing:
            from janus.services.followup import add_followup_via_ingest
            add_followup_via_ingest(title="Test Followup", note="a note")

        mock_ing.assert_called_once()
        records = mock_ing.call_args.args[0]
        assert records[0].type == ActivityType.FOLLOWUP_ADDED
        assert records[0].source == "cli"
        assert records[0].captured_text == "Test Followup"
        assert records[0].evidence.get("note") == "a note"

    def test_add_inbox_item_via_ingest_record(self):
        with patch(INGEST_PATCH, return_value=[_mock_ok_result("appended")]) as mock_ing:
            from janus.services.inbox import add_inbox_item_via_ingest
            add_inbox_item_via_ingest(captured_text="Inbox item text", source="telegram")

        mock_ing.assert_called_once()
        records = mock_ing.call_args.args[0]
        assert records[0].type == ActivityType.INBOX_CAPTURED
        assert records[0].source == "telegram"
        assert records[0].captured_text == "Inbox item text"

    def test_add_workout_via_ingest_record(self):
        with patch(INGEST_PATCH, return_value=[_mock_ok_result("appended")]) as mock_ing:
            from janus.services.workout_analytics import add_workout_via_ingest
            add_workout_via_ingest(
                workout_type="running",
                workout_id="rw-001",
                distance_km=5.0,
                duration_minutes=30.0,
            )

        mock_ing.assert_called_once()
        records = mock_ing.call_args.args[0]
        assert records[0].type == ActivityType.WORKOUT_ADDED
        assert records[0].source == "cli"
        assert records[0].workout_type == "running"
        assert records[0].workout_id == "rw-001"
        assert records[0].distance_km == 5.0

    def test_create_artifact_via_ingest_record(self):
        with patch(INGEST_PATCH, return_value=[_mock_ok_result("created")]) as mock_ing:
            from janus.services.research_artifacts import create_artifact_via_ingest
            body = "---\ntitle: My Artifact\ntype: research\n---\n\nContent."
            create_artifact_via_ingest(body, title="My Artifact")

        mock_ing.assert_called_once()
        records = mock_ing.call_args.args[0]
        assert records[0].type == ActivityType.RESEARCH_ARTIFACT
        assert records[0].captured_text == body

    def test_create_decision_via_ingest_record(self):
        with patch(INGEST_PATCH, return_value=[_mock_ok_result("created")]) as mock_ing:
            from janus.services.decisions import create_decision_via_ingest
            body = "---\nadr_number: 999\ntitle: Test\ntype: decision\n---\n\nContent."
            create_decision_via_ingest(body, title="Test")

        mock_ing.assert_called_once()
        records = mock_ing.call_args.args[0]
        assert records[0].type == ActivityType.DECISION_CREATED
        assert records[0].captured_text == body


# ── CLI routing tests ─────────────────────────────────────────────────────────
# Verify CLI handlers call *_via_ingest wrappers, NOT the underlying service
# functions.

class TestCLIRoutesThroughIngest:
    """CLI handlers must route through the *_via_ingest wrapper, never
    calling the underlying service function directly."""

    def test_goal_add_uses_wrapper(self):
        ingest_ret = [_mock_ok_result()]
        with patch(INGEST_PATCH, return_value=ingest_ret) as mock_ing, \
             patch("janus.goals_cli.add_goal") as mock_direct, \
             patch("janus.goals_cli.get_goal") as mock_get, \
             patch("janus.integrations.markdown_tasks.load_tasks", return_value=[]):
            from janus.goals_cli import handle_goal_add
            handle_goal_add(["My Goal"])

        mock_ing.assert_called_once()
        mock_direct.assert_not_called()

    def test_goal_update_uses_wrapper(self):
        ingest_ret = [_mock_ok_result("updated")]
        with patch(INGEST_PATCH, return_value=ingest_ret) as mock_ing, \
             patch("janus.goals_cli.update_goal_fields") as mock_direct, \
             patch("janus.goals_cli.get_goal") as mock_get:
            from janus.goals_cli import handle_goal_update
            handle_goal_update(["My Goal", "--description", "Updated"])

        mock_ing.assert_called_once()
        mock_direct.assert_not_called()

    def test_goal_complete_uses_wrapper(self):
        ingest_ret = [_mock_ok_result("updated")]
        with patch(INGEST_PATCH, return_value=ingest_ret) as mock_ing, \
             patch("janus.goals_cli.complete_goal") as mock_direct, \
             patch("janus.goals_cli.get_goal") as mock_get:
            from janus.goals_cli import handle_goal_complete
            handle_goal_complete(["My Goal"])

        mock_ing.assert_called_once()
        mock_direct.assert_not_called()

    def test_followup_add_uses_wrapper(self):
        ingest_ret = [_mock_ok_result("appended")]
        with patch(INGEST_PATCH, return_value=ingest_ret) as mock_ing, \
             patch("janus.followup_cli.add_followup") as mock_direct, \
             patch("janus.followup_cli.list_followups", return_value=[]):
            from janus.followup_cli import handle_followup_add
            handle_followup_add(["Test followup"])

        mock_ing.assert_called_once()
        mock_direct.assert_not_called()

    def test_task_complete_uses_wrapper(self):
        ingest_ret = [_mock_ok_result("updated")]
        with patch(INGEST_PATCH, return_value=ingest_ret) as mock_ing, \
             patch("janus.tasks_cli.complete_task") as mock_direct:
            from janus.tasks_cli import handle_task_complete
            handle_task_complete(["Build feature"])

        mock_ing.assert_called_once()
        mock_direct.assert_not_called()

    def test_workout_add_uses_wrapper(self):
        ingest_ret = [_mock_ok_result("appended")]
        with patch(INGEST_PATCH, return_value=ingest_ret) as mock_ing, \
             patch("janus.workout_cli.load_workouts", return_value=[]):
            from janus.workout_cli import handle_workout_add
            handle_workout_add([
                "--type", "running",
                "--distance", "5.0",
                "--duration", "30",
            ])

        mock_ing.assert_called_once()

    def test_research_add_uses_wrapper(self):
        ingest_ret = [_mock_ok_result("created")]
        with patch(INGEST_PATCH, return_value=ingest_ret) as mock_ing, \
             patch("janus.services.research_artifacts.create_artifact") as mock_direct, \
             patch("janus.services.research_artifacts.load_artifact", side_effect=ValueError("not found")), \
             patch("janus.integrations.markdown_research._parse_artifact_content") as mock_parse, \
             patch("janus.integrations.markdown_research.RESEARCH_DIR", Path("/tmp")):
            mock_parse.return_value = MagicMock(title="Test", findings=[])
            from janus.research_cli import handle_research_add
            import tempfile, os
            d = tempfile.mkdtemp()
            adr_file = os.path.join(d, "adr.md")
            with open(adr_file, "w") as f:
                f.write("---\ntitle: Test\ntype: research\n---\n\nContent.")
            handle_research_add([adr_file])

        mock_ing.assert_called_once()
        mock_direct.assert_not_called()

    def test_decision_propose_uses_wrapper(self):
        ingest_ret = [_mock_ok_result("created")]
        with patch(INGEST_PATCH, return_value=ingest_ret) as mock_ing, \
             patch("janus.services.decisions.create_decision") as mock_direct:
            from janus.decision_cli import handle_decision_propose
            # Need an ADR file argument
            import tempfile, os
            d = tempfile.mkdtemp()
            adr_file = os.path.join(d, "001-test.md")
            with open(adr_file, "w") as f:
                f.write("---\nadr_number: 1\ntitle: Test\ntype: decision\n---\n\nContent.")
            handle_decision_propose([adr_file])

        mock_ing.assert_called_once()
        mock_direct.assert_not_called()
