#!/usr/bin/env python3
"""Build a seven-day, six-location Movement Colorado yoga calendar.

The source is Movement's public, location-specific yoga calendar pages.
No credentials or private account data are used.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

TZ = ZoneInfo("America/Denver")
LOCATIONS = {
    "Baker": "baker",
    "Boulder": "boulder",
    "Centennial": "centennial",
    "Englewood": "englewood",
    "Golden": "golden",
    "RiNo": "rino",
}
def ics_escape(value: str) -> str:
    return (value.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r", "").replace("\n", "\\n"))


def fold_ics_line(line: str) -> str:
    """Fold content lines at 75 UTF-8 octets as required by RFC 5545."""
    chunks, current, size = [], "", 0
    for char in line:
        encoded = char.encode("utf-8")
        if size + len(encoded) > 75:
            chunks.append(current)
            current, size = " ", 1
        current += char
        size += len(encoded)
    chunks.append(current)
    return "\r\n".join(chunks)


def scrape() -> list[dict]:
    """Read Movement's public calendar JSON API, not the page's rendered UI."""
    today = datetime.now(TZ).date()
    last_day = today + timedelta(days=7)
    months = {(today.year, today.month), (last_day.year, last_day.month)}
    all_events: list[dict] = []
    failures = []

    with sync_playwright() as playwright:
        api = playwright.request.new_context(
            user_agent="Mozilla/5.0 (compatible; MovementYogaCalendar/1.0)"
        )
        try:
            for location, slug in LOCATIONS.items():
                location_events = []
                try:
                    for year, month in sorted(months):
                        month_key = f"{year:04d}-{month:02d}"
                        url = f"https://movementgyms.com/api/calendar/{slug}?m={month_key}"
                        response = api.get(url, timeout=45000)
                        if not response.ok:
                            raise RuntimeError(f"API returned HTTP {response.status} for {month_key}")
                        payload = response.json()
                        if not isinstance(payload, dict) or not isinstance(payload.get("occurrences"), list):
                            raise RuntimeError(f"Unexpected API response structure for {month_key}")
                        if payload.get("failedMonths"):
                            raise RuntimeError(f"Movement reported unavailable schedule data: {payload['failedMonths']}")
                        for item in payload["occurrences"]:
                            if not isinstance(item, dict) or str(item.get("discipline", "")).lower() != "yoga":
                                continue
                            try:
                                class_date = date.fromisoformat(item["date"])
                                if not today <= class_date <= last_day:
                                    continue
                                clock = datetime.strptime(item["time"], "%H:%M").time()
                                start = datetime.combine(class_date, clock, TZ)
                                duration = int(item["durationMinutes"])
                                if duration <= 0:
                                    raise ValueError("non-positive duration")
                                name = str(item.get("name") or "Yoga")
                                instructor = str(item.get("instructor") or "").strip()
                                details = f"{name} with {instructor}" if instructor else name
                                location_events.append({
                                    "location": location,
                                    "start": start,
                                    "end": start + timedelta(minutes=duration),
                                    "details": details,
                                    "source": str(item.get("signUpLink") or f"https://movementgyms.com/{slug}/calendar/yoga/"),
                                })
                            except (KeyError, TypeError, ValueError) as exc:
                                raise RuntimeError(f"Invalid yoga occurrence record: {item!r}: {exc}") from exc
                    all_events.extend(location_events)
                    print(f"{location}: {len(location_events)} yoga classes in {today} through {last_day}", flush=True)
                except Exception as exc:
                    failures.append(f"{location}: {exc}")
        finally:
            api.dispose()

    if failures:
        raise RuntimeError("One or more location APIs could not be read; not publishing a partial calendar:\\n" + "\\n".join(failures))
    if not all_events:
        raise RuntimeError("No yoga classes were returned for the next eight calendar days; refusing to publish an empty calendar.")

    unique = {}
    for event in all_events:
        key = (event["location"], event["start"], event["details"])
        unique[key] = event
    return sorted(unique.values(), key=lambda item: (item["start"], item["location"], item["details"]))


def make_calendar(events: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Movement Colorado Yoga Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Movement Yoga - Colorado",
        "X-WR-TIMEZONE:America/Denver",
        "X-PUBLISHED-TTL:PT12H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    ]
    for event in events:
        identity = "|".join([
            event["location"], event["start"].isoformat(), event["details"]
        ])
        uid = hashlib.sha256(identity.encode("utf-8")).hexdigest() + "@movement-yoga-calendar"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID=America/Denver:{event['start'].strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID=America/Denver:{event['end'].strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{ics_escape(event['details'])} ({ics_escape(event['location'])})",
            f"LOCATION:{ics_escape('Movement ' + event['location'] + ', Colorado')}",
            f"DESCRIPTION:{ics_escape('Instructor/class details as listed by Movement. Official schedule: ' + event['source'])}",
            f"URL:{event['source']}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_ics_line(line) for line in lines) + "\r\n"


if __name__ == "__main__":
    result = scrape()
    output = Path("calendar.ics")
    output.write_text(make_calendar(result), encoding="utf-8", newline="")
    print(f"Wrote {len(result)} classes to {output}")

# Controlled publish validation run.
