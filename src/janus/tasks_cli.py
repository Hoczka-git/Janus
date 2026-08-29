"""CLI command handler for 'janus task add' and 'janus task complete'."""

from datetime import date
import sys

from janus.services.tasks import add_task, complete_task


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
