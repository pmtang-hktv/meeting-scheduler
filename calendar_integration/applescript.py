from __future__ import annotations
import subprocess
import time as _time
from datetime import datetime


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
            if attempt < retries:
                _time.sleep(1)
        except subprocess.TimeoutExpired:
            if attempt < retries:
                _time.sleep(1)
    return ""


def _as_date_str(dt: datetime) -> str:
    """Format datetime as AppleScript-safe date string: 'MM/DD/YYYY HH:MM:SS'"""
    return dt.strftime("%-m/%-d/%Y %H:%M:%S")


def get_events_script(start_dt: datetime, end_dt: datetime) -> str:
    s = _as_date_str(start_dt)
    e = _as_date_str(end_dt)
    return f'''
tell application "Calendar"
    set output to ""
    set startDate to date "{s}"
    set endDate to date "{e}"
    repeat with cal in calendars
        set evts to (every event of cal whose start date >= startDate and start date < endDate)
        repeat with evt in evts
            set uid to uid of evt
            set evtStart to start date of evt
            set evtEnd to end date of evt
            set startStr to do shell script "date -jf '%m/%d/%Y %H:%M:%S' '" & (evtStart as string) & "' '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo ''"
            set endStr to do shell script "date -jf '%m/%d/%Y %H:%M:%S' '" & (evtEnd as string) & "' '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo ''"
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
    s = _as_date_str(start_dt)
    e = _as_date_str(end_dt)
    safe_title = title.replace('"', '\\"')
    safe_loc = location.replace('"', '\\"')
    safe_notes = notes.replace('"', '\\"')
    return f'''
tell application "Calendar"
    tell calendar "{calendar_name}"
        set newEvent to make new event with properties {{summary:"{safe_title}", start date:date "{s}", end date:date "{e}", location:"{safe_loc}", description:"{safe_notes}"}}
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
