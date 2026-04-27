from __future__ import annotations
import logging
import subprocess
import time as _time
from datetime import datetime

logger = logging.getLogger(__name__)

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


def run_applescript(script: str, retries: int = 1) -> str:
    """Run an AppleScript string and return stdout. Retries once on failure."""
    for attempt in range(retries + 1):
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            logger.warning("AppleScript error (attempt %d): %s", attempt + 1, result.stderr.strip())
            if attempt < retries:
                _time.sleep(1)
        except subprocess.TimeoutExpired:
            logger.warning("AppleScript timed out (attempt %d)", attempt + 1)
            if attempt < retries:
                _time.sleep(1)
    return ""


def _date_args(dt: datetime) -> str:
    """Return AppleScript makeDate() call for a datetime."""
    return f"makeDate({dt.year}, {dt.month}, {dt.day}, {dt.hour}, {dt.minute}, {dt.second})"


def get_events_script(start_dt: datetime, end_dt: datetime) -> str:
    s = _date_args(start_dt)
    e = _date_args(end_dt)
    return f'''
{_MAKE_DATE_HANDLER}
tell application "Calendar"
    set output to ""
    set startDate to {s}
    set endDate to {e}
    repeat with cal in calendars
        set evts to (every event of cal whose start date >= startDate and start date < endDate)
        repeat with evt in evts
            set uid to uid of evt
            set evtStart to start date of evt
            set evtEnd to end date of evt
            set startEpoch to (do shell script "date -jf '%A, %B %e, %Y %H:%M:%S' '" & (evtStart as string) & "' '+%s' 2>/dev/null || echo ''")
            set endEpoch to (do shell script "date -jf '%A, %B %e, %Y %H:%M:%S' '" & (evtEnd as string) & "' '+%s' 2>/dev/null || echo ''")
            set output to output & "|||" & uid & "|" & startEpoch & "|" & endEpoch & return
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
{_MAKE_DATE_HANDLER}
tell application "Calendar"
    tell calendar "{calendar_name}"
        set startDate to {s}
        set endDate to {e}
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
