"""Tests for extended stall detection signals in the attention engine.

Tests the multi-signal stall assessment (§5.2 of DESIGN_EXECUTION_PLANNING.md)
and goal attention item construction.
"""

import pytest

from datetime import date, datetime, timezone
from pathlib import Path

from janus.models.attention import AttentionItem
from janus.models.goal import Goal
from janus.models.task import Task
from janus.services.attention import get_attention_items, assess_goal_stall, StallSignal

FIXED_TODAY = date(2026, 8, 28)


def _make_goal(title, status="active", deadline=None, related_tasks=None,
               milestones=None):
    return Goal(
        title=title,
        status=status,
        deadline=deadline,
        related_tasks=related_tasks or [],
        milestones=milestones or [],
    )


def _setup_tasks_file(tmp_path, monkeypatch, content="- [ ] Open task\n"):
    """Set up a tasks.md file so _load_all_task_titles works in tests."""
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
    # Also patch the path used internally by attention.py
    import janus.services.attention as attn
    monkeypatch.setattr(
        "janus.services.attention._load_all_task_titles",
        lambda _: _load_task_titles(tasks_file),
    )


def _load_task_titles(tasks_path):
    """Load all task titles from a tasks.md file (open + completed)."""
    if not tasks_path.exists():
        return set()
    titles = set()
    with tasks_path.open() as f:
        for line in f:
            line = line.strip()
            if line.startswith("- [ ") or line.startswith("- [x]") or line.startswith("- [ ]"):
                content = line[5:].strip()
                title = content.split("|", 1)[0].strip()
                if title:
                    titles.add(title)
    return titles


# =============================================================================
# 1. Deadline signals
# =============================================================================

class TestDeadlineSignals:
    def test_deadline_today_signal(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", deadline="2026-08-28", related_tasks=["Task A"])
        signals = assess_goal_stall(
            goal, FIXED_TODAY, set(), set(),
        )
        signal_names = [s[0].signal for s in signals]
        assert "goal_deadline_today" in signal_names
        today_sig = next(s for s in signals if s[0].signal == "goal_deadline_today")
        assert today_sig[0].score == 90

    def test_deadline_within_7_days_signal(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        # 3 days away
        goal = _make_goal("G", deadline="2026-08-31", related_tasks=["Task A"])
        signals = assess_goal_stall(
            goal, FIXED_TODAY, set(), {"Task A"},
        )
        signal_names = [s[0].signal for s in signals]
        assert "goal_deadline_soon" in signal_names
        soon_sig = next(s for s in signals if s[0].signal == "goal_deadline_soon")
        assert soon_sig[0].score == 60
        assert "3 days" in soon_sig[0].reason

    def test_deadline_far_future_no_signal(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        # 30 days away — not in scope for "soon"
        goal = _make_goal("G", deadline="2026-09-27", related_tasks=[])
        signals = assess_goal_stall(
            goal, FIXED_TODAY, set(), set(),
        )
        signal_names = [s[0].signal for s in signals]
        assert "goal_deadline_soon" not in signal_names

    def test_deadline_overdue_no_open_tasks(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch,
            content="- [x] Task A\n")
        goal = _make_goal("G", deadline="2026-08-25", related_tasks=["Task A"])
        # Task A is completed → no open tasks
        signals = assess_goal_stall(
            goal, FIXED_TODAY, set(), {"Task A"},
        )
        signal_names = [s[0].signal for s in signals]
        assert "goal_overdue" in signal_names
        overdue_sig = next(s for s in signals if s[0].signal == "goal_overdue")
        assert overdue_sig[0].score == 100

    def test_deadline_overdue_with_open_task_no_overdue_signal(self,
            tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch,
            content="- [ ] Task A\n")
        goal = _make_goal("G", deadline="2026-08-25", related_tasks=["Task A"])
        # Task A is open → overdue signal should NOT fire
        signals = assess_goal_stall(
            goal, FIXED_TODAY, {"Task A"}, {"Task A"},
        )
        signal_names = [s[0].signal for s in signals]
        assert "goal_overdue" not in signal_names


# =============================================================================
# 2. Milestone slipped signal
# =============================================================================

class TestMilestoneSlipped:
    def test_milestone_past_deadline_signal(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", related_tasks=[], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-08-25", "status": "open",
            "related_tasks": [], "order": 0,
        }])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), set())
        signal_names = [s[0].signal for s in signals]
        assert "milestone_slipped" in signal_names
        ms_sig = next(s for s in signals if s[0].signal == "milestone_slipped")
        assert ms_sig[0].score == 50

    def test_milestone_completed_no_slipped_signal(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", related_tasks=[], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-08-25", "status": "completed",
            "related_tasks": [], "order": 0,
        }])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), set())
        signal_names = [s[0].signal for s in signals]
        assert "milestone_slipped" not in signal_names


