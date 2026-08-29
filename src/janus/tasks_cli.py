"""CLI command handlers for 'janus task add', 'janus task complete',
'janus task state', and 'janus task progress'.
"""

from datetime import date
import sys

from janus.services.tasks import (
    add_task,
    complete_task,
    set_task_state,
    set_task_progress,
)

ALLOWED_STATES = frozenset({"todo", "in_progress", "blocked"})


def handle_task_add(args: list[str]) -> None:
    """Parse 'janus task add' arguments and call the task write service.

    Usage:
        janus task add "Title"
        janus task add "Title" --due 2026-09-04 --priority 2
    """
    title_parts: list[str] = []
    due_date: date | None = None
    priority: int | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--due":
            i += 1
            if i >= len(args):
                print("Error: --due requires a value (YYYY-MM-DD)", file=sys.stderr)
                sys.exit(1)
            try:
                due_date = date.fromisoformat(args[i])
            except ValueError:
                print(f"Error: invalid due date: {args[i]}", file=sys.stderr)
                sys.exit(1)
        elif arg == "--priority":
            i += 1
            if i >= len(args):
                print("Error: --priority requires a value (integer >= 1)", file=sys.stderr)
                sys.exit(1)
            try:
                priority = int(args[i])
                if priority < 1:
                    raise ValueError
            except ValueError:
                print(f"Error: invalid priority: {args[i]}", file=sys.stderr)
                sys.exit(1)
        else:
            title_parts.append(arg)
        i += 1

    if not title_parts:
        print("Error: task title is required", file=sys.stderr)
        sys.exit(1)

    title = " ".join(title_parts)
    priority = priority if priority is not None else 1

    try:
        task = add_task(title, due_date, priority)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    due_str = f" -- due {task.due_date.isoformat()}" if task.due_date else ""
    priority_str = f" -- priority {task.priority}" if task.priority != 1 else ""

    print("Added task:")
    print(f"{task.title}{due_str}{priority_str}")


def handle_task_complete(args: list[str]) -> None:
    """Parse 'janus task complete' arguments and mark a task as completed.

    Usage:
        janus task complete "Title"
    """
    if not args:
        print("Error: task title is required", file=sys.stderr)
        sys.exit(1)

    title = " ".join(args)

    try:
        complete_task(title)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Completed task: {title}")


def handle_task_state(args: list[str]) -> None:
    """Parse 'janus task state' arguments and update the task state.

    Usage:
        janus task state "Title" --state in_progress
        janus task state "Title" --state blocked
        janus task state "Title" --state todo

    The checkbox [x] remains the only completion authority.
    'state: done' is not accepted and cannot be written by the CLI.
    """
    title_parts: list[str] = []
    state: str | None = None
    i = 0

    while i < len(args):
        arg = args[i]
        if arg == "--state":
            i += 1
            if i >= len(args):
                print("Error: --state requires a value", file=sys.stderr)
                sys.exit(1)
            state = args[i]
        else:
            title_parts.append(arg)
            i += 1
            continue
        i += 1

    if not title_parts:
        print("Error: task title is required", file=sys.stderr)
        sys.exit(1)

    if state is None:
        print("Error: --state is required", file=sys.stderr)
        sys.exit(1)

    if state not in ALLOWED_STATES:
        print(
            f"Error: invalid state {state!r}. "
            f"Allowed values: {', '.join(sorted(ALLOWED_STATES))}",
            file=sys.stderr,
        )
        sys.exit(1)

    title = " ".join(title_parts)

    try:
        task = set_task_state(title, state)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    state_suffix = f" -- state {task.state}" if task.state else ""
    print(f"Updated task state: {task.title}{state_suffix}")


def handle_task_progress(args: list[str]) -> None:
    """Parse 'janus task progress' arguments and update the task progress.

    Usage:
        janus task progress "Title" --pct 70
        janus task progress "Title" --pct 100

    Progress 100 does NOT automatically complete the task.
    Completion still requires 'janus task complete'.
    """
    title_parts: list[str] = []
    progress: int | None = None
    i = 0

    while i < len(args):
        arg = args[i]
        if arg == "--pct":
            i += 1
            if i >= len(args):
                print("Error: --pct requires a value", file=sys.stderr)
                sys.exit(1)
            try:
                progress = int(args[i])
                if not (0 <= progress <= 100):
                    raise ValueError
            except ValueError:
                print(
                    "Error: --pct requires an integer between 0 and 100",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            title_parts.append(arg)
            i += 1
            continue
        i += 1

    if not title_parts:
        print("Error: task title is required", file=sys.stderr)
        sys.exit(1)

    if progress is None:
        print("Error: --pct is required", file=sys.stderr)
        sys.exit(1)

    title = " ".join(title_parts)

    try:
        task = set_task_progress(title, progress)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Updated task progress: {task.title} -- {task.progress}%")