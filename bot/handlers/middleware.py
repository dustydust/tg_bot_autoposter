from __future__ import annotations

import logging
from typing import Any

from telegram import Update
from telegram.ext import BaseHandler, ContextTypes

logger = logging.getLogger(__name__)


def authorized_only(allowed_ids: frozenset[int]):
    """Decorator that silently drops updates from non-whitelisted users."""

    def decorator(func):
        async def wrapper(
            update: Update, context: ContextTypes.DEFAULT_TYPE, *args: Any, **kwargs: Any
        ):
            user = update.effective_user
            if user is None or user.id not in allowed_ids:
                if user:
                    logger.warning("Unauthorized access attempt by user %s (%s)", user.id, user.username)
                return  # silently ignore
            return await func(update, context, *args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator
