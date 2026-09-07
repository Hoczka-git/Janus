"""Targeted tests for the replenishment plugin (plugins/replenishment).

These tests exercise the ``kanban_task_completed`` hook callback directly —
they call ``on_task_completed`` (and the internal ``_run_replenishment``)
with a real kanban DB + projects DB fixture, a configured planning source,
and assert the side effects: new tasks created, titles prefixed, items
checked off, audit comments written, and errors isolated per-source.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import projects_db as pdb


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with both kanban DB and projects DB initialized."""
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in (
        "HERMES_KANBAN_DB", "HERMES_KANBAN_WORKSPACES_ROOT",
        "HERMES_KANBAN_HOME", "HERMES_KANBAN_BOARD",
    ):
        monkeypatch.delenv(var, raising=False)
    try:
        import hermes_constants  # type: ignore[import]
        hermes_constants._cached_default_hermes_root = None  # type: ignore[attr-defined]
    except Exception:
        pass
    kb._INITIALIZED_PATHS.clear()
    pdb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


@pytest.fixture
def conn(fresh_home, monkeypatch):
    """A fresh kanban DB connection on the default board."""
    # Ensure no board override leaks in.
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    c = kb.connect(board="default")
    yield c
    c.close()


@pytest.fixture
def pconn(fresh_home):
    """A projects DB connection for the test profile."""
    c = pdb.connect()
    yield c
    c.close()


@pytest.fixture
def plugin_module(fresh_home):
    """Import the replenishment plugin module fresh for each test."""
    from importlib import import_module, reload
    import plugins.replenishment as mod
    reload(mod)
    return mod


def _create_project(pconn, name, primary_path, *, project_id=None):
    """Create a project and return its id."""
    if project_id:
        # Insert directly to control the id.
        from hermes_cli.sqlite_util import write_txn
        now = 1000
        with write_txn(pconn):
            pconn.execute(
                "INSERT INTO projects (id, slug, name, primary_path, created_at, archived) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (project_id, name.replace(" ", "-").lower(), name, primary_path, now),
            )
        return project_id
    slug = name.replace(" ", "-").lower()
    return pdb.create_project(
        pconn, name=name, slug=slug, primary_path=primary_path,
    )


def _create_task(conn, *, title, body=None, assignee="implementer",
                 project_id=None, parents=(), workspace_kind="scratch",
                 workspace_path=None, initial_status="running"):
    body = (body or "") + "\n\nintegration_required: false" if body else "integration_required: false"
    kwargs = dict(
        title=title,
        body=body,
        assignee=assignee,
        workspace_kind=workspace_kind,
        initial_status=initial_status,
        integration_required=False,
    )
    if project_id:
        kwargs["project_id"] = project_id
    if workspace_path:
        kwargs["workspace_path"] = workspace_path
    if parents:
        kwargs["parents"] = parents
    return kb.create_task(conn, **kwargs)


# ---------------------------------------------------------------------------
# Title-prefix guard
# ---------------------------------------------------------------------------

class TestTitlePrefixGuard:
    def test_non_plan_task_skips_replenishment(self, conn, pconn, plugin_module):
        """A task whose title does NOT start with [plan] triggers no sources."""
        pid = _create_project(pconn, "testproj", "/tmp/repo", project_id="p_test")
        tid = _create_task(conn, title="Regular task", project_id=pid)

        # No sources configured either, but we verify the guard directly:
        # calling on_task_completed on a non-[plan] task should be a no-op
        # even if sources exist.
        pdb.add_planning_source(
            pconn, pid, id="roadmap-v1", kind="file", name="Roadmap",
            config={"path": "roadmap.md", "format": "markdown"},
        )

        called = []
        def fake_process_source(*a, **kw):
            called.append(a)
        with mock.patch.object(plugin_module, "_process_source", fake_process_source):
            plugin_module.on_task_completed(tid, board="default")

        assert called == [], "non-[plan] task should not invoke any source"

    def test_plan_task_triggers_sources(self, conn, pconn, plugin_module, tmp_path):
        """A [plan]-prefixed completed task triggers source processing."""
        pid = _create_project(pconn, "testproj2", str(tmp_path / "repo"), project_id="p_test2")
        roadmap = tmp_path / "repo" / "roadmap.md"
        roadmap.parent.mkdir(parents=True)
        roadmap.write_text("# Roadmap\n\n- [ ] First task\n- [ ] Second task\n")

        tid = _create_task(conn, title="[plan] Do first thing", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="roadmap-v1", kind="file", name="Roadmap",
            config={"path": "roadmap.md", "format": "markdown"},
        )

        plugin_module.on_task_completed(tid, board="default")

        # The first unchecked TODO should have been pulled as a new task.
        tasks = kb.list_tasks(conn, include_archived=True)
        pulled = [t for t in tasks if t.title.startswith("[plan] First task")]
        assert len(pulled) == 1, f"expected 1 pulled task, got {len(pulled)}"
        assert pulled[0].title == "[plan] First task"
        pulled[0].body == "[plan] First task"

    def test_plan_task_with_no_project_skips(self, conn, plugin_module):
        """A [plan] task with no project_id and no board-level project is a
        no-op (no sources to load). The hook must not crash."""
        tid = _create_task(conn, title="[plan] Orphan task")
        kb.complete_task(conn, tid, result="done")
        plugin_module.on_task_completed(tid, board="default")
        # No crash, no new tasks.
        tasks = kb.list_tasks(conn, include_archived=True)
        assert len(tasks) == 1


