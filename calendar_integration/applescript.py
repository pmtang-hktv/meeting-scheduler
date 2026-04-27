from __future__ import annotations
import logging
import subprocess
import time as _time
from datetime import datetime

logger = logging.getLogger(__name__)

# Formats an AppleScript date as ISO8601 with HKT offset — no shell calls needed.
_DATE_TO_ISO_HANDLER = """
on pad2(n)
    if n < 10 then return "0" & (n as string)
    return n as string
end pad2

on dateToISO(d)
    set t to time of d
    set hr to t div 3600
    set mn to (t mod 3600) div 60
    set sc to t mod 60
    return (year of d as string) & "-" & my pad2(month of d as integer) & "-" & ¬
           my pad2(day of d) & "T" & my pad2(hr) & ":" & my pad2(mn) & ":" & ¬
           my pad2(sc) & "+08:00"
end dateToISO
"""

# AppleScript handler that builds a date by setting individual components,
# avoiding all locale-sensitive date string parsing.
_MAKE_DATE_HANDLER = """
on makeDate(yr, mo, dy, hr, mn, sc)
    set d to current date
    set time of d to 0
    set year of d to yr
    set month of d to 1
    set day of d to 1
    set month of d to mo
    set day of d to dy
    set time of d to (hr * 3600 + mn * 60 + sc)
    return d
end makeDate
"""

_ALL_HANDLERS = _DATE_TO_ISO_HANDLER + _MAKE_DATE_HANDLER


def run_applescript(script: str, retries: int = 2, timeout: int = 15) -> str | None:
    """Run an AppleScript string and return stdout, or None on error/timeout."""
    for attempt in range(retries + 1):
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            logger.warning("AppleScript error (attempt %d): %s", attempt + 1, result.stderr.strip())
            if attempt < retries:
                _time.sleep(0.5)
        except subprocess.TimeoutExpired:
            logger.warning("AppleScript timed out after %ds (attempt %d)", timeout, attempt + 1)
            if attempt < retries:
                _time.sleep(0.5)
    return None


def _date_args(dt: datetime) -> str:
    """Return AppleScript makeDate() call for a datetime."""
    return f"makeDate({dt.year}, {dt.month}, {dt.day}, {dt.hour}, {dt.minute}, {dt.second})"


def get_events_script(start_dt: datetime, end_dt: datetime) -> str:
    s = _date_args(start_dt)
    e = _date_args(end_dt)
    return f'''
{_ALL_HANDLERS}
tell application "Calendar"
    set output to ""
    set startDate to my {s}
    set endDate to my {e}
    repeat with cal in calendars
        set evts to (every event of cal whose start date >= startDate and start date < endDate)
        repeat with evt in evts
            set uid to uid of evt
            set startStr to my dateToISO(start date of evt)
            set endStr to my dateToISO(end date of evt)
            set output to output & "|||" & uid & "|" & startStr & "|" & endStr & return
        end repeat
    end repeat
    return output
end tell
'''


def create_event_script(
    calendar_name: str,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    location: str = "",
    notes: str = "",
) -> str:
    s = _date_args(start_dt)
    e = _date_args(end_dt)
    safe_title = title.replace('"', '\\"')
    safe_loc = location.replace('"', '\\"')
    safe_notes = notes.replace('"', '\\"')
    return f'''
{_ALL_HANDLERS}
tell application "Calendar"
    tell calendar "{calendar_name}"
        set startDate to my {s}
        set endDate to my {e}
        set newEvent to make new event with properties {{summary:"{safe_title}", start date:startDate, end date:endDate, location:"{safe_loc}", description:"{safe_notes}"}}
        return uid of newEvent
    end tell
end tell
'''


def delete_event_script(uid: str) -> str:
    safe_uid = uid.replace('"', '\\"')
    return f'''
tell application "Calendar"
    repeat with cal in calendars
        set evts to (every event of cal whose uid = "{safe_uid}")
        if length of evts > 0 then
            delete first item of evts
            return "deleted"
        end if
    end repeat
    return "not_found"
end tell
'''


def find_event_script(uid: str) -> str:
    safe_uid = uid.replace('"', '\\"')
    return f'''
tell application "Calendar"
    repeat with cal in calendars
        set evts to (every event of cal whose uid = "{safe_uid}")
        if length of evts > 0 then
            set evt to first item of evts
            return uid of evt & "|" & (start date of evt as string) & "|" & (end date of evt as string)
        end if
    end repeat
    return ""
end tell
'''
