from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.database import Database
from bot.errors import send_error_to_admins
from bot.generator import generate_post, regenerate_image
from bot.handlers.middleware import authorized_only

logger = logging.getLogger(__name__)

WAITING_EDIT_TEXT = 50


def _get_db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.bot_data["db"]


def register(app, allowed_ids: frozenset[int]):
    """Register moderation callback handlers."""
    auth = authorized_only(allowed_ids)

    app.add_handler(CallbackQueryHandler(auth(cb_publish), pattern=r"^pub:\d+$"))
    app.add_handler(CallbackQueryHandler(auth(cb_reject), pattern=r"^reject:\d+$"))
    app.add_handler(CallbackQueryHandler(auth(cb_regenerate), pattern=r"^regen:\d+$"))
    app.add_handler(CallbackQueryHandler(auth(cb_regen_image), pattern=r"^regenimg:\d+$"))

    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(auth(cb_edit_start), pattern=r"^edit:\d+$")],
        states={
            WAITING_EDIT_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, auth(recv_edit_text)),
            ],
        },
        fallbacks=[],
        per_message=True,
    )
    app.add_handler(edit_conv)


def moderation_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"pub:{post_id}"),
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit:{post_id}"),
        ],
        [
            InlineKeyboardButton("🔄 Перегенерировать пост", callback_data=f"regen:{post_id}"),
            InlineKeyboardButton("🖼️ Перегенерировать картинку", callback_data=f"regenimg:{post_id}"),
        ],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{post_id}")],
    ])


async def cb_publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    post_id = int(query.data.split(":")[1])
    db = _get_db(context)
    post = await db.get_post(post_id)

    if not post:
        await query.edit_message_text("Пост не найден.")
        return

    channel = await db.get_setting("channel_id")
    if not channel:
        await query.message.reply_text("Канал не задан! Установите через /settings.")
        return

    try:
        if post.get("image_path"):
            from bot.utils import send_photo_with_caption
            await send_photo_with_caption(
                bot=context.bot,
                photo_path=post["image_path"],
                chat_id=channel,
                caption=post["text"],
                parse_mode="HTML",
            )
        else:
            await context.bot.send_message(
                chat_id=channel,
                text=post["text"],
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception("Failed to publish post #%d", post_id)
        await send_error_to_admins(context.application, e, prefix="❌ Ошибка публикации:\n\n")
        await query.message.reply_text("Ошибка публикации. Подробности отправлены админам.")
        return

    await db.publish_post(post_id)

    try:
        pub_caption = f"✅ <b>Опубликовано</b>\n\n{post['text']}"
        if len(pub_caption) > 1024:
            pub_caption = pub_caption[:1000] + "\n\n… (обрезано)"
        await query.edit_message_caption(
            caption=pub_caption,
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        try:
            await query.edit_message_text(
                text=f"✅ <b>Опубликовано</b>\n\n{post['text']}",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass

    logger.info("Post #%d published to %s", post_id, channel)


async def cb_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    post_id = int(query.data.split(":")[1])
    db = _get_db(context)

    await db.reject_post(post_id)

    try:
        await query.edit_message_caption(
            caption="❌ <b>Отклонено</b>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        try:
            await query.edit_message_text(
                text="❌ <b>Отклонено</b>",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass

    logger.info("Post #%d rejected", post_id)


async def cb_regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Перегенерирую…")
    old_post_id = int(query.data.split(":")[1])
    db = _get_db(context)
    openai_client = context.bot_data["openai"]

    await db.reject_post(old_post_id)

    try:
        await query.edit_message_caption(
            caption="🔄 Перегенерация…",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        try:
            await query.edit_message_text("🔄 Перегенерация…", reply_markup=None)
        except Exception:
            pass

    try:
        post_id = await generate_post(db, openai_client)
    except Exception as e:
        logger.exception("Regeneration failed")
        await send_error_to_admins(context.application, e, prefix="❌ Ошибка перегенерации:\n\n")
        await query.message.reply_text("Ошибка при перегенерации. Подробности отправлены админам.")
        return

    post = await db.get_post(post_id)
    if not post:
        return

    keyboard = moderation_keyboard(post_id)

    if post.get("image_path"):
        from bot.utils import send_photo_with_caption
        sent = await send_photo_with_caption(
            bot=context.bot,
            photo_path=post["image_path"],
            caption=post["text"],
            parse_mode="HTML",
            reply_markup=keyboard,
            reply_to_message=query.message,
        )
    else:
        sent = await query.message.reply_text(
            post["text"],
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    await db.update_post(post_id, admin_message_id=sent.message_id)


async def cb_regen_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Перегенерирую картинку…")
    post_id = int(query.data.split(":")[1])
    db = _get_db(context)
    openai_client = context.bot_data["openai"]
    post = await db.get_post(post_id)

    if not post:
        await query.message.reply_text("Пост не найден.")
        return

    try:
        await query.edit_message_caption(
            caption="🖼️ Перегенерация картинки…",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        try:
            await query.edit_message_text("🖼️ Перегенерация картинки…", reply_markup=None)
        except Exception:
            pass

    try:
        settings = await db.get_all_settings()
        new_image_path = await regenerate_image(
            openai_client, post["text"], settings
        )
        await db.update_post(post_id, image_path=new_image_path)
    except Exception as e:
        logger.exception("Image regeneration failed for post #%d", post_id)
        await send_error_to_admins(context.application, e, prefix="❌ Ошибка перегенерации картинки:\n\n")
        await query.message.reply_text("Ошибка при перегенерации картинки. Подробности отправлены админам.")
        return

    post = await db.get_post(post_id)
    keyboard = moderation_keyboard(post_id)

    from bot.utils import send_photo_with_caption
    sent = await send_photo_with_caption(
        bot=context.bot,
        photo_path=post["image_path"],
        caption=post["text"],
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message=query.message,
    )
    await db.update_post(post_id, admin_message_id=sent.message_id)


async def cb_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    post_id = int(query.data.split(":")[1])
    context.user_data["editing_post_id"] = post_id
    await query.message.reply_text(
        "Отправьте новый текст поста (HTML-разметка поддерживается):"
    )
    return WAITING_EDIT_TEXT


async def recv_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    post_id = context.user_data.pop("editing_post_id", None)
    if post_id is None:
        await update.message.reply_text("Нет поста для редактирования. Попробуйте /generate.")
        return ConversationHandler.END

    db = _get_db(context)
    await db.update_post(post_id, text=update.message.text.strip())
    post = await db.get_post(post_id)
    if not post:
        await update.message.reply_text("Пост не найден.")
        return ConversationHandler.END

    keyboard = moderation_keyboard(post_id)

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
    return ConversationHandler.END
