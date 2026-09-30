"""Agent role taxonomy for multi-agent orchestration.

This module defines the AgentRole enum — the specialized agent roles
that the dispatch function can assign tasks to. Each role corresponds
to a set of capabilities provided by SKILL.md files.

Roles are orthogonal to ExecutionMode and SupportMode:
- ExecutionMode: who should perform the task (USER/JANUS/COLLABORATIVE)
- SupportMode: how much support is needed (EXPLAIN/COACH/SCAFFOLD/REVIEW/EXECUTE)
- AgentRole: which specialized capability is needed (PLANNER/RESEARCHER/EXECUTOR/REVIEWER/COACH)

Design reference: docs/design/phase_h_multi_agent_orchestration.md
"""

from enum import StrEnum


class AgentRole(StrEnum):
    """Specialized agent roles for multi-agent orchestration.

    Each role corresponds to a set of capabilities provided by SKILL.md
    files. The role is a dispatch signal: it tells Hermes which agent
    (with which skills) should handle a task.

    Roles are orthogonal to ExecutionMode and SupportMode:
    - ExecutionMode: who should perform the task (USER/JANUS/COLLABORATIVE)
    - SupportMode: how much support is needed (EXPLAIN/COACH/SCAFFOLD/REVIEW/EXECUTE)
    - AgentRole: which specialized capability is needed (PLANNER/RESEARCHER/EXECUTOR/REVIEWER/COACH)
    """

    PLANNER = "planner"
    RESEARCHER = "researcher"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    COACH = "coach"
