"""
Anime Index — Flask web server (serves the mini app + JSON API) and the
Telegram bot (running in webhook mode, fed by Telegram through the same
Flask process).

Why webhook mode, not polling: Render and Koyeb both run this as a "web
service" that must listen on $PORT — long-polling would fight that model
and waste a dyno doing nothing but polling. Webhook mode means Telegram
pushes updates straight to /webhook/<secret>, which is what the platforms
expect.

Important deployment note: this process keeps in-memory bot "sessions"
(for the multi-step /addpost and /delpost flows) and a single asyncio
event loop. Run it with a single worker (see Dockerfile / render.yaml) —
multiple worker processes would each have their own session store and
event loop, breaking the multi-step flows.
"""

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import parse_qsl

import requests
from flask import Flask, abort, jsonify, render_template, request

from config import Config
from database import database as db
from plugins import SOURCES
from plugins import news as news_plugin

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = Config.SECRET_KEY

db.init_db()

# ---------------------------------------------------------------------------
# Telegram bot (python-telegram-bot v20, async) glued into sync Flask via a
# single long-lived event loop.
# ---------------------------------------------------------------------------

bot_app: Application | None = None
_loop = asyncio.new_event_loop()


def run_async(coro):
    return _loop.run_until_complete(coro)


# In-memory session store for the multi-step /addpost (source -> results ->
# pick) and /delpost (pick which match to delete) conversations. Telegram's
# callback_data has a 64-byte limit, so we keep the real state here and only
# pass a short session id through callback_data.
SESSIONS: dict[str, dict] = {}
SESSION_TTL = 15 * 60  # 15 minutes


def new_session(**kwargs) -> str:
    sid = secrets.token_hex(4)
    kwargs["_created"] = time.time()
    SESSIONS[sid] = kwargs
    _gc_sessions()
    return sid


def _gc_sessions():
    now = time.time()
    expired = [k for k, v in SESSIONS.items() if now - v.get("_created", now) > SESSION_TTL]
    for k in expired:
        SESSIONS.pop(k, None)


def _webapp_button(label: str = None) -> InlineKeyboardButton:
    label = label or f"\U0001f4d6 Open {Config.BRAND_NAME}"
    if Config.WEBAPP_URL.startswith("https://"):
        return InlineKeyboardButton(label, web_app=WebAppInfo(url=Config.WEBAPP_URL))
    # Telegram requires an https URL for web_app buttons — fall back to a
    # plain link so the bot still works before you have a deployed URL.
    return InlineKeyboardButton(label, url=Config.WEBAPP_URL or "https://telegram.org")


# --- Commands -----------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start no longer shows the welcome card — it just exists so joining
    the bot doesn't feel broken. Use /anidex for the actual start menu."""
    return


async def cmd_anidex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        text = Config.START_MSG.format(first_name=user.first_name, brand_name=Config.BRAND_NAME)
    except (KeyError, IndexError, ValueError):
        # A malformed custom START_MSG (e.g. a stray "{" or "}") shouldn't
        # break /anidex entirely — fall back to the literal text.
        text = Config.START_MSG
    keyboard = InlineKeyboardMarkup([[_webapp_button()]])
    if Config.BANNER_IMAGE_URL:
        await update.message.reply_photo(Config.BANNER_IMAGE_URL, caption=text,
                                          reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def cmd_addpost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ADMIN_IDS:
        await update.message.reply_text("\u26d4 You're not authorized to use this command.")
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage: /addpost <anime name>\nExample: /addpost one piece")
        return

    sid = new_session(kind="addpost", query=query, source="anilist")
    src = SOURCES["anilist"]
    try:
        data = await asyncio.to_thread(src.search, query, 1)
    except Exception:
        await update.message.reply_text("Couldn't reach AniList right now. Try again shortly.")
        return
    sess = SESSIONS[sid]
    sess.update(page=1, results=data["results"], has_next=data["has_next"])
    if not data["results"]:
        await update.message.reply_text(f"No results found on AniList for '{query}'.")
        SESSIONS.pop(sid, None)
        return
    await send_results(update.message, sid)


async def cmd_delpost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ADMIN_IDS:
        await update.message.reply_text("\u26d4 You're not authorized to use this command.")
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage: /delpost <anime name>\nExample: /delpost one piece")
        return

    matches = db.search_local(query)
    if not matches:
        await update.message.reply_text(f"No post found matching '{query}'.")
        return
    if len(matches) == 1:
        db.delete_anime(matches[0]["id"])
        await update.message.reply_text(f"\U0001f5d1 Deleted: {matches[0]['title']}")
        return

    sid = new_session(kind="delpost", matches=matches)
    rows = [[InlineKeyboardButton(m["title"], callback_data=f"delpick:{sid}:{i}")]
            for i, m in enumerate(matches[:10])]
    rows.append([InlineKeyboardButton("Cancel", callback_data=f"cancel:{sid}")])
    await update.message.reply_text(
        f"Multiple matches for '{query}'. Pick one to delete:",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# --- Callback query routing ---------------------------------------------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""

    # Title text can itself contain colons (e.g. "Attack on Titan: Final
    # Season"), so this one is checked before the generic colon-split below.
    if data.startswith("reqtext:"):
        await handle_reqtext(q, data[len("reqtext:"):])
        return

    parts = data.split(":")
    action = parts[0]

    if action == "noop":
        await q.answer()
        return

    if action == "cancel":
        sid = parts[1] if len(parts) > 1 else None
        SESSIONS.pop(sid, None)
        await q.answer("Cancelled")
        await q.edit_message_text("Cancelled.")
        return

    if action == "page":
        _, sid, page = parts
        await handle_page(q, sid, int(page))
        return

    if action == "pick":
        _, sid, idx = parts
        await handle_pick(q, update, sid, int(idx))
        return

    if action == "delpick":
        _, sid, idx = parts
        await handle_delpick(q, sid, int(idx))
        return

    if action == "searchpick":
        _, sid, idx = parts
        await handle_searchpick(q, sid, int(idx))
        return

    if action == "discoverpick":
        _, sid, idx = parts
        await handle_discoverpick(q, sid, int(idx))
        return

    if action == "req":
        _, req_id, decision = parts
        await handle_request_decision(q, int(req_id), decision)
        return

    await q.answer()


async def handle_page(q, sid, page):
    session = SESSIONS.get(sid)
    if not session:
        await q.answer("Session expired — run /addpost again.", show_alert=True)
        return
    await q.answer()
    src = SOURCES[session["source"]]
    data = await asyncio.to_thread(src.search, session["query"], page)
    session.update(page=page, results=data["results"], has_next=data["has_next"])
    await render_results(q, sid)


def _results_text(session):
    return "Search Results (ANILIST)\nSelect the correct title from the list below:"


def _results_keyboard(sid, session):
    rows = [
        [InlineKeyboardButton(
            f"{r['title']}" + (f" ({r['year']})" if r.get("year") else ""),
            callback_data=f"pick:{sid}:{i}",
        )]
        for i, r in enumerate(session["results"])
    ]
    nav = []
    if session["page"] > 1:
        nav.append(InlineKeyboardButton("\u2b05 Prev", callback_data=f"page:{sid}:{session['page'] - 1}"))
    nav.append(InlineKeyboardButton(str(session["page"]), callback_data="noop"))
    if session.get("has_next"):
        nav.append(InlineKeyboardButton("Next \u27a1", callback_data=f"page:{sid}:{session['page'] + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("Cancel", callback_data=f"cancel:{sid}")])
    return InlineKeyboardMarkup(rows)


async def send_results(message, sid):
    """Initial results message, sent as a fresh reply from cmd_addpost."""
    session = SESSIONS[sid]
    await message.reply_text(_results_text(session), reply_markup=_results_keyboard(sid, session))


async def render_results(q, sid):
    """Same results view, but editing an existing message (Next/Prev)."""
    session = SESSIONS[sid]
    if not session["results"]:
        await q.edit_message_text(f"No results found on AniList for '{session['query']}'.")
        SESSIONS.pop(sid, None)
        return
    await q.edit_message_text(_results_text(session), reply_markup=_results_keyboard(sid, session))


async def handle_pick(q, update, sid, idx):
    session = SESSIONS.get(sid)
    if not session:
        await q.answer("Session expired — run /addpost again.", show_alert=True)
        return
    await q.answer("Fetching details...")
    r = session["results"][idx]
    src = SOURCES[session["source"]]
    try:
        details = await asyncio.to_thread(src.get_details, r["source_id"])
    except Exception:
        await q.edit_message_text("Couldn't fetch full details for that title. Try again.")
        return

    db.upsert_anime(details, added_by=update.effective_user.id)
    SESSIONS.pop(sid, None)

    await q.edit_message_text(
        f"\u2705 Post created: {details['title']}\n\n"
        f"It's live under Available on {Config.BRAND_NAME} now.",
        reply_markup=InlineKeyboardMarkup([[_webapp_button()]]),
    )
    # Separate follow-up message, as its own bubble, prompting the join link.
    await q.message.reply_text(
        f"\U0001f4ce Now set a join link for {details['title']} — open the mini app, "
        f"tap the post, then tap \u2795 next to Join/Request to add it."
    )


async def handle_delpick(q, sid, idx):
    session = SESSIONS.get(sid)
    if not session:
        await q.answer("Session expired — run /delpost again.", show_alert=True)
        return
    match = session["matches"][idx]
    db.delete_anime(match["id"])
    SESSIONS.pop(sid, None)
    await q.answer()
    await q.edit_message_text(f"\U0001f5d1 Deleted: {match['title']}")


# --- Auto-search: plain text messages (no command) search the library ----

def _anime_card_text_and_keyboard(anime: dict):
    genres = " | ".join(anime.get("genres") or [])
    lines = [f"*{anime['title']}*"]
    if genres:
        lines.append(genres)
    if anime.get("rating"):
        lines.append(f"\u2b50 {anime['rating']}")
    if anime.get("description"):
        desc = anime["description"]
        lines.append(desc[:400] + ("\u2026" if len(desc) > 400 else ""))
    text = "\n\n".join(lines)

    if anime.get("join_link"):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("\u25b6 Join", url=anime["join_link"])]])
    else:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
            "Request Anime", callback_data=f"reqtext:{anime['title'][:200]}")]])
    return text, keyboard


