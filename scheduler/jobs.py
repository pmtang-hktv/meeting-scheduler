from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from db import follow_ups as fu_db, meetings as meet_db

logger = logging.getLogger(__name__)
HKT = ZoneInfo("Asia/Hong_Kong")

_scheduler: AsyncIOScheduler | None = None
_bot = None
_db_path: str = ""


def configure(bot, db_path: str) -> None:
    global _bot, _db_path
    _bot = bot
    _db_path = db_path


def start_scheduler(db_path: str) -> AsyncIOScheduler:
    global _scheduler
    jobstores = {
        "default": SQLAlchemyJobStore(url=f"sqlite:///{db_path}")
    }
    _scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=HKT)
    _scheduler.start()
    logger.info("APScheduler started")
    return _scheduler


def schedule_location_followup(
    fu_id: int,
    meeting_id: int,
    trigger_dt: datetime,
    job_type: str,
) -> None:
    if _scheduler is None:
        return
    job_id = f"location_{fu_id}_{job_type}"
    _scheduler.add_job(
        _location_chase_job,
        "date",
        run_date=trigger_dt,
        args=[fu_id, meeting_id],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=300,
    )
    asyncio.get_event_loop().run_until_complete(
        fu_db.set_apscheduler_id(fu_id, job_id)
    )


async def _location_chase_job(fu_id: int, meeting_id: int) -> None:
    meeting = await meet_db.get_meeting(meeting_id)
    if not meeting:
        await fu_db.mark_skipped(fu_id)
        return

    if meeting.get("location_confirmed") or meeting.get("status") != "confirmed":
        await fu_db.mark_skipped(fu_id)
        return

    if _bot is None:
        logger.error("Bot not configured for location chase")
        return

    start_dt = datetime.fromisoformat(meeting["start_dt"]).astimezone(HKT)
    local_start = start_dt.strftime("%a %d %b at %H:%M HKT")
    try:
        await _bot.send_message(
            chat_id=meeting["requester_chat_id"],
            text=(
                f"Reminder: your meeting on {local_start} is coming up soon.\n"
                f"Could you please confirm the exact venue/address?"
            ),
        )
        await fu_db.mark_sent(fu_id)
    except Exception:
        logger.exception("Failed to send location chase message")
