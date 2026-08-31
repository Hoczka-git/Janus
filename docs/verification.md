# Repository Verification Contract

This document defines what "the Janus repository is verified" means and how to reproduce it locally.

## Command

```bash
uv run pytest tests/
```

Run from the repository root. `uv sync --dev` must be satisfied first (handled automatically by `uv run`).

## Success

- **Exit code 0** — all tests pass, the repository is verified.
- **Non-zero exit code** — verification failed; do not report completion until the failure is resolved.

## Scope

The command above runs the full test suite (18 files under `tests/`), covering:

- Domain models: `Task`, `Goal`, `Workout` (dedicated tests); `WeeklyReview`, `DailyBriefing`, `Attention` (via their own test files); `Event` (covered through attention, Telegram, and today tests)
- CLI handlers: `task state`, `task progress`, `tasks_cli`, `workout_cli`, `goals_cli`, `weekly`
- Integrations: Markdown goals, Markdown tasks, attention, Google Calendar, daily briefing, fitness, Telegram
- Domain logic: workout analytics, goal progress, weekly review

## Artifacts

The command produces no persistent artifacts by default. To produce a machine-readable result for CI or scripting:

```bash
uv run pytest tests/ --junitxml=reports/junit.xml
```

Output is written to `reports/junit.xml` (create the `reports/` directory first). Add `reports/` to `.gitignore` to keep the repository clean. A non-zero exit code still indicates failure regardless of artifact presence.

## CI

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs the same command on every push to `master`/`main` and on every pull request. Failure in CI blocks merging.

## Local debugging

To run a single failing test file:

```bash
uv run pytest tests/<name>.py -v
```

To run with verbose output and a short traceback:

```bash
uv run pytest tests/ --tb=short -q
```

## Pre-completion checklist

Before reporting a task as done:

1. Run `uv run pytest tests/` from the repository root.
2. Confirm exit code 0.
3. If a test failure is intentional (e.g. uncovered edge case found during the task), either fix it or document why it is acceptable before completing.
