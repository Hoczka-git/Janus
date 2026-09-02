#!/usr/bin/env python3
"""
Select the next company from the watchlist for research.

Reads companies/watchlist.json, picks the company with no last_research (priority 1)
or the oldest last_research (priority 2), with alphabetical tiebreak by ticker.
Prints JSON to stdout.

Output format:
    {"ticker": "...", "folder": "...", "name": "...", "name_pl": "...", "isin": "...", "sector": "...", "last_research": "...", "chosen_today": true, "reason": "..."}

Exit 0 on success, 1 on error.
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

WATCHLIST_PATH = Path("/home/dan11hermes/workspaces/companies/watchlist.json")


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def select(data: dict) -> dict:
    companies = data.get("companies", [])
    today = date.today()

    # Priority 1: no last_research
    no_research = [c for c in companies if parse_date(c.get("last_research")) is None]
    if no_research:
        no_research.sort(key=lambda c: c.get("ticker", ""))
        chosen = no_research[0]
        chosen["chosen_today"] = True
        chosen["reason"] = "no_last_research"
        return chosen

    # Priority 2: oldest last_research, alphabetical tiebreak by ticker
    def key(c):
        d = parse_date(c.get("last_research"))
        return (d if d else today, c.get("ticker", ""))

    candidates = sorted(companies, key=key)
    chosen = candidates[0]
    chosen["chosen_today"] = True
    chosen["reason"] = "oldest_last_research"
    return chosen


def main() -> None:
    try:
        raw = WATCHLIST_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"ERROR: {WATCHLIST_PATH} not found", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: read failed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    company = select(data)
    # Remove status/note fields that are internal
    company.pop("status", None)
    company.pop("note", None)
    print(json.dumps(company, ensure_ascii=False))


if __name__ == "__main__":
    main()