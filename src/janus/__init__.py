import sys

from janus.today import show_today, show_telegram
from janus.tasks_cli import handle_task_add


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
        if len(sys.argv) < 3 or sys.argv[2] != "add":
            print("Usage: janus task add <title> [--due YYYY-MM-DD] [--priority N]")
            return
        handle_task_add(sys.argv[3:])
    else:
        print(f"Unknown command: {command}")
