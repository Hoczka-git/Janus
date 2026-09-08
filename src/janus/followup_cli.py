"""CLI handlers for `janus followup` subcommands."""

import sys
from datetime import date

from janus.services.followup import (
    add_followup,
    get_followup,
    list_followups,
    set_followup_state,
    schedule_followup,
    complete_followup,
    convert_followup_to_task,
)


def print_followup_help() -> None:
    print("Usage: janus followup <command> [options]")
    print()
    print("Commands:")
    print("  list             List follow-ups (optionally filter by --state)")
    print("  add <title>      Create a new follow-up")
    print("  show <id>        Show details of a follow-up")
    print("  update <id>      Update a follow-up (state, dates, priority)")
    print("  complete <id>    Mark a follow-up as completed")
    print("  convert-to-task <id>  Convert a follow-up to a Janus Task")
    print()
    print("Examples:")
    print('  janus followup list')
    print('  janus followup list --state pending')
    print('  janus followup add "Check Memmingen train times" --due 2026-09-18 --priority 2')
    print('  janus followup show fu-abc12345')
    print('  janus followup update fu-abc12345 --state scheduled --scheduled 2026-09-15')
    print('  janus followup complete fu-abc12345')
    print('  janus followup convert-to-task fu-abc12345 --title "Research Memmingen travel options"')


def handle_followup_list(args: list[str]) -> None:
    """janus followup list [--state <state>]"""
    state = None
    i = 0
    while i < len(args):
        if args[i] == "--state" and i + 1 < len(args):
            state = args[i + 1]
            i += 2
        else:
            i += 1

    if state is not None and state not in ("pending", "scheduled", "in_progress", "blocked", "completed", "deferred"):
        print(f"Invalid state filter: {state!r}. Allowed: pending, scheduled, in_progress, blocked, completed, deferred",
              file=sys.stderr)
        sys.exit(1)

    items = list_followups(state)
    if not items:
        print("No follow-ups.")
        return

    print(f"Follow-ups ({len(items)}):")
    for fu in items:
        state_icon = {"pending": "○", "scheduled": "◷", "in_progress": "◉", "blocked": "⊘", "completed": "✓", "deferred": "⇢"}.get(fu.state, "?")
        print(f"  [{state_icon}] {fu.id} — {fu.title}")
        print(f"      state: {fu.state}, priority: {fu.priority}")
        if fu.due_date:
            print(f"      due: {fu.due_date.isoformat()}")
        if fu.scheduled_for:
            print(f"      scheduled: {fu.scheduled_for.isoformat()}")
        if fu.created_by:
            print(f"      created by: {fu.created_by}")
        if fu.note:
            print(f"      note: {fu.note}")
        if fu.linked_goal_title:
            print(f"      goal: {fu.linked_goal_title}")
        if fu.converted_to_task_title:
            print(f"      converted to task: {fu.converted_to_task_title}")
        print()


