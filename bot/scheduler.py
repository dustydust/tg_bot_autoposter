from __future__ import annotations

import logging
from pathlib import Path

from telegram.ext import Application, ContextTypes

from bot.database import Database
from bot.errors import send_error_to_admins
from bot.generator import generate_post
from bot.handlers.callbacks import moderation_keyboard

logger = logging.getLogger(__name__)

JOB_NAME = "auto_generate"


def _parse_cron(expr: str) -> dict[str, str]:
    """Parse a 5-field cron expression into kwargs for JobQueue.run_custom.

    Format: minute hour day_of_month month day_of_week
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (need 5 fields): {expr!r}")

    minute, hour, day, month, dow = parts
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": dow,
    }


async def _scheduled_generate(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback invoked by the job queue on schedule."""
    db: Database = context.bot_data["db"]
    openai_client = context.bot_data["openai"]
    allowed_ids: frozenset[int] = context.bot_data["allowed_ids"]

    logger.info("Scheduled post generation triggered")

    try:
        post_id = await generate_post(db, openai_client)
    except Exception as e:
        logger.exception("Scheduled generation failed")
        await send_error_to_admins(context.application, e, prefix="⚠️ Ошибка автогенерации:\n\n")
        return

    post = await db.get_post(post_id)
    if not post:
        return

    keyboard = moderation_keyboard(post_id)

    for uid in allowed_ids:
        try:
            if post.get("image_path"):
                from bot.utils import send_photo_with_caption
                sent = await send_photo_with_caption(
                    bot=context.bot,
                    photo_path=post["image_path"],
                    chat_id=uid,
                    caption=post["text"],
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            else:
                sent = await context.bot.send_message(
                    chat_id=uid,
                    text=post["text"],
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            await db.update_post(post_id, admin_message_id=sent.message_id)
        except Exception:
            logger.exception("Failed to send draft to admin %d", uid)


async def schedule_jobs(app: Application) -> None:
    """Read cron setting from DB, set up (or replace) the scheduled job."""
    db: Database = app.bot_data["db"]
    cron_expr = await db.get_setting("schedule_cron") or ""

    _remove_existing(app)

    if not cron_expr.strip():
        logger.info("No schedule configured — auto-generation is off")
        return

    try:
        cron = _parse_cron(cron_expr)
    except ValueError:
        logger.error("Invalid cron expression in settings: %r", cron_expr)
        return

    app.job_queue.run_custom(
        callback=_scheduled_generate,
        name=JOB_NAME,
        job_kwargs={
            "trigger": "cron",
            **cron,
        },
    )
    logger.info("Scheduled auto-generation with cron: %s", cron_expr)


async def reschedule(app: Application) -> None:
    """Called when the admin changes the schedule via /settings."""
    await schedule_jobs(app)


def _remove_existing(app: Application) -> None:
    jobs = app.job_queue.get_jobs_by_name(JOB_NAME)
    for job in jobs:
        job.schedule_removal()
