"""Plugins test fixtures for the Janus worktree."""
import sys, os

# Add hermes-agent to sys.path so hermes_cli can be imported
_hermes_agent = os.path.expanduser("~/.hermes/hermes-agent")
if _hermes_agent not in sys.path:
    sys.path.insert(0, _hermes_agent)
