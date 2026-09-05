"""Test configuration: ensure data/tasks.md exists for tests that read it
directly from the repository root (the attention engine reads task titles
from this file to determine goal stall status).

This file is gitignored and represents local runtime state; the attention
engine's ``_load_all_task_titles`` reads it at a hardcoded path derived
from the module location. Without it, several goal-stagnation tests
incorrectly report no attention items. This fixture materialises a minimal
fixture file before the test session runs and removes it afterward so no
repository state is modified.
"""

from pathlib import Path
import pytest

# Minimal task file that includes the "Prepare training plan" entry
# expected by goal-stagnation tests in test_attention.py,
# test_daily_briefing.py, and test_today.py.
_TASKS_MD_CONTENT = """\
# Tasks

- [ ] Prepare training plan | priority: 3
"""


@pytest.fixture(scope="session", autouse=True)
def _ensure_tasks_md():
    """Create data/tasks.md before tests, clean up after."""
    import janus.services.attention as att

    tasks_path = Path(att.__file__).resolve().parents[3] / "data" / "tasks.md"
    tasks_path.parent.mkdir(parents=True, exist_ok=True)

    existed = tasks_path.exists()
    original = tasks_path.read_text() if existed else ""

    tasks_path.write_text(_TASKS_MD_CONTENT)

    yield

    if existed:
        tasks_path.write_text(original)
    else:
        try:
            tasks_path.unlink()
        except FileNotFoundError:
            pass
