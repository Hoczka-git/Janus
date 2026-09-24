"""CLI command handlers for 'janus goal list', 'janus goal show',
'janus goal add', 'janus goal update', 'janus goal complete',
'janus goal audit'.
"""

import json
import sys
from datetime import date
from typing import Optional

from janus.services.goals import (
    add_goal,
    add_goal_via_ingest,
    complete_goal,
    complete_goal_via_ingest,
    get_goal,
    update_goal_fields,
    update_goal_via_ingest,
)
from janus.services.goal_progress import compute_goal_progress
from janus.services.milestones import (
    add_milestone_for_goal,
    get_milestone,
    get_milestones_for_goal,
    update_milestone,
    complete_milestone,
    start_milestone,
    skip_milestone,
    reopen_milestone,
)
from janus.domain.planning import derive_next_action
from janus.services.projects import (
    add_project_for_milestone,
    get_project,
    get_projects_for_goal,
    get_projects_for_milestone,
    update_project,
    complete_project,
    skip_project,
    block_project,
    start_project,
    reopen_project,
)
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

    if goal.projects:
        from janus.services.projects import get_projects_for_goal
        projects = get_projects_for_goal(goal.title)
        if projects:
            print("\n  Projects:")
            for p in projects:
                print(f"    [{p.status}] (order: {p.order}) {p.title}")
                if p.milestone_title:
                    print(f"        Milestone: {p.milestone_title}")
                if p.deadline:
                    print(f"        Deadline: {p.deadline}")
                if p.description:
                    print(f"        Description: {p.description}")
                if p.related_tasks:
                    print(f"        Tasks: {', '.join(p.related_tasks)}")
    else:
        print("\n  No projects.")

    if goal.skill_name:
        print(f"\n  Skill:       {goal.skill_name}")
        if goal.skill_evidence:
            print(f"  Evidence entries: {len(goal.skill_evidence)}")
    else:
        print("\n  Skill:       not set")


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
    skill_name: Optional[str] = None

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
            elif arg == "--skill":
                i += 1
                if i >= len(args):
                    print("Error: --skill requires a value", file=sys.stderr)
                    sys.exit(1)
                skill_name = args[i]
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
        result = add_goal_via_ingest(
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
            skill_name=skill_name,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if result.action == "rejected":
        print(f"Error: goal already exists: {title!r}", file=sys.stderr)
        sys.exit(1)

    goal = get_goal(title)

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
            elif arg == "--skill":
                i += 1
                if i >= len(args):
                    print("Error: --skill requires a value", file=sys.stderr)
                    sys.exit(1)
                updates["skill_name"] = args[i]
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
        result = update_goal_via_ingest(title, **updates)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if result.action == "rejected":
        print(f"Error: goal not found: {title!r}", file=sys.stderr)
        sys.exit(1)

    goal = get_goal(title)

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
        result = complete_goal_via_ingest(title)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if result.action == "rejected":
        print(f"Error: goal not found: {title!r}", file=sys.stderr)
        sys.exit(1)

    goal = get_goal(title)
    print(f"Completed goal: {goal.title}")


def handle_goal_skills(args: list[str]) -> None:
    """janus goal skills
    List all skills tracked across goals with evidence counts.
    """
    from janus.services.skill_tracking import list_all_skills

    skills = list_all_skills()
    print("JANUS — SKILLS")
    print("=" * 60)
    if not skills:
        print("  No skills tracked.")
        return
    print(f"  {len(skills)} skill(s) tracked:")
    for s in skills:
        print(f"    {s['skill_name']}: {s['evidence_count']} evidence entries, {len(s['goals'])} goal(s)")
        for t in s["goals"]:
            print(f"      - {t}")


def handle_goal_set_skill(args: list[str]) -> None:
    """janus goal set-skill <title> [--skill NAME]

    Set or clear the skill association on an existing goal.
    """
    if len(args) < 1:
        print("Error: goal title is required", file=sys.stderr)
        sys.exit(1)

    title_parts: list[str] = []
    skill: Optional[str] = None
    clear: bool = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--skill":
            i += 1
            if i >= len(args):
                print("Error: --skill requires a value", file=sys.stderr)
                sys.exit(1)
            skill = args[i]
        elif arg == "--clear":
            clear = True
        else:
            title_parts.append(arg)
        i += 1

    title = " ".join(title_parts)
    if not title:
        print("Error: goal title is required", file=sys.stderr)
        sys.exit(1)

    updates: dict = {}
    if clear:
        if skill is not None:
            print("Error: cannot use --clear with --skill", file=sys.stderr)
            sys.exit(1)
        updates["skill_name"] = None
    else:
        if skill is None:
            print("Error: --skill NAME is required (or use --clear to remove skill)", file=sys.stderr)
            sys.exit(1)
        updates["skill_name"] = skill.strip()

    try:
        goal = update_goal_fields(title, **updates)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if clear:
        print(f"Cleared skill on goal: {goal.title}")
    else:
        print(f"Set skill '{goal.skill_name}' on goal: {goal.title}")


# ===========================================================================
# Milestone CLI handlers
# ===========================================================================

_VALID_MILESTONE_STATUSES = ("open", "in_progress", "completed", "skipped")


def print_goal_help() -> None:
    """Print usage and available options for the ``janus goal`` command.

    Invoked when ``janus goal --help`` or ``janus goal -h`` is passed.
    """
    help_text = """\
Usage: janus goal <command> [options]

Manage long-term goals with metrics, deadlines, and related tasks.

Commands:
  list                            Display all goals grouped by status
  show <title>                    Display full details for a single goal
  add <title> [options]           Create a new goal
  update <title> [options]        Update fields of an existing goal
  complete <title>                Mark a goal as completed
  next <title>                    Print the derived next action for a goal
  health [<title>]                Show health assessment for goals
  audit [--json]                  Run Goal Integrity Audit
  skills                          List all tracked skills with evidence counts
  set-skill <title> --skill NAME  Set the skill for a goal
  set-skill <title> --clear       Clear the skill from a goal
  milestone <action> ...          Manage milestones for a goal
  project <action> ...            Manage projects under milestones

Goal options:
  --description D                 Goal description
  --status <active|completed|inactive>  Goal status (default: active)
  --deadline YYYY-MM-DD           Goal deadline
  --metric NAME                   Metric being tracked
  --unit UNIT                     Metric unit
  --start VALUE                   Starting metric value
  --current VALUE                 Current metric value
  --target VALUE                  Target metric value
  --direction <increase|decrease>  Metric direction
  --related-task TITLE            Link a related task (repeatable)
  --skill NAME                    Track this goal under a named skill

Milestone subcommands:
  add <goal> <title> [options]    Create a milestone
  list <goal>                     List milestones for a goal
  show <goal> <title>             Show a single milestone
  complete <goal> <title>         Mark a milestone as completed
  start <goal> <title>            Mark a milestone as in_progress
  skip <goal> <title>             Mark a milestone as skipped
  reopen <goal> <title>           Reopen a terminal milestone
  update <goal> <title> [options] Update a milestone
  --description D                 Milestone description
  --deadline YYYY-MM-DD           Milestone deadline
  --status <open|in_progress|completed|skipped>  Milestone status

Project subcommands:
  add <goal> <milestone> <title> [options]    Create a project under a milestone
  list <goal> [<milestone>] [--status S]      List projects
  show <goal> <milestone> <project>           Show a single project
  update <goal> <milestone> <project> [options] Update a project
  start <goal> <milestone> <project>          Mark a project as active
  complete <goal> <milestone> <project>       Mark a project as completed
  skip <goal> <milestone> <project>           Mark a project as skipped
  block <goal> <milestone> <project>          Mark a project as blocked
  reopen <goal> <milestone> <project>         Reopen a terminal project
  --description D                 Project description
  --deadline YYYY-MM-DD           Project deadline
  --status <open|active|blocked|completed|skipped>  Project status
  --add-related-task T            Assign a task to the project (repeatable)
  --remove-related-task T         Unassign a task from the project (repeatable)
"""
    print(help_text)


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
    """janus goal milestone <add|list|show|complete|update|start|skip|reopen> <goal> ..."""
    if not args:
        print("Usage: janus goal milestone <add|list|show|complete|update|start|skip|reopen> <goal> ...")
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
    elif subcommand == "start":
        _handle_goal_milestone_status_change(rest, "in_progress", "Started milestone")
    elif subcommand == "skip":
        _handle_goal_milestone_status_change(rest, "skipped", "Skipped milestone")
    elif subcommand == "reopen":
        _handle_goal_milestone_status_change(rest, "open", "Reopened milestone")
    else:
        print(f"Unknown milestone subcommand: {subcommand}")
        print("Usage: janus goal milestone <add|list|show|complete|update|start|skip|reopen> <goal> ...")
        sys.exit(1)


def _handle_goal_milestone_status_change(
    args: list[str], status: str, label: str,
) -> None:
    """Helper: change a milestone's status (start/skip/reopen)."""
    if len(args) < 2:
        print("Error: goal title and milestone title are required", file=sys.stderr)
        sys.exit(1)
    goal_title = args[0]
    ms_title = " ".join(args[1:])
    try:
        ms = update_milestone(goal_title, ms_title, status=status)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"{label}: {ms.title}")
    print(f"  Goal: {ms.goal_title}")
    print(f"  Status: {ms.status}")


