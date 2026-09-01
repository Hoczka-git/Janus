# Janus

Personal chief of staff assistant focused on proactive personal life management. Janus is the persistent application, domain, and personal-state layer for the Hermes personal agent system — it owns structured data, domain logic, and deterministic analysis across tasks, goals, fitness, calendars, and reviews.

## Overview

Janus provides a local, file-backed personal operations system. All state is stored as plain-text markdown/JSON files in `data/` (trackable in git where you choose), and the CLI renders deterministic views over that state. The daily briefing integrates with Google Calendar (read-only) and the Attention Engine to surface what deserves your attention right now.

Key subsystems:

| Area         | CLI command            | Data file          | Description                                              |
|--------------|------------------------|--------------------|----------------------------------------------------------|
| Daily briefing | `janus today`       | —                  | Schedule + attention items + suggested focus           |
| Tasks        | `janus task <subcommand>` | `data/tasks.md` | Open tasks, priorities, states, progress, due dates      |
| Goals        | `janus goal <subcommand>` | `data/goals.md` | Long-term goals with metrics and related-task tracking   |
| Fitness      | `janus workout <subcommand>` | `data/workouts.md` | Strength and running workouts with analytics        |
| Weekly review | `janus weekly`      | —                  | Completed tasks, open tasks, and goal progress           |
| Telegram     | `janus telegram` / `janus telegram-weekly` | — | Deliver the daily / weekly briefing to Telegram     |
| Verification | `janus verify-contract <file>` | —          | Run an implementation contract verification pipeline     |

## Current capabilities

- **Daily briefing** (`janus today`) — upcoming calendar events (Google Calendar, read-only scope), open tasks, active goals, deterministic attention ranking (top 3), and a single recommended suggested-focus item.
- **Task management** (`janus task`) — list, add, complete, set state (`todo`/`in_progress`/`blocked`), and set progress percentage. Completion authority is the `[x]` checkbox; `state: done` is rejected.
- **Goal tracking** (`janus goal`) — goals with optional metrics (`--metric`, `--unit`, `--start`, `--current`, `--target`, `--direction`), deadlines, status (`active`/`completed`/`inactive`), and links to related tasks.
- **Fitness tracking** (`janus workout`) — strength workouts (exercises, sets, weights, RPE) and running workouts (distance, duration, heart rate, elevation). Analytics: overall, running-specific, and per-exercise progression.
- **Weekly review** (`janus weekly`) — completed tasks, open/needs-attention tasks, and goal progress with next-step suggestions.
- **Telegram delivery** — push the daily briefing or weekly review to a Telegram chat via bot.
- **Verification pipeline** (`janus verify-contract`) — validate an implementation contract (`contract.yaml`) against the repository: file creation/immutability checks, modified-file scope, untracked-file detection, AST-based required/forbidden symbol checks, and verification command execution.

## Setup

### Requirements

