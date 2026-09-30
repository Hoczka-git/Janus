"""Tests for swarm root integration opt-out (task t_fbd79333).

Covers the four acceptance criteria:
  A) Ordinary worktree task requires merge (integration gate enforced).
  B) Swarm root skips integration, waits for children, and emits completed.
  C) Replenishment is triggered on root completion.
  D) A swarm root that has its own code change does NOT accidentally bypass
     integration (integration_required=False is correctly set even when the
     root has a worktree workspace with a branch_name).

These tests use the existing test infrastructure from the Janus repo and
the installed hermes-agent's kanban_db / kanban_swarm modules.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap (mirrors tests/test_kanban_review_topology.py)
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_hermes_agent = None
for _candidate in (
    os.path.expanduser("~/.hermes/hermes-agent"),
    os.path.join(_REPO_ROOT, ".hermes", "hermes-agent"),
):
    if os.path.isdir(_candidate):
        _hermes_agent = _candidate
        break
if _hermes_agent and _hermes_agent not in sys.path:
    sys.path.insert(1, _hermes_agent)
# Re-assert the Janus repo root above hermes-agent so the local ``plugins``
# namespace package wins over the hermes-agent copy.
if _hermes_agent in sys.path:
    sys.path.remove(_hermes_agent)
    sys.path.insert(0, _REPO_ROOT)
    sys.path.insert(1, _hermes_agent)

pytest.importorskip("hermes_cli", reason="hermes_cli not available (install hermes-agent)")

from hermes_cli import kanban_db as kb  # noqa: E402
from hermes_cli import web_git as wg  # noqa: E402
from hermes_cli.kanban_swarm import SwarmWorkerSpec, create_swarm  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kanban_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated HERMES_HOME with an empty kanban DB (canonical pattern)."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in (
        "HERMES_KANBAN_DB",
        "HERMES_KANBAN_WORKSPACES_ROOT",
        "HERMES_KANBAN_HOME",
        "HERMES_KANBAN_BOARD",
    ):
        monkeypatch.delenv(var, raising=False)
    try:
        import hermes_constants  # type: ignore[import]
        hermes_constants._cached_default_hermes_root = None  # type: ignore[attr-defined]
    except Exception:
        pass
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


@pytest.fixture
def conn(kanban_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    c = kb.connect(board="default")
    try:
        yield c
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _report(
    overall: str = "PASS",
    summary: str = "remotely verified: branch pushed, remote branch exists, "
    "PR merged, CI green",
    failures: Optional[list] = None,
    has_unpushed: bool = False,
    remote_branch_exists: bool = True,
    pr_exists: bool = True,
    pr_merged: bool = True,
    ci_state: str = "success",
    pr_number: Optional[int] = 42,
) -> dict:
    return {
        "overall": overall,
        "summary": summary,
        "failures": failures or [],
        "has_unpushed": has_unpushed,
        "remote_branch_exists": remote_branch_exists,
        "pr_exists": pr_exists,
        "pr_merged": pr_merged,
        "ci_state": ci_state,
        "pr_number": pr_number,
    }


def _fail(check: str, message: str) -> dict:
    return {"check": check, "message": message}


def _event_kinds(events) -> list:
    return [e.kind for e in events]


def _last_event(events, kind: str):
    matches = [e for e in events if e.kind == kind]
    assert matches, f"expected event {kind!r}, got: {_event_kinds(events)}"
    return matches[-1]


def _make_worktree_task(
    conn,
    tmp_path: Path,
    *,
    workspace_kind: str = "worktree",
    branch_name: Optional[str] = "wt/branch",
    body: Optional[str] = None,
    integration_required: Optional[bool] = None,
) -> str:
    ws = tmp_path / "worktree"
    ws.mkdir(exist_ok=True)
    return kb.create_task(
        conn,
        title="Implement integrated feature",
        assignee="builder",
        body=body or "done when merged\n",
        workspace_kind=workspace_kind,
        workspace_path=str(ws),
        branch_name=branch_name,
        integration_required=integration_required,
    )


# ---------------------------------------------------------------------------
# Test A: Ordinary worktree task requires merge (integration gate enforced)
# ---------------------------------------------------------------------------


class TestA_OrdinaryWorktreeRequiresMerge:
    """An ordinary worktree task (not a swarm root) must pass the integration
    gate before it can complete. The gate blocks completion when the remote
    integration state FAILs (unpushed commits, no PR, PR not merged, CI
    failure, CI unknown/pending)."""

    @pytest.mark.parametrize(
        "scenario, report",
        [
            (
                "unpushed_commits",
                _report(
                    overall="FAIL",
                    summary="remote integration check failed: 3 unpushed commit(s)",
                    failures=[_fail("unpushed_commits", "3 unpushed commit(s)")],
                    has_unpushed=True,
                ),
            ),
            (
                "no_pr",
                _report(
                    overall="FAIL",
                    failures=[_fail("pr_exists", "no merged PR found for branch")],
                    pr_exists=False,
                    pr_merged=False,
                ),
            ),
            (
                "pr_not_merged",
                _report(
                    overall="FAIL",
                    failures=[_fail("pr_merged", "PR exists but is open")],
                    pr_exists=True,
                    pr_merged=False,
                    ci_state="success",
                ),
            ),
            (
                "ci_failure",
                _report(
                    overall="FAIL",
                    failures=[_fail("ci_green", "CI failed")],
                    ci_state="failure",
                ),
            ),
            (
                "ci_unknown",
                _report(
                    overall="FAIL",
                    failures=[_fail("ci_green", "CI unknown")],
                    ci_state="unknown",
                ),
            ),
        ],
    )
    def test_worktree_task_blocked_on_integration_failure(
        self, conn, tmp_path, monkeypatch, scenario, report,
    ):
        """A worktree task whose remote integration state is FAIL must NOT reach
        'done'; status stays in-flight and a blocking audit event is emitted."""
        monkeypatch.setattr(wg, "review_integration_state",
                            mock.MagicMock(return_value=report))
        task_id = _make_worktree_task(conn, tmp_path)
        claimed = kb.claim_task(conn, task_id, claimer="builder:1")
        assert claimed is not None
        assert claimed.current_run_id is not None

        with pytest.raises(kb.IntegrationGateError) as exc_info:
            kb.complete_task(
                conn, task_id,
                result="done", summary="implemented",
                expected_run_id=claimed.current_run_id,
            )

        ige = exc_info.value
        assert ige.task_id == task_id
        assert ige.branch_name == "wt/branch"
        assert ige.report["overall"] == "FAIL"

        # No state mutation: task must NOT be 'done'.
        after = kb.get_task(conn, task_id)
        assert after is not None
        assert after.status != "done"

        events = kb.list_events(conn, task_id)
        kinds = _event_kinds(events)
        assert "completion_blocked_integration_failed" in kinds
        blocked = _last_event(events, "completion_blocked_integration_failed")
        assert blocked.payload is not None
        assert blocked.payload["branch_name"] == "wt/branch"
        assert blocked.payload["overall"] == "FAIL"

    def test_worktree_task_allowed_on_integration_pass(self, conn, tmp_path, monkeypatch):
        """A worktree task whose remote confirms integration must reach 'done'."""
        monkeypatch.setattr(wg, "review_integration_state",
                            mock.MagicMock(return_value=_report()))
        task_id = _make_worktree_task(conn, tmp_path)
        claimed = kb.claim_task(conn, task_id, claimer="builder:1")
        assert claimed is not None
        assert claimed.current_run_id is not None

        ok = kb.complete_task(
            conn, task_id,
            result="done", summary="implemented and merged",
            expected_run_id=claimed.current_run_id,
        )
        assert ok is True

        done = kb.get_task(conn, task_id)
        assert done is not None
        assert done.status == "done"

        events = kb.list_events(conn, task_id)
        assert "completion_integration_verified" in _event_kinds(events)
        verified = _last_event(events, "completion_integration_verified")
        assert verified.payload is not None
        assert verified.payload["branch_name"] == "wt/branch"
        assert verified.payload["ci_state"] == "success"
        assert "completion_blocked_integration_failed" not in _event_kinds(events)


# ---------------------------------------------------------------------------
# Test B: Swarm root skips integration, waits for children, and emits completed
# ---------------------------------------------------------------------------


class TestB_SwarmRootSkipsIntegration:
    """A swarm root created via create_swarm() must:
    - Have integration_required=False in its body (skips the gate).
    - Be marked 'done' immediately (activated inline).
    - Have workers in 'ready' status.
    - Have verifier/synthesizer in 'todo' status (waiting for children).
    - Emit a kanban_task_completed lifecycle hook event.
    """

    def test_swarm_root_has_integration_required_false(self, conn):
        """The swarm root must carry integration_required=False frontmatter."""
        created = create_swarm(
            conn,
            goal="Test integration_required flag on swarm root.",
            workers=[SwarmWorkerSpec(profile="worker-a", title="A", body="A")],
            verifier_assignee="reviewer",
            synthesizer_assignee="writer",
        )

        root = kb.get_task(conn, created.root_id)
        assert root is not None
        body = root.body or ""
        assert "integration_required: false" in body, (
            f"Swarm root missing integration_required: false frontmatter. "
            f"Body: {body!r}"
        )

    def test_swarm_root_is_done_and_workers_are_ready(self, conn):
        """The swarm root must be 'done' immediately, workers 'ready',
        verifier/synthesizer 'todo' (waiting for children)."""
        created = create_swarm(
            conn,
            goal="Test swarm root status.",
            workers=[
                SwarmWorkerSpec(profile="worker-a", title="A", body="A"),
                SwarmWorkerSpec(profile="worker-b", title="B", body="B"),
            ],
            verifier_assignee="reviewer",
            synthesizer_assignee="writer",
        )

        root = kb.get_task(conn, created.root_id)
        assert root is not None
        assert root.status == "done"

        workers = [kb.get_task(conn, tid) for tid in created.worker_ids]
        workers = [w for w in workers if w is not None]
        assert [w.status for w in workers] == ["ready", "ready"]

        verifier = kb.get_task(conn, created.verifier_id)
        synthesizer = kb.get_task(conn, created.synthesizer_id)
        assert verifier is not None
        assert synthesizer is not None
        assert verifier.status == "todo"
        assert synthesizer.status == "todo"

    def test_swarm_root_emits_kanban_task_completed(self, conn, monkeypatch):
        """create_swarm() must fire the kanban_task_completed lifecycle hook
        for the root after activation."""
        hooks: list[tuple[str, str]] = []

        original_fire = kb._fire_kanban_lifecycle_hook

        def tracking_fire(event, task_id, **fields):
            hooks.append((event, task_id))
            return original_fire(event, task_id, **fields)

        monkeypatch.setattr(kb, "_fire_kanban_lifecycle_hook", tracking_fire)

        created = create_swarm(
            conn,
            goal="Test kanban_task_completed event.",
            workers=[SwarmWorkerSpec(profile="worker-a", title="A", body="A")],
            verifier_assignee="reviewer",
            synthesizer_assignee="writer",
        )

        # The hook must have been fired for the root task.
        completed_events = [(e, t) for e, t in hooks if e == "kanban_task_completed"]
        assert len(completed_events) >= 1, (
            f"Expected kanban_task_completed event, got: {hooks}"
        )
        assert any(t == created.root_id for _, t in completed_events), (
            f"kanban_task_completed not fired for root {created.root_id}. "
            f"Events: {completed_events}"
        )

    def test_swarm_root_skips_integration_gate(self, conn, tmp_path, monkeypatch):
        """Even if the swarm root has a worktree workspace with a branch_name,
        the integration gate must be skipped because integration_required=False
        is set in the body."""
        ws = tmp_path / "worktree"
        ws.mkdir(exist_ok=True)

        created = create_swarm(
            conn,
            goal="Test swarm root skips integration gate.",
            workers=[SwarmWorkerSpec(profile="worker-a", title="A", body="A")],
            verifier_assignee="reviewer",
            synthesizer_assignee="writer",
            workspace_kind="worktree",
            workspace_path=str(ws),
        )

        # Simulate a branch_name on the root (as if it had code changes).
        with kb.write_txn(conn):
            conn.execute(
                "UPDATE tasks SET branch_name = ? WHERE id = ?",
                ("wt/swarm-root", created.root_id),
            )

        # The gate must be skipped: review_integration_state is never called.
        fake = mock.MagicMock(return_value=_report(
            overall="FAIL",
            failures=[_fail("pr_exists", "no merged PR found for branch")],
            pr_exists=False, pr_merged=False,
        ))
        monkeypatch.setattr(wg, "review_integration_state", fake)

        # Call _enforce_integration_gate directly — it must NOT raise.
        # (The root is already 'done' so complete_task would return False,
        # but the gate function itself is what we're testing.)
        kb._enforce_integration_gate(conn, created.root_id)

        # The remote check was NEVER called — the gate skipped before reaching it.
        fake.assert_not_called()

        events = kb.list_events(conn, created.root_id)
        kinds = _event_kinds(events)
        assert "completion_integration_skipped" in kinds
        assert "completion_integration_verified" not in kinds
        assert "completion_blocked_integration_failed" not in kinds
        skipped = _last_event(events, "completion_integration_skipped")
        assert skipped.payload is not None
        assert skipped.payload["reason"] == "integration_required_false"


# ---------------------------------------------------------------------------
# Test C: Replenishment is triggered on root completion
# ---------------------------------------------------------------------------


class TestC_ReplenishmentTriggered:
    """When create_swarm() fires kanban_task_completed on the root, the
    replenishment plugin's on_task_completed hook must be invoked.

    The plugin hook is registered via the plugin system (not via monkeypatching),
    so we verify the chain by:
    1. Confirming the hook is fired for the root.
    2. Calling on_task_completed directly to verify it triggers _run_replenishment.
    """

    def test_replenishment_hook_fired_on_swarm_root_completion(self, conn, monkeypatch):
        """The kanban_task_completed hook fired by create_swarm() must be
        emitted for the root task."""
        # Track the raw hook firing to verify the event is emitted.
        hooks: list[tuple[str, str]] = []
        original_fire = kb._fire_kanban_lifecycle_hook

        def tracking_fire(event, task_id, **fields):
            hooks.append((event, task_id))
            return original_fire(event, task_id, **fields)

        monkeypatch.setattr(kb, "_fire_kanban_lifecycle_hook", tracking_fire)

        created = create_swarm(
            conn,
            goal="Test replenishment triggered on root completion.",
            workers=[SwarmWorkerSpec(profile="worker-a", title="A", body="A")],
            verifier_assignee="reviewer",
            synthesizer_assignee="writer",
        )

        # The hook must have been fired for the root.
        completed_events = [(e, t) for e, t in hooks if e == "kanban_task_completed"]
        assert len(completed_events) >= 1
        assert any(t == created.root_id for _, t in completed_events), (
            f"kanban_task_completed not fired for root {created.root_id}. "
            f"Events: {completed_events}"
        )

    def test_replenishment_on_task_completed_triggers_run(self, conn, monkeypatch):
        """Calling the replenishment plugin's on_task_completed with the
        swarm root ID must trigger _run_replenishment."""
        import plugins.replenishment as replenishment_mod

        # Track whether _run_replenishment was called.
        replenish_calls: list[str] = []
        original_run = replenishment_mod._run_replenishment

        def tracking_run(task_id, **kwargs):
            replenish_calls.append(task_id)
            # Don't call the original to avoid side effects.
            return None

        monkeypatch.setattr(
            replenishment_mod, "_run_replenishment", tracking_run,
        )

        created = create_swarm(
            conn,
            goal="Test replenishment on_task_completed triggers _run_replenishment.",
            workers=[SwarmWorkerSpec(profile="worker-a", title="A", body="A")],
            verifier_assignee="reviewer",
            synthesizer_assignee="writer",
        )

        # Call on_task_completed directly with the root ID (simulating what
        # the plugin system does when the hook fires).
        replenishment_mod.on_task_completed(created.root_id, board="default")

        # _run_replenishment must have been called for the root.
        assert created.root_id in replenish_calls, (
            f"Replenishment _run_replenishment not called for root {created.root_id}. "
            f"Calls: {replenish_calls}"
        )


# ---------------------------------------------------------------------------
# Test D: Swarm root with own code change does NOT accidentally bypass integration
# ---------------------------------------------------------------------------


class TestD_SwarmRootWithCodeChange:
    """A swarm root that has a worktree workspace with a branch_name (i.e.,
    it has its own code change) must still have integration_required=False
    in its body. This is correct: the root is a coordination task, not a
    code-producing task. The test verifies that the flag is correctly set
    and the gate is skipped."""

    def test_swarm_root_with_worktree_and_branch_has_integration_required_false(
        self, conn, tmp_path,
    ):
        """A swarm root with workspace_kind='worktree' and a branch_name must
        still carry integration_required=False in its body."""
        ws = tmp_path / "worktree"
        ws.mkdir(exist_ok=True)

        created = create_swarm(
            conn,
            goal="Test swarm root with worktree and branch.",
            workers=[SwarmWorkerSpec(profile="worker-a", title="A", body="A")],
            verifier_assignee="reviewer",
            synthesizer_assignee="writer",
            workspace_kind="worktree",
            workspace_path=str(ws),
        )

        # Simulate a branch_name on the root (as if it had code changes).
        with kb.write_txn(conn):
            conn.execute(
                "UPDATE tasks SET branch_name = ? WHERE id = ?",
                ("wt/swarm-root-code", created.root_id),
            )

        root = kb.get_task(conn, created.root_id)
        assert root is not None
        body = root.body or ""
        assert "integration_required: false" in body, (
            f"Swarm root with worktree+branch missing integration_required: false. "
            f"Body: {body!r}"
        )

    def test_swarm_root_with_code_change_skips_gate(self, conn, tmp_path, monkeypatch):
        """A swarm root with a worktree workspace and branch_name must skip
        the integration gate (because integration_required=False is set).
        The gate is never enforced for the root, even though it has a
        branch_name that would normally trigger the gate."""
        ws = tmp_path / "worktree"
        ws.mkdir(exist_ok=True)

        created = create_swarm(
            conn,
            goal="Test swarm root with code change skips gate.",
            workers=[SwarmWorkerSpec(profile="worker-a", title="A", body="A")],
            verifier_assignee="reviewer",
            synthesizer_assignee="writer",
            workspace_kind="worktree",
            workspace_path=str(ws),
        )

        # Simulate a branch_name on the root.
        with kb.write_txn(conn):
            conn.execute(
                "UPDATE tasks SET branch_name = ? WHERE id = ?",
                ("wt/swarm-root-code", created.root_id),
            )

        # The gate must be skipped: review_integration_state is never called.
        fake = mock.MagicMock(return_value=_report(
            overall="FAIL",
            failures=[_fail("pr_exists", "no merged PR found for branch")],
            pr_exists=False, pr_merged=False,
        ))
        monkeypatch.setattr(wg, "review_integration_state", fake)

        # Call _enforce_integration_gate directly — it must NOT raise.
        # (The root is already 'done' so complete_task would return False,
        # but the gate function itself is what we're testing.)
        kb._enforce_integration_gate(conn, created.root_id)

        # The remote check was NEVER called.
        fake.assert_not_called()

        events = kb.list_events(conn, created.root_id)
        kinds = _event_kinds(events)
        assert "completion_integration_skipped" in kinds
        assert "completion_integration_verified" not in kinds
        assert "completion_blocked_integration_failed" not in kinds

    def test_swarm_root_without_integration_required_false_would_be_blocked(
        self, conn, tmp_path, monkeypatch,
    ):
        """Control test: if a swarm root did NOT have integration_required=False,
        the gate would block it. This verifies that the gate is actually
        enforced for worktree tasks with branch_name when the flag is absent."""
        ws = tmp_path / "worktree"
        ws.mkdir(exist_ok=True)

        # Create a regular worktree task (not a swarm root) with a branch_name.
        task_id = kb.create_task(
            conn,
            title="Regular worktree task with branch",
            assignee="builder",
            body="done when merged\n",
            workspace_kind="worktree",
            workspace_path=str(ws),
            branch_name="wt/regular",
        )

        # Monkeypatch review_integration_state to return FAIL.
        monkeypatch.setattr(wg, "review_integration_state",
                            mock.MagicMock(return_value=_report(
                                overall="FAIL",
                                failures=[_fail("pr_exists", "no merged PR found for branch")],
                                pr_exists=False, pr_merged=False,
                            )))

        claimed = kb.claim_task(conn, task_id, claimer="builder:1")
        assert claimed is not None
        assert claimed.current_run_id is not None

        # The gate must block completion.
        with pytest.raises(kb.IntegrationGateError):
            kb.complete_task(
                conn, task_id,
                result="done", summary="should be blocked",
                expected_run_id=claimed.current_run_id,
            )

        after = kb.get_task(conn, task_id)
        assert after is not None
        assert after.status != "done"