# ===========================================================================
# Project CLI handlers
# ===========================================================================

_VALID_PROJECT_STATUSES = ("open", "active", "blocked", "completed", "skipped")


def handle_goal_project(args: list[str]) -> None:
    """janus goal project <add|list|show|update|start|complete|skip|block|reopen> <goal> ..."""
    if not args:
        _print_project_usage()
        sys.exit(1)
    subcommand = args[0]
    rest = args[1:]
    if subcommand == "add":
        handle_goal_project_add(rest)
    elif subcommand == "list":
        handle_goal_project_list(rest)
    elif subcommand == "show":
        handle_goal_project_show(rest)
    elif subcommand == "update":
        handle_goal_project_update(rest)
    elif subcommand == "start":
        _handle_goal_project_status_change(rest, "active", "Started project")
    elif subcommand == "complete":
        _handle_goal_project_status_change(rest, "completed", "Completed project")
    elif subcommand == "skip":
        _handle_goal_project_status_change(rest, "skipped", "Skipped project")
    elif subcommand == "block":
        _handle_goal_project_status_change(rest, "blocked", "Blocked project")
    elif subcommand == "reopen":
        _handle_goal_project_status_change(rest, "open", "Reopened project")
    else:
        print(f"Unknown project subcommand: {subcommand}")
        _print_project_usage()
        sys.exit(1)


