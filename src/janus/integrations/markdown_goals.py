"""Markdown goals persistence for Janus.

Loads, saves, and updates goals from data/goals.md.

Backward compatible: parses existing fields (Description, Status, Related tasks)
and 7 new optional fields (Metric, Unit, Start, Current, Target, Direction, Deadline).

Unknown fields are ignored on parse and NOT preserved through update_goal rewrite.
Malformed numeric/date/direction values raise ValueError with line number.
"""

from datetime import date
from pathlib import Path

from janus.models.goal import Goal

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOALS_PATH = PROJECT_ROOT / "data" / "goals.md"


def load_goals() -> list[Goal]:
    """Load goals from data/goals.md.

    Returns [] if file is missing (changed from raising FileNotFoundError).
    Unknown fields in the file are ignored.
    Malformed numeric values, invalid directions, and invalid dates raise ValueError.
    """
    if not GOALS_PATH.exists():
        return []

    goals: list[Goal] = []
    current: dict | None = None

    with GOALS_PATH.open() as f:
        for line_num, line in enumerate(f, start=1):
            stripped = lint = line.strip()

            if stripped.startswith("# Goals"):
                continue

            if stripped.startswith("## Goal:"):
                if current is not None:
                    goals.append(_finalize_goal(current))
                title = stripped[8:].strip()
                current = {
                    "title": title,
                    "description": "",
                    "status": "active",
                    "deadline": None,
                    "metric_name": None,
                    "metric_unit": None,
                    "start_value": None,
                    "current_value": None,
                    "target_value": None,
                    "direction": None,
                    "related_tasks": None,
                }
                # Empty title after strip is invalid
                if not current["title"]:
                    raise ValueError(f"Goal missing title at line {line_num}")
                continue

            if current is None:
                continue

            if stripped.startswith("Description:"):
                current["description"] = stripped[12:].strip()
            elif stripped.startswith("Status:"):
                current["status"] = stripped[7:].strip()
            elif stripped.startswith("Deadline:"):
                raw = stripped[9:].strip()
                try:
                    date.fromisoformat(raw)
                except ValueError:
                    raise ValueError(f"Invalid Deadline at line {line_num}: {raw}")
                current["deadline"] = raw
            elif stripped.startswith("Metric:"):
                raw = stripped[7:].strip()
                current["metric_name"] = raw if raw else None
            elif stripped.startswith("Unit:"):
                raw = stripped[5:].strip()
                current["metric_unit"] = raw if raw else None
            elif stripped.startswith("Start:"):
                raw = stripped[6:].strip()
                try:
                    current["start_value"] = float(raw) if raw else None
                except ValueError:
                    raise ValueError(f"Invalid Start value at line {line_num}: {raw}")
            elif stripped.startswith("Current:"):
                raw = stripped[8:].strip()
                try:
                    current["current_value"] = float(raw) if raw else None
                except ValueError:
                    raise ValueError(f"Invalid Current value at line {line_num}: {raw}")
            elif stripped.startswith("Target:"):
                raw = stripped[7:].strip()
                try:
                    current["target_value"] = float(raw) if raw else None
                except ValueError:
                    raise ValueError(f"Invalid Target value at line {line_num}: {raw}")
            elif stripped.startswith("Direction:"):
                raw = stripped[10:].strip()
                if raw in ("increase", "decrease"):
                    current["direction"] = raw
                else:
                    raise ValueError(f"Invalid Direction at line {line_num}: {raw}")
            if stripped.startswith("Related tasks:"):
                current["related_tasks"] = []
            elif stripped.startswith("- ") and "related_tasks" in current:
                task = stripped[2:].strip()
                if task:
                    current["related_tasks"].append(task)
            # else: unknown field — ignore

    if current is not None:
        goals.append(_finalize_goal(current))

    return goals


def _finalize_goal(data: dict) -> Goal:
    return Goal(
        title=data["title"],
        description=data["description"],
        status=data["status"],
        deadline=data["deadline"],
        metric_name=data["metric_name"],
        metric_unit=data["metric_unit"],
        start_value=data["start_value"],
        current_value=data["current_value"],
        target_value=data["target_value"],
        direction=data["direction"],
        related_tasks=data["related_tasks"],
    )


def _format_goal_block(goal: Goal) -> list[str]:
    """Format a Goal as lines for goals.md. Only known fields are written.

    Unknown fields are NOT preserved through rewrite.
    """
    lines: list[str] = [f"## Goal: {goal.title}"]

    if goal.description:
        lines.append(f"Description: {goal.description}")
    lines.append(f"Status: {goal.status}")

    if goal.deadline:
        lines.append(f"Deadline: {goal.deadline}")
    if goal.metric_name:
        lines.append(f"Metric: {goal.metric_name}")
    if goal.metric_unit:
        lines.append(f"Unit: {goal.metric_unit}")
    if goal.start_value is not None:
        lines.append(f"Start: {goal.start_value}")
    if goal.current_value is not None:
        lines.append(f"Current: {goal.current_value}")
    if goal.target_value is not None:
        lines.append(f"Target: {goal.target_value}")
    if goal.direction:
        lines.append(f"Direction: {goal.direction}")

    if goal.related_tasks is not None and goal.related_tasks:
        lines.append("Related tasks:")
        for task in goal.related_tasks:
            lines.append(f"- {task}")

    return lines


def save_goal(goal: Goal) -> None:
    """Append a goal block to goals.md.

    Raises ValueError if title is empty.
    """
    if not goal.title:
        raise ValueError("Goal title must not be empty")

    block = _format_goal_block(goal)
    with GOALS_PATH.open("a") as f:
        f.write("\n")
        for line in block:
            f.write(line + "\n")


def update_goal(goal: Goal) -> None:
    """Replace an existing goal block by title.

    Only known fields survive — unknown fields are lost.
    Raises ValueError if title is empty or goal not found.
    """
    if not goal.title:
        raise ValueError("Goal title must not be empty")

    if not GOALS_PATH.exists():
        raise ValueError(f"Goals file not found: {GOALS_PATH}")

    all_lines = GOALS_PATH.read_text().splitlines()
    new_block = _format_goal_block(goal)
    output: list[str] = []
    found = False
    i = 0

    while i < len(all_lines):
        line = all_lines[i]
        if line.startswith("## Goal:") and line[8:].strip() == goal.title:
            found = True
            output.extend(new_block)
            i += 1
            # Skip until next ## Goal: or end
            while i < len(all_lines) and not all_lines[i].startswith("## Goal:"):
                i += 1
        else:
            output.append(line)
            i += 1

    if not found:
        raise ValueError(f"Goal not found: {goal.title}")

    GOALS_PATH.write_text("\n".join(output) + "\n")
