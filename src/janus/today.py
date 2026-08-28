from datetime import date

from janus.integrations.markdown_tasks import load_tasks
from janus.models.task import Task


def requires_attention(task: Task, today: date) -> bool:
    """Return True if a task needs attention today."""
    return (
        (task.due_date is not None and task.due_date <= today)
        or task.priority >= 3
    )


def show_today() -> None:
    """Print today's overview using Markdown tasks and Google Calendar events."""
    today = date.today()

    tasks = load_tasks()

    attention_tasks = [
        task
        for task in tasks
        if requires_attention(task, today)
    ]

    print("JANUS — TODAY")
    print()

    print("Requires attention:")

    for task in attention_tasks:
        print(f"- {task.title}")

    if not attention_tasks:
        print("Nothing requires your attention today.")
