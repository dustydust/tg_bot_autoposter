from __future__ import annotations

import logging

from openai import AsyncOpenAI
from telegram.ext import ApplicationBuilder

from bot.config import Config
from bot.database import Database
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

    logger.info("Starting bot…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