# =============================================================================
# 3. Existing binary stall (fallback)
# =============================================================================

class TestBinaryStallFallback:
    def test_all_tasks_done_no_deadline_no_milestones_stalled(self,
            tmp_path, monkeypatch):
        """The classic case: all tasks completed, no deadline, no milestones."""
        _setup_tasks_file(tmp_path, monkeypatch,
            content="- [x] Task A\n")
        goal = _make_goal("G", related_tasks=["Task A"])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), {"Task A"})
        signal_names = [s[0].signal for s in signals]
        assert "goal_stalled" in signal_names
        stall_sig = next(s for s in signals if s[0].signal == "goal_stalled")
        assert stall_sig[0].score == 40

    def test_all_tasks_done_with_future_deadline_not_stalled(self,
            tmp_path, monkeypatch):
        """Goal with all tasks done but future deadline → NOT goal_stalled.

        Per spec §5.2: a goal with all tasks done but a future deadline is
        'waiting for its next action' — goal_stalled (40) does not fire
        because goal_deadline_soon (60) scores higher.
        """
        _setup_tasks_file(tmp_path, monkeypatch,
            content="- [x] Task A\n")
        goal = _make_goal("G", deadline="2026-08-31",
                          related_tasks=["Task A"])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), {"Task A"})
        signal_names = [s[0].signal for s in signals]
        assert "goal_stalled" not in signal_names
        # deadline_soon should fire instead
        assert "goal_deadline_soon" in signal_names


# =============================================================================
# 3b. Goal inactive signal
# =============================================================================

class TestGoalInactiveSignal:
    def test_goal_inactive_fires_all_done_no_future_milestone(self,
            tmp_path, monkeypatch):
        """All tasks done, no future deadline, no future milestone → goal_inactive."""
        _setup_tasks_file(tmp_path, monkeypatch,
            content="- [x] Task A\n")
        goal = _make_goal("G", related_tasks=["Task A"])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), {"Task A"})
        signal_names = [s[0].signal for s in signals]
        assert "goal_inactive" in signal_names
        inactive_sig = next(s for s in signals if s[0].signal == "goal_inactive")
        assert inactive_sig[0].score == 30

    def test_goal_inactive_does_not_fire_with_future_deadline(self,
            tmp_path, monkeypatch):
        """With a future goal deadline, inactive should not fire."""
        _setup_tasks_file(tmp_path, monkeypatch,
            content="- [x] Task A\n")
        goal = _make_goal("G", deadline="2026-09-15",
                          related_tasks=["Task A"])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), {"Task A"})
        signal_names = [s[0].signal for s in signals]
        assert "goal_inactive" not in signal_names

    def test_goal_inactive_does_not_fire_with_open_milestone(self,
            tmp_path, monkeypatch):
        """With an open milestone (no deadline), inactive should not fire."""
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", related_tasks=[], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": None, "status": "open",
            "related_tasks": [], "order": 0,
        }])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), set())
        signal_names = [s[0].signal for s in signals]
        assert "goal_inactive" not in signal_names


# =============================================================================
# 3c. Milestone deadline soon signal
# =============================================================================

