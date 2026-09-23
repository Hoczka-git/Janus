"""Boundary-case tests for the consolidated goal execution planning extension.

These tests focus on edge conditions around the domain-layer consolidation
(``janus.domain.planning``) and its backward-compatible shim
(``janus.services.next_action``) from PR #213. They cover:

- Empty / null inputs (empty goals, None fields, empty lists)
- Invalid configurations (bad status strings, missing required fields,
  unexpected keys) and that they raise the right error from the right place
- Maximum / minimum values (order extremes, empty task sets, all-terminal
  milestone/project lists)
- State transitions (milestone complete/skip, project terminal, task moves
  between milestones)
- Public API surface parity between the domain module and the shim
  (consolidation regression guard)

These tests exercise ``janus.domain.planning`` directly (the new home of the
engine) and assert that the shim re-exports remain backward compatible.
"""

from datetime import date

import pytest

from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.models.project import Project
from janus.models.task import Task

# Direct domain-layer imports — the consolidation moved the engine here.
from janus.domain.planning import (
    NextAction,
    derive_milestone_task_set,
    derive_milestone_tasks,
    derive_next_action,
    milestone_objs,
    project_objs,
    _first_active_milestone,
)

FIXED_TODAY = date(2026, 8, 28)


# ── Construction helpers ──────────────────────────────────────────


def _make_task(title: str) -> Task:
    return Task(title=title, due_date=None, priority=1)


def _make_goal(title: str, related_tasks=None, milestones=None, projects=None):
    """Build a Goal with all optional fields explicitly defaulted to lists."""
    return Goal(
        title=title,
        status="active",
        related_tasks=related_tasks or [],
        milestones=milestones or [],
        projects=projects or [],
    )


_MS = {"title": "M1", "goal_title": "G", "description": "",
       "deadline": None, "status": "open", "order": 0}


# ── Empty / null inputs ────────────────────────────────────────────

class TestEmptyAndNullInputs:
    """Goal boundaries: empty goals, None fields, empty task/milestone lists."""

    def test_empty_goal_returns_none(self):
        """A goal with no tasks, no milestones, no projects has no next action."""
        goal = _make_goal("G", related_tasks=[], milestones=[], projects=[])
        result = derive_next_action(goal, [], set(), FIXED_TODAY)
        assert result is None

    def test_goal_with_none_milestones_becomes_empty(self):
        """Goal.__post_init__ normalizes ``None`` milestones/projects/related_tasks
        to empty lists (consolidation must not break this default)."""
        goal = Goal(title="G")  # all optional fields default to None
        assert goal.milestones == []
        assert goal.projects == []
        assert goal.related_tasks == []

    def test_goal_with_none_milestones_to_objs_returns_empty(self):
        """milestone_objs / project_objs must handle a Goal whose fields
        were normalized to [] (the parser-emitted None → [] path)."""
        goal = Goal(title="G")
        assert milestone_objs(goal) == []
        assert project_objs(goal) == []

    def test_empty_open_task_set(self):
        """An empty set of open task titles yields no tasks anywhere."""
        goal = _make_goal("G", related_tasks=["T1", "T2"], milestones=[_MS])
        ms = milestone_objs(goal)
        assert derive_milestone_tasks(ms[0], ms, goal, set()) == []
        assert derive_milestone_task_set(ms, goal, set()) == set()

    def test_empty_tasks_list_to_derive_next_action(self):
        """derive_next_action with no open tasks at all (but related tasks
        exist) does not pick a task — it falls through to milestone actions."""
        goal = _make_goal("G", related_tasks=["T1"], milestones=[_MS])
        # No open tasks provided, none completed.
        action = derive_next_action(goal, [], set(), FIXED_TODAY)
        # R3: current open milestone M1 with no open tasks -> milestone action
        assert action is not None
        assert action.kind == "milestone"
        assert action.title == "M1"


# ── Invalid configurations ─────────────────────────────────────────

