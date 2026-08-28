import sys

from janus.today import show_today


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: janus <command>")
        return

    command = sys.argv[1]

    if command == "today":
        show_today()
    else:
        print(f"Unknown command: {command}")