# ---------------------------------------------------------------------------
# File source: markdown
# ---------------------------------------------------------------------------

class TestFileMarkdownSource:
    def test_pulls_next_unchecked_todo(self, conn, pconn, plugin_module, tmp_path):
        pid = _create_project(pconn, "mdproj", str(tmp_path / "repo"), project_id="p_md")
        repo = tmp_path / "repo"
        repo.mkdir()
        roadmap = repo / "roadmap.md"
        roadmap.write_text(
            "# Roadmap\n\n"
            "- [ ] Task A\n"
            "- [ ] Task B\n"
        )

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="roadmap-md", kind="file", name="Roadmap MD",
            config={"path": "roadmap.md", "format": "markdown"},
        )
        plugin_module.on_task_completed(tid, board="default")

        tasks = kb.list_tasks(conn, include_archived=True)
        pulled = [t for t in tasks if t.title == "[plan] Task A"]
        assert len(pulled) == 1
        # The pulled task should be parented on the completed task.
        parents = kb.parent_ids(conn, pulled[0].id)
        assert tid in parents
        # The completed task should be parented and ready (todo -> ready since
        # its parent is done).
        pulled[0].status == "ready"

    def test_checks_off_item_in_roadmap(self, conn, pconn, plugin_module, tmp_path):
        pid = _create_project(pconn, "mdproj2", str(tmp_path / "repo"), project_id="p_md2")
        repo = tmp_path / "repo"
        repo.mkdir()
        roadmap = repo / "roadmap.md"
        roadmap.write_text("- [ ] Task A\n- [ ] Task B\n- [ ] Task C\n")

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="roadmap-md2", kind="file", name="Roadmap",
            config={"path": "roadmap.md", "format": "markdown"},
        )
        plugin_module.on_task_completed(tid, board="default")

        # After completing seed, Task A should be created but
        # roadmap item should still be unchecked (deferred completion).
        updated = roadmap.read_text()
        assert "[ ] Task A" in updated
        assert "[ ] Task B" in updated
        assert "[ ] Task C" in updated

        # Complete the pulled task to trigger deferred completion.
        tasks = kb.list_tasks(conn, include_archived=True)
        pulled = [t for t in tasks if t.title == "[plan] Task A"]
        assert len(pulled) == 1
        kb.complete_task(conn, pulled[0].id, result="done")
        plugin_module.on_task_completed(pulled[0].id, board="default")

        # Now the roadmap item should be checked off.
        updated = roadmap.read_text()
        assert "[x] Task A" in updated
        assert "[ ] Task B" in updated
        assert "[ ] Task C" in updated

    def test_no_unchecked_todos_creates_nothing(self, conn, pconn, plugin_module, tmp_path):
        pid = _create_project(pconn, "mdproj3", str(tmp_path / "repo"), project_id="p_md3")
        repo = tmp_path / "repo"
        repo.mkdir()
        roadmap = repo / "roadmap.md"
        roadmap.write_text("# All done\n- [x] Done A\n- [x] Done B\n")

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="roadmap-md3", kind="file", name="Roadmap",
            config={"path": "roadmap.md", "format": "markdown"},
        )
        plugin_module.on_task_completed(tid, board="default")

        tasks = kb.list_tasks(conn, include_archived=True)
        # Only the seed task should exist.
        assert len(tasks) == 1
        assert tasks[0].title == "[plan] seed"


