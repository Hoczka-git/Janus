"""Tests for dispatch_task() and capability extraction.

Covers:
- Capability extraction from task titles
- Agent role matching
- dispatch_task() returns valid AgentAssignment
- dispatch_task() falls back to classify_task() on failure
- dispatch_task() preserves execution_mode and support_mode
"""

import pytest

from janus.models.agent_role import AgentRole
from janus.models.execution_mode import ExecutionMode
from janus.models.goal import Goal
from janus.models.support_mode import SupportMode
from janus.models.task import Task
from janus.services.agency_planning import (
    AgencyContext,
    _extract_required_capabilities,
    _match_agent_role,
    classify_task,
    dispatch_task,
)


def _task(title: str, **kwargs) -> Task:
    return Task(title=title, **kwargs)


def _goal(title: str = "Test Goal", **kwargs) -> Goal:
    return Goal(title=title, **kwargs)


def _context(**kwargs) -> AgencyContext:
    return AgencyContext(**kwargs)


class TestExtractRequiredCapabilities:
    def test_plan_keywords(self):
        task = _task("Plan Q4 roadmap")
        goal = _goal()
        caps = _extract_required_capabilities(task, goal)
        assert "plan-roadmap" in caps

    def test_research_keywords(self):
        task = _task("Research multi-agent patterns")
        goal = _goal()
        caps = _extract_required_capabilities(task, goal)
        assert "research-literature" in caps

    def test_implement_keywords(self):
        task = _task("Implement feature X")
        goal = _goal()
        caps = _extract_required_capabilities(task, goal)
        assert "implement-feature" in caps

    def test_review_keywords(self):
        task = _task("Review PR #123")
        goal = _goal()
        caps = _extract_required_capabilities(task, goal)
        assert "review-code" in caps

    def test_explain_keywords(self):
        task = _task("Explain concept X")
        goal = _goal()
        caps = _extract_required_capabilities(task, goal)
        assert "explain-concept" in caps

    def test_no_keywords(self):
        task = _task("Design architecture")
        goal = _goal()
        caps = _extract_required_capabilities(task, goal)
        assert caps == []

    def test_multiple_keywords(self):
        task = _task("Plan and implement feature")
        goal = _goal()
        caps = _extract_required_capabilities(task, goal)
        assert "plan-roadmap" in caps
        assert "implement-feature" in caps

    def test_case_insensitive(self):
        task = _task("PLAN roadmap")
        goal = _goal()
        caps = _extract_required_capabilities(task, goal)
        assert "plan-roadmap" in caps


class TestMatchAgentRole:
    def test_match_planner(self):
        role = _match_agent_role(["plan-roadmap"], _context())
        assert role == AgentRole.PLANNER

    def test_match_researcher(self):
        role = _match_agent_role(["research-literature"], _context())
        assert role == AgentRole.RESEARCHER

    def test_match_executor(self):
        role = _match_agent_role(["implement-feature"], _context())
        assert role == AgentRole.EXECUTOR

    def test_match_reviewer(self):
        role = _match_agent_role(["review-code"], _context())
        assert role == AgentRole.REVIEWER

    def test_match_coach(self):
        role = _match_agent_role(["explain-concept"], _context())
        assert role == AgentRole.COACH

    def test_no_match(self):
        role = _match_agent_role(["nonexistent"], _context())
        assert role is None

    def test_empty_capabilities(self):
        role = _match_agent_role([], _context())
        assert role is None


class TestDispatchTask:
    def test_dispatch_returns_agent_assignment(self):
        task = _task("Plan Q4 roadmap")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert assignment.execution_mode is not None
        assert assignment.support_mode is not None
        assert assignment.agent_role is not None
        assert assignment.reason is not None
        assert assignment.confidence > 0.0

    def test_dispatch_plan_task(self):
        task = _task("Plan Q4 roadmap")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert assignment.agent_role == AgentRole.PLANNER
        assert assignment.required_capabilities is not None
        assert "plan-roadmap" in assignment.required_capabilities

    def test_dispatch_research_task(self):
        task = _task("Research multi-agent patterns")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert assignment.agent_role == AgentRole.RESEARCHER

    def test_dispatch_implement_task(self):
        task = _task("Implement feature X")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert assignment.agent_role == AgentRole.EXECUTOR

    def test_dispatch_review_task(self):
        task = _task("Review PR #123")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert assignment.agent_role == AgentRole.REVIEWER

    def test_dispatch_explain_task(self):
        task = _task("Explain concept X")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert assignment.agent_role == AgentRole.COACH

    def test_dispatch_no_specialized_agent(self):
        task = _task("Design architecture")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert assignment.agent_role is None

    def test_dispatch_preserves_execution_mode(self):
        task = _task("Sync data files")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert assignment.execution_mode == ExecutionMode.JANUS

    def test_dispatch_preserves_support_mode(self):
        task = _task("Sync data files")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert assignment.support_mode == SupportMode.EXECUTE

    def test_dispatch_fallback_on_failure(self):
        """When classify_task raises, dispatch_task falls back gracefully."""
        task = _task("Sync data files")
        goal = _goal()
        context = _context()

        # Monkeypatch classify_task to raise
        import janus.services.agency_planning as ap
        original = ap.classify_task
        def raising_classify(*args, **kwargs):
            raise RuntimeError("Simulated failure")
        ap.classify_task = raising_classify
        try:
            assignment = dispatch_task(task, goal, context)
            assert assignment.agent_role is None
            assert "Fallback" in assignment.reason
            assert assignment.confidence < 0.5
        finally:
            ap.classify_task = original

    def test_dispatch_deterministic(self):
        """Same inputs → same output."""
        task = _task("Plan Q4 roadmap")
        goal = _goal()
        context = _context()
        a1 = dispatch_task(task, goal, context)
        a2 = dispatch_task(task, goal, context)
        assert a1.agent_role == a2.agent_role
        assert a1.execution_mode == a2.execution_mode
        assert a1.support_mode == a2.support_mode
        assert a1.confidence == a2.confidence

    def test_dispatch_required_capabilities_populated(self):
        task = _task("Plan Q4 roadmap")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert assignment.required_capabilities is not None
        assert len(assignment.required_capabilities) > 0

    def test_dispatch_reason_populated(self):
        task = _task("Plan Q4 roadmap")
        goal = _goal()
        context = _context()
        assignment = dispatch_task(task, goal, context)
        assert len(assignment.reason) > 0
