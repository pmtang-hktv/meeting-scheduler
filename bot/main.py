from __future__ import annotations
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ai import claude_client
from bot.handlers import colleague, error as error_handler, owner as owner_handler
from bot.handlers.colleague import (
    GATHERING_INFO,
    CHECKING_AVAILABILITY,
    SUGGESTING_ALTERNATIVES,
    AWAITING_OWNER_DECISION,
    handle_message,
    handle_slot_choice,
)
from calendar_integration import calendar_service
from config.settings import Settings
from db.database import init_db
from notifications import owner_notify
from scheduler.jobs import configure as configure_scheduler, start_scheduler

logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    await init_db(settings.db_path)
    logger.info("Database initialised at %s", settings.db_path)
    start_scheduler(settings.db_path)


def build_application(settings: Settings) -> Application:
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )
    app.bot_data["settings"] = settings

    # Configure sub-modules
    claude_client.configure(settings.anthropic_api_key)
    calendar_service.configure(settings.default_calendar_name)
    owner_notify.configure(app.bot, settings.owner_telegram_id)
    owner_handler.configure(app.bot, settings)
    colleague.set_settings(settings)
    configure_scheduler(app.bot, settings.db_path)

    # Conversation handler for colleague messages
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
        ],
        states={
            GATHERING_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
            ],
            CHECKING_AVAILABILITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
            ],
            SUGGESTING_ALTERNATIVES: [
                CallbackQueryHandler(handle_slot_choice, pattern=r"^slot:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
            ],
            AWAITING_OWNER_DECISION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
            ],
        },
        fallbacks=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
        ],
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(owner_handler.handle_owner_callback, pattern=r"^(approve|reject):"))
    app.add_error_handler(error_handler.error_handler)

    return app
