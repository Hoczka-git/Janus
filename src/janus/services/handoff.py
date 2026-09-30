"""Task-based handoff metadata for multi-agent orchestration.

Agent-to-agent communication happens through Janus state. When Agent A
completes a task that produces work for Agent B, the handoff goes through
Janus state: Agent A completes the task, writes evidence, and the next
task in the chain is created (or an existing task is unblocked) for
Agent B.

The handoff metadata is stored in the task body frontmatter:

    ---
    janus_domain:
      object: task
      title: "Implement feature X"
      handoff_from: "researcher"
      handoff_reason: "Research complete, ready for implementation"
      required_capabilities:
        - implement-feature
        - run-tests
    ---

Design reference: docs/design/phase_h_multi_agent_orchestration.md
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from janus.models.agent_role import AgentRole

logger = logging.getLogger(__name__)


@dataclass
class HandoffMetadata:
    """Handoff metadata extracted from a task body."""

    handoff_from: AgentRole | None = None
    handoff_reason: str = ""
    required_capabilities: list[str] = field(default_factory=list)


def parse_handoff_metadata(task_body: str) -> HandoffMetadata:
    """Parse handoff metadata from a task body.

    Extracts the janus_domain frontmatter and returns the handoff
    metadata. Returns empty metadata if no handoff info is found.

    Args:
        task_body: The task body text (may contain frontmatter).

    Returns:
        HandoffMetadata with extracted fields.
    """
    metadata = HandoffMetadata()

    # Extract frontmatter
    frontmatter_match = re.match(
        r'^---\s*\n(.*?)\n---',
        task_body,
        re.DOTALL,
    )
    if not frontmatter_match:
        return metadata

    frontmatter = frontmatter_match.group(1)

    # Extract handoff_from
    handoff_from_match = re.search(
        r'handoff_from:\s*"?([^"\n]+)"?',
        frontmatter,
    )
    if handoff_from_match:
        handoff_from_str = handoff_from_match.group(1).strip()
        try:
            metadata.handoff_from = AgentRole(handoff_from_str)
        except ValueError:
            logger.warning(f"Unknown agent role in handoff_from: {handoff_from_str}")

    # Extract handoff_reason
    handoff_reason_match = re.search(
        r'handoff_reason:\s*"?([^"\n]+)"?',
        frontmatter,
    )
    if handoff_reason_match:
        metadata.handoff_reason = handoff_reason_match.group(1).strip()

    # Extract required_capabilities
    capabilities_section = re.search(
        r'required_capabilities:\s*\n((?:\s*-\s*.+\n?)*)',
        frontmatter,
    )
    if capabilities_section:
        capabilities_text = capabilities_section.group(1)
        metadata.required_capabilities = [
            line.strip().lstrip("- ").strip()
            for line in capabilities_text.strip().split("\n")
            if line.strip()
        ]

    return metadata