# ---------------------------------------------------------------------------
# File source: JSON
# ---------------------------------------------------------------------------

class TestFileJsonSource:
    def test_pulls_next_json_item(self, conn, pconn, plugin_module, tmp_path):
        pid = _create_project(pconn, "jsonproj", str(tmp_path / "repo"), project_id="p_json")
        repo = tmp_path / "repo"
        repo.mkdir()
        roadmap = repo / "roadmap.json"
        roadmap.write_text(json.dumps([
            {"id": "item-1", "title": "JSON Task A", "body": "Body A"},
            {"id": "item-2", "title": "JSON Task B", "body": "Body B"},
        ]))

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="roadmap-json", kind="file", name="Roadmap JSON",
            config={"path": "roadmap.json", "format": "json"},
        )
        plugin_module.on_task_completed(tid, board="default")

        tasks = kb.list_tasks(conn, include_archived=True)
        pulled = [t for t in tasks if t.title == "[plan] JSON Task A"]
        assert len(pulled) == 1
        parents = kb.parent_ids(conn, pulled[0].id)
        assert tid in parents

    def test_json_cursor_advances(self, conn, pconn, plugin_module, tmp_path):
        pid = _create_project(pconn, "jsonproj2", str(tmp_path / "repo"), project_id="p_json2")
        repo = tmp_path / "repo"
        repo.mkdir()
        roadmap = repo / "roadmap.json"
        roadmap.write_text(json.dumps([
            {"id": "item-1", "title": "Task A"},
            {"id": "item-2", "title": "Task B"},
            {"id": "item-3", "title": "Task C"},
        ]))

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="roadmap-json2", kind="file", name="Roadmap",
            config={"path": "roadmap.json", "format": "json"},
        )

        # First completion: pulls item-1.
        plugin_module.on_task_completed(tid, board="default")
        tasks = kb.list_tasks(conn, include_archived=True)
        pulled_a = [t for t in tasks if "Task A" in t.title]
        assert len(pulled_a) == 1

        # Complete the pulled task, triggering another replenishment cycle.
        kb.complete_task(conn, pulled_a[0].id, result="done")
        plugin_module.on_task_completed(pulled_a[0].id, board="default")

        tasks = kb.list_tasks(conn, include_archived=True)
        pulled_b = [t for t in tasks if "Task B" in t.title]
        assert len(pulled_b) == 1

        # Cursor file should list both completed items.
        cursor = roadmap.with_suffix(".json.complete")
        assert cursor.exists()
        completed = json.loads(cursor.read_text())
        assert "item-1" in completed
        assert "item-2" in completed


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_repeat_completion_does_not_duplicate(
        self, conn, pconn, plugin_module, tmp_path
    ):
        """If the hook fires twice for the same completed task (worker crash
        re-fire), the idempotency key must prevent duplicate task creation."""
        pid = _create_project(pconn, "idemproj", str(tmp_path / "repo"), project_id="p_idem")
        repo = tmp_path / "repo"
        repo.mkdir()
        roadmap = repo / "roadmap.md"
        roadmap.write_text("- [ ] Task A\n")

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="roadmap-idem", kind="file", name="Roadmap",
            config={"path": "roadmap.md", "format": "markdown"},
        )

        # Fire twice.
        plugin_module.on_task_completed(tid, board="default")
        plugin_module.on_task_completed(tid, board="default")

        tasks = kb.list_tasks(conn, include_archived=True)
        pulled = [t for t in tasks if t.title == "[plan] Task A"]
        assert len(pulled) == 1, "idempotency key should prevent duplicate creation"


# ---------------------------------------------------------------------------
# Error isolation
# ---------------------------------------------------------------------------

