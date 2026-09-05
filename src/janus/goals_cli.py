"""CLI command handlers for 'janus goal list', 'janus goal show',
'janus goal add', 'janus goal update', and 'janus goal complete'.
"""

from datetime import date
import sys
from typing import Optional

from janus.services.goals import (
    add_goal,
    complete_goal,
    get_goal,
    update_goal_fields,
)
from janus.services.goal_progress import compute_goal_progress
from janus.services.milestones import (
    add_milestone_for_goal,
    get_milestone,
    get_milestones_for_goal,
    update_milestone,
    complete_milestone,
)
from janus.services.next_action import derive_next_action
from janus.integrations.markdown_tasks import (
    TASKS_PATH,
    load_tasks,
)


def _parse_date(s: Optional[str]) -> date | None:
    """Parse YYYY-MM-DD or return None."""
    if s is None:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        print(f"Error: invalid date: {s}", file=sys.stderr)
        sys.exit(1)


def _parse_float(s: Optional[str]) -> float | None:
    """Parse a float or exit with error."""
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        print(f"Error: invalid number: {s}", file=sys.stderr)
        sys.exit(1)


def handle_goal_list(args: list[str]) -> None:
    """janus goal list
    Display all goals grouped by status with progress.
    """
    if args:
        print("Error: 'goal list' does not accept arguments", file=sys.stderr)
        sys.exit(1)

    from janus.integrations.markdown_goals import load_goals
    from janus.services.goal_progress import compute_goal_progress
    from janus.integrations.markdown_tasks import load_tasks as _load_tasks
    import janus.integrations.markdown_tasks as _md_tasks

    goals = load_goals()
    tasks = _load_tasks()
    completed_titles = {t.title for t in tasks if t.state == "done"}

    # Also read completed tasks from raw file (load_tasks filters them out)
    if _md_tasks.TASKS_PATH.exists():
        for line in _md_tasks.TASKS_PATH.read_text().splitlines():
            if line.startswith("- [x] "):
                content = line[5:].strip()
                title = content.split(" | ")[0] if " | " in content else content
                completed_titles.add(title)

    active: list[tuple[str, float | None, str | None]] = []
    completed_list: list[tuple[str, float | None, str | None]] = []
    inactive_list: list[tuple[str, float | None, str | None]] = []

    for g in goals:
        prog = compute_goal_progress(g, completed_titles)
        detail = _goal_progress_detail(g, prog, completed_titles)
        entry = (g.title, prog, detail)
        if g.status == "active":
            active.append(entry)
        elif g.status == "completed":
            completed_list.append(entry)
        else:
            inactive_list.append(entry)

    print("JANUS — GOALS")
    print("=" * 60)

    def _print_group(name: str, items: list[tuple[str, float | None, str | None]]) -> None:
        print(f"\n{name} ({len(items)}):")
        if not items:
            print("  —")
            return
        for title, prog, detail in items:
            if prog is not None:
                print(f"  {title:<40} {prog:5.1f}%   {detail}")
            else:
                print(f"  {title:<40} N/A     {detail or 'no progress'}")

    _print_group("ACTIVE", active)
    _print_group("COMPLETED", completed_list)
    _print_group("INACTIVE", inactive_list)


def _goal_progress_detail(
    goal,
    prog: float | None,
    completed_titles: set[str],
) -> str | None:
    """Build human-readable progress detail line (no duplicate %)."""
    if prog is None:
        if goal.metric_name and goal.target_value is not None:
            return f"{goal.current_value} → {goal.target_value}, {goal.direction or 'no direction'}"
        if goal.related_tasks:
            completed = sum(1 for rt in goal.related_tasks if rt in completed_titles)
            return f"{completed}/{len(goal.related_tasks)} tasks completed"
        return None

    if goal.metric_name and goal.target_value is not None:
        return f"{goal.current_value} → {goal.target_value}, {goal.direction}"
    if goal.related_tasks:
        completed = sum(1 for rt in goal.related_tasks if rt in completed_titles)
        return f"{completed}/{len(goal.related_tasks)} tasks completed"
    return None