def _display_name_from_user(tg_user) -> str:
    if tg_user.username:
        return f"@{tg_user.username}"
    return tg_user.full_name or str(tg_user.id)


async def on_text_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any plain-text message (not a command) is treated as an anime title
    search — first against the local library, then against AniList if
    nothing local matches, so there's always a useful result or a way to
    request the title."""
    text = (update.message.text or "").strip()
    if len(text) < 2:
        return

    local_matches = await asyncio.to_thread(db.search_local, text)
    if local_matches:
        if len(local_matches) == 1:
            text_out, keyboard = _anime_card_text_and_keyboard(local_matches[0])
            await update.message.reply_text(text_out, reply_markup=keyboard, parse_mode="Markdown")
        else:
            sid = new_session(kind="searchpick", matches=local_matches[:8])
            rows = [[InlineKeyboardButton(m["title"], callback_data=f"searchpick:{sid}:{i}")]
                    for i, m in enumerate(local_matches[:8])]
            rows.append([InlineKeyboardButton("Cancel", callback_data=f"cancel:{sid}")])
            await update.message.reply_text(
                f"Found {len(local_matches)} matches for '{text}':",
                reply_markup=InlineKeyboardMarkup(rows),
            )
        return

    try:
        data = await asyncio.to_thread(SOURCES["anilist"].search, text, 1)
    except Exception:
        data = {"results": []}

    results = data.get("results", [])
    if not results:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Request Anime", callback_data=f"reqtext:{text[:200]}")
        ]])
        await update.message.reply_text(f"No results found for '{text}'.", reply_markup=keyboard)
        return

    sid = new_session(kind="discoverpick", query=text, results=results)
    rows = [
        [InlineKeyboardButton(
            r["title"] + (f" ({r['year']})" if r.get("year") else ""),
            callback_data=f"discoverpick:{sid}:{i}",
        )]
        for i, r in enumerate(results)
    ]
    rows.append([InlineKeyboardButton("Cancel", callback_data=f"cancel:{sid}")])
    await update.message.reply_text(
        f"'{text}' isn't posted yet — did you mean one of these?",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_searchpick(q, sid, idx):
    session = SESSIONS.get(sid)
    if not session:
        await q.answer("Session expired — search again.", show_alert=True)
        return
    match = session["matches"][idx]
    SESSIONS.pop(sid, None)
    await q.answer()
    text, keyboard = _anime_card_text_and_keyboard(match)
    await q.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def handle_discoverpick(q, sid, idx):
    session = SESSIONS.get(sid)
    if not session:
        await q.answer("Session expired — search again.", show_alert=True)
        return
    await q.answer("Fetching details...")
    r = session["results"][idx]
    SESSIONS.pop(sid, None)
    try:
        details = await asyncio.to_thread(SOURCES["anilist"].get_details, r["source_id"])
    except Exception:
        await q.edit_message_text("Couldn't fetch details for that title. Try again.")
        return
    text, keyboard = _anime_card_text_and_keyboard(details)
    await q.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def handle_reqtext(q, title: str):
    requester_name = _display_name_from_user(q.from_user)
    req_id = db.create_request(title, q.from_user.id, requester_name)
    notify_new_request(req_id, title, requester_name)
    await q.answer("Request sent")
    await q.edit_message_reply_markup(reply_markup=None)
    await q.message.reply_text(f"\U0001f4ec Request sent for '{title}' — you'll be notified once it's added.")


async def handle_request_decision(q, req_id, decision):
    req = db.get_request(req_id)
    if not req:
        await q.answer("This request no longer exists.", show_alert=True)
        return
    if req["status"] != "pending":
        await q.answer(f"Already {req['status']}.", show_alert=True)
        return

    status = "accepted" if decision == "accept" else "cancelled"
    db.update_request_status(req_id, status)
    await q.answer("Saved")
    icon = "\u2705 Accepted" if status == "accepted" else "\u274c Cancelled"
    await q.edit_message_text(
        f"\U0001f4e5 Anime Request\n"
        f"Title: {req['anime_title']}\n"
        f"Requested by: {req['requested_by_name'] or req['requested_by']}\n\n"
        f"{icon}"
    )


# --- Notifications to the log channel ------------------------------------

def notify_new_request(req_id: int, title: str, requester_name: str):
    if not Config.LOG_CHANNEL_ID or not bot_app:
        return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("\u2705 Accept", callback_data=f"req:{req_id}:accept"),
        InlineKeyboardButton("\u274c Cancel", callback_data=f"req:{req_id}:cancel"),
    ]])
    text = f"\U0001f4e5 New Anime Request\nTitle: {title}\nRequested by: {requester_name}"
    run_async(bot_app.bot.send_message(Config.LOG_CHANNEL_ID, text, reply_markup=keyboard))


def notify_new_report(title: str, reason: str, details: str, reporter_name: str):
    if not Config.LOG_CHANNEL_ID or not bot_app:
        return
    text = (
        f"\U0001f6a9 New Report\n"
        f"Anime: {title}\n"
        f"Reason: {reason}\n"
        + (f"Details: {details}\n" if details else "")
        + f"By: {reporter_name}"
    )
    run_async(bot_app.bot.send_message(Config.LOG_CHANNEL_ID, text))


# ---------------------------------------------------------------------------
# Telegram WebApp initData verification
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
# ---------------------------------------------------------------------------

def verify_init_data(init_data: str) -> dict | None:
    if not init_data or not Config.BOT_TOKEN:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", Config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    user_raw = parsed.get("user")
    if not user_raw:
        return None
    return json.loads(user_raw)


def current_user():
    """Returns the verified Telegram user dict for this request, or None if
    the request didn't come from inside Telegram (or failed verification)."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    return verify_init_data(init_data)