class TestInvalidConfigurations:
    """Bad states must raise from the model layer or the domain layer,
    not silently produce wrong output."""

    def test_milestone_invalid_status_raises(self):
        """Milestone rejects an unrecognized status at construction."""
        with pytest.raises(ValueError, match="Invalid milestone status"):
            Milestone(title="M", goal_title="G", status="pending")

    def test_milestone_empty_title_raises(self):
        with pytest.raises(ValueError, match="Milestone title must not be empty"):
            Milestone(title="", goal_title="G")

    def test_milestone_none_title_raises(self):
        with pytest.raises((ValueError, TypeError)):
            Milestone(title=None, goal_title="G")  # type: ignore[arg-type]

    def test_goal_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid goal status"):
            Goal(title="G", status="bogus")

    def test_goal_empty_title_raises(self):
        with pytest.raises(ValueError, match="Goal title must not be empty"):
            Goal(title="   ")

    def test_project_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid project status"):
            Project(title="P", milestone_title="M", status="pending")

    def test_project_empty_milestone_title_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            Project(title="P", milestone_title="")

    def test_milestone_objs_missing_title_raises_typeerror(self):
        """A milestone dict without a 'title' key cannot construct a Milestone
        — it surfaces as a TypeError (positional argument missing)."""
        goal = _make_goal("G", milestones=[{"goal_title": "G", "status": "open", "order": 0}])
        with pytest.raises(TypeError):
            milestone_objs(goal)

    def test_milestone_objs_missing_goal_title_raises_typeerror(self):
        """A milestone dict without 'goal_title' cannot construct a Milestone."""
        goal = _make_goal("G", milestones=[{"title": "M1", "status": "open", "order": 0}])
        with pytest.raises(TypeError):
            milestone_objs(goal)

    def test_milestone_objs_unexpected_key_raises_typeerror(self):
        """milestone_objs passes dict contents as kwargs to Milestone, so
        unknown keys are NOT silently ignored (they become a TypeError).

        This is a consolidation boundary: the engine consumes dicts emitted by
        the markdown parser, so callers must be aware that extraneous keys
        crash here rather than being filtered.
        """
        goal = _make_goal("G", milestones=[{
            "title": "M1", "goal_title": "G", "status": "open", "order": 0,
            "extra": "surprise",
        }])
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            milestone_objs(goal)

    def test_project_objs_missing_title_raises(self):
        """A project dict without 'title' raises (Project enforces non-empty)."""
        goal = _make_goal("G", projects=[{"milestone_title": "M1"}])
        with pytest.raises((KeyError, ValueError)):
            project_objs(goal)


# ── Maximum / minimum values ─────────────────────────────────────

class TestMinMaxValues:
    """Boundary values: single-element lists, all-terminal sets, order=0."""

    def test_single_active_milestone(self):
        goal = _make_goal("G", related_tasks=["T1"], milestones=[_MS])
        action = derive_next_action(goal, [_make_task("T1")], set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "task"
        assert action.title == "T1"
        assert "M1" in action.reason

    def test_single_completed_milestone_no_open_task(self):
        """All milestones terminal + the only related task not open → None."""
        goal = _make_goal("G", related_tasks=["T1"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "", "deadline": None,
             "status": "completed", "order": 0}])
        # T1 is related but neither open nor completed -> R5 None
        action = derive_next_action(goal, [], set(), FIXED_TODAY)
        assert action is None

    def test_all_projects_terminal_returns_none(self):
        """Every project is terminal and no milestones are actionable → None."""
        goal = _make_goal("G", milestones=[
            {"title": "M1", "goal_title": "G", "status": "completed", "order": 0}])
        projs = [Project(title="P1", milestone_title="M1", status="completed")]
        action = derive_next_action(goal, [], set(), FIXED_TODAY, projects=projs)
        assert action is None

    def test_min_order_value(self):
        """order=0 is the minimum; the first milestone in sequence uses it."""
        goal = _make_goal("G", milestones=[
            {"title": "M1", "goal_title": "G", "status": "open", "order": 0}])
        ms = milestone_objs(goal)
        assert ms[0].order == 0
        active = _first_active_milestone(ms)
        assert active is not None
        assert active.title == "M1"


# ── State transitions ──────────────────────────────────────────────