def handle_goal_show(args: list[str]) -> None:
    """janus goal show <title>
    Display single goal with full details and progress.
    """
    if len(args) < 1:
        print("Error: goal title is required", file=sys.stderr)
        sys.exit(1)
    title = " ".join(args)
    try:
        goal = get_goal(title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    from janus.integrations.markdown_goals import load_goals
    from janus.services.goal_progress import compute_goal_progress
    from janus.integrations.markdown_tasks import load_tasks

    tasks = load_tasks()
    completed_titles = {t.title for t in tasks if t.state == "done"}
    prog = compute_goal_progress(goal, completed_titles)
    detail = _goal_progress_detail(goal, prog, completed_titles)

    print("JANUS — GOAL: " + goal.title)
    print("=" * 60)
    print(f"  Status:      {goal.status}")
    if goal.deadline:
        print(f"  Deadline:    {goal.deadline}")
    else:
        print("  Deadline:    not set")
    if goal.metric_name:
        print(f"  Metric:      {goal.metric_name}")
        if goal.metric_unit:
            print(f"  Unit:        {goal.metric_unit}")
        if goal.start_value is not None:
            print(f"  Start:       {goal.start_value}")
        if goal.current_value is not None:
            print(f"  Current:     {goal.current_value}")
        if goal.target_value is not None:
            print(f"  Target:      {goal.target_value}")
        if goal.direction:
            print(f"  Direction:   {goal.direction}")
    if prog is not None:
        print(f"  Progress:    {prog:.1f}%")
    else:
        # Show N/A only if goal has NO related tasks.
        # If related tasks exist but none are completed, show 0.0% (real data).
        if goal.related_tasks:
            print("  Progress:    0.0%")
        else:
            print("  Progress:    N/A")
    if detail:
        print(f"  Detail:      {detail}")

    if goal.related_tasks:
        print("\n  Related tasks:")
        for rt in goal.related_tasks:
            state = "completed" if rt in completed_titles else "open"
            print(f"    - {rt} ({state})")
    else:
        print("\n  No related tasks.")
    if goal.milestones:
        from janus.services.milestones import get_milestones_for_goal
        milestones = get_milestones_for_goal(goal.title)
        if milestones:
            print("\n  Milestones:")
            for ms in milestones:
                print(f"    [{ms.status}] (order: {ms.order}) {ms.title}")
                if ms.deadline:
                    print(f"        Deadline: {ms.deadline}")
                if ms.description:
                    print(f"        Description: {ms.description}")
    else:
        print("\n  No milestones.")


def handle_goal_add(args: list[str]) -> None:
    """janus goal add <title> [options]
    Create a new goal.
    """
    title_parts: list[str] = []
    description: str = ""
    status: str = "active"
    deadline: Optional[str] = None
    metric_name: Optional[str] = None
    metric_unit: Optional[str] = None
    start_value: Optional[float] = None
    current_value: Optional[float] = None
    target_value: Optional[float] = None
    direction: Optional[str] = None
    related_tasks: list[str] = []

    state = "parse_title"
    i = 0
    while i < len(args):
        arg = args[i]
        if state == "parse_title":
            if arg.startswith("--"):
                state = "parse_flags"
                continue
            else:
                title_parts.append(arg)
        elif state == "parse_flags":
            if arg == "--description":
                i += 1
                if i >= len(args):
                    print("Error: --description requires a value", file=sys.stderr)
                    sys.exit(1)
                description = args[i]
            elif arg == "--status":
                i += 1
                if i >= len(args):
                    print("Error: --status requires a value", file=sys.stderr)
                    sys.exit(1)
                status = args[i]
                if status not in ("active", "completed", "inactive"):
                    print(
                        f"Error: invalid status {status!r}. "
                        f"Allowed: active, completed, inactive",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            elif arg == "--deadline":
                i += 1
                if i >= len(args):
                    print("Error: --deadline requires a value (YYYY-MM-DD)", file=sys.stderr)
                    sys.exit(1)
                deadline = args[i]
                _ = _parse_date(deadline)  # validates, result discarded (we store string)
            elif arg == "--metric":
                i += 1
                if i >= len(args):
                    print("Error: --metric requires a value", file=sys.stderr)
                    sys.exit(1)
                metric_name = args[i]
            elif arg == "--unit":
                i += 1
                if i >= len(args):
                    print("Error: --unit requires a value", file=sys.stderr)
                    sys.exit(1)
                metric_unit = args[i]
            elif arg == "--start":
                i += 1
                if i >= len(args):
                    print("Error: --start requires a value", file=sys.stderr)
                    sys.exit(1)
                start_value = _parse_float(args[i])
            elif arg == "--current":
                i += 1
                if i >= len(args):
                    print("Error: --current requires a value", file=sys.stderr)
                    sys.exit(1)
                current_value = _parse_float(args[i])
            elif arg == "--target":
                i += 1
                if i >= len(args):
                    print("Error: --target requires a value", file=sys.stderr)
                    sys.exit(1)
                target_value = _parse_float(args[i])
            elif arg == "--direction":
                i += 1
                if i >= len(args):
                    print("Error: --direction requires a value", file=sys.stderr)
                    sys.exit(1)
                direction = args[i]
                if direction not in ("increase", "decrease"):
                    print(
                        f"Error: invalid direction {direction!r}. "
                        f"Allowed: increase, decrease",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            elif arg == "--related-task":
                i += 1
                if i >= len(args):
                    print("Error: --related-task requires a value", file=sys.stderr)
                    sys.exit(1)
                related_tasks.append(args[i])
            else:
                print(f"Error: unknown argument: {arg}", file=sys.stderr)
                sys.exit(1)
        i += 1

    if not title_parts:
        print("Error: goal title is required", file=sys.stderr)
        sys.exit(1)

    title = " ".join(title_parts)
    if status == "active" and not metric_name and not related_tasks:
        pass  # minimal goal is OK

    try:
        goal = add_goal(
            title=title,
            description=description,
            status=status,
            deadline=deadline,
            metric_name=metric_name,
            metric_unit=metric_unit,
            start_value=start_value,
            current_value=current_value,
            target_value=target_value,
            direction=direction,
            related_tasks=related_tasks,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Added goal: {goal.title}")
    print(f"  Status: {goal.status}")
    if goal.metric_name:
        print(f"  Metric: {goal.metric_name} (target: {goal.target_value}, {goal.direction})")
        from janus.services.goal_progress import compute_goal_progress
        from janus.integrations.markdown_tasks import load_tasks
        tasks = load_tasks()
        completed_titles = {t.title for t in tasks if t.state == "done"}
        prog = compute_goal_progress(goal, completed_titles)
        if prog is not None:
            print(f"  Progress: {prog:.1f}%")
    elif goal.related_tasks:
        print(f"  Related tasks: {', '.join(goal.related_tasks)}")


def handle_goal_update(args: list[str]) -> None:
    """janus goal update <title> [options]
    Update specific fields of an existing goal.
    """
    title_parts: list[str] = []
    updates: dict = {}
    add_tasks: list[str] = []
    remove_tasks: list[str] = []

    state = "parse_title"
    i = 0
    while i < len(args):
        arg = args[i]
        if state == "parse_title":
            if arg.startswith("--"):
                state = "parse_flags"
                continue
            else:
                title_parts.append(arg)
        elif state == "parse_flags":
            if arg == "--description":
                i += 1
                if i >= len(args):
                    print("Error: --description requires a value", file=sys.stderr)
                    sys.exit(1)
                updates["description"] = args[i]
            elif arg == "--status":
                i += 1
                if i >= len(args):
                    print("Error: --status requires a value", file=sys.stderr)
                    sys.exit(1)
                updates["status"] = args[i]
                if updates["status"] not in ("active", "completed", "inactive"):
                    print(
                        f"Error: invalid status {updates['status']!r}. "
                        f"Allowed: active, completed, inactive",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            elif arg == "--deadline":
                i += 1
                if i >= len(args):
                    print("Error: --deadline requires a value (YYYY-MM-DD)", file=sys.stderr)
                    sys.exit(1)
                updates["deadline"] = args[i]
                _ = _parse_date(updates["deadline"])
            elif arg == "--metric":
                i += 1
                if i >= len(args):
                    print("Error: --metric requires a value", file=sys.stderr)
                    sys.exit(1)
                updates["metric_name"] = args[i]
            elif arg == "--unit":
                i += 1
                if i >= len(args):
                    print("Error: --unit requires a value", file=sys.stderr)
                    sys.exit(1)
                updates["metric_unit"] = args[i]
            elif arg == "--start":
                i += 1
                if i >= len(args):
                    print("Error: --start requires a value", file=sys.stderr)
                    sys.exit(1)
                updates["start_value"] = _parse_float(args[i])
            elif arg == "--current":
                i += 1
                if i >= len(args):
                    print("Error: --current requires a value", file=sys.stderr)
                    sys.exit(1)
                updates["current_value"] = _parse_float(args[i])
            elif arg == "--target":
                i += 1
                if i >= len(args):
                    print("Error: --target requires a value", file=sys.stderr)
                    sys.exit(1)
                updates["target_value"] = _parse_float(args[i])
            elif arg == "--direction":
                i += 1
                if i >= len(args):
                    print("Error: --direction requires a value", file=sys.stderr)
                    sys.exit(1)
                updates["direction"] = args[i]
                if updates["direction"] not in ("increase", "decrease"):
                    print(
                        f"Error: invalid direction {updates['direction']!r}. "
                        f"Allowed: increase, decrease",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            elif arg == "--add-related-task":
                i += 1
                if i >= len(args):
                    print("Error: --add-related-task requires a value", file=sys.stderr)
                    sys.exit(1)
                add_tasks.append(args[i])
            elif arg == "--remove-related-task":
                i += 1
                if i >= len(args):
                    print("Error: --remove-related-task requires a value", file=sys.stderr)
                    sys.exit(1)
                remove_tasks.append(args[i])
            else:
                print(f"Error: unknown argument: {arg}", file=sys.stderr)
                sys.exit(1)
        i += 1

    if not title_parts:
        print("Error: goal title is required", file=sys.stderr)
        sys.exit(1)

    title = " ".join(title_parts)
    for t in add_tasks:
        updates["add_related_task"] = t
    for t in remove_tasks:
        updates["remove_related_task"] = t

    try:
        goal = update_goal_fields(title, **updates)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Updated goal: {goal.title}")
    if "current_value" in updates or "target_value" in updates or "start_value" in updates:
        from janus.services.goal_progress import compute_goal_progress
        from janus.integrations.markdown_tasks import load_tasks
        tasks = load_tasks()
        completed_titles = {t.title for t in tasks if t.state == "done"}
        prog = compute_goal_progress(goal, completed_titles)
        if prog is not None:
            print(f"  Progress: {prog:.1f}%")


def handle_goal_complete(args: list[str]) -> None:
    """janus goal complete <title>
    Mark a goal as completed (manual action).
    """
    if len(args) < 1:
        print("Error: goal title is required", file=sys.stderr)
        sys.exit(1)
    title = " ".join(args)
    try:
        goal = complete_goal(title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Completed goal: {goal.title}")


# ===========================================================================
# Milestone CLI handlers
# ===========================================================================

_VALID_MILESTONE_STATUSES = ("open", "in_progress", "completed", "skipped")


def handle_goal_milestone_list(args: list[str]) -> None:
    """janus goal milestone list <goal_title>
    Display ordered milestones for a goal.
    """
    if not args:
        print("Error: goal title is required", file=sys.stderr)
        sys.exit(1)
    goal_title = " ".join(args)
    try:
        milestones = get_milestones_for_goal(goal_title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"JANUS — MILESTONES: {goal_title}")
    print("=" * 60)
    if not milestones:
        print("  No milestones defined.")
        return
    for ms in milestones:
        print(f"  [{ms.status}] (order: {ms.order}) {ms.title}")
        if ms.deadline:
            print(f"      Deadline: {ms.deadline}")
        if ms.description:
            print(f"      Description: {ms.description}")


def handle_goal_milestone_show(args: list[str]) -> None:
    """janus goal milestone show <goal_title> <milestone_title>
    Display full details for a single milestone.
    """
    if len(args) < 2:
        print("Error: goal title and milestone title are required", file=sys.stderr)
        sys.exit(1)
    goal_title = args[0]
    ms_title = " ".join(args[1:])
    try:
        ms = get_milestone(goal_title, ms_title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"JANUS — MILESTONE: {ms.title}")
    print("=" * 60)
    print(f"  Goal:      {ms.goal_title}")
    print(f"  Status:    {ms.status}")
    if ms.deadline:
        print(f"  Deadline:  {ms.deadline}")
    else:
        print("  Deadline:  not set")
    if ms.description:
        print(f"  Description: {ms.description}")
    else:
        print("  Description: (none)")
    print(f"  Order:     {ms.order}")
    # Task membership is derived dynamically — see derive_milestone_tasks


def handle_goal_milestone_add(args: list[str]) -> None:
    """janus goal milestone add <goal_title> <title> [--description D] [--deadline D] [--status S]
    Create a new milestone for a goal.

    Task-to-milestone membership is NOT stored. Use ``janus goal update
    --add-related-task`` to add tasks to the goal's related_tasks list;
    they are dynamically assigned to the earliest non-terminal milestone.
    """
    if len(args) < 2:
        print("Error: goal title and milestone title are required", file=sys.stderr)
        sys.exit(1)
    goal_title = args[0]
    title_parts: list[str] = []
    description: str = ""
    deadline: str | None = None
    status: str = "open"

    i = 1
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            if arg == "--description":
                i += 1
                if i >= len(args):
                    print("Error: --description requires a value", file=sys.stderr)
                    sys.exit(1)
                description = args[i]
            elif arg == "--deadline":
                i += 1
                if i >= len(args):
                    print("Error: --deadline requires a value (YYYY-MM-DD)", file=sys.stderr)
                    sys.exit(1)
                deadline = args[i]
                _ = _parse_date(deadline)
            elif arg == "--status":
                i += 1
                if i >= len(args):
                    print("Error: --status requires a value", file=sys.stderr)
                    sys.exit(1)
                status = args[i]
                if status not in _VALID_MILESTONE_STATUSES:
                    print(
                        f"Error: invalid status {status!r}. "
                        f"Allowed: {', '.join(_VALID_MILESTONE_STATUSES)}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            else:
                print(f"Error: unknown argument: {arg}", file=sys.stderr)
                sys.exit(1)
        else:
            title_parts.append(arg)
        i += 1

    if not title_parts:
        print("Error: milestone title is required", file=sys.stderr)
        sys.exit(1)
    ms_title = " ".join(title_parts)

    try:
        ms = add_milestone_for_goal(
            goal_title, ms_title,
            description=description, deadline=deadline,
            status=status,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Added milestone: {ms.title} (order: {ms.order})")
    print(f"  Goal: {ms.goal_title}")
    print(f"  Status: {ms.status}")
    if ms.deadline:
        print(f"  Deadline: {ms.deadline}")


def handle_goal_milestone_complete(args: list[str]) -> None:
    """janus goal milestone complete <goal_title> <milestone_title>
    Mark a milestone as completed.
    """
    if len(args) < 2:
        print("Error: goal title and milestone title are required", file=sys.stderr)
        sys.exit(1)
    goal_title = args[0]
    ms_title = " ".join(args[1:])
    try:
        ms = complete_milestone(goal_title, ms_title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Completed milestone: {ms.title}")
    print(f"  Goal: {ms.goal_title}")


def handle_goal_milestone_update(args: list[str]) -> None:
    """janus goal milestone update <goal_title> <milestone_title> [options]
    Update fields of an existing milestone.
    """
    if len(args) < 2:
        print("Error: goal title and milestone title are required", file=sys.stderr)
        sys.exit(1)
    goal_title = args[0]
    ms_title = args[1]
    remaining = args[2:]

    updates: dict = {}
    i = 0
    while i < len(remaining):
        arg = remaining[i]
        if arg == "--description":
            i += 1
            if i >= len(remaining):
                print("Error: --description requires a value", file=sys.stderr)
                sys.exit(1)
            updates["description"] = remaining[i]
        elif arg == "--deadline":
            i += 1
            if i >= len(remaining):
                print("Error: --deadline requires a value (YYYY-MM-DD)", file=sys.stderr)
                sys.exit(1)
            updates["deadline"] = remaining[i]
            _ = _parse_date(updates["deadline"])
        elif arg == "--status":
            i += 1
            if i >= len(remaining):
                print("Error: --status requires a value", file=sys.stderr)
                sys.exit(1)
            status = remaining[i]
            if status not in _VALID_MILESTONE_STATUSES:
                print(
                    f"Error: invalid status {status!r}. "
                    f"Allowed: {', '.join(_VALID_MILESTONE_STATUSES)}",
                    file=sys.stderr,
                )
                sys.exit(1)
            updates["status"] = status
        elif arg == "--title":
            i += 1
            if i >= len(remaining):
                print("Error: --title requires a value", file=sys.stderr)
                sys.exit(1)
            updates["title"] = remaining[i]
        else:
            print(f"Error: unknown argument: {arg}", file=sys.stderr)
            sys.exit(1)
        i += 1

    try:
        ms = update_milestone(goal_title, ms_title, **updates)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Updated milestone: {ms.title}")
    print(f"  Status: {ms.status}")
    if ms.deadline:
        print(f"  Deadline: {ms.deadline}")


def handle_goal_milestone(args: list[str]) -> None:
    """janus goal milestone <add|list|show|complete|update> <goal> ..."""
    if not args:
        print("Usage: janus goal milestone <add|list|show|complete|update> <goal> ...")
        sys.exit(1)
    subcommand = args[0]
    rest = args[1:]
    if subcommand == "list":
        handle_goal_milestone_list(rest)
    elif subcommand == "show":
        handle_goal_milestone_show(rest)
    elif subcommand == "add":
        handle_goal_milestone_add(rest)
    elif subcommand == "complete":
        handle_goal_milestone_complete(rest)
    elif subcommand == "update":
        handle_goal_milestone_update(rest)
    else:
        print(f"Unknown milestone subcommand: {subcommand}")
        print("Usage: janus goal milestone <add|list|show|complete|update> <goal> ...")
        sys.exit(1)


def handle_goal_next(args: list[str]) -> None:
    """janus goal next <title>
    Print the derived next action for a goal, with its reason.
    """
    if not args:
        print("Error: goal title is required", file=sys.stderr)
        sys.exit(1)
    goal_title = " ".join(args)
    try:
        goal = get_goal(goal_title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    tasks = load_tasks()
    from janus.services.weekly_review import _read_completed_task_titles
    completed_titles = set(_read_completed_task_titles())
    from datetime import date
    today = date.today()

    action = derive_next_action(goal, tasks, completed_titles, today)
    if action is None:
        print("No next action.")
        return
    print(f"Next action: {action.title} ({action.kind})")
    print(f"  Reason: {action.reason}")
    print(f"  Goal: {action.goal_title}")
