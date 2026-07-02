from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    owner_telegram_id: int
    anthropic_api_key: str
    anthropic_model: str
    google_maps_api_key: str
    default_calendar_name: str
    db_path: str
    office_address: str
    owner_name: str
    # Optional: comma-separated Google Calendar IDs to monitor for conflicts.
    # Required when using a service account (auto-discovery doesn't work for service accounts).
    calendar_ids: list[str]


def load_settings() -> Settings:
    load_dotenv()
    raw_ids = os.getenv("CALENDAR_IDS", "")
    calendar_ids = [i.strip() for i in raw_ids.split(",") if i.strip()]
    return Settings(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        owner_telegram_id=int(_require("OWNER_TELEGRAM_ID")),
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        # Sonnet 4.6 handles messy multi-part requests more reliably than Haiku; override
        # via ANTHROPIC_MODEL to roll back to e.g. claude-haiku-4-5 without a code change.
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        google_maps_api_key=_require("GOOGLE_MAPS_API_KEY"),
        default_calendar_name=os.getenv("DEFAULT_CALENDAR_NAME", "HKTV"),
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        office_address=os.getenv("OFFICE_ADDRESS", "1 Chun Cheong Street, Tseung Kwan O, Hong Kong"),
        owner_name=os.getenv("OWNER_NAME", "Simon"),
        calendar_ids=calendar_ids,
    )


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val
