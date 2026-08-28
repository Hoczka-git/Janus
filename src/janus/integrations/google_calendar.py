import tomllib
from datetime import date, datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

from janus.models.event import Event

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
TOKEN_PATH = PROJECT_ROOT / "token.json"


def get_calendar_service():
    credentials = None

    if TOKEN_PATH.exists():
        credentials = Credentials.from_authorized_user_file(
            TOKEN_PATH,
            SCOPES,
        )

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_PATH,
            SCOPES,
        )

        credentials = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(credentials.to_json())

    return build(
        "calendar",
        "v3",
        credentials=credentials,
    )


def parse_event(event: dict, source: str | None = None) -> Event:
    start_data = event["start"]
    end_data = event.get("end", {})

    if "dateTime" in start_data:
        start = datetime.fromisoformat(
            start_data["dateTime"].replace("Z", "+00:00")
        )
        end = datetime.fromisoformat(
            end_data["dateTime"].replace("Z", "+00:00")
        ) if "dateTime" in end_data else None

        return Event(
            title=(event.get("summary") or "Untitled event"),
            start=start,
            end=end,
            all_day=False,
            source=source,
        )

    return Event(
        title=(event.get("summary") or "Untitled event"),
        start=datetime.combine(
            date.fromisoformat(start_data["date"]),
            datetime.min.time(),
            tzinfo=timezone.utc,
        ),
        end=None,
        all_day=True,
        source=source,
    )


def _load_config() -> list[tuple[str, str]]:
    config_path = PROJECT_ROOT / "config" / "config.toml"
    if not config_path.exists():
        return []

    with config_path.open("rb") as f:
        data = tomllib.load(f)

    calendars: list[tuple[str, str]] = []
    gc = data.get("google_calendar", {})
    for entry in gc.get("calendars", []):
        calendar_id = entry.get("id", "")
        calendar_name = entry.get("name", calendar_id)
        if calendar_id:
            calendars.append((calendar_id, calendar_name))

    return calendars


def list_events(calendar_id: str) -> list[Event]:
    service = get_calendar_service()

    now = datetime.now().astimezone().isoformat()

    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    return [
        parse_event(event)
        for event in result.get("items", [])
    ]


def list_upcoming_events() -> list[Event]:
    calendars = _load_config()

    if not calendars:
        return []

    all_events: list[Event] = []

    for calendar_id, calendar_name in calendars:
        events = list_events(calendar_id)
        for event in events:
            event.source = calendar_name
        all_events.extend(events)

    all_events.sort(key=lambda e: (
        e.start is None or e.all_day,
        e.start or datetime.min.replace(tzinfo=timezone.utc),
    ))

    return all_events


