"""Minimal iCalendar (.ics) reader for importing upcoming events as priority tasks.

Reads SUMMARY and DTSTART from each VEVENT. Works with exports from Google Calendar,
Outlook, and Apple Calendar. It is not a full RFC 5545 implementation (no recurrence rules).
"""
import re
from datetime import date

MAX_EVENTS = 200


def _unfold(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n[ \t]", "", text)


def _unescape(value):
    return (value.replace("\\,", ",").replace("\\;", ";")
                 .replace("\\n", " ").replace("\\N", " ").replace("\\\\", "\\").strip())


def _to_date(value):
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_events(text):
    """Return a list of {"title": str, "date": "YYYY-MM-DD"} for every usable event."""
    events, current = [], None
    for line in _unfold(text or "").split("\n"):
        line = line.strip()
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            key_part, value = line.split(":", 1)
            key = key_part.split(";")[0].upper()
            if key in ("SUMMARY", "DTSTART"):
                current[key] = value
    out = []
    for ev in events:
        title = _unescape(ev.get("SUMMARY", ""))
        day = _to_date(ev.get("DTSTART", ""))
        if title and day:
            out.append({"title": title[:120], "date": day.isoformat()})
    return out