def is_admin(user: dict | None) -> bool:
    return bool(user) and user.get("id") in Config.ADMIN_IDS


# A Telegram public username: 5-32 chars, must start with a letter, only
# letters/digits/underscores after that (Telegram's own username rules).
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def normalize_join_link(raw: str) -> str:
    """Turn whatever an admin pastes — a bare @username, a bare username, a
    t.me/... link missing its scheme, or a full URL — into a URL that's
    actually safe to open. Raises ValueError with a user-facing message on
    anything that can't be turned into an openable link.

    This is the fix for "Set Join Link" silently failing: previously the
    raw input was stored as-is, so an admin pasting "@my_channel" (instead
    of a full https://t.me/my_channel URL) saved a string that Telegram's
    web_app openLink() call can't open, and the Join button just did
    nothing with no error shown anywhere.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""  # clearing the link is always allowed

    if raw.startswith("http://") or raw.startswith("https://"):
        if "t.me/" not in raw and "telegram.me/" not in raw:
            raise ValueError("That doesn't look like a Telegram link.")
        return raw

    if raw.startswith("t.me/") or raw.startswith("telegram.me/"):
        return "https://" + raw

    if re.fullmatch(r"-?\d+", raw):
        raise ValueError(
            "A numeric channel ID can't be opened directly — paste the "
            "channel's invite link (https://t.me/+...) or its @username instead."
        )

    username = raw[1:] if raw.startswith("@") else raw
    if not USERNAME_RE.match(username):
        raise ValueError(
            "Enter a Telegram @username, a t.me/ link, or an invite link (https://t.me/+...)."
        )
    return f"https://t.me/{username}"


# ---------------------------------------------------------------------------
# Web app + JSON API
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html", brand_name=Config.BRAND_NAME, brand_handle=Config.BRAND_HANDLE)


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.get("/api/catalog/trending")
def api_trending():
    try:
        return jsonify(SOURCES["anilist"].get_trending())
    except requests.RequestException:
        return jsonify([])


@app.get("/api/catalog/popular")
def api_popular():
    try:
        return jsonify(SOURCES["anilist"].get_popular())
    except requests.RequestException:
        return jsonify([])


@app.get("/api/news/spotlight")
def api_news_spotlight():
    """The single most recent anime news story, for the News tab's
    #1 Spotlight card. Returns null if the feed is unreachable, so the
    frontend just hides the section rather than showing broken content."""
    try:
        return jsonify(news_plugin.get_spotlight())
    except requests.RequestException:
        return jsonify(None)


@app.get("/api/catalog/available")
def api_available():
    return jsonify(db.list_available())


@app.get("/api/anime/<int:anime_id>")
def api_anime_detail(anime_id):
    anime = db.get_anime(anime_id)
    if not anime:
        abort(404)
    return jsonify(anime)


@app.get("/api/anilist/<int:anilist_id>")
def api_anilist_details(anilist_id):
    """Full details (genres/synopsis/banner) for a Trending/Popular card —
    the lightweight discovery query doesn't include those fields."""
    try:
        return jsonify(SOURCES["anilist"].get_details(anilist_id))
    except requests.RequestException:
        abort(502)