def _print_project_usage() -> None:
    print("Usage: janus goal project <add|list|show|update|start|complete|skip|block|reopen> <goal> ...")


def _handle_goal_project_status_change(
    args: list[str], status: str, label: str,
) -> None:
    """Helper: change a project's status (start/complete/skip/block/reopen)."""
    if len(args) < 3:
        print("Error: goal title, milestone title, and project title are required", file=sys.stderr)
        sys.exit(1)
    goal_title = args[0]
    milestone_title = args[1]
    project_title = " ".join(args[2:])
    try:
        if status == "active":
            proj = start_project(goal_title, milestone_title, project_title)
        elif status == "completed":
            proj = complete_project(goal_title, milestone_title, project_title)
        elif status == "skipped":
            proj = skip_project(goal_title, milestone_title, project_title)
        elif status == "blocked":
            proj = block_project(goal_title, milestone_title, project_title)
        else:
            proj = reopen_project(goal_title, milestone_title, project_title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"{label}: {proj.title}")
    print(f"  Goal: {goal_title}")
    print(f"  Milestone: {milestone_title}")
    print(f"  Status: {proj.status}")


def handle_goal_project_add(args: list[str]) -> None:
    """janus goal project add <goal> <milestone> <title> [options]"""
    if len(args) < 3:
        print("Error: goal title, milestone title, and project title are required", file=sys.stderr)
        sys.exit(1)
    goal_title = args[0]
    milestone_title = args[1]
    title_parts: list[str] = []
    description: str = ""
    deadline: str | None = None
    status: str = "open"
    related_tasks: list[str] = []

    i = 2
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
                if status not in _VALID_PROJECT_STATUSES:
                    print(
                        f"Error: invalid status {status!r}. "
                        f"Allowed: {', '.join(_VALID_PROJECT_STATUSES)}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            elif arg == "--add-related-task":
                i += 1
                if i >= len(args):
                    print("Error: --add-related-task requires a value", file=sys.stderr)
                    sys.exit(1)
                related_tasks.append(args[i])
            else:
                print(f"Error: unknown argument: {arg}", file=sys.stderr)
                sys.exit(1)
        else:
            title_parts.append(arg)
        i += 1

    if not title_parts:
        print("Error: project title is required", file=sys.stderr)
        sys.exit(1)
    title = " ".join(title_parts)

    try:
        proj = add_project_for_milestone(
            goal_title, milestone_title, title,
            description=description, deadline=deadline,
            status=status, related_tasks=related_tasks,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Added project: {proj.title} (order: {proj.order})")
    print(f"  Goal: {goal_title}")
    print(f"  Milestone: {milestone_title}")
    print(f"  Status: {proj.status}")


def handle_goal_project_list(args: list[str]) -> None:
    """janus goal project list <goal> [<milestone>] [--status S]"""
    if not args:
        print("Error: goal title is required", file=sys.stderr)
        sys.exit(1)

    goal_title = args[0]
    milestone_title: str | None = None
    status_filter: str | None = None

    remaining = args[1:]
    i = 0
    positional: list[str] = []
    while i < len(remaining):
        arg = remaining[i]
        if arg == "--status":
            i += 1
            if i >= len(remaining):
                print("Error: --status requires a value", file=sys.stderr)
                sys.exit(1)
            status_filter = remaining[i]
            if status_filter not in _VALID_PROJECT_STATUSES:
                print(
                    f"Error: invalid status {status_filter!r}. "
                    f"Allowed: {', '.join(_VALID_PROJECT_STATUSES)}",
                    file=sys.stderr,
                )
                sys.exit(1)
        elif arg.startswith("--"):
            print(f"Error: unknown argument: {arg}", file=sys.stderr)
            sys.exit(1)
        else:
            positional.append(arg)
        i += 1

    if positional:
        milestone_title = " ".join(positional)

    try:
        if milestone_title:
            projs = get_projects_for_milestone(goal_title, milestone_title)
        else:
            projs = get_projects_for_goal(goal_title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"JANUS — PROJECTS: {goal_title}")
    print("=" * 60)
    if milestone_title:
        print(f"  Milestone: {milestone_title}")
    if not projs:
        print("  No projects defined.")
        return

    for p in projs:
        if status_filter and p.status != status_filter:
            continue
        print(f"  [{p.status}] (order: {p.order}) {p.title}")
        if p.milestone_title:
            print(f"      Milestone: {p.milestone_title}")
        if p.deadline:
            print(f"      Deadline: {p.deadline}")
        if p.description:
            print(f"      Description: {p.description}")
        if p.related_tasks:
            print(f"      Tasks: {', '.join(p.related_tasks)}")


def handle_goal_project_show(args: list[str]) -> None:
    """janus goal project show <goal> <milestone> <project>"""
    if len(args) < 3:
        print("Error: goal title, milestone title, and project title are required", file=sys.stderr)
        sys.exit(1)
    goal_title = args[0]
    milestone_title = args[1]
    project_title = " ".join(args[2:])
    try:
        proj = get_project(goal_title, milestone_title, project_title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"JANUS — PROJECT: {proj.title}")
    print("=" * 60)
    print(f"  Goal:      {goal_title}")
    print(f"  Milestone: {proj.milestone_title}")
    print(f"  Status:    {proj.status}")
    print(f"  Order:     {proj.order}")
    if proj.deadline:
        print(f"  Deadline:  {proj.deadline}")
    else:
        print("  Deadline:  not set")
    if proj.description:
        print(f"  Description: {proj.description}")
    else:
        print("  Description: (none)")
    if proj.related_tasks:
        print("  Related tasks:")
        for t in proj.related_tasks:
            print(f"    - {t}")
    else:
        print("  No related tasks.")


def handle_goal_project_update(args: list[str]) -> None:
    """janus goal project update <goal> <milestone> <project> [options]"""
    if len(args) < 3:
        print("Error: goal title, milestone title, and project title are required", file=sys.stderr)
        sys.exit(1)
    goal_title = args[0]
    milestone_title = args[1]
    title_parts: list[str] = []
    updates: dict = {}
    add_tasks: list[str] = []
    remove_tasks: list[str] = []

    i = 2
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            if arg == "--description":
                i += 1
                if i >= len(args):
                    print("Error: --description requires a value", file=sys.stderr)
                    sys.exit(1)
                updates["description"] = args[i]
            elif arg == "--deadline":
                i += 1
                if i >= len(args):
                    print("Error: --deadline requires a value (YYYY-MM-DD)", file=sys.stderr)
                    sys.exit(1)
                updates["deadline"] = args[i]
                _ = _parse_date(updates["deadline"])
            elif arg == "--status":
                i += 1
                if i >= len(args):
                    print("Error: --status requires a value", file=sys.stderr)
                    sys.exit(1)
                status = args[i]
                if status not in _VALID_PROJECT_STATUSES:
                    print(
                        f"Error: invalid status {status!r}. "
                        f"Allowed: {', '.join(_VALID_PROJECT_STATUSES)}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                updates["status"] = status
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
        else:
            title_parts.append(arg)
        i += 1

    if not title_parts:
        print("Error: project title is required", file=sys.stderr)
        sys.exit(1)

    project_title = " ".join(title_parts)

    try:
        proj = update_project(goal_title, milestone_title, project_title, **updates)
        for t in add_tasks:
            proj = update_project(goal_title, milestone_title, project_title,
                                  add_related_task=t)
        for t in remove_tasks:
            proj = update_project(goal_title, milestone_title, project_title,
                                  remove_related_task=t)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Updated project: {proj.title}")
    print(f"  Goal: {goal_title}")
    print(f"  Milestone: {milestone_title}")
    print(f"  Status: {proj.status}")
    print(f"  Order: {proj.order}")
    if proj.related_tasks:
        print(f"  Related tasks: {', '.join(proj.related_tasks)}")


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
    from janus.domain.planning import project_objs
    from janus.services.weekly_review import _read_completed_task_titles
    completed_titles = set(_read_completed_task_titles())
    from datetime import date
    today = date.today()

    action = derive_next_action(goal, tasks, completed_titles, today,
                                projects=project_objs(goal))
    if action is None:
        print("No next action.")
        return
    print(f"Next action: {action.title} ({action.kind})")
    print(f"  Reason: {action.reason}")
    print(f"  Goal: {action.goal_title}")


def handle_goal_health(args: list[str]) -> None:
    """janus goal health [<title>]
    Display health assessment for one or all active goals.

    Without a title: lists all active goals with health state, sorted by
    severity (stalled first, then watch, then healthy).
    With a title: shows full health assessment for that single goal.
    """
    from janus.integrations.markdown_goals import load_goals
    from janus.integrations.markdown_tasks import load_tasks, TASKS_PATH
    from janus.services.weekly_review import _read_completed_task_titles
    from janus.services.goal_health import assess_goal_health
    from datetime import date

    goals = load_goals()
    open_task_titles: set[str] = set()
    all_task_titles: set[str] = set()
    if TASKS_PATH.exists():
        tasks = load_tasks()
        open_task_titles = {t.title for t in tasks}
        all_task_titles = {t.title for t in tasks}
    completed_titles = _read_completed_task_titles()
    all_task_titles |= set(completed_titles)

    # Build completed_task_dates for days_since_last_activity
    today = date.today()
    completed_task_dates: dict[str, date] | None = None
    # We don't have task completion timestamps in the current model;
    # this is a known limitation (design §13.4 / open question 1).
    # Pass None to indicate no completion date data available.

    if args:
        # Single goal
        title = " ".join(args)
        matching = [g for g in goals if g.title == title]
        if not matching:
            print(f"Error: goal not found: {title}", file=sys.stderr)
            sys.exit(1)
        goal = matching[0]
        if goal.status != "active":
            print(f"Goal '{goal.title}' is {goal.status} — health assessment only "
                  f"applies to active goals.", file=sys.stderr)
            sys.exit(1)
        assessment = assess_goal_health(
            goal, today, open_task_titles, all_task_titles,
            completed_task_dates=completed_task_dates,
        )
        if assessment is None:
            print(f"Goal '{goal.title}' has no health assessment (inactive).",
                  file=sys.stderr)
            sys.exit(1)
        _print_health_detail(assessment)
        return

    # All goals
    assessments = []
    for g in goals:
        if g.status != "active":
            continue
        a = assess_goal_health(
            g, today, open_task_titles, all_task_titles,
            completed_task_dates=completed_task_dates,
        )
        if a is not None:
            assessments.append(a)

    # Sort by severity: stalled, watch, healthy
    severity_order = {"stalled": 0, "watch": 1, "healthy": 2, "completed": 3}
    assessments.sort(
        key=lambda a: (severity_order.get(a.health_state, 4), a.goal_title)
    )

    print("JANUS — GOAL HEALTH")
    print("=" * 60)
    if not assessments:
        print("No active goals to assess.")
        return
    for a in assessments:
        dom = a.dominant_signal
        if dom:
            print(f"  {a.goal_title:<40} {a.health_state:<8} "
                  f"[score: {dom.score}] {dom.reason}")
        else:
            print(f"  {a.goal_title:<40} {a.health_state:<8}")


def _print_health_detail(assessment) -> None:
    """Print full health assessment for a single goal."""
    print(f"JANUS — GOAL HEALTH: {assessment.goal_title}")
    print("=" * 60)
    print(f"  Health state:     {assessment.health_state}")
    print(f"  Progress:         {assessment.progress:.1f}%" if assessment.progress is not None else "  Progress:         N/A")
    if assessment.progress_delta is not None:
        print(f"  Progress delta:   {assessment.progress_delta:+.1f}%")
    else:
        print("  Progress delta:   N/A")
    if assessment.days_since_last_activity is not None:
        print(f"  Last activity:    {assessment.days_since_last_activity} days ago")
    else:
        print("  Last activity:    N/A")
    print(f"  Measurements overdue: {assessment.measurement_overdue_count}")
    print()

    if assessment.signals:
        print("  Signals:")
        for s in sorted(assessment.signals, key=lambda x: x.score, reverse=True):
            marker = " * " if s == assessment.dominant_signal else "   "
            category_str = f" ({s.category})" if s.category else ""
            print(f"  {marker} [{s.score:3d}] {s.signal}{category_str}: {s.reason}")
    else:
        print("  Signals: none (healthy)")


def handle_goal_audit(args: list[str]) -> None:
    """janus goal audit [--json]
    Run a deterministic Goal Integrity Audit and print the results.

    Without --json: human-readable summary (spec sec 9).
    With --json: machine-readable JSON report (spec sec 10).

    Exit code is non-zero when one or more error-severity issues are found
    (spec sec 11). Warnings alone do not cause failure.
    """
    from janus.integrations.markdown_goals import load_goals
    from janus.integrations.markdown_tasks import load_tasks
    from janus.services.goal_integrity import audit_goal_integrity
    from datetime import datetime

    as_json = "--json" in args

    goals = load_goals()
    tasks = load_tasks() if goals else []
    now = datetime.now().astimezone()

    report = audit_goal_integrity(goals=goals, tasks=tasks, now=now)

    if as_json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        _print_audit_report(report)

    if report.has_errors:
        sys.exit(1)


def _print_audit_report(report) -> None:
    """Render a GoalIntegrityReport in human-readable form (spec sec 9)."""
    print("Goal Integrity Audit")
    print("=" * 60)
    print(f"Goals checked: {report.goals_checked}")
    print(f"Tasks checked: {report.tasks_checked}")
    print()

    if report.issues:
        print("Issues:")
        by_code: dict[str, list] = {}
        for issue in report.issues:
            by_code.setdefault(issue.code, []).append(issue)
        for code in sorted(by_code):
            severity_marker = "X" if by_code[code][0].severity == "error" else "!"
            count = len(by_code[code])
            print(f"  {severity_marker} {code:<32} {count}")
        print()

        print("Details:")
        for issue in report.issues:
            marker = "X" if issue.severity == "error" else "!"
            goal_str = f"goal={issue.goal_id}" if issue.goal_id else ""
            task_str = f"task={issue.task_id}" if issue.task_id else ""
            locator = ", ".join(p for p in (goal_str, task_str) if p)
            print(f"  {marker} {issue.code} ({locator}): {issue.message}")
        print()
    else:
        print("No issues found.")
        print()

    print("Summary:")
    print(f"  Errors:   {report.error_count}")
    print(f"  Warnings: {report.warning_count}")
    print(f"  Info:     {report.info_count}")

