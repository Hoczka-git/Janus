"""Tests for mutation guardrails in the Action Proposal Engine V1.

These tests verify that the proposal engine cannot modify tasks,
goals, or calendar entries. They cover:

- MutationBlockedError
- MutationGuard (runtime interception)
- ProposalOnlyEngine (sealed wrapper)
- ImportGuard (static import checking)
- proposal_only decorator
- proposal_only_context
- All three protected domains (task, goal, calendar)
- Zero write access verification
"""

from __future__ import annotations

import pytest

from janus.models.policy import RiskLevel
from janus.planner.models import (
    PlannedTask,
    PlanningContext,
    PlanningRisk,
    PlanningSignals,
    Priority,
    PriorityEntry,
    RiskSeverity,
    WeeklyPlan,
)
from janus.proposal import (
    ActionProposal,
    ActionProposalEngine,
    ActionType,
    ImportGuard,
    MutationBlockedError,
    MutationGuard,
    ProposalOnlyEngine,
    ProposalStatus,
    proposal_only,
    proposal_only_context,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


class MockEngine:
    """A mock proposal engine for testing."""

    def generate(
        self,
        plan: WeeklyPlan,
        context: PlanningContext,
    ) -> list[ActionProposal]:
        return [
            ActionProposal(
                action_type=ActionType.CREATE_TASK,
                reason="Test proposal",
                source="test",
            )
        ]

    # Mutation methods that should be blocked
    def create_task(self, title: str) -> None:
        pass

    def update_task(self, task_id: str, **kwargs: object) -> None:
        pass

    def delete_task(self, task_id: str) -> None:
        pass

    def modify_goal(self, goal_id: str, **kwargs: object) -> None:
        pass

    def create_calendar_event(self, title: str, **kwargs: object) -> None:
        pass

    def execute(self) -> None:
        pass

    def apply(self) -> None:
        pass

    def validate(self) -> bool:
        return True


def _make_plan() -> WeeklyPlan:
    return WeeklyPlan(week_summary="Test week")


def _make_context() -> PlanningContext:
    return PlanningContext(goals=[], tasks=[], calendar=[])


# ── MutationBlockedError ─────────────────────────────────────────────────────


class TestMutationBlockedError:
    def test_is_runtime_error(self) -> None:
        assert issubclass(MutationBlockedError, RuntimeError)

    def test_has_domain(self) -> None:
        err = MutationBlockedError("test", domain="task")
        assert err.domain == "task"
        assert "test" in str(err)

    def test_domain_optional(self) -> None:
        err = MutationBlockedError("test")
        assert err.domain is None


# ── Mutation detection ───────────────────────────────────────────────────────


class TestMutationDetection:
    def test_is_mutation_method_task(self) -> None:
        assert MutationGuard.__module__  # sanity
        from janus.proposal.guard import is_mutation_method
        assert is_mutation_method("create_task")
        assert is_mutation_method("update_task")
        assert is_mutation_method("delete_task")
        assert is_mutation_method("complete_task")

    def test_is_mutation_method_goal(self) -> None:
        from janus.proposal.guard import is_mutation_method
        assert is_mutation_method("create_goal")
        assert is_mutation_method("update_goal")
        assert is_mutation_method("delete_goal")
        assert is_mutation_method("modify_goal")

    def test_is_mutation_method_calendar(self) -> None:
        from janus.proposal.guard import is_mutation_method
        assert is_mutation_method("create_calendar_event")
        assert is_mutation_method("update_calendar_event")
        assert is_mutation_method("delete_calendar_event")
        assert is_mutation_method("add_event")
        assert is_mutation_method("remove_event")

    def test_is_mutation_method_generic(self) -> None:
        from janus.proposal.guard import is_mutation_method
        assert is_mutation_method("execute")
        assert is_mutation_method("apply")
        assert is_mutation_method("mutate")
        assert is_mutation_method("write")
        assert is_mutation_method("save")
        assert is_mutation_method("persist")

    def test_is_not_mutation_method(self) -> None:
        from janus.proposal.guard import is_mutation_method
        assert not is_mutation_method("generate")
        assert not is_mutation_method("to_dict")
        assert not is_mutation_method("from_dict")
        assert not is_mutation_method("is_actionable")

    def test_get_mutation_domain_task(self) -> None:
        from janus.proposal.guard import get_mutation_domain
        assert get_mutation_domain("create_task") == "task"
        assert get_mutation_domain("update_task") == "task"

    def test_get_mutation_domain_goal(self) -> None:
        from janus.proposal.guard import get_mutation_domain
        assert get_mutation_domain("modify_goal") == "goal"
        assert get_mutation_domain("delete_goal") == "goal"

    def test_get_mutation_domain_calendar(self) -> None:
        from janus.proposal.guard import get_mutation_domain
        assert get_mutation_domain("create_calendar_event") == "calendar"
        assert get_mutation_domain("delete_event") == "calendar"

    def test_get_mutation_domain_none(self) -> None:
        from janus.proposal.guard import get_mutation_domain
        assert get_mutation_domain("execute") is None
        assert get_mutation_domain("apply") is None


# ── MutationGuard ────────────────────────────────────────────────────────────


class TestMutationGuard:
    def test_generate_works(self) -> None:
        engine = MockEngine()
        guard = MutationGuard(engine)
        plan = _make_plan()
        ctx = _make_context()
        proposals = guard.generate(plan, ctx)
        assert len(proposals) == 1
        assert proposals[0].action_type == ActionType.CREATE_TASK

    def test_blocks_create_task(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError, match="create_task"):
            guard.create_task("test")

    def test_blocks_update_task(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError, match="update_task"):
            guard.update_task("task-1")

    def test_blocks_delete_task(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError, match="delete_task"):
            guard.delete_task("task-1")

    def test_blocks_modify_goal(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError, match="modify_goal"):
            guard.modify_goal("goal-1")

    def test_blocks_create_calendar_event(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError, match="create_calendar_event"):
            guard.create_calendar_event("event-1")

    def test_blocks_execute(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError, match="execute"):
            guard.execute()

    def test_blocks_apply(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError, match="apply"):
            guard.apply()

    def test_blocks_callable_attribute(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError, match="blocked"):
            _ = guard.validate

    def test_domain_in_error(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError) as exc_info:
            guard.create_task("test")
        assert exc_info.value.domain == "task"

    def test_domain_in_error_goal(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError) as exc_info:
            guard.modify_goal("goal-1")
        assert exc_info.value.domain == "goal"

    def test_domain_in_error_calendar(self) -> None:
        guard = MutationGuard(MockEngine())
        with pytest.raises(MutationBlockedError) as exc_info:
            guard.create_calendar_event("event-1")
        assert exc_info.value.domain == "calendar"


# ── ProposalOnlyEngine ───────────────────────────────────────────────────────


class TestProposalOnlyEngine:
    def test_generate_works(self) -> None:
        engine = MockEngine()
        sealed = ProposalOnlyEngine(engine)
        plan = _make_plan()
        ctx = _make_context()
        proposals = sealed.generate(plan, ctx)
        assert len(proposals) == 1
        assert proposals[0].action_type == ActionType.CREATE_TASK

    def test_blocks_create_task(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="create_task"):
            sealed.create_task("test")

    def test_blocks_update_task(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="update_task"):
            sealed.update_task("task-1")

    def test_blocks_delete_task(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="delete_task"):
            sealed.delete_task("task-1")

    def test_blocks_modify_goal(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="modify_goal"):
            sealed.modify_goal("goal-1")

    def test_blocks_create_calendar_event(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="create_calendar_event"):
            sealed.create_calendar_event("event-1")

    def test_blocks_execute(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="execute"):
            sealed.execute()

    def test_blocks_apply(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="apply"):
            sealed.apply()

    def test_blocks_mutate(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="mutate"):
            sealed.mutate()

    def test_blocks_write(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="write"):
            sealed.write()

    def test_blocks_save(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="save"):
            sealed.save()

    def test_blocks_persist(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="persist"):
            sealed.persist()

    def test_blocks_unknown_attribute(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="blocked"):
            _ = sealed.unknown_attribute

    def test_blocks_setattr(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="immutable"):
            sealed.anything = "value"

    def test_blocks_delattr(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError, match="immutable"):
            del sealed.anything

    def test_domain_in_error_task(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError) as exc_info:
            sealed.create_task("test")
        assert exc_info.value.domain == "task"

    def test_domain_in_error_goal(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError) as exc_info:
            sealed.modify_goal("goal-1")
        assert exc_info.value.domain == "goal"

    def test_domain_in_error_calendar(self) -> None:
        sealed = ProposalOnlyEngine(MockEngine())
        with pytest.raises(MutationBlockedError) as exc_info:
            sealed.create_calendar_event("event-1")
        assert exc_info.value.domain == "calendar"

    def test_only_generate_accessible(self) -> None:
        """Verify that only generate is accessible on the sealed engine."""
        sealed = ProposalOnlyEngine(MockEngine())
        # generate should work
        assert hasattr(sealed, "generate")
        assert callable(sealed.generate)

        # These should all be blocked
        blocked_attrs = [
            "create_task", "update_task", "delete_task",
            "modify_goal", "create_goal", "update_goal", "delete_goal",
            "create_calendar_event", "update_calendar_event", "delete_calendar_event",
            "execute", "apply", "mutate", "write", "save", "persist",
        ]
        for attr in blocked_attrs:
            with pytest.raises(MutationBlockedError):
                getattr(sealed, attr)


# ── ImportGuard ──────────────────────────────────────────────────────────────


class TestImportGuard:
    def test_check_imports_returns_list(self) -> None:
        violations = ImportGuard.check_imports()
        assert isinstance(violations, list)

    def test_no_violations_in_proposal_package(self) -> None:
        """The proposal package should have no write-access imports."""
        violations = ImportGuard.check_imports()
        assert violations == [], f"Unexpected violations: {violations}"

    def test_assert_no_write_access_passes(self) -> None:
        """Should not raise if no violations."""
        ImportGuard.assert_no_write_access()

    def test_forbidden_imports_defined(self) -> None:
        from janus.proposal.guard import FORBIDDEN_IMPORT_ROOTS
        assert "janus.tasks_cli" in FORBIDDEN_IMPORT_ROOTS
        assert "janus.goals_cli" in FORBIDDEN_IMPORT_ROOTS
        assert "janus.integrations.google_calendar" in FORBIDDEN_IMPORT_ROOTS


# ── proposal_only decorator ─────────────────────────────────────────────────


class TestProposalOnlyDecorator:
    def test_decorator_allows_generate(self) -> None:
        @proposal_only
        def process(engine: object, plan: WeeklyPlan, ctx: PlanningContext) -> list[ActionProposal]:
            return engine.generate(plan, ctx)  # type: ignore[attr-defined]

        engine = MockEngine()
        plan = _make_plan()
        ctx = _make_context()
        proposals = process(engine, plan, ctx)
        assert len(proposals) == 1

    def test_decorator_blocks_mutation(self) -> None:
        @proposal_only
        def process(engine: object, plan: WeeklyPlan, ctx: PlanningContext) -> None:
            engine.create_task("test")  # type: ignore[attr-defined]

        engine = MockEngine()
        plan = _make_plan()
        ctx = _make_context()
        with pytest.raises(MutationBlockedError, match="create_task"):
            process(engine, plan, ctx)


# ── proposal_only_context ────────────────────────────────────────────────────


class TestProposalOnlyContext:
    def test_context_allows_generate(self) -> None:
        engine = MockEngine()
        plan = _make_plan()
        ctx = _make_context()
        with proposal_only_context(engine) as safe_engine:
            proposals = safe_engine.generate(plan, ctx)
            assert len(proposals) == 1

    def test_context_blocks_mutation(self) -> None:
        engine = MockEngine()
        with proposal_only_context(engine) as safe_engine:
            with pytest.raises(MutationBlockedError):
                safe_engine.create_task("test")


# ── Zero write access verification ───────────────────────────────────────────


class TestZeroWriteAccess:
    def test_proposal_model_no_mutation_methods(self) -> None:
        """ActionProposal must not expose mutation methods."""
        ap = ActionProposal(reason="test")
        mutation_methods = [
            "execute", "apply", "mutate", "create_task", "update_task",
            "delete_task", "modify_goal", "create_calendar_event", "write",
            "save", "persist", "commit", "sync",
        ]
        for method in mutation_methods:
            assert not hasattr(ap, method), f"ActionProposal has mutation method: {method}"

    def test_engine_protocol_no_mutation_methods(self) -> None:
        """ActionProposalEngine protocol must not expose mutation methods."""
        mutation_methods = [
            "execute", "apply", "mutate", "create_task", "update_task",
            "delete_task", "modify_goal", "create_calendar_event", "write",
            "save", "persist", "commit", "sync",
        ]
        for method in mutation_methods:
            assert not hasattr(ActionProposalEngine, method), (
                f"ActionProposalEngine has mutation method: {method}"
            )

    def test_proposal_package_no_write_imports(self) -> None:
        """The proposal package must not import write-access modules."""
        violations = ImportGuard.check_imports()
        assert violations == []

    def test_all_three_domains_protected(self) -> None:
        """Verify guardrails cover task, goal, and calendar domains."""
        from janus.proposal.guard import PROTECTED_DOMAINS
        assert "task" in PROTECTED_DOMAINS
        assert "goal" in PROTECTED_DOMAINS
        assert "calendar" in PROTECTED_DOMAINS

    def test_mutation_patterns_cover_all_domains(self) -> None:
        """Verify mutation patterns cover all three domains."""
        from janus.proposal.guard import MUTATION_METHOD_PATTERNS
        patterns_str = " ".join(MUTATION_METHOD_PATTERNS)
        assert "task" in patterns_str
        assert "goal" in patterns_str
        assert "calendar" in patterns_str
        assert "event" in patterns_str

    def test_sealed_engine_blocks_all_domains(self) -> None:
        """ProposalOnlyEngine blocks mutations for all three domains."""
        sealed = ProposalOnlyEngine(MockEngine())

        # Task domain
        with pytest.raises(MutationBlockedError):
            sealed.create_task("test")
        with pytest.raises(MutationBlockedError):
            sealed.update_task("task-1")
        with pytest.raises(MutationBlockedError):
            sealed.delete_task("task-1")

        # Goal domain
        with pytest.raises(MutationBlockedError):
            sealed.create_goal("test")
        with pytest.raises(MutationBlockedError):
            sealed.update_goal("goal-1")
        with pytest.raises(MutationBlockedError):
            sealed.delete_goal("goal-1")
        with pytest.raises(MutationBlockedError):
            sealed.modify_goal("goal-1")

        # Calendar domain
        with pytest.raises(MutationBlockedError):
            sealed.create_calendar_event("event-1")
        with pytest.raises(MutationBlockedError):
            sealed.update_calendar_event("event-1")
        with pytest.raises(MutationBlockedError):
            sealed.delete_calendar_event("event-1")

    def test_guard_blocks_all_domains(self) -> None:
        """MutationGuard blocks mutations for all three domains."""
        guard = MutationGuard(MockEngine())

        # Task domain
        with pytest.raises(MutationBlockedError):
            guard.create_task("test")
        with pytest.raises(MutationBlockedError):
            guard.update_task("task-1")
        with pytest.raises(MutationBlockedError):
            guard.delete_task("task-1")

        # Goal domain
        with pytest.raises(MutationBlockedError):
            guard.create_goal("test")
        with pytest.raises(MutationBlockedError):
            guard.update_goal("goal-1")
        with pytest.raises(MutationBlockedError):
            guard.delete_goal("goal-1")
        with pytest.raises(MutationBlockedError):
            guard.modify_goal("goal-1")

        # Calendar domain
        with pytest.raises(MutationBlockedError):
            guard.create_calendar_event("event-1")
        with pytest.raises(MutationBlockedError):
            guard.update_calendar_event("event-1")
        with pytest.raises(MutationBlockedError):
            guard.delete_calendar_event("event-1")


# ── Integration with existing models ─────────────────────────────────────────


class TestIntegrationWithModels:
    def test_proposal_model_still_works(self) -> None:
        """ActionProposal model should still work normally."""
        ap = ActionProposal(
            action_type=ActionType.CREATE_TASK,
            reason="Test",
            source="test",
        )
        assert ap.action_type == ActionType.CREATE_TASK
        assert ap.reason == "Test"
        assert ap.status == ProposalStatus.PROPOSED
        assert ap.is_actionable is True

    def test_proposal_serialization_still_works(self) -> None:
        """Serialization should still work normally."""
        ap = ActionProposal(
            action_type=ActionType.RESCHEDULE_TASK,
            reason="Test",
            source="test",
        )
        d = ap.to_dict()
        ap2 = ActionProposal.from_dict(d)
        assert ap2.action_type == ap.action_type
        assert ap2.reason == ap.reason

    def test_weekly_plan_still_works(self) -> None:
        """WeeklyPlan should still work normally."""
        plan = WeeklyPlan(
            week_summary="Test",
            priorities=[PriorityEntry(goal_id="g1", reason="test", priority=Priority.HIGH)],
            planned_tasks=[PlannedTask(task_id="t1", goal_id="g1", priority=Priority.HIGH, reason="test", suggested_day=__import__("datetime").date.today())],
            risks=[PlanningRisk(description="test", severity=RiskSeverity.LOW)],
        )
        assert plan.week_summary == "Test"
        assert len(plan.priorities) == 1
        assert len(plan.planned_tasks) == 1
        assert len(plan.risks) == 1

    def test_planning_context_still_works(self) -> None:
        """PlanningContext should still work normally."""
        ctx = PlanningContext(
            goals=[],
            tasks=[],
            calendar=[],
            signals=PlanningSignals(),
        )
        assert ctx.goals == []
        assert ctx.tasks == []
        assert ctx.calendar == []
