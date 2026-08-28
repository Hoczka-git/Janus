from datetime import date, datetime
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

def parse_event(event: dict) -> Event:
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
            title=event.get("summary", "Untitled event"),
            start=start,
            end=end,
            all_day=False,
        )

    return Event(
        title=event.get("summary", "Untitled event"),
        start=datetime.combine(
            date.fromisoformat(start_data["date"]),
            datetime.min.time(),
        ),
        end=None,
        all_day=True,
    )

def list_upcoming_events() -> list[Event]:
    service = get_calendar_service()

    now = datetime.now().astimezone().isoformat()

    result = (
        service.events()
        .list(
            calendarId="primary",
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

def main() -> None:
    events = list_upcoming_events()

    if not events:
        print("No upcoming events.")
        return

    for event in events:
        print(f"{event.start} — {event.title}")


if __name__ == "__main__":
    main()