class TestStateTransitions:
    """Milestone/project lifecycle transitions must re-derive membership."""

    def test_task_moves_when_milestone_completed(self):
        """When M1 completes, the shared task dynamically moves to M2."""
        g_open = _make_goal("G", related_tasks=["T1"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "", "deadline": None,
             "status": "open", "order": 0},
            {"title": "M2", "goal_title": "G", "description": "", "deadline": None,
             "status": "open", "order": 1}])
        action = derive_next_action(g_open, [_make_task("T1")], set(), FIXED_TODAY)
        assert action is not None
        assert "M1" in action.reason

        # Transition: M1 -> completed
        g_done = _make_goal("G", related_tasks=["T1"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "", "deadline": None,
             "status": "completed", "order": 0},
            {"title": "M2", "goal_title": "G", "description": "", "deadline": None,
             "status": "open", "order": 1}])
        action2 = derive_next_action(g_done, [_make_task("T1")], set(), FIXED_TODAY)
        assert action2 is not None
        assert "M2" in action2.reason
        assert action2.title == "T1"

    def test_task_moves_when_milestone_skipped(self):
        """A skipped milestone is terminal — tasks move to the next."""
        g = _make_goal("G", related_tasks=["T1"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "", "deadline": None,
             "status": "skipped", "order": 0},
            {"title": "M2", "goal_title": "G", "description": "", "deadline": None,
             "status": "open", "order": 1}])
        action = derive_next_action(g, [_make_task("T1")], set(), FIXED_TODAY)
        assert action is not None
        assert "M2" in action.reason

    def test_in_progress_milestone_is_current(self):
        """in_progress milestones are treated as non-terminal (current)."""
        g = _make_goal("G", related_tasks=["T1"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "", "deadline": None,
             "status": "in_progress", "order": 0}])
        action = derive_next_action(g, [_make_task("T1")], set(), FIXED_TODAY)
        assert action is not None
        assert action.kind == "task"
        assert "M1" in action.reason

    def test_project_completion_shifts_next_action(self):
        """When a project completes (terminal), P1 falls to P3 / P2."""
        g = _make_goal("G", related_tasks=["T1", "T2"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "", "deadline": None,
             "status": "open", "order": 0}])
        active = [Project(title="P1", milestone_title="M1", related_tasks=["T1"], status="active")]

        # P1 active with open task T1 -> P1 returns T1
        action = derive_next_action(g, [_make_task("T1"), _make_task("T2")], set(),
                                    FIXED_TODAY, projects=active)
        assert action.kind == "task"
        assert action.title == "T1"

        # Transition: P1 -> completed. Now T1 is assigned to a terminal project
        # and excluded from P2; T2 (unassigned) is in the current milestone.
        completed = [Project(title="P1", milestone_title="M1", related_tasks=["T1"],
                             status="completed")]
        action2 = derive_next_action(g, [_make_task("T1"), _make_task("T2")], set(),
                                     FIXED_TODAY, projects=completed)
        assert action2 is not None
        assert action2.title == "T2"
        assert action2.kind == "task"
        assert "M1" in action2.reason

    def test_all_milestones_terminal_no_open_tasks(self):
        """Full transition: all milestones done, no open tasks → None (R5)."""
        g = _make_goal("G", related_tasks=["T1"], milestones=[
            {"title": "M1", "goal_title": "G", "description": "", "deadline": None,
             "status": "completed", "order": 0},
            {"title": "M2", "goal_title": "G", "description": "", "deadline": None,
             "status": "completed", "order": 1}])
        action = derive_next_action(g, [], {"T1"}, FIXED_TODAY)
        assert action is None


# ── Consolidation regression guard ────────────────────────────────