- Python 3.11
- [uv](https://github.com/astral-sh/uv)
- Google Calendar OAuth credentials (for calendar integration)
- Telegram bot token + chat id (for Telegram delivery)

### Installation

```bash
uv sync
```

### Google Calendar setup

1. Place `credentials.json` (OAuth client secrets) in the project root.
2. Copy `config/config.example.toml` to `config/config.toml` and fill in your calendar IDs:

```toml
[google_calendar]
[[google_calendar.calendars]]
id = "JOB_CALENDAR_ID"
name = "Job"

[[google_calendar.calendars]]
id = "PERSONAL_CALENDAR_ID"
name = "Personal"
```

3. Run `uv run janus today` — OAuth token is generated automatically on first run and stored in `token.json`.

### Telegram setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and obtain the bot token.
2. Get your chat id (e.g. by messaging [@userinfobot](https://t.me/userinfobot)).
3. Add a `[telegram]` section to `config/config.toml`:

```toml
[telegram]
bot_token = "YOUR_BOT_TOKEN"
chat_id = "YOUR_CHAT_ID"
```

## Usage

### Today

```bash
uv run janus today
```

Example output:

```
JANUS — TODAY

SCHEDULE
- 09:00 — Daily standup — Job
- 18:00 — Gym session — Personal

REQUIRES ATTENTION
1. Prepare training plan [FOCUS]
   Metric progress: 0% — linked to goal
and 1 more

SUGGESTED FOCUS
1. Prepare training plan
   Metric progress: 0% — linked to goal
```

### Telegram briefing

```bash
uv run janus telegram
```

Sends the daily briefing to the configured Telegram chat.

### Tasks

```bash
janus task add "Prepare training plan" --priority 3
janus task add "Book dentist appointment" --due 2026-08-30 --priority 2
janus task complete "Prepare training plan"
janus task state "Prepare training plan" --state in_progress
janus task progress "Prepare training plan" --pct 70
```

Task lines in `data/tasks.md` use the format:

```markdown
- [ ] Title | due: 2026-08-30 | priority: 2 | state: in_progress | progress: 70
```

Only `- [ ]` (open) and `- [x]` (completed) tasks are tracked. `state: done` is not accepted — completion is authoritative via the checkbox.

### Goals

```bash
janus goal list
janus goal show "Complete autumn endurance challenge"
janus goal add "Lose 5 kg" --metric "Body fat" --unit "%" --start 22 --current 20 --target 17 --direction decrease
janus goal update "Lose 5 kg" --current 19
janus goal add "Run a marathon" --related-task "Prepare training plan" --deadline 2026-10-15
janus goal complete "Run a marathon"
```

Goals are stored in `data/goals.md` as structured blocks:

```markdown
## Goal: Lose 5 kg

Description: Drop body fat before autumn.
Status: active
Deadline: 2026-10-15
Metric: Body fat
Unit: %
Start: 22
Current: 20
Target: 17
Direction: decrease
Related tasks:
- Prepare training plan
```

### Workouts

```bash
janus workout add --type strength --exercise "Back Squat" --sets "5x80kg@8,5x80kg@8.5"
janus workout add --type running --distance 5.0 --duration 30
janus workout add --type running --distance 8.74 --duration 69.77 --hr 151 --elevation 69.4 --notes "Tempo 7'59\"/km"
```

Viewing workouts:

```bash
janus workout show                  # last 5
janus workout show --last 10
janus workout show --from 2026-09-01 --to 2026-09-30
janus workout show --running
janus workout show --exercise "Back Squat"
```

Analytics:

```bash
janus workout summary               # overall
janus workout summary --running     # running-specific
janus workout summary --exercise "Back Squat"  # per-exercise progression
```

### Weekly review

```bash
janus weekly
```

Renders completed tasks, open/needs-attention tasks, and goal progress with suggested next steps and related-task status.

```bash
janus telegram-weekly
```

Sends the weekly review to Telegram.

### Verification pipeline

```bash
janus verify-contract contract.yaml
```

Runs an implementation contract against the repository. See [`docs/verification.md`](docs/verification.md) and [`docs/examples/contract_phase1.yaml`](docs/examples/contract_phase1.yaml) for the contract format and supported checks.

## Data

All structured personal data lives in `data/` as tracked markdown files:

| File           | Contents                                           |
|----------------|----------------------------------------------------|
| `data/tasks.md`     | Open and completed tasks with metadata         |
| `data/goals.md`     | Long-term goals with metrics and related tasks  |
| `data/workouts.md`  | Strength and running workouts                  |

These files are committed to git by default so task/goal/workout history is version-controlled.

## Security

- `credentials.json` — not committed (Google OAuth client secrets)
- `token.json` — not committed (generated OAuth token)
- `config/config.toml` — not committed (per-user configuration; `config/config.example.toml` is the template)
- Google Calendar access is read-only (`calendar.readonly` scope)
- Telegram bot tokens are stored in `config/config.toml` (local only)

## Tests

```bash
uv run pytest tests/ -v
```

## Project layout

```text
src/janus/
├── __init__.py              # CLI entry point — dispatches commands
├── today.py                 # Daily briefing renderer
├── weekly.py                # Weekly review renderer
├── telegram_weekly_cli.py
├── tasks_cli.py             # janus task <add|complete|state|progress>
├── workout_cli.py           # janus workout <add|show|summary>
├── goals_cli.py             # janus goal <list|show|add|update|complete>
├── verification.py          # Implementation contract verification pipeline
├── integrations/            # External integrations (Google Calendar, Telegram, markdown persistence)
├── models/                  # Domain models (Task, Goal, Workout, Event, AttentionItem, DailyBriefing,
│                              Source, Finding, ResearchArtifact, TopicBlock, KnowledgeSummary)
├── services/                # Business logic (briefing, goals, tasks, workouts, weekly review,
│                              knowledge pipeline — validation + summary generation)
data/                        # Tracked markdown data files
config/                      # Per-user configuration (gitignored)
docs/                        # Design docs, decisions, roadmap, verification pipeline
scripts/                     # Utility scripts (e.g. CI validation)
```

See [`docs/vision.md`](docs/vision.md) for the Hermes/Janus system model and [`docs/roadmap.md`](docs/roadmap.md) for strategic direction.