def handle_followup_add(args: list[str]) -> None:
    """janus followup add <title> [--due YYYY-MM-DD] [--scheduled YYYY-MM-DD] [--priority N] [--note "..."]"""
    if len(args) < 1:
        print("Error: title required", file=sys.stderr)
        print("Usage: janus followup add <title> [--due YYYY-MM-DD] [--scheduled YYYY-MM-DD] [--priority N] [--note \"...\"]",
              file=sys.stderr)
        sys.exit(1)

    title = args[0]
    due_date = None
    scheduled_for = None
    priority = 1
    note = ""

    i = 1
    while i < len(args):
        if args[i] == "--due" and i + 1 < len(args):
            try:
                due_date = date.fromisoformat(args[i + 1])
            except ValueError:
                print(f"Invalid due date: {args[i + 1]!r}", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == "--scheduled" and i + 1 < len(args):
            try:
                scheduled_for = date.fromisoformat(args[i + 1])
            except ValueError:
                print(f"Invalid scheduled date: {args[i + 1]!r}", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == "--priority" and i + 1 < len(args):
            try:
                priority = int(args[i + 1])
            except ValueError:
                print(f"Invalid priority: {args[i + 1]!r}", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == "--note" and i + 1 < len(args):
            note = args[i + 1]
            i += 2
        else:
            i += 1

    if priority not in (1, 2, 3, 4, 5):
        print(f"Invalid priority: {priority!r}. Must be 1-5.", file=sys.stderr)
        sys.exit(1)

    fu = add_followup(
        title=title,
        due_date=due_date,
        scheduled_for=scheduled_for,
        priority=priority,
        note=note,
    )
    print(f"Follow-up created: '{fu.title}' ({fu.id})")


def handle_followup_show(args: list[str]) -> None:
    """janus followup show <id>"""
    if len(args) < 1:
        print("Error: follow-up id required", file=sys.stderr)
        sys.exit(1)

    fu = get_followup(args[0])
    _print_followup_detail(fu)


def handle_followup_update(args: list[str]) -> None:
    """janus followup update <id> [--state <state>] [--due YYYY-MM-DD] [--scheduled YYYY-MM-DD] [--priority N]"""
    if len(args) < 1:
        print("Error: follow-up id required", file=sys.stderr)
        print("Usage: janus followup update <id> [--state <state>] [--due YYYY-MM-DD] [--scheduled YYYY-MM-DD] [--priority N]",
              file=sys.stderr)
        sys.exit(1)

    fu_id = args[0]
    state = None
    due_date = None
    scheduled_for = None
    priority = None

    i = 1
    while i < len(args):
        if args[i] == "--state" and i + 1 < len(args):
            state = args[i + 1]
            i += 2
        elif args[i] == "--due" and i + 1 < len(args):
            try:
                due_date = date.fromisoformat(args[i + 1])
            except ValueError:
                print(f"Invalid due date: {args[i + 1]!r}", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == "--scheduled" and i + 1 < len(args):
            try:
                scheduled_for = date.fromisoformat(args[i + 1])
            except ValueError:
                print(f"Invalid scheduled date: {args[i + 1]!r}", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == "--priority" and i + 1 < len(args):
            try:
                priority = int(args[i + 1])
            except ValueError:
                print(f"Invalid priority: {args[i + 1]!r}", file=sys.stderr)
                sys.exit(1)
            i += 2
        else:
            i += 1

    if state is not None:
        if state not in ("pending", "scheduled", "in_progress", "blocked", "completed", "deferred"):
            print(f"Invalid state: {state!r}", file=sys.stderr)
            sys.exit(1)
        set_followup_state(fu_id, state)

    if due_date is not None or scheduled_for is not None:
        schedule_followup(fu_id, scheduled_for=scheduled_for, due_date=due_date)

    if priority is not None:
        if priority not in (1, 2, 3, 4, 5):
            print(f"Invalid priority: {priority!r}. Must be 1-5.", file=sys.stderr)
            sys.exit(1)
        fu = get_followup(fu_id)
        fu.priority = priority
        from janus.integrations.markdown_followups import update_followup
        update_followup(fu)
        print(f"Priority updated to {priority}")

    fu = get_followup(fu_id)
    _print_followup_detail(fu)


def handle_followup_complete(args: list[str]) -> None:
    """janus followup complete <id>"""
    if len(args) < 1:
        print("Error: follow-up id required", file=sys.stderr)
        sys.exit(1)

    fu = complete_followup(args[0])
    print(f"Follow-up completed: '{fu.title}' ({fu.id})")


def handle_followup_convert(args: list[str]) -> None:
    """janus followup convert-to-task <id> [--title "..."]"""
    if len(args) < 1:
        print("Error: follow-up id required", file=sys.stderr)
        print("Usage: janus followup convert-to-task <id> [--title \"...\"]",
              file=sys.stderr)
        sys.exit(1)

    fu_id = args[0]
    task_title = ""

    i = 1
    while i < len(args):
        if args[i] == "--title" and i + 1 < len(args):
            task_title = args[i + 1]
            i += 2
        else:
            i += 1

    fu = get_followup(fu_id)
    final_title = task_title.strip() if task_title.strip() else fu.title

    from janus.services.tasks import add_task
    task = add_task(title=final_title)
    convert_followup_to_task(fu_id, task_title=task.title)
    print(f"Follow-up converted to task: '{fu.title}' → Task '{task.title}'")


def _print_followup_detail(fu) -> None:
    print(f"Follow-up: {fu.id}")
    print(f"  Title: {fu.title}")
    print(f"  State: {fu.state}")
    print(f"  Priority: {fu.priority}")
    if fu.due_date:
        print(f"  Due: {fu.due_date.isoformat()}")
    if fu.scheduled_for:
        print(f"  Scheduled: {fu.scheduled_for.isoformat()}")
    if fu.assigned_to:
        print(f"  Assigned to: {fu.assigned_to}")
    print(f"  Created: {fu.created_at.strftime('%Y-%m-%d %H:%M')}")
    if fu.completed_at:
        print(f"  Completed: {fu.completed_at.strftime('%Y-%m-%d %H:%M')}")
    if fu.created_by:
        print(f"  Created by: {fu.created_by}")
    if fu.note:
        print(f"  Note: {fu.note}")
    if fu.linked_goal_title:
        print(f"  Goal: {fu.linked_goal_title}")
    if fu.linked_task_title:
        print(f"  Linked task: {fu.linked_task_title}")
    if fu.converted_to_task_title:
        print(f"  Converted to task: {fu.converted_to_task_title}")
    if fu.originating_inbox_id:
        print(f"  Originating inbox item: {fu.originating_inbox_id}")