@app.post("/api/request")
def api_request():
    payload = request.get_json(force=True, silent=True) or {}
    title = (payload.get("title") or "").strip()
    if not title:
        return jsonify(error="title is required"), 400

    user = current_user()
    requester_id = user.get("id") if user else None
    requester_name = _telegram_user_label(user) if user else "Guest"

    req_id = db.create_request(title, requester_id, requester_name)
    notify_new_request(req_id, title, requester_name)
    return jsonify(status="pending", id=req_id), 201


@app.post("/api/report")
def api_report():
    payload = request.get_json(force=True, silent=True) or {}
    reason = (payload.get("reason") or "").strip()
    if not reason:
        return jsonify(error="reason is required"), 400
    details = (payload.get("details") or "").strip()[:50]
    anime_id = payload.get("anime_id")
    anime_title = (payload.get("anime_title") or "").strip()

    user = current_user()
    reporter_id = user.get("id") if user else None
    reporter_name = _telegram_user_label(user) if user else "Guest"

    db.create_report(anime_id, anime_title, reason, details, reporter_id, reporter_name)
    notify_new_report(anime_title, reason, details, reporter_name)
    return jsonify(status="received"), 201


@app.get("/api/profile")
def api_profile():
    user = current_user()
    if not user:
        return jsonify(error="Open this from inside Telegram to view your profile."), 401
    profile = db.get_or_create_user(
        telegram_id=user["id"],
        username=user.get("username"),
        first_name=user.get("first_name"),
        is_admin=is_admin(user),
    )
    return jsonify(profile)


@app.patch("/api/anime/<int:anime_id>/link")
def api_edit_link(anime_id):
    user = current_user()
    if not is_admin(user):
        abort(403)
    payload = request.get_json(force=True, silent=True) or {}
    raw_link = (payload.get("link") or "").strip()
    if not db.get_anime(anime_id):
        abort(404)
    try:
        link = normalize_join_link(raw_link)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    db.update_link(anime_id, link)
    return jsonify(status="updated", link=link)


def _telegram_user_label(user: dict) -> str:
    if user.get("username"):
        return f"@{user['username']}"
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
    return name or str(user.get("id"))


# ---------------------------------------------------------------------------
# Telegram webhook endpoint
# ---------------------------------------------------------------------------

@app.post("/webhook/<secret>")
def webhook(secret):
    if secret != Config.WEBHOOK_SECRET or bot_app is None:
        abort(403)
    update = Update.de_json(request.get_json(force=True), bot_app.bot)
    run_async(bot_app.process_update(update))
    return "ok"


# ---------------------------------------------------------------------------
# Bot startup
# ---------------------------------------------------------------------------

def build_bot_app() -> Application | None:
    if not Config.BOT_TOKEN:
        return None
    application = Application.builder().token(Config.BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("anidex", cmd_anidex))
    application.add_handler(CommandHandler("addpost", cmd_addpost))
    application.add_handler(CommandHandler("delpost", cmd_delpost))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_search))
    return application


bot_app = build_bot_app()
if bot_app is not None:
    run_async(bot_app.initialize())
    if Config.WEBAPP_URL.startswith("https://"):
        webhook_url = f"{Config.WEBAPP_URL}/webhook/{Config.WEBHOOK_SECRET}"
        run_async(bot_app.bot.set_webhook(url=webhook_url))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)