class TestConsolidationShimParity:
    """The consolidation moved logic to ``janus.domain.planning`` and left
    ``janus.services.next_action`` as a re-export shim. Both import paths and
    the private aliases must resolve to the same callables so existing
    consumers/tests don't break."""

    def test_shim_reexports_domain_functions(self):
        """services.next_action.derive_next_action is the SAME function object
        as domain.planning.derive_next_action (not a copy)."""
        from janus.services.next_action import (
            derive_next_action as shim_derive,
            derive_next_action as shim_next,
            derive_milestone_tasks as shim_dmt,
            derive_milestone_task_set as shim_dmts,
            milestone_objs as shim_mo,
            project_objs as shim_po,
        )
        assert shim_derive is derive_next_action
        assert shim_dmt is derive_milestone_tasks
        assert shim_dmts is derive_milestone_task_set
        assert shim_mo is milestone_objs
        assert shim_po is project_objs

    def test_shim_private_aliases_resolve_to_public(self):
        """The legacy private aliases (_milestone_objs, _project_objs) must
        point at the public domain functions so old test imports keep working."""
        from janus.services.next_action import _milestone_objs, _project_objs
        assert _milestone_objs is milestone_objs
        assert _project_objs is project_objs

    def test_shim_exports_next_action_via_star_dunder_all(self):
        """__all__ on the shim must expose the public API."""
        import janus.services.next_action as shim
        for name in ("NextAction", "derive_next_action",
                     "derive_milestone_tasks", "derive_milestone_task_set"):
            assert name in shim.__all__
            assert hasattr(shim, name)

    def test_domain_package_public_api(self):
        """janus.domain.__init__ must re-export the engine's public API."""
        from janus.domain import (
            NextAction as domain_NA,
            derive_next_action as domain_dna,
            derive_milestone_tasks as domain_dmt,
            derive_milestone_task_set as domain_dmts,
            milestone_objs as domain_mo,
            project_objs as domain_po,
        )
        assert domain_NA is NextAction
        assert domain_dna is derive_next_action
        assert domain_dmt is derive_milestone_tasks
        assert domain_dmts is derive_milestone_task_set
        assert domain_mo is milestone_objs
        assert domain_po is project_objs

    def test_shim_and_domain_produce_identical_results(self):
        """A behavioral parity check: calling via the shim path and the
        domain path must yield identical NextAction values for the same input."""
        from janus.services.next_action import derive_next_action as shim_dna
        from janus.services.next_action import _project_objs, _milestone_objs

        goal = _make_goal("G", related_tasks=["T1", "T2"], milestones=[{
            "title": "M1", "goal_title": "G", "description": "", "deadline": None,
            "status": "open", "order": 0,
            # legacy related_tasks key that must be filtered out
            "related_tasks": ["T1"],
        }])
        tasks = [_make_task("T1"), _make_task("T2")]

        via_shim = shim_dna(goal, tasks, set(), FIXED_TODAY)
        via_domain = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert via_shim == via_domain
        assert via_shim is not None
        assert via_shim.title == "T1"

        # Helper parity too.
        assert _milestone_objs(goal) == milestone_objs(goal)
        assert _project_objs(goal) == project_objs(goal)

    def test_legacy_milestone_related_tasks_key_is_filtered(self):
        """Consolidation boundary: old milestone dicts may carry a
        ``related_tasks`` key (legacy stored membership). It must be stripped
        before constructing Milestone objects so the derived-membership model
        (which ignores stored task lists) is preserved."""
        goal = _make_goal("G", related_tasks=["T1"], milestones=[{
            "title": "M1", "goal_title": "G", "description": "", "deadline": None,
            "status": "open", "order": 0,
            "related_tasks": ["T1", "T2"],  # legacy — must be ignored
        }])
        mss = milestone_objs(goal)
        assert len(mss) == 1
        assert not hasattr(mss[0], "related_tasks")


# ── Ordering and deduplication ────────────────────────────────────

class TestOrderingAndDedup:
    """The consolidation preserves ordering and dedup invariants."""

    def test_milestones_sorted_by_order(self):
        goal = _make_goal("G", milestones=[
            {"title": "C", "goal_title": "G", "status": "open", "order": 2},
            {"title": "A", "goal_title": "G", "status": "open", "order": 0},
            {"title": "B", "goal_title": "G", "status": "open", "order": 1},
        ])
        titles = [m.title for m in milestone_objs(goal)]
        assert titles == ["A", "B", "C"]

    def test_projects_sorted_by_order_then_title(self):
        goal = _make_goal("G", projects=[
            {"title": "Z", "milestone_title": "M", "order": 1},
            {"title": "A", "milestone_title": "M", "order": 0},
            {"title": "B", "milestone_title": "M", "order": 0},
        ])
        projs = project_objs(goal)
        # order 0: A before B (title tie-break), then order 1: Z
        assert [p.title for p in projs] == ["A", "B", "Z"]

    def test_duplicate_order_milestones_preserve_input_order(self):
        """Same order value → stable sort keeps input sequence."""
        goal = _make_goal("G", milestones=[
            {"title": "M1", "goal_title": "G", "status": "open", "order": 0},
            {"title": "M2", "goal_title": "G", "status": "open", "order": 0},
        ])
        titles = [m.title for m in milestone_objs(goal)]
        assert titles == ["M1", "M2"]

    def test_project_related_tasks_deduped(self):
        projs = project_objs(_make_goal("G", projects=[{
            "title": "P1", "milestone_title": "M1",
            "related_tasks": ["T", "T", "U"]
        }]))
        assert projs[0].related_tasks == ["T", "U"]

    def test_related_tasks_order_preserved_in_derive(self):
        """derive_next_action picks the first open task by goal.related_tasks
        order, not by the order tasks are supplied."""
        goal = _make_goal("G", related_tasks=["Zeta", "Alpha", "Beta"])
        tasks = [_make_task("Alpha"), _make_task("Beta"), _make_task("Zeta")]
        action = derive_next_action(goal, tasks, set(), FIXED_TODAY)
        assert action is not None
        assert action.title == "Zeta"

    def test_duplicate_task_titles_collapsed(self):
        """Duplicate Task objects in the open list collapse to one title in
        the open-title set — no error, deterministic result."""
        goal = _make_goal("G", related_tasks=["T1"], milestones=[_MS])
        dups = [_make_task("T1"), _make_task("T1")]
        action = derive_next_action(goal, dups, set(), FIXED_TODAY)
        assert action is not None
        assert action.title == "T1"


