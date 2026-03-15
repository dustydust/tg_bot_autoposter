# Telegram Auto-Poster Bot

AI-powered Telegram channel auto-poster with admin moderation. Generates post text (OpenAI GPT) and illustrations (DALL-E 3), sends drafts to admins for approval, and publishes to your channel on confirmation.

## Features

- Automatic post generation on a cron schedule
- AI-generated illustrations for every post
- Context-aware: considers recent posts to avoid repetition
- Admin moderation: approve, edit, regenerate, or reject each draft
- All management via Telegram — no web panel needed
- Configurable topic, style, schedule, and image hints — all changeable at runtime
- Access restricted to a whitelist of Telegram user IDs

## Quick Start

### 1. Create a Telegram bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot`, follow the prompts
3. Copy the bot token

### 2. Add the bot to your channel

1. Open your Telegram channel settings
2. Add the bot as an **administrator**
3. Grant it permission to **post messages**

### 3. Get your Telegram user ID

Send `/start` to [@userinfobot](https://t.me/userinfobot) — it will reply with your numeric ID.

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
OPENAI_API_KEY=sk-...
ALLOWED_USER_IDS=123456789
DEFAULT_CHANNEL=@your_channel
DEFAULT_TOPIC=Технологии и AI
DEFAULT_STYLE=Информативный, с примерами, 200-300 слов
DEFAULT_SCHEDULE=0 9,18 * * *
```

- `ALLOWED_USER_IDS` — comma-separated list of Telegram user IDs that can control the bot
- `DEFAULT_SCHEDULE` — cron expression (minute hour day month weekday). `0 9,18 * * *` = 09:00 and 18:00 daily

### 5. Run with Docker

```bash
docker compose up -d
```

That's it. The bot is running.

### 5b. Run without Docker (development)

```bash
pip install -r requirements.txt
python -m bot.main
```

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/generate` | Generate a new draft post immediately |
| `/settings` | View and edit bot settings |
| `/history` | Show last 5 published posts |
| `/cancel` | Cancel current action |
| `/help` | Show command list |

## Moderation Flow

1. Bot generates a post (on schedule or via `/generate`)
2. Draft is sent to all admins with inline buttons:
   - **Publish** — sends the post to the channel
   - **Edit** — enter new text, then re-approve
   - **Regenerate** — create a completely new post
   - **Reject** — discard the draft
3. Once published, the post is saved to history for future context

## Settings (changeable via Telegram)

| Setting | Description |
|---|---|
| Topic | Channel topic / niche |
| Style | Writing style guidelines for GPT |
| Channel | Target channel `@username` |
| Schedule | Cron expression for auto-generation |
| Context count | How many recent posts GPT sees (3 / 5 / 10) |
| Image style | Visual style hint for DALL-E |

## Architecture

```
bot/
  main.py           — Entry point, bot initialization
  config.py         — Environment variable loading
  database.py       — SQLite schema and CRUD
  generator.py      — OpenAI GPT + DALL-E integration
  scheduler.py      — Cron-based auto-generation (APScheduler via job queue)
  handlers/
    commands.py     — /start, /generate, /settings, etc.
    callbacks.py    — Inline button handlers (publish, edit, reject)
    middleware.py   — Access control decorator
```

## Data Persistence

- SQLite database and generated images are stored in the `data/` directory
- When using Docker, `./data` on the host is mounted into the container — all data stays on the host filesystem

## Requirements

- Python 3.12+
- OpenAI API key with GPT-4o and DALL-E 3 access
- A Telegram bot token
