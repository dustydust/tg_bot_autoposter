from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "bot.db"
IMAGES_DIR = DATA_DIR / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Config:
    telegram_token: str
    openai_api_key: str
    allowed_user_ids: frozenset[int]
    default_channel: str
    default_topic: str
    default_style: str
    default_schedule: str  # cron expression, e.g. "0 9,18 * * *"

    @classmethod
    def from_env(cls) -> Config:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

        openai_key = os.getenv("OPENAI_API_KEY", "")
        if not openai_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        raw_ids = os.getenv("ALLOWED_USER_IDS", "")
        allowed = frozenset(
            int(uid.strip()) for uid in raw_ids.split(",") if uid.strip()
        )
        if not allowed:
            raise RuntimeError("ALLOWED_USER_IDS is not set")

        return cls(
            telegram_token=token,
            openai_api_key=openai_key,
            allowed_user_ids=allowed,
            default_channel=os.getenv("DEFAULT_CHANNEL", ""),
            default_topic=os.getenv("DEFAULT_TOPIC", "General"),
            default_style=os.getenv(
                "DEFAULT_STYLE", "Informative, 200-300 words"
            ),
            default_schedule=os.getenv("DEFAULT_SCHEDULE", "0 9 * * *"),
        )
