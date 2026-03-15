from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any

import httpx
from openai import AsyncOpenAI

from bot.config import IMAGES_DIR
from bot.database import Database

logger = logging.getLogger(__name__)

TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o")
IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "dall-e-3")


def _build_system_prompt(settings: dict[str, str]) -> str:
    topic = settings.get("topic", "General")
    style = settings.get("style", "")
    image_hint = settings.get("image_style_hint", "")

    parts = [
        "You are a professional copywriter for a Telegram channel.",
        f"Channel topic: {topic}.",
    ]
    if style:
        parts.append(f"Writing style guidelines: {style}.")
    parts += [
        "Write the post text using Telegram HTML formatting (<b>, <i>, <a>, <code>, etc.).",
        "Do NOT wrap the entire text in a single tag. Use tags sparingly for emphasis.",
        "Output ONLY the post text — no preamble, no explanation.",
    ]
    if image_hint:
        parts.append(f"Visual style hint (for reference only): {image_hint}.")
    return "\n".join(parts)


def _build_context_block(recent_posts: list[dict[str, Any]]) -> str:
    if not recent_posts:
        return ""
    lines = ["Here are the most recent published posts (newest first) — avoid repeating their topics:\n"]
    for i, p in enumerate(recent_posts, 1):
        text_preview = (p["text"] or "")[:300]
        lines.append(f"{i}. {text_preview}")
    return "\n".join(lines)


async def generate_text(
    client: AsyncOpenAI,
    settings: dict[str, str],
    recent_posts: list[dict[str, Any]],
) -> str:
    system = _build_system_prompt(settings)
    context = _build_context_block(recent_posts)

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if context:
        messages.append({"role": "user", "content": context})
    messages.append({
        "role": "user",
        "content": "Write a new, original post for the channel.",
    })

    logger.info(
        "--- OpenAI text request --- model=%s | system=%d chars | messages=%d",
        TEXT_MODEL, len(system), len(messages),
    )
    logger.info("System prompt: %s", system[:500] + ("..." if len(system) > 500 else ""))
    if context:
        logger.info("Context (recent posts): %s", context[:500] + ("..." if len(context) > 500 else ""))

    resp = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=messages,  # type: ignore[arg-type]
        max_completion_tokens=1024,
    )
    return resp.choices[0].message.content or ""


def _fallback_image_prompt(post_text: str, hint: str = "") -> str:
    """Create a simple DALL-E prompt from post text when GPT returns empty."""
    # Take first 400 chars, remove HTML for cleaner prompt
    text = re.sub(r"<[^>]+>", "", post_text)[:400].strip()
    base = f"Professional abstract illustration for a blog post. Theme: {text}"
    if hint:
        base += f". Style: {hint}"
    return base + "."


async def generate_image_prompt(
    client: AsyncOpenAI,
    post_text: str,
    settings: dict[str, str],
) -> str:
    hint = settings.get("image_style_hint", "")
    user_msg = (
        "Based on the following Telegram post, write a concise DALL-E image prompt "
        "(in English, max 900 chars) that would make a fitting illustration. "
        "Output ONLY the prompt.\n\n"
        f"Post:\n{post_text}"
    )
    if hint:
        user_msg += f"\n\nPreferred visual style: {hint}"

    logger.info(
        "--- OpenAI image prompt request --- model=%s | post=%d chars",
        TEXT_MODEL, len(post_text),
    )
    logger.info("Image prompt request: %s", user_msg[:600] + ("..." if len(user_msg) > 600 else ""))

    resp = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": user_msg}],
        max_completion_tokens=256,
    )
    result = (resp.choices[0].message.content or "").strip()


    if not result:
        logger.warning(
            "Empty image prompt from GPT (model=%s). Using fallback from post text.",
            TEXT_MODEL,
        )
        return _fallback_image_prompt(post_text, hint)
    return result


async def generate_image(client: AsyncOpenAI, prompt: str) -> str:
    """Returns a URL of the generated image."""
    if not (prompt and prompt.strip()):
        prompt = "A professional abstract illustration suitable for a blog post"
        logger.warning("Empty image prompt, using fallback")
    logger.info(
        "--- OpenAI DALL-E request --- model=%s | prompt=%s",
        IMAGE_MODEL, prompt[:600] + ("..." if len(prompt) > 600 else ""),
    )
    resp = await client.images.generate(
        model=IMAGE_MODEL,
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1,
    )
    return resp.data[0].url or ""


async def download_image(url: str) -> str:
    """Downloads image from URL, saves to IMAGES_DIR, returns local path."""
    filename = f"{uuid.uuid4().hex}.png"
    path = IMAGES_DIR / filename
    async with httpx.AsyncClient() as http:
        r = await http.get(url, follow_redirects=True, timeout=60)
        r.raise_for_status()
        path.write_bytes(r.content)
    logger.info("Image saved to %s", path)
    return str(path)


async def regenerate_image(
    client: AsyncOpenAI,
    post_text: str,
    settings: dict[str, str],
) -> str:
    """Regenerate only the image for an existing post. Returns new image path."""
    image_prompt = await generate_image_prompt(client, post_text, settings)
    logger.info("Regenerated image prompt: %s", image_prompt[:120])
    image_url = await generate_image(client, image_prompt)
    return await download_image(image_url)


async def generate_post(db: Database, client: AsyncOpenAI) -> int:
    """Full pipeline: generate text + image, save draft, return post id."""
    settings = await db.get_all_settings()
    ctx_count = int(settings.get("posts_context_count", "5"))
    recent = await db.get_recent_posts(limit=ctx_count)

    text = await generate_text(client, settings, recent)
    logger.info("Generated post text (%d chars)", len(text))

    image_prompt = await generate_image_prompt(client, text, settings)
    logger.info("Image prompt: %s", image_prompt[:120])

    image_url = await generate_image(client, image_prompt)
    image_path = await download_image(image_url)

    post_id = await db.create_post(text, image_prompt, image_path)
    logger.info("Draft post #%d created", post_id)
    return post_id
