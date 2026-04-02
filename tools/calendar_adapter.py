"""Calendar tools — list, create, and manage events via local .ics files.

ZERO external dependencies — generates valid ICS files using plain string formatting.
Includes demo/mock events so the calendar is never empty for the prototype.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_CAL_DIR: Path | None = None

# =========================================================================== #
#  ICS generation (no dependencies)
# =========================================================================== #

_ICS_TEMPLATE = """\
BEGIN:VCALENDAR
PRODID:-//HaloDesk//EN
VERSION:2.0
CALSCALE:GREGORIAN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{dtstamp}
DTSTART:{dtstart}
DTEND:{dtend}
SUMMARY:{summary}
DESCRIPTION:{description}
LOCATION:{location}
END:VEVENT
END:VCALENDAR"""


def _fmt_dt(dt: datetime) -> str:
    """Format datetime as ICS timestamp (e.g. 20260210T140000)."""
    return dt.strftime("%Y%m%dT%H%M%S")


def _write_ics(path: Path, summary: str, dt_start: datetime, dt_end: datetime,
               description: str = "", location: str = "") -> Path:
    """Write a valid .ics file and return the path."""
    content = _ICS_TEMPLATE.format(
        uid=str(uuid.uuid4()),
        dtstamp=_fmt_dt(datetime.now()),
        dtstart=_fmt_dt(dt_start),
        dtend=_fmt_dt(dt_end),
        summary=summary,
        description=description,
        location=location,
    )
    path.write_text(content)
    return path


# =========================================================================== #
#  ICS reading (no dependencies — simple text parser)
# =========================================================================== #

def _parse_ics_dt(val: str) -> str:
    """Parse an ICS datetime string into a human-readable format."""
    val = val.strip().rstrip("Z")
    try:
        dt = datetime.strptime(val, "%Y%m%dT%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        try:
            dt = datetime.strptime(val, "%Y%m%d")
            return dt.strftime("%Y-%m-%d (all day)")
        except ValueError:
            return val


def _parse_ics_events(path: Path) -> list[dict]:
    """Parse a .ics file using plain text. Returns list of event dicts."""
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return []

    events = []
    # Split on VEVENT blocks
    blocks = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.DOTALL)
    for block in blocks:
        ev: dict[str, str] = {}
        for line in block.strip().splitlines():
            line = line.strip()
            if ":" in line:
                key, _, val = line.partition(":")
                # Handle keys with parameters like DTSTART;VALUE=DATE:20260210
                key = key.split(";")[0].upper()
                ev[key] = val.strip()
        events.append({
            "uid": ev.get("UID", ""),
            "summary": ev.get("SUMMARY", "(no title)"),
            "start": _parse_ics_dt(ev.get("DTSTART", "")),
            "end": _parse_ics_dt(ev.get("DTEND", "")),
            "description": ev.get("DESCRIPTION", ""),
            "location": ev.get("LOCATION", ""),
            "file": str(path),
        })
    return events


# =========================================================================== #
#  Demo / mock calendar
# =========================================================================== #

def _ensure_demo_events(cal_dir: Path):
    """Seed a few demo events so the calendar isn't empty."""
    marker = cal_dir / ".demo_seeded"
    if marker.exists():
        return

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    demos = [
        {
            "file": "demo_standup.ics",
            "summary": "Daily Standup",
            "start": today + timedelta(days=1, hours=9, minutes=30),
            "end": today + timedelta(days=1, hours=9, minutes=45),
            "description": "Quick sync with the team",
            "location": "Zoom",
        },
        {
            "file": "demo_lunch.ics",
            "summary": "Lunch with Marketing Team",
            "start": today + timedelta(days=1, hours=12),
            "end": today + timedelta(days=1, hours=13),
            "description": "Discuss Q1 campaign results",
            "location": "Cafeteria",
        },
        {
            "file": "demo_review.ics",
            "summary": "Project Review",
            "start": today + timedelta(days=2, hours=14),
            "end": today + timedelta(days=2, hours=15),
            "description": "Sprint retrospective and planning",
            "location": "Conference Room B",
        },
        {
            "file": "demo_free_afternoon.ics",
            "summary": "Focus Time (blocked)",
            "start": today + timedelta(days=3, hours=14),
            "end": today + timedelta(days=3, hours=17),
            "description": "Deep work block",
            "location": "",
        },
    ]

    for d in demos:
        _write_ics(
            cal_dir / d["file"],
            summary=d["summary"],
            dt_start=d["start"],
            dt_end=d["end"],
            description=d["description"],
            location=d["location"],
        )

    marker.write_text("demo events created")
    logger.info("Seeded %d demo calendar events in %s", len(demos), cal_dir)


# =========================================================================== #
#  Init
# =========================================================================== #

def _init_cal_dir(cfg: dict) -> Path:
    global _CAL_DIR
    _CAL_DIR = Path(cfg.get("ics_directory", "data/calendars"))
    _CAL_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_demo_events(_CAL_DIR)
    return _CAL_DIR


# =========================================================================== #
#  list_events
# =========================================================================== #

