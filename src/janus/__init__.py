import sys

from janus.today import show_today, show_telegram
from janus.weekly import show_weekly
from janus.tasks_cli import handle_task_add, handle_task_complete, handle_task_state, handle_task_progress, handle_task_list
from janus.workout_cli import handle_workout_add, handle_workout_show, handle_workout_summary
from janus.goals_cli import (
    handle_goal_list,
    handle_goal_show,
    handle_goal_add,
    handle_goal_update,
    handle_goal_complete,
    handle_goal_next,
    handle_goal_milestone,
)


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
            print("Usage: janus task <add|complete|list|state|progress> ...")
            return
        subcommand = sys.argv[2]
        if subcommand == "add":
            handle_task_add(sys.argv[3:])
        elif subcommand == "complete":
            handle_task_complete(sys.argv[3:])
        elif subcommand == "list":
            handle_task_list(sys.argv[3:])
        elif subcommand == "state":
            handle_task_state(sys.argv[3:])
        elif subcommand == "progress":
            handle_task_progress(sys.argv[3:])
        else:
            print(f"Unknown task subcommand: {subcommand}")
            print("Usage: janus task add <title> [--due YYYY-MM-DD] [--priority N]")
            print("       janus task complete <title>")
            print("       janus task list")
            print("       janus task state <title> --state <todo|in_progress|blocked>")
            print("       janus task progress <title> --pct <0-100>")
    elif command == "workout":
        if len(sys.argv) < 3:
            print("Usage: janus workout <add|show|summary> ...")
            return
        subcommand = sys.argv[2]
        if subcommand == "add":
            handle_workout_add(sys.argv[3:])
        elif subcommand == "show":
            handle_workout_show(sys.argv[3:])
        elif subcommand == "summary":
            handle_workout_summary(sys.argv[3:])
        else:
            print(f"Unknown workout subcommand: {subcommand}")
            print("Usage: janus workout add --type strength|running [options]")
            print("       janus workout show [--last N] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--running] [--exercise NAME]")
            print("       janus workout summary [--running] [--exercise NAME]")
    elif command == "goal":
        if len(sys.argv) < 3:
            print("Usage: janus goal <list|show|add|update|complete|milestone|next> ...")
            return
        subcommand = sys.argv[2]
        if subcommand == "list":
            handle_goal_list(sys.argv[3:])
        elif subcommand == "show":
            handle_goal_show(sys.argv[3:])
        elif subcommand == "add":
            handle_goal_add(sys.argv[3:])
        elif subcommand == "update":
            handle_goal_update(sys.argv[3:])
        elif subcommand == "complete":
            handle_goal_complete(sys.argv[3:])
        elif subcommand == "milestone":
            handle_goal_milestone(sys.argv[3:])
        elif subcommand == "next":
            handle_goal_next(sys.argv[3:])
        else:
            print(f"Unknown goal subcommand: {subcommand}")
            print("Usage: janus goal list")
            print("       janus goal show <title>")
            print("       janus goal add <title> [options]")
            print("       janus goal update <title> [options]")
            print("       janus goal complete <title>")
            print("       janus goal milestone <add|list|show|complete|update> <goal> ...")
            print("       janus goal next <title>")
    elif command == "weekly":
        show_weekly()
    else:
        print(f"Unknown command: {command}")
