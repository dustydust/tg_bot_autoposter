"""Error reporting to Telegram admins."""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram.ext import Application, ContextTypes

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4000


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_error(exc: BaseException) -> str:
    """Format exception for Telegram (truncate if needed)."""
    tb = traceback.format_exc()
    err_type = type(exc).__name__
    err_msg = _escape(str(exc) or "(no message)")
    tb_escaped = _escape(tb)
    if len(tb_escaped) > MAX_MESSAGE_LENGTH - 150:
        tb_escaped = tb_escaped[: MAX_MESSAGE_LENGTH - 150] + "\n… (обрезано)"
    return f"<code>{err_type}: {err_msg}</code>\n\n<pre>{tb_escaped}</pre>"[:MAX_MESSAGE_LENGTH]


async def send_error_to_admins(
    app: "Application",
    exc: BaseException,
    prefix: str = "⚠️ Ошибка бота:\n\n",
) -> None:
    """Send formatted error to all admins."""
    allowed_ids = app.bot_data.get("allowed_ids", frozenset())
    if not allowed_ids:
        return
    text = prefix + format_error(exc)
    for uid in allowed_ids:
        try:
            await app.bot.send_message(uid, text, parse_mode="HTML")
        except Exception:
            logger.exception("Failed to send error notification to admin %s", uid)
