"""Plugins test fixtures for the Janus worktree."""
import sys, os

# Add hermes-agent to sys.path so hermes_cli can be imported
# Try the local .hermes first, then the standard location
_hermes_agent = None
for candidate in [
    os.path.expanduser("~/.hermes/hermes-agent"),
    os.path.join(os.path.dirname(os.path.dirname(__file__)), ".hermes", "hermes-agent"),
]:
    if os.path.isdir(candidate):
        _hermes_agent = candidate
        break

if _hermes_agent and _hermes_agent not in sys.path:
    sys.path.insert(0, _hermes_agent)

# Skip all tests in this directory if hermes_cli is not available
import pytest
pytest.importorskip("hermes_cli", reason="hermes_cli not available (install hermes-agent)")