# ── NextAction dataclass edge cases ───────────────────────────────

class TestNextActionDataclass:
    def test_score_defaults_to_zero(self):
        a = NextAction(title="X", kind="task", reason="r", goal_title="G")
        assert a.score == 0

    def test_all_fields_set(self):
        a = NextAction(title="X", kind="project", reason="r",
                       goal_title="G", score=7)
        assert a.title == "X"
        assert a.kind == "project"
        assert a.reason == "r"
        assert a.goal_title == "G"
        assert a.score == 7

    def test_valid_kinds_are_not_restricted(self):
        """The NextAction dataclass itself does not validate ``kind`` — any
        string is accepted (consumers are responsible for valid values)."""
        a = NextAction(title="X", kind="anything", reason="r", goal_title="G")
        assert a.kind == "anything"


# ── Derive milestone tasks boundaries ─────────────────────────────

class TestDeriveMilestoneTasksBoundaries:
    """Direct tests for derive_milestone_tasks edge behaviour."""

    def test_no_non_terminal_milestone_returns_empty(self):
        m = Milestone(title="M1", goal_title="G", status="completed", order=0)
        goal = _make_goal("G", related_tasks=["T1"])
        assert derive_milestone_tasks(m, [m], goal, {"T1"}) == []

    def test_empty_all_milestones_returns_empty(self):
        m = Milestone(title="M1", goal_title="G")
        goal = _make_goal("G", related_tasks=["T1"])
        assert derive_milestone_tasks(m, [], goal, {"T1"}) == []

    def test_only_open_tasks_returned(self):
        """Closed related tasks (in related_tasks but not open) are excluded."""
        m = Milestone(title="M1", goal_title="G", status="open", order=0)
        goal = _make_goal("G", related_tasks=["Open", "Closed"])
        result = derive_milestone_tasks(m, [m], goal, {"Open"})
        assert result == ["Open"]

    def test_related_tasks_order_preserved(self):
        m = Milestone(title="M1", goal_title="G", status="open", order=0)
        goal = _make_goal("G", related_tasks=["Zeta", "Alpha", "Beta"])
        result = derive_milestone_tasks(m, [m], goal, {"Zeta", "Alpha", "Beta"})
        assert result == ["Zeta", "Alpha", "Beta"]

    def test_task_set_empty_when_all_milestones_terminal(self):
        m = Milestone(title="M1", goal_title="G", status="completed", order=0)
        goal = _make_goal("G", related_tasks=["T1"])
        assert derive_milestone_task_set([m], goal, {"T1"}) == set()

    def test_task_set_empty_when_no_milestones(self):
        goal = _make_goal("G", related_tasks=["T1"])
        assert derive_milestone_task_set([], goal, {"T1"}) == set()

    def test_task_set_returns_active_milestone_tasks(self):
        m = Milestone(title="M1", goal_title="G", status="open", order=0)
        goal = _make_goal("G", related_tasks=["T1", "T2"])
        result = derive_milestone_task_set([m], goal, {"T1", "T2"})
        assert result == {"T1", "T2"}
