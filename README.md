# Janus

Personal chief of staff assistant focused on proactive personal life management.

## Current capabilities

- Google Calendar read-only integration
- Multiple configured calendars (Job, Personal, and more)
- Unified event stream across all configured calendars
- Daily briefing via `janus today`

## Setup

### Requirements

- Python 3.11
- [uv](https://github.com/astral-sh/uv)
- Google Calendar OAuth credentials

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

3. Run `uv run janus today` — OAuth token is generated automatically on first run.

### Run

```bash
uv run janus today
```

Example output:

```
JANUS — TODAY

Events:
09:00 — Daily standup — Job
18:00 — Gym session — Personal

Requires attention:
- Buy groceries
- Prepare training plan
```

### Tests

```bash
uv run pytest
```

## Security

- `credentials.json` — not committed
- `token.json` — not committed
- `config/config.toml` — not committed
- Google Calendar access is read-only (`calendar.readonly` scope)
