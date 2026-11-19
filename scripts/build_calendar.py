#!/usr/bin/env python3
"""Build a seven-day, six-location Movement Colorado yoga calendar.

The source is Movement's public, location-specific yoga calendar pages.
No credentials or private account data are used.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

TZ = ZoneInfo("America/Denver")
LOCATIONS = {
    "Baker": "baker",
    "Boulder": "boulder",
    "Centennial": "centennial",
    "Englewood": "englewood",
    "Golden": "golden",
    "RiNo": "rino",
}
DAY_RE = re.compile(r"\b(?:SUN|MON|TUE|WED|THU|FRI|SAT)\s+(\d{1,2}),\s*([A-Z]{3})\b", re.I)
EVENT_RE = re.compile(r"\b(\d{1,2}:\d{2}[ap])\s+(\d+)\s+min\s+(.+?)\s*$", re.I)
MONTHS = {name.upper(): number for number, name in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
) if name}


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


def date_from_heading(day: int, month_name: str, today: date) -> date:
    month = MONTHS[month_name.upper()]
    year = today.year
    candidate = date(year, month, day)
    if candidate < today - timedelta(days=180):
        candidate = date(year + 1, month, day)
    elif candidate > today + timedelta(days=180):
        candidate = date(year - 1, month, day)
    return candidate


def parse_location_text(text: str, location: str, today: date) -> list[dict]:
    events = []
    current_day = None
    saw_calendar_day = False
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        heading = DAY_RE.search(line)
        if heading:
            current_day = date_from_heading(int(heading.group(1)), heading.group(2), today)
            if today <= current_day <= today + timedelta(days=7):
                saw_calendar_day = True
            continue

        match = EVENT_RE.search(line)
        if not match or current_day is None or not (today <= current_day <= today + timedelta(days=7)):
            continue

        clock, duration, details = match.groups()
        parsed_time = datetime.strptime(clock.lower(), "%I:%M%p").time()
        start = datetime.combine(current_day, parsed_time, TZ)
        events.append({
            "location": location,
            "start": start,
            "end": start + timedelta(minutes=int(duration)),
            "details": details.strip(),
            "source": f"https://movementgyms.com/{LOCATIONS[location]}/calendar/yoga/",
        })

    if not saw_calendar_day:
        raise RuntimeError(f"{location}: could not find the current week's calendar dates; refusing to publish incomplete data")
    return events


def scrape() -> list[dict]:
    today = datetime.now(TZ).date()
    all_events: list[dict] = []
    failures = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(locale="en-US", timezone_id="America/Denver")

        # Diagnostic capture: identify the actual schedule-data request and failures.
        def log_request(request):
            u = request.url.lower()
            if any(term in u for term in ("api", "calendar", "graphql", "wp-json", "schedule", "class", "portal")):
                print(f"NET REQUEST {request.method} {request.url}")
        def log_response(response):
            u = response.url.lower()
            if any(term in u for term in ("api", "calendar", "graphql", "wp-json", "schedule", "class", "portal")):
                try:
                    ctype = response.headers.get("content-type", "")
                except Exception:
                    ctype = ""
                print(f"NET RESPONSE {response.status} {ctype} {response.url}")
                if "json" in ctype.lower():
                    try:
                        data = response.json()
                        print(f"NET JSON KEYS {response.url}: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}", flush=True)
                        if isinstance(data, dict):
                            for key, value in data.items():
                                if isinstance(value, list):
                                    first = value[0] if value else None
                                    print(f"NET JSON FIELD {key}: count={len(value)} first_type={type(first).__name__} first_sample={json.dumps(first, ensure_ascii=False)[:1800]}")
                                else:
                                    print(f"NET JSON FIELD {key}: type={type(value).__name__} sample={str(value)[:300]}")
                    except Exception as exc:
                        print(f"NET JSON READ ERROR {response.url}: {exc}")
        page.on("request", log_request)
        page.on("response", log_response)
        page.on("requestfailed", lambda request: print(f"NET FAILED {request.url} :: {request.failure}"))
        page.on("pageerror", lambda error: print(f"PAGE ERROR {error}"))
        page.on("console", lambda message: print(f"BROWSER CONSOLE {message.type}: {message.text}") if message.type == "error" else None)
        for location, slug in LOCATIONS.items():
            url = f"https://movementgyms.com/{slug}/calendar/yoga/"
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if response is None or response.status >= 400:
                    raise RuntimeError(f"page returned HTTP {response.status if response else 'no response'}")
                try:
                    page.wait_for_function(
                        "() => document.body && /\\d{1,2}:\\d{2}[ap]\\s+\\d+\\s+min/i.test(document.body.innerText)",
                        timeout=25000,
                    )
                except PlaywrightTimeoutError:
                    # A location can legitimately have no yoga sessions in the visible week.
                    page.wait_for_timeout(3000)
                body_text = page.locator("body").inner_text(timeout=15000)
                print(f"{location}: rendered body has {len(body_text)} characters; event-pattern matches={len(re.findall(EVENT_RE, body_text))}; day-heading matches={len(re.findall(DAY_RE, body_text))}")
                try:
                    parsed = parse_location_text(body_text, location, today)
                except Exception as parse_exc:
                    sample = "\\n".join(body_text.splitlines()[:45])
                    raise RuntimeError(f"{parse_exc}; page text sample:\\n{sample}") from parse_exc
                all_events.extend(parsed)
                print(f"{location}: {len(parsed)} yoga classes")
            except Exception as exc:
                failures.append(f"{location}: {exc}")
        browser.close()

    if failures:
        raise RuntimeError("One or more location calendars could not be read; not publishing a partial calendar:\n" + "\n".join(failures))
    if not all_events:
        raise RuntimeError("No yoga classes were found across all six locations; refusing to publish an empty calendar.")

    # Deduplicate repeated entries that can appear in Movement's calendar markup.
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
