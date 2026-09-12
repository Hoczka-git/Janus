"""Markdown goals persistence for Janus.

Loads, saves, and updates goals from data/goals.md.

Backward compatible: parses existing fields (Description, Status, Related tasks)
and 7 new optional fields (Metric, Unit, Start, Current, Target, Direction, Deadline).

Unknown fields are ignored on parse and NOT preserved through update_goal rewrit
Malformed numeric/date/direction values raise ValueError with line number.
"""
import json
import logging
from datetime import date
from pathlib import Path

from janus._log import emit
from janus.models.goal import Goal

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOALS_PATH = PROJECT_ROOT / "data" / "goals.md"

logger = logging.getLogger(__name__)


def load_goals(trace_id: str | None = None) -> list[Goal]:
    """Load goals from data/goals.md.

    Returns [] if file is missing (changed from raising FileNotFoundError).
    Unknown fields in the file are ignored.
    Malformed numeric values, invalid directions, and invalid dates raise ValueError.
    """
    if not GOALS_PATH.exists():
        emit(logger, "source.goals.loaded",
             trace_id=trace_id, span_id="load_goals",
             correlation_id=trace_id,
             file_present=False,
             file_path=str(GOALS_PATH),
             goals_loaded=0,
             validation_errors=0,
             message="Goals file not found")
        return []
    goals: list[Goal] = []
    current: dict | None = None
    in_milestones = False       # inside a goal's ## Milestones section
    in_milestone = False        # inside a single ### Milestone: block
    current_milestone: dict | None = None
    in_projects = False          # inside a goal's ## Projects section
    in_project = False           # inside a single ### Project block
    current_project: dict | None = None
    in_measurement_requirements = False
    current_requirement: dict | None = None
    in_list_section: str | None = None  # "related_tasks", "research_artifacts", or "project_related_tasks"
    in_recent_activity = False          # inside a goal's ## Recent activity section
    lines_scanned = 0
    validation_errors = 0

    with GOALS_PATH.open() as f:
        for line_num, line in enumerate(f, start=1):
            lines_scanned += 1
            stripped = line.strip()

            if stripped.startswith("# Goals"):
                continue

            if stripped.startswith("## Goal:"):
                if current is not None:
                    # Flush any pending milestone before finalizing
                    if current_milestone is not None:
                        current["milestones"].append(_finalize_milestone(current_milestone))
                        current_milestone = None
                    # Flush any pending project before finalizing
                    if current_project is not None:
                        current["projects"].append(_finalize_project(current_project))
                        current_project = None
                    # Flush any pending measurement requirement
                    if current_requirement is not None:
                        current["measurement_requirements"].append(current_requirement)
                        current_requirement = None
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
                    "milestones": [],
                    "projects": [],
                    "measurement_requirements": [],
                    "research_artifact_titles": [],
                    "decision_numbers": [],
                    "followup_ids": [],
                    "inactivity_window_days": None,
                    "recent_activity": [],
                }
                # Empty title after strip is invalid
                if not current["title"]:
                    raise ValueError(f"Goal missing title at line {line_num}")
                in_milestones = False
                in_milestone = False
                current_milestone = None
                in_projects = False
                in_project = False
                current_project = None
                in_measurement_requirements = False
                current_requirement = None
                in_list_section = None
                in_recent_activity = False
                continue

            if current is None:
                continue

            # --- Measurement requirements section detection ---
            if stripped == "Measurement requirements:":
                # Flush any pending milestone
                if current_milestone is not None:
                    current["milestones"].append(_finalize_milestone(current_milestone))
                    current_milestone = None
                in_milestones = False
                in_milestone = False
                current_milestone = None
                # Flush any pending project
                if current_project is not None:
                    current["projects"].append(_finalize_project(current_project))
                    current_project = None
                in_projects = False
                in_project = False
                current_project = None
                in_measurement_requirements = True
                continue

            # --- Milestone section detection ---
            if stripped == "## Milestones":
                # Flush any pending measurement requirement
                if current_requirement is not None:
                    current["measurement_requirements"].append(current_requirement)
                    current_requirement = None
                in_measurement_requirements = False
                # Flush any pending project before entering milestones
                if current_project is not None:
                    current["projects"].append(_finalize_project(current_project))
                    current_project = None
                in_projects = False
                in_project = False
                current_project = None
                in_milestones = True
                in_milestone = False
                current_milestone = None
                continue

            if in_milestones and stripped.startswith("## "):
                # End of milestones section — another goal-level section
                # Flush any pending milestone before leaving
                if current_milestone is not None:
                    current["milestones"].append(_finalize_milestone(current_milestone))
                    current_milestone = None
                in_milestones = False
                in_milestone = False
                current_milestone = None
                # Fall through to process this line as a goal-level field

            # --- Projects section detection ---
            if stripped == "## Projects":
                # Flush any pending milestone before leaving milestones section
                if current_milestone is not None:
                    current["milestones"].append(_finalize_milestone(current_milestone))
                    current_milestone = None
                in_milestones = False
                in_milestone = False
                current_milestone = None
                # Flush any pending measurement requirement
                if current_requirement is not None:
                    current["measurement_requirements"].append(current_requirement)
                    current_requirement = None
                in_measurement_requirements = False
                in_list_section = None
                in_projects = True
                in_project = False
                current_project = None
                continue

            # --- Recent activity section detection ---
            if stripped == "## Recent activity":
                # Flush any pending milestone before leaving milestones section
                if current_milestone is not None:
                    current["milestones"].append(_finalize_milestone(current_milestone))
                    current_milestone = None
                in_milestones = False
                in_milestone = False
                current_milestone = None
                # Flush any pending project
                if current_project is not None:
                    current["projects"].append(_finalize_project(current_project))
                    current_project = None
                in_projects = False
                in_project = False
                current_project = None
                # Flush any pending measurement requirement
                if current_requirement is not None:
                    current["measurement_requirements"].append(current_requirement)
                    current_requirement = None
                in_measurement_requirements = False
                in_list_section = None
                in_recent_activity = True
                continue

            # --- Handle measurement requirements lines ---
            if in_measurement_requirements:
                if stripped.startswith("- metric:"):
                    # Finalize any pending requirement
                    if current_requirement is not None:
                        current["measurement_requirements"].append(current_requirement)
                    current_requirement = {"metric": stripped[9:].strip()}
                elif current_requirement is not None and ":" in stripped:
                    key, _, val = stripped.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if key in ("unit", "frequency", "preferred_time"):
                        if val:
                            current_requirement[key] = val
                    elif key == "interval_days":
                        if val:
                            try:
                                current_requirement["interval_days"] = int(val)
                            except ValueError:
                                raise ValueError(
                                    f"Invalid interval_days at line {line_num}: {val}"
                                )
                    # Unknown keys are ignored (forward compatibility)
                elif not stripped:
                    # Blank line inside requirements — finalize pending requirement
                    if current_requirement is not None:
                        current["measurement_requirements"].append(current_requirement)
                        current_requirement = None
                # If the line does not look like a requirement field, exit the section
                elif not (stripped.startswith("- ") or stripped.startswith("    ")):
                    if current_requirement is not None:
                        current["measurement_requirements"].append(current_requirement)
                        current_requirement = None
                    in_measurement_requirements = False
                    # Fall through to let the line be processed as a goal-level field
                continue

            # --- Handle projects lines ---
            if in_projects:
                if stripped.startswith("### Project:"):
                    # Start a new project block
                    if current_project is not None:
                        current["projects"].append(_finalize_project(current_project))
                    proj_title = stripped[13:].strip()
                    if not proj_title:
                        raise ValueError(
                            f"Project missing title at line {line_num}"
                        )
                    current_project = {
                        "title": proj_title,
                        "goal_title": current["title"],
                        "milestone_title": "",
                        "description": "",
                        "deadline": None,
                        "status": "open",
                        "order": 0,
                        "related_tasks": [],
                    }
                    in_project = True
                    in_list_section = None
                elif in_project and current_project is not None:
                    if stripped.startswith("Milestone:"):
                        ms_ref = stripped[10:].strip()
                        if not ms_ref:
                            raise ValueError(
                                f"Project missing Milestone reference at line {line_num}"
                            )
                        current_project["milestone_title"] = ms_ref
                    elif stripped.startswith("Order:"):
                        raw = stripped[6:].strip()
                        try:
                            current_project["order"] = int(raw) if raw else 0
                        except ValueError:
                            raise ValueError(
                                f"Invalid Project Order at line {line_num}: {raw}"
                            )
                    elif stripped.startswith("Description:"):
                        current_project["description"] = stripped[12:].strip()
                    elif stripped.startswith("Deadline:"):
                        raw = stripped[9:].strip()
                        try:
                            date.fromisoformat(raw)
                        except ValueError:
                            raise ValueError(f"Invalid Deadline at line {line_num}: {raw}")
                        current_project["deadline"] = raw
                    elif stripped.startswith("Status:"):
                        current_project["status"] = stripped[7:].strip()
                    elif stripped.startswith("Related tasks:"):
                        current_project["related_tasks"] = []
                        in_list_section = "project_related_tasks"
                    elif stripped.startswith("- ") and in_list_section == "project_related_tasks":
                        item = _unquote(stripped[2:].strip())
                        if item:
                            current_project["related_tasks"].append(item)
                    # Unknown field in project — ignore
                continue

            # --- Handle recent activity lines ---
            if in_recent_activity:
                if stripped.startswith("# "):
                    # Comment line containing a JSON dict
                    json_str = stripped[2:].strip()
                    if json_str:
                        try:
                            entry = json.loads(json_str)
                            if isinstance(entry, dict):
                                current["recent_activity"].append(entry)
                        except json.JSONDecodeError:
                            validation_errors += 1
                elif stripped.startswith("## ") or stripped.startswith("### "):
                    # End of recent activity section
                    in_recent_activity = False
                    continue  # let the goal-level section handler process it
                continue

            if not in_milestones:
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
                elif stripped.startswith("InactivityWindowDays:"):
                    raw = stripped[20:].strip()
                    if raw:
                        try:
                            current["inactivity_window_days"] = int(raw)
                        except ValueError:
                            raise ValueError(
                                f"Invalid InactivityWindowDays at line {line_num}: {raw}"
                            )
                if stripped.startswith("Related tasks:") or stripped.startswith("Research artifacts:") or stripped.startswith("Decision numbers:") or stripped.startswith("Follow-up IDs:"):
                    # Determine which list section we're entering
                    if stripped.startswith("Research artifacts:"):
                        current["research_artifact_titles"] = []
                        in_list_section = "research_artifacts"
                    elif stripped.startswith("Decision numbers:"):
                        current["decision_numbers"] = []
                        in_list_section = "decision_numbers"
                    elif stripped.startswith("Follow-up IDs:"):
                        current["followup_ids"] = []
                        in_list_section = "followup_ids"
                    else:
                        current["related_tasks"] = []
                        in_list_section = "related_tasks"
                elif stripped.startswith("- ") and in_list_section is not None:
                    item = _unquote(stripped[2:].strip())
                    if item:
                        if in_list_section == "related_tasks":
                            current["related_tasks"].append(item)
                        elif in_list_section == "research_artifacts":
                            current["research_artifact_titles"].append(item)
                        elif in_list_section == "decision_numbers":
                            current["decision_numbers"].append(item)
                        elif in_list_section == "followup_ids":
                            current["followup_ids"].append(item)
                # else: unknown field — ignore

            else:
                # Inside ## Milestones section
                if stripped.startswith("### Milestone:"):
                    # Start a new milestone block
                    if current_milestone is not None:
                        current["milestones"].append(_finalize_milestone(current_milestone))
                    ms_title = stripped[14:].strip()
                    # Extract optional order from parenthetical "(order: N)"
                    ms_order = 0
                    if ms_title.endswith(")") and "(order:" in ms_title:
                        order_idx = ms_title.rfind("(order:")
                        order_str = ms_title[order_idx + 7:].rstrip(")")
                        try:
                            ms_order = int(order_str.strip())
                        except ValueError:
                            ms_order = 0
                        ms_title = ms_title[:order_idx].strip()
                    if not ms_title:
                        raise ValueError(
                            f"Milestone missing title at line {line_num}"
                        )
                    current_milestone = {
                        "title": ms_title,
                        "goal_title": current["title"],
                        "description": "",
                        "deadline": None,
                        "status": "open",
                        "order": ms_order,
                    }
                    in_milestone = True
                elif in_milestone and current_milestone is not None:
                    if stripped.startswith("Description:"):
                        current_milestone["description"] = stripped[12:].strip()
                    elif stripped.startswith("Deadline:"):
                        raw = stripped[9:].strip()
                        try:
                            date.fromisoformat(raw)
                        except ValueError:
                            raise ValueError(f"Invalid Deadline at line {line_num}: {raw}")
                        current_milestone["deadline"] = raw
                    elif stripped.startswith("Status:"):
                        current_milestone["status"] = stripped[7:].strip()
                    # Note: task-to-milestone membership is NOT stored on
                    # milestones. Related tasks live on the Goal model and
                    # are derived dynamically at query time.
                    # Unknown field in milestone — ignore

    if current is not None:
        if current_milestone is not None:
            current["milestones"].append(_finalize_milestone(current_milestone))
        if current_project is not None:
            current["projects"].append(_finalize_project(current_project))
        if current_requirement is not None:
            current["measurement_requirements"].append(current_requirement)
            current_requirement = None
        goals.append(_finalize_goal(current))

    emit(logger, "source.goals.loaded",
         trace_id=trace_id, span_id="load_goals",
         correlation_id=trace_id,
         file_present=True,
         file_path=str(GOALS_PATH),
         lines_scanned=lines_scanned,
         goals_loaded=len(goals),
         validation_errors=validation_errors,
         message=f"Loaded {len(goals)} goals from goals.md")

    return goals


