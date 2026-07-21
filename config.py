"""
Central configuration for Anime Index.

Everything here is driven by environment variables so the exact same
codebase runs unmodified locally, on Render, and on Koyeb. See
.env.example for the full list of variables you need to set.
"""

import os


def _split_ids(raw: str) -> list[int]:
    ids = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            ids.append(int(chunk))
    return ids


class Config:
    # --- Branding ---
    BRAND_NAME = os.environ.get("BRAND_NAME", "Anime Index")
    BRAND_HANDLE = os.environ.get("BRAND_HANDLE", "ANIME_INDEX")
    # Optional banner image shown above the /anidex welcome message
    BANNER_IMAGE_URL = os.environ.get("BANNER_IMAGE_URL", "")

    # --- Telegram bot ---
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")
    # Public HTTPS base URL of this deployment, e.g. https://anime-index.onrender.com
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "").rstrip("/")
    # Channel/group the bot posts request + report notifications to (e.g. -1001234567890)
    LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")
    # Telegram user IDs allowed to run /addpost, /delpost, and edit links in-app
    ADMIN_IDS = _split_ids(os.environ.get("ADMIN_IDS", ""))

    # --- App / server ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    PORT = int(os.environ.get("PORT", 8000))
    DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

    # --- Database ---
    DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join("database", "anime_index.db"))

    # --- External metadata sources ---
    ANILIST_ENDPOINT = "https://graphql.anilist.co"
    JIKAN_ENDPOINT = "https://api.jikan.moe/v4"

    # How long (seconds) trending/popular results are cached in memory
    # before being re-fetched from AniList.
    CATALOG_CACHE_TTL = int(os.environ.get("CATALOG_CACHE_TTL", "600"))
