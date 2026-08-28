# Janus

Personal chief of staff assistant focused on proactive personal life management.

## Current capabilities

- Google Calendar read-only integration
- Multiple configured calendars (Job, Personal, and more)
- Unified daily view with events from all configured calendars
- `janus today` command for daily overview

## Setup

### Requirements

- Python 3.11
- [uv](https://github.com/astral-sh/uv)
- Google Calendar OAuth credentials

### Installation

```bash
uv sync
```

### Configuration

Copy `config/config.example.toml` to `config/config.toml` and fill in your calendar IDs:

```toml
[google_calendar]
[[google_calendar.calendars]]
id = "JOB_CALENDAR_ID"
name = "Job"

[[google_calendar.calendars]]
id = "PERSONAL_CALENDAR_ID"
name = "Personal"
```

**Do not commit `config/config.toml`** — it is listed in `.gitignore`. The example file is safe to commit.

### Google Calendar OAuth

1. Create a project in Google Cloud Console
2. Enable the Calendar API
3. Create OAuth 2.0 credentials (Desktop app)
4. Download `credentials.json` and place it in the project root
5. Run `uv run janus today` — the OAuth token is generated automatically

### Usage

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

## Development

### Running tests

```bash
uv run pytest
```

### Project structure

```
janus/
├── src/janus/
│   ├── __init__.py        # CLI entry point
│   ├── today.py           # Today command
│   ├── models/
│   │   ├── event.py       # Event model
│   │   └── task.py        # Task model
│   └── integrations/
│       ├── __init__.py
│       └── google_calendar.py
├── tests/
│   ├── test_today.py
│   └── test_google_calendar.py
├── config/
│   ├── config.example.toml  # Template (committed)
│   └── config.toml          # Your config (not committed)
├── pyproject.toml
└── .gitignore
```

## Security

- `credentials.json` — OAuth client secrets (not committed)
- `token.json` — OAuth access/refresh tokens (not committed)
- `config/config.toml` — calendar IDs (not committed)
- Read-only scope: `https://www.googleapis.com/auth/calendar.readonly`

## License