def _unquote(val: str) -> str:
    """Strip surrounding single or double quotes from a string value."""
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]
    return val


def _finalize_milestone(data: dict) -> dict:
    """Apply final normalization to a parsed milestone dict.

    No dedup needed — milestones no longer store task lists (membership is
    derived dynamically). This function is kept for forward compatibility
    and to ensure the dict is in canonical form.
    """
    return data


def _finalize_project(data: dict) -> dict:
    """Apply final normalization to a parsed project dict.

    Ensures all expected keys are present with defaults.
    """
    data.setdefault("goal_title", "")
    data.setdefault("milestone_title", "")
    data.setdefault("description", "")
    data.setdefault("deadline", None)
    data.setdefault("status", "open")
    data.setdefault("order", 0)
    data.setdefault("related_tasks", [])
    return data


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
        milestones=data["milestones"],
        projects=data["projects"],
        measurement_requirements=data["measurement_requirements"],
        research_artifact_titles=data["research_artifact_titles"],
        decision_numbers=data["decision_numbers"],
        followup_ids=data["followup_ids"],
        inactivity_window_days=data["inactivity_window_days"],
        recent_activity=data["recent_activity"],
    )


def _format_goal_block(goal: Goal) -> list[str]:
    """Format a Goal as lines for goals.md. Only known fields are written.

    Unknown fields are NOT preserved through update_goal rewrite.
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
    if goal.inactivity_window_days is not None:
        lines.append(f"InactivityWindowDays: {goal.inactivity_window_days}")

    if goal.related_tasks is not None and goal.related_tasks:
        lines.append("Related tasks:")
        for task in goal.related_tasks:
            lines.append(f"- {task}")

    if goal.research_artifact_titles:
        lines.append("Research artifacts:")
        for artifact in goal.research_artifact_titles:
            lines.append(f"- {artifact}")

    if goal.decision_numbers:
        lines.append("Decision numbers:")
        for num in goal.decision_numbers:
            lines.append(f"- {num}")

    if goal.followup_ids:
        lines.append("Follow-up IDs:")
        for fid in goal.followup_ids:
            lines.append(f"- {fid}")

    if goal.milestones:
        lines.append("## Milestones")
        for ms in goal.milestones:
            lines.append("")
            title = ms.get("title", "")
            order = ms.get("order", 0)
            lines.append(f"### Milestone: {title} (order: {order})")
            if ms.get("description"):
                lines.append(f"Description: {ms['description']}")
            if ms.get("deadline"):
                lines.append(f"Deadline: {ms['deadline']}")
            if ms.get("status"):
                lines.append(f"Status: {ms['status']}")
            # Note: task-to-milestone membership is NOT serialized.
            # Related tasks are stored on the Goal model and derived
            # dynamically at query time (see derive_milestone_tasks).

    if goal.projects:
        lines.append("## Projects")
        for proj in goal.projects:
            lines.append("")
            lines.append(f"### Project: {proj.get('title', '')}")
            if proj.get("milestone_title"):
                lines.append(f"Milestone: {proj['milestone_title']}")
            lines.append(f"Order: {proj.get('order', 0)}")
            if proj.get("deadline"):
                lines.append(f"Deadline: {proj['deadline']}")
            if proj.get("status"):
                lines.append(f"Status: {proj['status']}")
            if proj.get("description"):
                lines.append(f"Description: {proj['description']}")
            if proj.get("related_tasks"):
                lines.append("Related tasks:")
                for task in proj["related_tasks"]:
                    lines.append(f"- {task}")

    if goal.measurement_requirements:
        lines.append("Measurement requirements:")
        for req in goal.measurement_requirements:
            lines.append(f"  - metric: {req['metric']}")
            if req.get("unit"):
                lines.append(f"    unit: {req['unit']}")
            if req.get("frequency") and req["frequency"] != "daily":
                lines.append(f"    frequency: {req['frequency']}")
            if req.get("preferred_time") and req["preferred_time"] != "anytime":
                lines.append(f"    preferred_time: {req['preferred_time']}")
            if req.get("interval_days"):
                lines.append(f"    interval_days: {req['interval_days']}")

    if goal.recent_activity:
        lines.append("## Recent activity")
        for entry in goal.recent_activity:
            lines.append(f"# {json.dumps(entry)}")

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
