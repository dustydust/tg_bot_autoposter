from __future__ import annotations

import logging
from typing import Any

from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.database import Database
from bot.errors import send_error_to_admins
from bot.generator import generate_post
from bot.handlers.middleware import authorized_only

logger = logging.getLogger(__name__)

SETTING_LABELS = {
    "topic": "Тематика",
    "style": "Стиль",
    "channel_id": "Канал",
    "schedule_cron": "Расписание (cron)",
    "posts_context_count": "Контекст (постов)",
    "image_style_hint": "Стиль картинок",
}

_SETTING_PROMPTS = {
    "topic": "Введите новую тематику канала:",
    "style": "Опишите желаемый стиль постов:",
    "channel_id": "Укажите @username канала (например, @mychannel):",
    "schedule_cron": "Введите расписание в формате cron (например, <code>0 9,18 * * *</code>):",
    "image_style_hint": "Опишите желаемый визуальный стиль картинок (или отправьте «—» чтобы очистить):",
}


def _get_deps(context: ContextTypes.DEFAULT_TYPE) -> tuple[Database, Any]:
    db: Database = context.bot_data["db"]
    openai_client = context.bot_data["openai"]
    return db, openai_client


def register(app, allowed_ids: frozenset[int]):
    """Register all command handlers on the Application."""
    auth = authorized_only(allowed_ids)

    app.add_handler(CommandHandler("start", auth(cmd_start)))
    app.add_handler(CommandHandler("help", auth(cmd_help)))
    app.add_handler(CommandHandler("generate", auth(cmd_generate)))
    app.add_handler(CommandHandler("history", auth(cmd_history)))
    app.add_handler(CommandHandler("clear_history", auth(cmd_clear_history)))
    app.add_handler(CommandHandler("settings", auth(cmd_settings)))
    app.add_handler(CommandHandler("cancel", auth(cmd_cancel)))

    app.add_handler(CallbackQueryHandler(auth(cb_edit_setting), pattern=r"^set:"))
    app.add_handler(CallbackQueryHandler(auth(cb_context_count), pattern=r"^ctx:"))
    app.add_handler(CallbackQueryHandler(auth(cb_clear_history_confirm), pattern=r"^clearhistory:(yes|no)$"))

    # Catch free-text replies used for setting edits.
    # This must be added AFTER callback/command handlers and AFTER
    # the edit-text ConversationHandler registered in callbacks.py
    # (group=1 so it doesn't conflict).
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auth(recv_setting_text)),
        group=1,
    )


# ── simple commands ───────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Autoposter Bot</b>\n\n"
        "Я генерирую посты для вашего Telegram-канала с помощью AI.\n\n"
        "Команды:\n"
        "/generate — сгенерировать новый пост\n"
        "/settings — настройки бота\n"
        "/history — последние посты\n"
        "/clear_history — сбросить историю\n"
        "/help — справка",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Доступные команды:</b>\n\n"
        "/generate — создать черновик поста (текст + картинка)\n"
        "/settings — просмотр и изменение настроек\n"
        "/history — последние 5 опубликованных постов\n"
        "/clear_history — сбросить историю постов\n"
        "/cancel — отменить текущее действие\n"
        "/help — эта справка",
        parse_mode="HTML",
    )


async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, openai_client = _get_deps(context)
    msg = await update.message.reply_text("⏳ Генерирую пост…")

    try:
        post_id = await generate_post(db, openai_client)
    except Exception as e:
        logger.exception("Post generation failed")
        await send_error_to_admins(context.application, e, prefix="❌ Ошибка генерации:\n\n")
        await msg.edit_text("❌ Ошибка при генерации. Подробности отправлены всем админам.")
        return

    post = await db.get_post(post_id)
    if not post:
        await msg.edit_text("Ошибка: пост не найден.")
        return

    from bot.handlers.callbacks import moderation_keyboard
    keyboard = moderation_keyboard(post_id)

    await msg.delete()

    if post.get("image_path"):
        from bot.utils import send_photo_with_caption
        sent = await send_photo_with_caption(
            bot=context.bot,
            photo_path=post["image_path"],
            caption=post["text"],
            parse_mode="HTML",
            reply_markup=keyboard,
            reply_to_message=update.message,
        )
    else:
        sent = await update.message.reply_text(
            post["text"],
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    await db.update_post(post_id, admin_message_id=sent.message_id)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, _ = _get_deps(context)
    posts = await db.get_recent_posts(limit=5)

    if not posts:
        await update.message.reply_text("Опубликованных постов пока нет.")
        return

    lines = ["<b>Последние 5 постов:</b>\n"]
    for p in posts:
        preview = (p["text"] or "")[:100].replace("\n", " ")
        date = (p["published_at"] or p["created_at"] or "")[:10]
        lines.append(f"• <i>{date}</i> — {preview}…")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, сбросить", callback_data="clearhistory:yes"),
            InlineKeyboardButton("❌ Отмена", callback_data="clearhistory:no"),
        ],
    ])
    await update.message.reply_text(
        "Сбросить всю историю постов? Это удалит все записи (черновики, опубликованные, отклонённые). "
        "Контекст для генерации будет пустым.",
        reply_markup=keyboard,
    )


async def cb_clear_history_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]
    if action == "no":
        await query.edit_message_text("Отменено.")
        return
    db = _get_deps(context)[0]
    count = await db.delete_all_posts()
    await query.edit_message_text(f"✅ История сброшена. Удалено постов: {count}")


# ── /settings ─────────────────────────────────────────────────

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, _ = _get_deps(context)
    settings = await db.get_all_settings()
    await _show_settings(update.message, settings)


async def _show_settings(message, settings: dict[str, str]) -> None:
    lines = ["<b>⚙️ Настройки:</b>\n"]
    for key, label in SETTING_LABELS.items():
        val = settings.get(key, "—")
        lines.append(f"<b>{label}:</b> {val}")

    buttons = [
        [InlineKeyboardButton(f"✏️ {SETTING_LABELS[k]}", callback_data=f"set:{k}")]
        for k in ("topic", "style", "channel_id", "schedule_cron", "image_style_hint")
    ]
    buttons.append([
        InlineKeyboardButton("3", callback_data="ctx:3"),
        InlineKeyboardButton("5", callback_data="ctx:5"),
        InlineKeyboardButton("10", callback_data="ctx:10"),
    ])

    await message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cb_edit_setting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":")[1]
    prompt = _SETTING_PROMPTS.get(key)
    if not prompt:
        return
    context.user_data["editing_setting"] = key
    await query.message.reply_text(prompt, parse_mode="HTML")


async def cb_context_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":")[1]
    db, _ = _get_deps(context)
    await db.set_setting("posts_context_count", value)
    await query.message.reply_text(
        f"Контекст установлен: <b>{value}</b> постов.", parse_mode="HTML"
    )


async def recv_setting_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receives free-text input when a setting edit is pending."""
    key = context.user_data.pop("editing_setting", None)
    if key is None:
        return  # no pending edit — ignore

    db, _ = _get_deps(context)
    value = update.message.text.strip()
    if value == "—":
        value = ""

    await db.set_setting(key, value)
    label = SETTING_LABELS.get(key, key)
    await update.message.reply_text(
        f"✅ <b>{label}</b> обновлено: {value or '(пусто)'}",
        parse_mode="HTML",
    )

    if key == "schedule_cron":
        from bot.scheduler import reschedule
        await reschedule(context.application)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("Действие отменено.")
