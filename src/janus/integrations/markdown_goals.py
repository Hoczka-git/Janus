"""Markdown goals loader for Janus."""

from pathlib import Path

from janus.models.goal import Goal


PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOALS_PATH = PROJECT_ROOT / "data" / "goals.md"


def load_goals() -> list[Goal]:
    """Load goals from data/goals.md."""
    if not GOALS_PATH.exists():
        raise FileNotFoundError(f"Goals file not found: {GOALS_PATH}")

    goals: list[Goal] = []
    current_goal: dict | None = None
    current_line = 1

    with GOALS_PATH.open() as f:
        for line_num, line in enumerate(f, start=1):
            current_line = line_num
            stripped = line.strip()

            if stripped.startswith("# Goals"):
                continue

            if stripped.startswith("## Goal:"):
                if current_goal is not None:
                    goals.append(_finalize_goal(current_goal, current_line))
                current_goal = {
                    "title": stripped[len("## Goal:"):].strip(),
                    "description": "",
                    "status": "active",
                    "related_tasks": [],
                }

            elif current_goal is not None:
                if stripped.startswith("Description:"):
                    current_goal["description"] = stripped[len("Description:"):].strip()
                elif stripped.startswith("Status:"):
                    status = stripped[len("Status:"):].strip()
                    if status not in ("active", "completed", "inactive"):
                        raise ValueError(
                            f"Invalid goal status at line {line_num}: {status}"
                        )
                    current_goal["status"] = status
                elif stripped.startswith("Related tasks:"):
                    current_goal["related_tasks"] = []
                elif stripped.startswith("- ") and "related_tasks" in current_goal:
                    task_title = stripped[2:].strip()
                    if task_title:
                        current_goal["related_tasks"].append(task_title)

        if current_goal is not None:
            goals.append(_finalize_goal(current_goal, current_line))

    return goals


def _finalize_goal(data: dict, line_num: int) -> Goal:
    if "title" not in data or not data["title"]:
        raise ValueError(f"Goal missing title at line {line_num}")
    return Goal(
        title=data["title"],
        description=data.get("description", ""),
        status=data.get("status", "active"),
        related_tasks=data.get("related_tasks", []),
    )
