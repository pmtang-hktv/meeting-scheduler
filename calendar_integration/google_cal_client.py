from __future__ import annotations
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_service = None


def authenticate(
    creds_path: str = "credentials.json",
    token_path: str = "data/google_token.json",
    service_account_path: str = "service_account.json",
) -> None:
    """Authenticate with Google Calendar API.

    Prefers service_account.json (permanent, no browser) if it exists.
    Falls back to OAuth flow (requires browser on first run).
    """
    global _service
    from googleapiclient.discovery import build

    sa_file = Path(service_account_path)
    if sa_file.exists():
        from google.oauth2 import service_account as sa_module
        creds = sa_module.Credentials.from_service_account_file(
            str(sa_file), scopes=_SCOPES
        )
        _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        logger.info("Google Calendar authenticated via service account (%s)", sa_file)
        return

    # Fall back to OAuth flow (user credentials)
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_file = Path(creds_path)
    token_file = Path(token_path)

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning("Token refresh failed (%s) — re-authenticating via browser", e)
                creds = None
        if not creds or not creds.valid:
            if not creds_file.exists():
                raise FileNotFoundError(
                    f"\n\nMissing {creds_path}.\n"
                    "Download OAuth credentials from Google Cloud Console:\n"
                    "  APIs & Services → Credentials → Create OAuth 2.0 Client ID"
                    " (Desktop app) → Download JSON\n"
                    f"Save the file as '{creds_path}' in your meeting-scheduler folder.\n"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), _SCOPES)
            creds = flow.run_local_server(port=0)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json())
        logger.info("Google Calendar OAuth credentials saved to %s", token_file)

    _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    logger.info("Google Calendar API authenticated via OAuth")


def get_service():
    if _service is None:
        raise RuntimeError("Google Calendar not authenticated — call authenticate() before starting the bot.")
    return _service


async def _run(fn):
    """Run a blocking Google API call in an executor so the event loop stays responsive."""
    return await asyncio.get_event_loop().run_in_executor(None, fn)


async def api_list_calendars() -> list[dict]:
    try:
        svc = get_service()
        result = await _run(lambda: svc.calendarList().list(minAccessRole="writer").execute())
        return result.get("items", [])
    except Exception:
        logger.exception("Failed to list calendars")
        return []


async def api_get_events(calendar_id: str, time_min: str, time_max: str) -> list[dict] | None:
    try:
        svc = get_service()
        result = await _run(
            lambda: svc.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=500,
            ).execute()
        )
        return result.get("items", [])
    except Exception as e:
        logger.warning("Failed to fetch events for calendar %s: %s", calendar_id, e)
        return None


async def api_create_event(calendar_id: str, body: dict) -> str:
    try:
        svc = get_service()
        result = await _run(lambda: svc.events().insert(calendarId=calendar_id, body=body).execute())
        return result.get("id", "")
    except Exception:
        logger.exception("Failed to create calendar event")
        return ""


async def api_delete_event(calendar_id: str, event_id: str) -> bool:
    try:
        svc = get_service()
        await _run(lambda: svc.events().delete(calendarId=calendar_id, eventId=event_id).execute())
        return True
    except Exception:
        logger.exception("Failed to delete calendar event %s", event_id)
        return False


async def api_get_event(calendar_id: str, event_id: str) -> dict | None:
    try:
        svc = get_service()
        return await _run(lambda: svc.events().get(calendarId=calendar_id, eventId=event_id).execute())
    except Exception:
        logger.exception("Failed to get event %s", event_id)
        return None
