"""Plugins test fixtures for the Janus worktree."""
import sys, os

# Add hermes-agent to sys.path so hermes_cli can be imported
# Try the local .hermes first, then the standard location
# The Janus repo root (parent of this tests/ dir's parent) must come BEFORE
# the live hermes-agent install on sys.path. Otherwise the hermes-agent's
# bundled ``plugins/`` regular package (which ships ``replenishment`` but not
# ``janus_sync``) shadows the Janus-repo ``plugins/`` namespace package, and
# ``import plugins.janus_sync`` fails under test.
_repo_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_hermes_agent = None
for candidate in [
    os.path.expanduser("~/.hermes/hermes-agent"),
    os.path.join(_repo_root, ".hermes", "hermes-agent"),
]:
    if os.path.isdir(candidate):
        _hermes_agent = candidate
        break

if _hermes_agent and _hermes_agent not in sys.path:
    sys.path.insert(0, _hermes_agent)
# Re-assert the repo root above hermes-agent so the local ``plugins`` package
# (regular package via plugins/__init__.py) wins over the hermes-agent copy.
if _hermes_agent in sys.path:
    sys.path.remove(_hermes_agent)
    sys.path.insert(0, _repo_root)
    sys.path.insert(1, _hermes_agent)

# Skip all tests in this directory if hermes_cli is not available
import pytest
pytest.importorskip("hermes_cli", reason="hermes_cli not available (install hermes-agent)")
