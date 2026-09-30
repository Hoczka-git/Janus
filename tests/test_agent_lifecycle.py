"""Tests for AgentLifecycle enum and transition validation.

Covers:
- Enum member count and values
- Valid transitions
- Invalid transitions
- Terminal state
"""

from janus.models.agent_lifecycle import (
    LIFECYCLE_TRANSITIONS,
    AgentLifecycle,
    is_valid_transition,
)


class TestAgentLifecycle:
    def test_has_four_members(self):
        assert len(AgentLifecycle) == 4

    def test_member_values(self):
        assert AgentLifecycle.SPAWNING == "spawning"
        assert AgentLifecycle.ACTIVE == "active"
        assert AgentLifecycle.IDLE == "idle"
        assert AgentLifecycle.SHUTDOWN == "shutdown"

    def test_spawning_transitions(self):
        assert is_valid_transition(AgentLifecycle.SPAWNING, AgentLifecycle.ACTIVE) is True
        assert is_valid_transition(AgentLifecycle.SPAWNING, AgentLifecycle.SHUTDOWN) is True
        assert is_valid_transition(AgentLifecycle.SPAWNING, AgentLifecycle.IDLE) is False
        assert is_valid_transition(AgentLifecycle.SPAWNING, AgentLifecycle.SPAWNING) is False

    def test_active_transitions(self):
        assert is_valid_transition(AgentLifecycle.ACTIVE, AgentLifecycle.IDLE) is True
        assert is_valid_transition(AgentLifecycle.ACTIVE, AgentLifecycle.SHUTDOWN) is True
        assert is_valid_transition(AgentLifecycle.ACTIVE, AgentLifecycle.SPAWNING) is False
        assert is_valid_transition(AgentLifecycle.ACTIVE, AgentLifecycle.ACTIVE) is False

    def test_idle_transitions(self):
        assert is_valid_transition(AgentLifecycle.IDLE, AgentLifecycle.ACTIVE) is True
        assert is_valid_transition(AgentLifecycle.IDLE, AgentLifecycle.SHUTDOWN) is True
        assert is_valid_transition(AgentLifecycle.IDLE, AgentLifecycle.SPAWNING) is False
        assert is_valid_transition(AgentLifecycle.IDLE, AgentLifecycle.IDLE) is False

    def test_shutdown_is_terminal(self):
        assert is_valid_transition(AgentLifecycle.SHUTDOWN, AgentLifecycle.SPAWNING) is False
        assert is_valid_transition(AgentLifecycle.SHUTDOWN, AgentLifecycle.ACTIVE) is False
        assert is_valid_transition(AgentLifecycle.SHUTDOWN, AgentLifecycle.IDLE) is False
        assert is_valid_transition(AgentLifecycle.SHUTDOWN, AgentLifecycle.SHUTDOWN) is False

    def test_lifecycle_transitions_map(self):
        assert AgentLifecycle.ACTIVE in LIFECYCLE_TRANSITIONS[AgentLifecycle.SPAWNING]
        assert AgentLifecycle.SHUTDOWN in LIFECYCLE_TRANSITIONS[AgentLifecycle.SPAWNING]
        assert AgentLifecycle.IDLE in LIFECYCLE_TRANSITIONS[AgentLifecycle.ACTIVE]
        assert AgentLifecycle.SHUTDOWN in LIFECYCLE_TRANSITIONS[AgentLifecycle.ACTIVE]
        assert AgentLifecycle.ACTIVE in LIFECYCLE_TRANSITIONS[AgentLifecycle.IDLE]
        assert AgentLifecycle.SHUTDOWN in LIFECYCLE_TRANSITIONS[AgentLifecycle.IDLE]
        assert len(LIFECYCLE_TRANSITIONS[AgentLifecycle.SHUTDOWN]) == 0
