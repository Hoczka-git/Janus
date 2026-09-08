"""CLI handlers for `janus inbox` subcommands."""

import sys
from datetime import datetime

from janus.services.inbox import add_inbox_item, triage_item, list_inbox_items, get_inbox_item
from janus.services.followup import add_followup


def print_inbox_help() -> None:
    print("Usage: janus inbox <command> [options]")
    print()
    print("Commands:")
    print("  list      List inbox items (optionally filter by --state)")
    print("  pending   List pending (untriaged) inbox items")
    print("  triage    Triage an item: janus inbox triage <id> --followup|--discard|--convert-to-task [--note \"...\"]")
    print()
    print("Examples:")
    print('  janus inbox list')
    print('  janus inbox list --state pending')
    print('  janus inbox pending')
    print('  janus inbox triage ix-abc12345 --followup --note "Travel planning"')
    print('  janus inbox triage ix-abc12345 --discard --note "Not actionable"')
    print('  janus inbox triage ix-abc12345 --convert-to-task --title "New task title"')


def handle_inbox_list(args: list[str]) -> None:
    """janus inbox list [--state <state>]"""
    state = None
    i = 0
    while i < len(args):
        if args[i] == "--state" and i + 1 < len(args):
            state = args[i + 1]
            i += 2
        else:
            i += 1

    if state is not None and state not in ("pending", "discarded", "converted", "follow_up"):
        print(f"Invalid state filter: {state!r}. Allowed: pending, discarded, converted, follow_up",
              file=sys.stderr)
        sys.exit(1)

    items = list_inbox_items(state)
    if not items:
        print("No inbox items.")
        return

    print(f"Inbox items ({len(items)}):")
    for item in items:
        state_marker = "●" if item.triage_state == "pending" else "○"
        print(f"  [{state_marker}] {item.id} — {item.captured_text}")
        captured_str = item.captured_at.strftime('%Y-%m-%d %H:%M') if item.captured_at else "unknown"
        print(f"      source: {item.source}, captured: {captured_str}")
        if item.triage_state != "pending":
            print(f"      triage: {item.triage_state} — {item.triage_note}")
        if item.linked_goal_title:
            print(f"      goal: {item.linked_goal_title}")
        print()


def handle_inbox_pending(args: list[str]) -> None:
    """janus inbox pending"""
    items = list_inbox_items("pending")
    if not items:
        print("No pending inbox items.")
        return

    print(f"Pending inbox items ({len(items)}):")
    for item in items:
        age = datetime.now() - (item.captured_at or datetime.now())
        days = age.days
        hours = age.seconds // 3600
        age_str = f"{days}d" if days > 0 else f"{hours}h"
        print(f"  {item.id} — {item.captured_text}  ({age_str} ago)")
        if item.context:
            print(f"    context: {item.context}")
        if item.linked_research_title:
            print(f"    research: {item.linked_research_title}")
        print()


def handle_inbox_triage(args: list[str]) -> None:
    """janus inbox triage <id> --followup|--discard|--convert-to-task [--note "..."] [--title "..."]"""
    if len(args) < 1:
        print("Error: inbox id required", file=sys.stderr)
        print("Usage: janus inbox triage <id> --followup|--discard|--convert-to-task [--note \"...\"] [--title \"...\"]",
              file=sys.stderr)
        sys.exit(1)

    inbox_id = args[0]
    action = None
    note = ""
    title = ""

    i = 1
    while i < len(args):
        if args[i] == "--followup":
            action = "follow_up"
            i += 1
        elif args[i] == "--discard":
            action = "discarded"
            i += 1
        elif args[i] == "--convert-to-task":
            action = "converted"
            i += 1
        elif args[i] == "--note" and i + 1 < len(args):
            note = args[i + 1]
            i += 2
        elif args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]
            i += 2
        else:
            i += 1

    if action is None:
        print("Error: one of --followup, --discard, or --convert-to-task is required",
              file=sys.stderr)
        sys.exit(1)

    if action == "follow_up":
        item = get_inbox_item(inbox_id)
        fu_title = title.strip() if title.strip() else _derive_title(item.captured_text)
        triage_item(inbox_id, "follow_up", note)
        fu = add_followup(
            title=fu_title,
            originating_inbox_id=inbox_id,
            created_by="cli",
            linked_goal_title=item.linked_goal_title,
        )
        print(f"Triage complete: '{item.captured_text[:60]}...' → FollowUp '{fu.title}' ({fu.id})")

    elif action == "discarded":
        triage_item(inbox_id, "discarded", note)
        item = get_inbox_item(inbox_id)
        print(f"Triage complete: '{item.captured_text[:60]}...' → discarded")

    elif action == "converted":
        item = get_inbox_item(inbox_id)
        task_title = title.strip() if title.strip() else _derive_title(item.captured_text)
        from janus.services.tasks import add_task
        task = add_task(title=task_title)
        triage_item(inbox_id, "converted", f"Converted to task: {task.title}")
        print(f"Triage complete: '{item.captured_text[:60]}...' → Task '{task.title}'")


def _derive_title(text: str) -> str:
    """Derive an actionable title from raw captured text."""
    text = text.strip()
    # Remove common prefixes
    for prefix in ("remember to ", "need to ", "have to ", "should "):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    # Truncate to reasonable length
    if len(text) > 80:
        text = text[:77] + "..."
    return text