class TestMilestoneDeadlineSoon:
    def test_milestone_deadline_today(self, tmp_path, monkeypatch):
        """Milestone with past deadline and open status → milestone_slipped."""
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", related_tasks=[], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-08-25", "status": "open",
            "related_tasks": [], "order": 0,
        }])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), set())
        signal_names = [s[0].signal for s in signals]
        assert "milestone_slipped" in signal_names
        ms_sig = next(s for s in signals if s[0].signal == "milestone_slipped")
        assert ms_sig[0].score == 50

    def test_milestone_future_deadline_no_signal(self, tmp_path, monkeypatch):
        """Milestone with future deadline → no milestone_slipped signal."""
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", related_tasks=[], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-10-15", "status": "open",
            "related_tasks": [], "order": 0,
        }])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), set())
        signal_names = [s[0].signal for s in signals]
        assert "milestone_slipped" not in signal_names

    def test_milestone_deadline_soon_within_7_days(self, tmp_path, monkeypatch):
        """Milestone with deadline within 7 days (future) → milestone_deadline_soon."""
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", related_tasks=[], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-08-30", "status": "open",
            "related_tasks": [], "order": 0,
        }])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), set())
        signal_names = [s[0].signal for s in signals]
        assert "milestone_deadline_soon" in signal_names
        soon_sig = next(s for s in signals if s[0].signal == "milestone_deadline_soon")
        assert soon_sig[0].score == 55
        assert "2 days" in soon_sig[0].reason
        assert soon_sig[1] == "milestone_deadline_soon"

    def test_milestone_deadline_soon_does_not_fire_when_completed(self, tmp_path, monkeypatch):
        """Milestone with future deadline within 7 days but completed → no signal."""
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", related_tasks=[], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-08-30", "status": "completed",
            "related_tasks": [], "order": 0,
        }])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), set())
        signal_names = [s[0].signal for s in signals]
        assert "milestone_deadline_soon" not in signal_names

    def test_milestone_deadline_soon_not_fired_for_far_future(self, tmp_path, monkeypatch):
        """Milestone with deadline > 7 days away → no milestone_deadline_soon."""
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", related_tasks=[], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-09-10", "status": "open",
            "related_tasks": [], "order": 0,
        }])
        signals = assess_goal_stall(goal, FIXED_TODAY, set(), set())
        signal_names = [s[0].signal for s in signals]
        assert "milestone_deadline_soon" not in signal_names

    def test_milestone_deadline_soon_in_attention_items(self, tmp_path, monkeypatch):
        """Milestone deadline soon appears as an attention item."""
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", related_tasks=[], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-08-30", "status": "open",
            "related_tasks": [], "order": 0,
        }])
        items = get_attention_items([], [], [goal], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].title == "G"
        assert items[0].score == 55
        assert items[0].category == "milestone_deadline_soon"


# =============================================================================
# 4. Goal attention item construction
# =============================================================================

class TestGoalAttentionItems:
    def test_overdue_goal_appears_in_attention(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch,
            content="- [x] Task A\n")
        goal = _make_goal("Overdue goal", deadline="2026-08-25",
                          related_tasks=["Task A"])
        items = get_attention_items([], [], [goal], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].title == "Overdue goal"
        assert items[0].score == 100
        assert items[0].category == "goal_overdue"

    def test_deadline_today_goal_in_attention(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("Due today", deadline="2026-08-28")
        items = get_attention_items([], [], [goal], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].score == 90
        assert items[0].category == "goal_deadline_today"

    def test_milestone_slipped_in_attention(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch, content="")
        goal = _make_goal("G", related_tasks=[], milestones=[{
            "title": "M1", "goal_title": "G", "description": "",
            "deadline": "2026-08-25", "status": "open",
            "related_tasks": [], "order": 0,
        }])
        items = get_attention_items([], [], [goal], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].score == 50
        assert items[0].category == "milestone_slipped"

    def test_goal_with_open_task_not_stalled(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch,
            content="- [ ] Task A\n")
        goal = _make_goal("G", related_tasks=["Task A"])
        open_task = Task(title="Task A", due_date=None, priority=1)
        items = get_attention_items([], [open_task], [goal], FIXED_TODAY)
        assert len(items) == 0

    def test_highest_signal_wins_for_goal(self, tmp_path, monkeypatch):
        """When multiple signals fire, the highest score wins."""
        _setup_tasks_file(tmp_path, monkeypatch,
            content="- [x] Task A\n")
        # Goal with past deadline (overdue=100) AND all tasks done (stalled=40)
        goal = _make_goal("G", deadline="2026-08-20",
                          related_tasks=["Task A"])
        items = get_attention_items([], [], [goal], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].score == 100
        assert items[0].category == "goal_overdue"

    def test_completed_goal_excluded(self, tmp_path, monkeypatch):
        _setup_tasks_file(tmp_path, monkeypatch,
            content="- [x] Task A\n")
        goal = _make_goal("G", status="completed",
                          deadline="2026-08-25", related_tasks=["Task A"])
        items = get_attention_items([], [], [goal], FIXED_TODAY)
        assert len(items) == 0
