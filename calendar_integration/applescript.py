from __future__ import annotations
import logging
import subprocess
import time as _time
from datetime import datetime

logger = logging.getLogger(__name__)


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


def _epoch(dt: datetime) -> int:
    """Convert datetime to Unix epoch seconds."""
    return int(dt.timestamp())


def get_events_script(start_dt: datetime, end_dt: datetime) -> str:
    s = _epoch(start_dt)
    e = _epoch(end_dt)
    return f'''
tell application "Calendar"
    set output to ""
    set startDate to (do shell script "date -r {s} '+%m/%d/%Y %H:%M:%S'")
    set endDate to (do shell script "date -r {e} '+%m/%d/%Y %H:%M:%S'")
    set startDate to date startDate
    set endDate to date endDate
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
    s = _epoch(start_dt)
    e = _epoch(end_dt)
    safe_title = title.replace('"', '\\"')
    safe_loc = location.replace('"', '\\"')
    safe_notes = notes.replace('"', '\\"')
    return f'''
tell application "Calendar"
    tell calendar "{calendar_name}"
        set startDate to (do shell script "date -r {s} '+%m/%d/%Y %H:%M:%S'")
        set endDate to (do shell script "date -r {e} '+%m/%d/%Y %H:%M:%S'")
        set newEvent to make new event with properties {{summary:"{safe_title}", start date:date startDate, end date:date endDate, location:"{safe_loc}", description:"{safe_notes}"}}
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
