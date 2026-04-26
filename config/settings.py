from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    owner_telegram_id: int
    anthropic_api_key: str
    google_maps_api_key: str
    default_calendar_name: str
    db_path: str
    office_address: str


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        owner_telegram_id=int(_require("OWNER_TELEGRAM_ID")),
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        google_maps_api_key=_require("GOOGLE_MAPS_API_KEY"),
        default_calendar_name=os.getenv("DEFAULT_CALENDAR_NAME", "HKTV"),
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        office_address=os.getenv("OFFICE_ADDRESS", "1 Chun Cheong Street, Tseung Kwan O, Hong Kong"),
    )


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val
