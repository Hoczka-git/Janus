"""Agent lifecycle model for multi-agent orchestration.

This module defines the AgentLifecycle enum and transition validation.
Agent lifecycle is managed by Hermes, not Janus. Janus only tracks
the dispatch decision and the task assignment.

Design reference: docs/design/phase_h_multi_agent_orchestration.md
"""

from enum import StrEnum


class AgentLifecycle(StrEnum):
    """Agent lifecycle states for multi-agent orchestration.

    Agent lifecycle is managed by Hermes, not Janus. Janus only tracks
    the dispatch decision and the task assignment.

    States:
        SPAWNING — Hermes is creating the worker process.
        ACTIVE — Agent is executing a task.
        IDLE — Agent is waiting for work.
        SHUTDOWN — Agent is terminating (terminal state).
    """

    SPAWNING = "spawning"
    ACTIVE = "active"
    IDLE = "idle"
    SHUTDOWN = "shutdown"


#: Valid lifecycle transitions.
LIFECYCLE_TRANSITIONS: dict[AgentLifecycle, frozenset[AgentLifecycle]] = {
    AgentLifecycle.SPAWNING: frozenset({AgentLifecycle.ACTIVE, AgentLifecycle.SHUTDOWN}),
    AgentLifecycle.ACTIVE: frozenset({AgentLifecycle.IDLE, AgentLifecycle.SHUTDOWN}),
    AgentLifecycle.IDLE: frozenset({AgentLifecycle.ACTIVE, AgentLifecycle.SHUTDOWN}),
    AgentLifecycle.SHUTDOWN: frozenset(),  # Terminal state
}


def is_valid_transition(from_state: AgentLifecycle, to_state: AgentLifecycle) -> bool:
    """Check if a lifecycle transition is valid.

    Args:
        from_state: The current lifecycle state.
        to_state: The target lifecycle state.

    Returns:
        True if the transition is valid, False otherwise.
    """
    return to_state in LIFECYCLE_TRANSITIONS.get(from_state, frozenset())
