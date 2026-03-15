from __future__ import annotations

import datetime as dt
from typing import Any

import aiosqlite

from bot.config import DB_PATH, Config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    text            TEXT    NOT NULL,
    image_prompt    TEXT,
    image_path      TEXT,
    status          TEXT    NOT NULL DEFAULT 'draft',
    created_at      TEXT    NOT NULL,
    published_at    TEXT,
    admin_message_id INTEGER
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | None = None) -> None:
        self._path = path or str(DB_PATH)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database not connected"
        return self._db

    # ── settings ──────────────────────────────────────────────

    async def init_defaults(self, cfg: Config) -> None:
        """Seed settings that don't yet exist in the DB."""
        defaults = {
            "topic": cfg.default_topic,
            "style": cfg.default_style,
            "channel_id": cfg.default_channel,
            "schedule_cron": cfg.default_schedule,
            "posts_context_count": "5",
            "image_style_hint": "",
        }
        for key, value in defaults.items():
            await self.db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        await self.db.commit()

    async def get_setting(self, key: str) -> str | None:
        cur = await self.db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.db.commit()

    async def get_all_settings(self) -> dict[str, str]:
        cur = await self.db.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ── posts ─────────────────────────────────────────────────

    async def create_post(
        self,
        text: str,
        image_prompt: str | None = None,
        image_path: str | None = None,
    ) -> int:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        cur = await self.db.execute(
            "INSERT INTO posts (text, image_prompt, image_path, status, created_at) "
            "VALUES (?, ?, ?, 'draft', ?)",
            (text, image_prompt, image_path, now),
        )
        await self.db.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def get_post(self, post_id: int) -> dict[str, Any] | None:
        cur = await self.db.execute(
            "SELECT * FROM posts WHERE id = ?", (post_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def update_post(self, post_id: int, **fields: Any) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [post_id]
        await self.db.execute(
            f"UPDATE posts SET {set_clause} WHERE id = ?", values
        )
        await self.db.commit()

    async def publish_post(self, post_id: int) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        await self.update_post(post_id, status="published", published_at=now)

    async def reject_post(self, post_id: int) -> None:
        await self.update_post(post_id, status="rejected")

    async def get_recent_posts(
        self, limit: int = 5, status: str = "published"
    ) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM posts WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_drafts(self) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM posts WHERE status = 'draft' ORDER BY created_at DESC"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
