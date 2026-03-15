from __future__ import annotations

import logging

from openai import AsyncOpenAI
from telegram.ext import ApplicationBuilder, ContextTypes

from bot.config import Config
from bot.database import Database
from bot.errors import send_error_to_admins
from bot.handlers import callbacks, commands
from bot.scheduler import schedule_jobs

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(app) -> None:
    db: Database = app.bot_data["db"]
    await db.connect()
    cfg: Config = app.bot_data["config"]
    await db.init_defaults(cfg)
    await schedule_jobs(app)
    logger.info("Bot initialized, DB ready, scheduler running")


async def _error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Send all uncaught errors to admins."""
    logger.exception("Unhandled exception", exc_info=context.error)
    await send_error_to_admins(context.application, context.error)


async def post_shutdown(app) -> None:
    db: Database = app.bot_data["db"]
    await db.close()
    logger.info("DB connection closed")


def main() -> None:
    cfg = Config.from_env()
    db = Database()
    openai_client = AsyncOpenAI(api_key=cfg.openai_api_key)

    app = (
        ApplicationBuilder()
        .token(cfg.telegram_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.bot_data["config"] = cfg
    app.bot_data["db"] = db
    app.bot_data["openai"] = openai_client
    app.bot_data["allowed_ids"] = cfg.allowed_user_ids

    commands.register(app, cfg.allowed_user_ids)
    callbacks.register(app, cfg.allowed_user_ids)
    app.add_error_handler(_error_handler)

    logger.info("Starting bot…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