class ListEventsTool(BaseTool):
    def __init__(self, cfg: dict):
        _init_cal_dir(cfg)

    @property
    def name(self) -> str:
        return "list_events"

    @property
    def description(self) -> str:
        return "List upcoming calendar events from local .ics files. Use this to check the user's schedule and find free time slots."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "Number of days to look ahead (default 7).",
                },
            },
            "required": [],
        }

    def run(self, **kwargs) -> ToolResult:
        all_events = []
        for ics in sorted(_CAL_DIR.glob("*.ics")):
            all_events.extend(_parse_ics_events(ics))

        if not all_events:
            return ToolResult(success=True, data="Calendar is completely free — no events scheduled.")

        # Build a clear busy/free report
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        lines = ["EXISTING EVENTS (these times are BUSY — do NOT suggest these):"]
        for e in all_events:
            lines.append(f"  BUSY: {e['start']} - {e['end']} — {e['summary']}")

        # Suggest free slots for the next 3 working days
        lines.append("")
        lines.append("SUGGESTED FREE TIMES (these are available — suggest these to the user):")
        busy_hours: set[str] = set()
        for e in all_events:
            # Extract the hour from start time
            busy_hours.add(e['start'][:13])  # e.g. "2026-02-10 09"

        for day_offset in range(1, 4):
            day = today + timedelta(days=day_offset)
            day_str = day.strftime("%Y-%m-%d")
            day_name = day.strftime("%A")
            if day.weekday() >= 5:  # skip weekends
                continue
            for hour in [10, 14, 16]:  # 10am, 2pm, 4pm
                slot_key = f"{day_str} {hour:02d}"
                if slot_key not in busy_hours:
                    lines.append(f"  FREE: {day_name} {day_str} at {hour}:00")

        return ToolResult(success=True, data="\n".join(lines))


# =========================================================================== #
#  create_event
# =========================================================================== #

class CreateEventTool(BaseTool):
    def __init__(self, cfg: dict):
        _init_cal_dir(cfg)

    @property
    def name(self) -> str:
        return "create_event"

    @property
    def description(self) -> str:
        return (
            "Create a new calendar event and save it as a downloadable .ics file. "
            "IMPORTANT: Only call this tool when you have a specific date AND time. "
            "If the user hasn't provided a date/time, ask them first — do NOT guess."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title."},
                "start": {"type": "string", "description": "Start datetime in ISO format (e.g. '2026-02-10T14:00:00'). REQUIRED — do NOT call without this."},
                "end": {"type": "string", "description": "End datetime (optional; defaults to 1 hour after start)."},
                "description": {"type": "string", "description": "Event description (optional)."},
                "location": {"type": "string", "description": "Location (optional)."},
            },
            "required": ["summary", "start"],
        }

    def run(self, **kwargs) -> ToolResult:
        try:
            summary = kwargs.get("summary", "")
            start_str = kwargs.get("start", "")
            end_str = kwargs.get("end")
            desc = kwargs.get("description", "")
            location = kwargs.get("location", "")

            if not summary:
                return ToolResult(success=False, error="Missing event title.")
            if not start_str:
                return ToolResult(success=False, error="Missing start time. Please ask the user for a specific date and time.")

            # Parse start
            dt_start = _parse_datetime(start_str)
            if dt_start is None:
                return ToolResult(success=False, error=f"Could not parse start time: '{start_str}'. Use ISO format like '2026-02-10T14:00:00'.")

            # Parse end
            if end_str:
                dt_end = _parse_datetime(end_str)
                if dt_end is None:
                    dt_end = dt_start + timedelta(hours=1)
            else:
                dt_end = dt_start + timedelta(hours=1)

            filename = f"event_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ics"
            out_path = _CAL_DIR / filename
            _write_ics(out_path, summary, dt_start, dt_end, desc, location)

            logger.info("Event created: %s → %s", summary, out_path)
            return ToolResult(success=True, data=json.dumps({
                "message": f"Event '{summary}' created successfully.",
                "ics_file": str(out_path),
                "summary": summary,
                "start": dt_start.strftime("%Y-%m-%d %H:%M"),
                "end": dt_end.strftime("%Y-%m-%d %H:%M"),
                "location": location,
            }), generated_files=[{"type": "ics", "path": str(out_path), "label": summary}])

        except Exception as exc:
            logger.error("create_event failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


# =========================================================================== #
#  create_reminder
# =========================================================================== #

class CreateReminderTool(BaseTool):
    def __init__(self, cfg: dict):
        _init_cal_dir(cfg)

    @property
    def name(self) -> str:
        return "create_reminder"

    @property
    def description(self) -> str:
        return (
            "Create a reminder saved as a short .ics calendar event. "
            "IMPORTANT: Only call this when you have a specific date/time. "
            "If the user hasn't provided when, ask them first."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Reminder title."},
                "when": {"type": "string", "description": "When to remind — ISO datetime. REQUIRED."},
            },
            "required": ["title", "when"],
        }

    def run(self, **kwargs) -> ToolResult:
        try:
            title = kwargs.get("title", "")
            when_str = kwargs.get("when", "")

            if not title:
                return ToolResult(success=False, error="Missing reminder title.")
            if not when_str:
                return ToolResult(success=False, error="Missing time. Please ask the user when they want to be reminded.")

            dt_start = _parse_datetime(when_str)
            if dt_start is None:
                return ToolResult(success=False, error=f"Could not parse time: '{when_str}'. Use ISO format.")

            dt_end = dt_start + timedelta(minutes=15)
            summary = title

            filename = f"reminder_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ics"
            out_path = _CAL_DIR / filename
            _write_ics(out_path, summary, dt_start, dt_end, "Reminder created by HaloDesk")

            logger.info("Reminder created: %s → %s", title, out_path)
            return ToolResult(success=True, data=json.dumps({
                "message": f"Reminder '{summary}' created successfully.",
                "ics_file": str(out_path),
                "summary": summary,
                "start": dt_start.strftime("%Y-%m-%d %H:%M"),
            }), generated_files=[{"type": "ics", "path": str(out_path), "label": title}])

        except Exception as exc:
            logger.error("create_reminder failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


# =========================================================================== #
#  Helpers
# =========================================================================== #

def _parse_datetime(s: str) -> datetime | None:
    """Try multiple datetime formats and return a datetime or None."""
    s = s.strip()
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%d/%m/%Y %H:%M",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Try Python's fromisoformat
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    return None
