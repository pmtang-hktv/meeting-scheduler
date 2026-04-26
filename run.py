#!/usr/bin/env python3
from __future__ import annotations
import logging
import signal
import sys

from config.settings import load_settings
from bot.main import build_application

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = load_settings()
    app = build_application(settings)

    def _shutdown(sig, frame):
        logger.info("Received signal %s — shutting down", sig)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Starting bot (polling)")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
