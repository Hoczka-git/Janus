import os
import sys
import time
import uuid

from janus.logging_config import setup_logging
from janus._log import emit
from janus.today import show_today, show_telegram
from janus.telegram_weekly_cli import send_weekly_telegram
from janus.weekly import show_weekly
from janus.strategic_cli import show_status
from janus.tasks_cli import handle_task_add, handle_task_complete, handle_task_state, handle_task_progress, handle_task_list, print_task_help
from janus.workout_cli import handle_workout_add, handle_workout_show, handle_workout_summary, print_workout_help
from janus.inbox_cli import (
    handle_inbox_list,
    handle_inbox_triage,
    handle_inbox_pending,
    print_inbox_help,
)
from janus.followup_cli import (
    handle_followup_list,
    handle_followup_add,
    handle_followup_show,
    handle_followup_update,
    handle_followup_complete,
    handle_followup_convert,
    print_followup_help,
)
from janus.research_cli import (
    handle_research_add,
    handle_research_show,
    handle_research_list,
    handle_research_link,
    handle_research_promote_finding,
    handle_research_propose,
    handle_research_approve,
    handle_research_reject,
    handle_research_defer,
    handle_research_promote,
    handle_research_show_proposal,
    handle_research_list_proposals,
    print_research_help,
)
from janus.knowledge_cli import main as _knowledge_main
from janus.decision_cli import (
    handle_decision_list,
    handle_decision_show,
    handle_decision_propose,
    handle_decision_link_finding,
    handle_decision_link_goal,
    print_decision_help,
)
from janus.goals_cli import (
    handle_goal_list,
    handle_goal_show,
    handle_goal_add,
    handle_goal_update,
    handle_goal_complete,
    handle_goal_next,
    handle_goal_milestone,
    handle_goal_project,
    handle_goal_health,
    handle_goal_audit,
    handle_goal_skills,
    handle_goal_set_skill,
    print_goal_help,
)

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    verbose = False
    args = list(sys.argv[1:])
    filtered: list[str] = []
    for arg in args:
        if arg in ("-v", "--verbose"):
            verbose = True
        else:
            filtered.append(arg)
    sys.argv = [sys.argv[0]] + filtered

    setup_logging(verbose=verbose)

    if not filtered:
        print("Usage: janus <command>")
        return

    command = filtered[0]
    subcommand = filtered[1] if len(filtered) > 1 else None

    trace_id = uuid.uuid4().hex
    start = time.monotonic()
    emit(logger, "cli.command.invoked",
         trace_id=trace_id, span_id="dispatch",
         command=command, subcommand=subcommand, pid=os.getpid(),
         message=f"CLI command '{command}' invoked")

    try:
        if command == "today":
            show_today(trace_id=trace_id)
        elif command == "telegram":
            show_telegram(trace_id=trace_id)
        elif command == "telegram-weekly":
            send_weekly_telegram(trace_id=trace_id)
        elif command == "task":
            if len(filtered) < 2 or filtered[1] in ("-h", "--help"):
                print_task_help()
                return
            sub = filtered[1]
            if sub == "add":
                handle_task_add(filtered[2:])
            elif sub == "complete":
                handle_task_complete(filtered[2:])
            elif sub == "list":
                handle_task_list(filtered[2:])
            elif sub == "state":
                handle_task_state(filtered[2:])
            elif sub == "progress":
                handle_task_progress(filtered[2:])
            else:
                print(f"Unknown task subcommand: {sub}")
                print("Usage: janus task add <title> [--due YYYY-MM-DD] [--priority N]")
                print("       janus task complete <title>")
                print("       janus task list")
                print("       janus task state <title> --state <todo|in_progress|blocked>")
                print("       janus task progress <title> --pct <0-100>")
        elif command == "workout":
            if len(filtered) < 2 or filtered[1] in ("-h", "--help"):
                print_workout_help()
                return
            sub = filtered[1]
            if sub == "add":
                handle_workout_add(filtered[2:])
            elif sub == "show":
                handle_workout_show(filtered[2:])
            elif sub == "summary":
                handle_workout_summary(filtered[2:])
            else:
                print(f"Unknown workout subcommand: {sub}")
                print("Usage: janus workout add --type strength|running [options]")
                print("       janus workout show [--last N] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--running] [--exercise NAME]")
                print("       janus workout summary [--running] [--exercise NAME]")
        elif command == "goal":
            if len(filtered) < 2:
                print("Usage: janus goal <list|show|add|update|complete|milestone|next|health> ...")
                return
            sub = filtered[1]
            if sub in ("--help", "-h", "help"):
                print_goal_help()
                return
            if sub == "list":
                handle_goal_list(filtered[2:])
            elif sub == "show":
                handle_goal_show(filtered[2:])
            elif sub == "add":
                handle_goal_add(filtered[2:])
            elif sub == "update":
                handle_goal_update(filtered[2:])
            elif sub == "complete":
                handle_goal_complete(filtered[2:])
            elif sub == "skills":
                handle_goal_skills(filtered[2:])
            elif sub == "set-skill":
                handle_goal_set_skill(filtered[2:])
            elif sub == "milestone":
                handle_goal_milestone(filtered[2:])
            elif sub == "project":
                handle_goal_project(filtered[2:])
            elif sub == "next":
                handle_goal_next(filtered[2:])
            elif sub == "health":
                handle_goal_health(filtered[2:])
            elif sub == "audit":
                handle_goal_audit(filtered[2:])
            else:
                print(f"Unknown goal subcommand: {sub}")
                print("Usage: janus goal list")
                print("       janus goal show <title>")
                print("       janus goal add <title> [options]")
                print("       janus goal update <title> [options]")
                print("       janus goal complete <title>")
                print("       janus goal milestone <add|list|show|complete|update> <goal> ...")
                print("       janus goal next <title>")
                print("       janus goal health [<title>]")
                print("       janus goal audit [--json]")
        elif command == "weekly":
            show_weekly(trace_id=trace_id)
        elif command == "status":
            show_status(trace_id=trace_id)
        elif command == "inbox":
            if len(filtered) < 2 or filtered[1] in ("-h", "--help"):
                print_inbox_help()
                return
            sub = filtered[1]
            if sub == "list":
                handle_inbox_list(filtered[2:])
            elif sub == "pending":
                handle_inbox_pending(filtered[2:])
            elif sub == "triage":
                handle_inbox_triage(filtered[2:])
            else:
                print(f"Unknown inbox subcommand: {sub}")
                print("Usage: janus inbox list|pending|triage ...")
        elif command == "followup":
            if len(filtered) < 2 or filtered[1] in ("-h", "--help"):
                print_followup_help()
                return
            sub = filtered[1]
            if sub == "list":
                handle_followup_list(filtered[2:])
            elif sub == "add":
                handle_followup_add(filtered[2:])
            elif sub == "show":
                handle_followup_show(filtered[2:])
            elif sub == "update":
                handle_followup_update(filtered[2:])
            elif sub == "complete":
                handle_followup_complete(filtered[2:])
            elif sub == "convert-to-task":
                handle_followup_convert(filtered[2:])
            else:
                print(f"Unknown followup subcommand: {sub}")
                print("Usage: janus followup list|add|show|update|complete|convert-to-task ...")
        elif command == "research":
            if len(filtered) < 2 or filtered[1] in ("-h", "--help", "help"):
                print_research_help()
                return
            sub = filtered[1]
            if sub == "add":
                handle_research_add(filtered[2:])
            elif sub == "show":
                handle_research_show(filtered[2:])
            elif sub == "list":
                handle_research_list(filtered[2:])
            elif sub == "link":
                handle_research_link(filtered[2:])
            elif sub == "promote-finding":
                handle_research_promote_finding(filtered[2:])
            elif sub == "propose":
                handle_research_propose(filtered[2:])
            elif sub == "approve":
                handle_research_approve(filtered[2:])
            elif sub == "reject":
                handle_research_reject(filtered[2:])
            elif sub == "defer":
                handle_research_defer(filtered[2:])
            elif sub == "promote":
                handle_research_promote(filtered[2:])
            elif sub == "show-proposal":
                handle_research_show_proposal(filtered[2:])
            elif sub == "list-proposals":
                handle_research_list_proposals(filtered[2:])
            else:
                print(f"Unknown research subcommand: {sub}")
                print_research_help()
        elif command == "knowledge":
            _knowledge_main(filtered[1:])
        elif command == "decision":
            if len(filtered) < 2 or filtered[1] in ("-h", "--help", "help"):
                print_decision_help()
                return
            sub = filtered[1]
            if sub == "propose":
                handle_decision_propose(filtered[2:])
            elif sub == "link-finding":
                handle_decision_link_finding(filtered[2:])
            elif sub == "link-goal":
                handle_decision_link_goal(filtered[2:])
            elif sub == "list":
                handle_decision_list(filtered[2:])
            elif sub == "show":
                handle_decision_show(filtered[2:])
            else:
                print(f"Unknown decision subcommand: {sub}")
                print_decision_help()
        else:
            print(f"Unknown command: {command}")
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        emit(logger, "cli.command.finished",
             trace_id=trace_id, span_id="dispatch",
             correlation_id=trace_id,
             command=command, subcommand=subcommand,
             status="error",
             duration_ms=duration_ms,
             error={"type": type(e).__name__, "message": str(e), "stack": None},
             message=f"CLI command '{command}' failed",
             level=logging.WARNING)
        raise
    else:
        duration_ms = (time.monotonic() - start) * 1000
        emit(logger, "cli.command.finished",
             trace_id=trace_id, span_id="dispatch",
             correlation_id=trace_id,
             command=command, subcommand=subcommand,
             status="ok",
             duration_ms=duration_ms,
             message=f"CLI command '{command}' completed")