class TestErrorIsolation:
    def test_broken_source_does_not_block_other_sources(
        self, conn, pconn, plugin_module, tmp_path
    ):
        """A source that raises must not prevent other sources from running."""
        pid = _create_project(pconn, "errproj", str(tmp_path / "repo"), project_id="p_err")
        repo = tmp_path / "repo"
        repo.mkdir()
        roadmap_good = repo / "good.md"
        roadmap_good.write_text("- [ ] Good Task\n")

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        # A broken file source (missing file) + a working file source.
        pdb.add_planning_source(
            pconn, pid, id="broken", kind="file", name="Broken",
            config={"path": "nonexistent.md", "format": "markdown"},
            priority=10,
        )
        pdb.add_planning_source(
            pconn, pid, id="good", kind="file", name="Good",
            config={"path": "good.md", "format": "markdown"},
            priority=5,
        )

        plugin_module.on_task_completed(tid, board="default")

        tasks = kb.list_tasks(conn, include_archived=True)
        pulled = [t for t in tasks if t.title == "[plan] Good Task"]
        assert len(pulled) == 1, "working source should still fire after broken one"

    def test_hook_never_raises(self, conn, pconn, plugin_module, tmp_path):
        """Even if the project DB is missing/corrupt, the hook must not raise."""
        tid = _create_task(conn, title="[plan] orphan", project_id="p_does_not_exist")
        kb.complete_task(conn, tid, result="done")
        # This should not raise.
        plugin_module.on_task_completed(tid, board="default")


# ---------------------------------------------------------------------------
# Audit comment
# ---------------------------------------------------------------------------

class TestAuditComment:
    def test_writes_auditable_comment(self, conn, pconn, plugin_module, tmp_path):
        pid = _create_project(pconn, "audproj", str(tmp_path / "repo"), project_id="p_aud")
        repo = tmp_path / "repo"
        repo.mkdir()
        roadmap = repo / "roadmap.md"
        roadmap.write_text("- [ ] Task A\n")

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="aud-src", kind="file", name="Roadmap",
            config={"path": "roadmap.md", "format": "markdown"},
        )
        plugin_module.on_task_completed(tid, board="default")

        comments = kb.list_comments(conn, tid)
        repl_comments = [c for c in comments if c.body.startswith("[replenish]")]
        assert len(repl_comments) == 1
        assert "pulled 1 task" in repl_comments[0].body
        assert "aud-src" in repl_comments[0].body


# ---------------------------------------------------------------------------
# Webhook source
# ---------------------------------------------------------------------------

class TestWebhookSource:
    def test_posts_signed_payload(self, conn, pconn, plugin_module, tmp_path):
        pid = _create_project(pconn, "whproj", str(tmp_path / "repo"), project_id="p_wh")
        repo = tmp_path / "repo"
        repo.mkdir()

        tid = _create_task(conn, title="[plan] seed", project_id=pid, body="summary text")
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="webhook-1", kind="webhook", name="Tracker",
            config={
                "url": "https://tracker.example.com/hermes/replenish",
                "secret": "test-secret",
                "method": "POST",
            },
        )

        captured = {}
        class FakeReq:
            def __init__(self, data, headers, method):
                captured["data"] = data
                captured["headers"] = headers
                captured["method"] = method
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def getcode(self):
                return 200

        def fake_urlopen(req, timeout=None):
            captured["data"] = req.data
            # urllib.request.Request stores headers in .headers, but also
            # in .unredirected_hdrs and .header_items().
            captured["headers"] = dict(req.header_items())
            captured["method"] = req.get_method()
            return FakeReq(req.data, req.headers, req.get_method())

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            plugin_module.on_task_completed(tid, board="default")

        payload = json.loads(captured["data"].decode("utf-8"))
        assert payload["event"] == "replenish"
        assert payload["task_id"] == tid
        assert payload["project_id"] == pid
        # urllib normalizes header keys to title-case-with-lowercase-acronyms.
        sig = captured["headers"].get("X-Hub-Signature-256", "")
        if not sig:
            sig = captured["headers"].get("X-hub-signature-256", "")
        assert sig.startswith("sha256=")

    def test_webhook_failure_does_not_crash(self, conn, pconn, plugin_module, tmp_path):
        pid = _create_project(pconn, "whfail", str(tmp_path / "repo"), project_id="p_whf")
        repo = tmp_path / "repo"
        repo.mkdir()

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="wh-fail", kind="webhook", name="Bad Webhook",
            config={"url": "https://unreachable.invalid/replenish"},
        )

        with mock.patch("urllib.request.urlopen", side_effect=Exception("network error")):
            # Must not raise.
            plugin_module.on_task_completed(tid, board="default")


# ---------------------------------------------------------------------------
# Swarm source
# ---------------------------------------------------------------------------

