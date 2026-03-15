"""Shared utilities."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import InlineKeyboardMarkup

MAX_CAPTION_LENGTH = 1024


async def send_photo_with_caption(
    *,
    bot,
    photo_path: str,
    chat_id: int | str | None = None,
    caption: str,
    parse_mode: str = "HTML",
    reply_markup: "InlineKeyboardMarkup | None" = None,
    reply_to_message=None,
) -> "telegram.Message":
    """
    Send photo with caption. If caption exceeds Telegram limit (1024 chars),
    sends photo first then text as separate message. Returns the message with keyboard.
    """
    photo = Path(photo_path)
    if len(caption) <= MAX_CAPTION_LENGTH:
        if reply_to_message is not None:
            return await reply_to_message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        return await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    # Caption too long: send photo, then text with keyboard
    if reply_to_message is not None:
        await reply_to_message.reply_photo(photo=photo)
        return await reply_to_message.reply_text(
            caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    await bot.send_photo(chat_id=chat_id, photo=photo)
    return await bot.send_message(
        chat_id=chat_id,
        text=caption,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )
