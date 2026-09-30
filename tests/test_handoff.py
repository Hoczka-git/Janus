"""Tests for handoff metadata parsing.

Covers:
- Parsing handoff_from
- Parsing handoff_reason
- Parsing required_capabilities
- Handling missing frontmatter
- Handling invalid agent role
"""

from janus.models.agent_role import AgentRole
from janus.services.handoff import parse_handoff_metadata


class TestParseHandoffMetadata:
    def test_parse_full_metadata(self):
        body = """---
janus_domain:
  object: task
  title: "Implement feature X"
  handoff_from: "researcher"
  handoff_reason: "Research complete, ready for implementation"
  required_capabilities:
    - implement-feature
    - run-tests
---

# Implement feature X

Task description here.
"""
        metadata = parse_handoff_metadata(body)
        assert metadata.handoff_from == AgentRole.RESEARCHER
        assert metadata.handoff_reason == "Research complete, ready for implementation"
        assert metadata.required_capabilities == ["implement-feature", "run-tests"]

    def test_parse_no_frontmatter(self):
        body = "# Just a task\n\nNo frontmatter here."
        metadata = parse_handoff_metadata(body)
        assert metadata.handoff_from is None
        assert metadata.handoff_reason == ""
        assert metadata.required_capabilities == []

    def test_parse_empty_body(self):
        metadata = parse_handoff_metadata("")
        assert metadata.handoff_from is None
        assert metadata.handoff_reason == ""
        assert metadata.required_capabilities == []

    def test_parse_handoff_from_only(self):
        body = """---
janus_domain:
  handoff_from: "planner"
---

# Task
"""
        metadata = parse_handoff_metadata(body)
        assert metadata.handoff_from == AgentRole.PLANNER
        assert metadata.handoff_reason == ""
        assert metadata.required_capabilities == []

    def test_parse_handoff_reason_only(self):
        body = """---
janus_domain:
  handoff_reason: "Planning complete"
---

# Task
"""
        metadata = parse_handoff_metadata(body)
        assert metadata.handoff_from is None
        assert metadata.handoff_reason == "Planning complete"
        assert metadata.required_capabilities == []

    def test_parse_capabilities_only(self):
        body = """---
janus_domain:
  required_capabilities:
    - plan-roadmap
    - task-sequencing
---

# Task
"""
        metadata = parse_handoff_metadata(body)
        assert metadata.handoff_from is None
        assert metadata.handoff_reason == ""
        assert metadata.required_capabilities == ["plan-roadmap", "task-sequencing"]

    def test_parse_invalid_agent_role(self):
        body = """---
janus_domain:
  handoff_from: "invalid_role"
---

# Task
"""
        metadata = parse_handoff_metadata(body)
        assert metadata.handoff_from is None

    def test_parse_all_agent_roles(self):
        for role in AgentRole:
            body = f"""---
janus_domain:
  handoff_from: "{role.value}"
---

# Task
"""
            metadata = parse_handoff_metadata(body)
            assert metadata.handoff_from == role

    def test_parse_single_capability(self):
        body = """---
janus_domain:
  required_capabilities:
    - implement-feature
---

# Task
"""
        metadata = parse_handoff_metadata(body)
        assert metadata.required_capabilities == ["implement-feature"]
