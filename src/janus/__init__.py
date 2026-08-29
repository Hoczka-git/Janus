import sys

from janus.today import show_today, show_telegram
from janus.weekly import show_weekly
from janus.tasks_cli import handle_task_add, handle_task_complete
from janus.workout_cli import handle_workout_add, handle_workout_show


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
    elif command == "workout":
        if len(sys.argv) < 3:
            print("Usage: janus workout <add|show> ...")
            return
        subcommand = sys.argv[2]
        if subcommand == "add":
            handle_workout_add(sys.argv[3:])
        elif subcommand == "show":
            handle_workout_show(sys.argv[3:])
        else:
            print(f"Unknown workout subcommand: {subcommand}")
            print("Usage: janus workout add --type strength|running [options]")
            print("       janus workout show [--last N] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--running] [--exercise NAME]")
    elif command == "weekly":
        show_weekly()
    else:
        print(f"Unknown command: {command}")