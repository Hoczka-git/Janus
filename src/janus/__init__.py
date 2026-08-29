import sys

from janus.today import show_today, show_telegram
from janus.tasks_cli import handle_task_add, handle_task_complete


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: janus <command>")
        return

    command = sys.argv[1]

    if command == "today":
        show_today()
    elif command == "telegram":
        show_telegram()
    elif command == "task":
        if len(sys.argv) < 3:
            print("Usage: janus task <add|complete> ...")
            return
        subcommand = sys.argv[2]
        if subcommand == "add":
            handle_task_add(sys.argv[3:])
        elif subcommand == "complete":
            handle_task_complete(sys.argv[3:])
        else:
            print(f"Unknown task subcommand: {subcommand}")
            print("Usage: janus task add <title> [--due YYYY-MM-DD] [--priority N]")
            print("       janus task complete <title>")
    else:
        print(f"Unknown command: {command}")