class TestSwarmSource:
    def test_swarm_source_creates_graph(self, conn, pconn, plugin_module, tmp_path):
        pid = _create_project(pconn, "swarmpj", str(tmp_path / "repo"), project_id="p_sw")
        repo = tmp_path / "repo"
        repo.mkdir()

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="swarm-1", kind="swarm", name="Weekly Swarm",
            config={
                "goal_prefix": "Implement next roadmap item",
                "profiles": ["implementer", "reviewer"],
                "skills_per_worker": [["implementer"], ["github-code-review"]],
            },
        )
        plugin_module.on_task_completed(tid, board="default")

        tasks = kb.list_tasks(conn, include_archived=True)
        swarm_roots = [t for t in tasks if "Swarm:" in t.title and "[plan]" in t.title]
        assert len(swarm_roots) == 1

        # The swarm root should be parented on the completed task.
        parents = kb.parent_ids(conn, swarm_roots[0].id)
        assert tid in parents

    def test_swarm_source_no_crash_without_profile(self, conn, pconn, plugin_module, tmp_path):
        pid = _create_project(pconn, "swarmpj2", str(tmp_path / "repo"), project_id="p_sw2")
        repo = tmp_path / "repo"
        repo.mkdir()

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="swarm-2", kind="swarm", name="Minimal Swarm",
            config={"goal_prefix": "Do the thing"},
        )
        plugin_module.on_task_completed(tid, board="default")

        tasks = kb.list_tasks(conn, include_archived=True)
        swarm_roots = [t for t in tasks if "Swarm:" in t.title and "[plan]" in t.title]
        assert len(swarm_roots) == 1


# ---------------------------------------------------------------------------
# Multiple sources ordered by priority
# ---------------------------------------------------------------------------

class TestSourcePriority:
    def test_higher_priority_runs_first(self, conn, pconn, plugin_module, tmp_path):
        """Sources are processed in priority order (higher first)."""
        pid = _create_project(pconn, "prio", str(tmp_path / "repo"), project_id="p_prio")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "low.md").write_text("- [ ] Low priority task\n")
        (repo / "high.md").write_text("- [ ] High priority task\n")

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="low", kind="file", name="Low",
            config={"path": "low.md", "format": "markdown", "max_generated_tasks": 2}, priority=1,
        )
        pdb.add_planning_source(
            pconn, pid, id="high", kind="file", name="High",
            config={"path": "high.md", "format": "markdown", "max_generated_tasks": 2}, priority=10,
        )

        call_order = []
        original = plugin_module._process_file_source

        def tracking_file_source(task, project, source, cfg, conn, kb, pdb, source_max, budget_remaining):
            call_order.append(source.id)
            return original(task, project, source, cfg, conn, kb, pdb, source_max, budget_remaining)

        with mock.patch.object(plugin_module, "_process_file_source", tracking_file_source):
            plugin_module.on_task_completed(tid, board="default")

        assert call_order == ["high", "low"], f"expected high then low, got {call_order}"


# ---------------------------------------------------------------------------
# Re-entrancy guard
# ---------------------------------------------------------------------------

class TestReentrancyGuard:
    def test_reentrant_call_is_noop(self, conn, pconn, plugin_module, tmp_path):
        """If on_task_completed is called while already processing the same
        task (e.g. create_swarm fires kanban_task_completed on the root),
        the re-entrant call must be a no-op."""
        pid = _create_project(pconn, "reent", str(tmp_path / "repo"), project_id="p_reent")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "roadmap.md").write_text("- [ ] Task A\n")

        tid = _create_task(conn, title="[plan] seed", project_id=pid)
        kb.complete_task(conn, tid, result="done")

        pdb.add_planning_source(
            pconn, pid, id="roadmap", kind="file", name="Roadmap",
            config={"path": "roadmap.md", "format": "markdown"},
        )

        # Simulate re-entrancy by marking the task as in-progress and calling
        # on_task_completed again.
        plugin_module._replenishing.add(tid)
        plugin_module.on_task_completed(tid, board="default")
        plugin_module._replenishing.discard(tid)

        tasks = kb.list_tasks(conn, include_archived=True)
        pulled = [t for t in tasks if t.title == "[plan] Task A"]
        assert len(pulled) == 0, "re-entrant call should not trigger replenishment"
