# Anime Index

A Telegram bot + Mini App for browsing, requesting, and moderating an anime
catalog. Flask serves both the JSON API and the mini app's HTML/CSS/JS; the
bot runs in the same process via a Telegram webhook.

## What's included

- **`/anidex`** — welcome message with an Open Mini App button (`/start` stays silent).
- **`/addpost <name>`** — admin-only. Searches AniList, shows paginated
  results, and on your pick, creates the post directly under **Available**
  — then sends a follow-up message prompting you to set its join link.
- **`/delpost <name>`** — admin-only. Deletes a matching post (or lets you
  choose which one, if several match).
- **Auto-search** — send the bot any plain text (not a command) and it
  searches your posted library first, then AniList if nothing local
  matches, replying with a card (and a Join or Request Anime button) right
  in the chat.
- **Mini app** — tabs are **Available** (your posted catalog, browsable
  A–Z) and **News** (a #1 Spotlight story from Anime News Network, plus
  Trending Now + Popular live from AniList — discovery only, no
  request/join/report actions there).
- **Request Anime / Join** — an Available post shows Request Anime until
  you set a join link, then shows Join instead. Requests notify your log
  channel with Accept / Cancel buttons.
- **Report an issue** — Available posts only (not News/Spotlight). Preset
  reasons + optional 50-character note, sent to your log channel.
- **Profile** — Telegram ID, registration status, role, access, verified
  via Telegram's WebApp `initData` signature.
- **Admin ➕ link editor** — a ➕ button next to Join/Request (admin/owner
  only) opens a "Set Join Link" sheet accepting a channel ID, @username, or
  URL — the input is validated and normalized into an openable
  `https://t.me/...` link server-side before saving, with a clear error
  message if it can't be turned into one (e.g. a bare numeric channel ID).
- Post details open as a small centered card, not a full-screen page.

## 1. Create the bot

1. Message **[@BotFather](https://t.me/BotFather)** → `/newbot` → follow
   the prompts → copy the token it gives you (`BOT_TOKEN`).
2. Get your own Telegram numeric ID from **[@userinfobot](https://t.me/userinfobot)**
   — this goes in `ADMIN_IDS`.
3. Create a private channel for logs (requests/reports), add the bot as an
   admin, and grab the channel ID (starts with `-100...`) — you can get it
   by forwarding a message from the channel to **[@userinfobot](https://t.me/userinfobot)**.
   This is `LOG_CHANNEL_ID`.

## 2. Set up MongoDB

Data (catalog, users, requests, reports) is stored in MongoDB — no local
file, so it survives redeploys on Render/Koyeb without any extra disk
config. Easiest option: create a free cluster at
[MongoDB Atlas](https://www.mongodb.com/cloud/atlas), then grab its
connection string for `MONGODB_URL` (looks like
`mongodb+srv://user:pass@cluster.mongodb.net`). `MONGODB_NAME` is just the
database name inside that cluster — `anime_index` by default, change it if
you like.

For local development, `docker compose up` starts a MongoDB container for
you automatically (see `docker-compose.yml`) — no Atlas account needed
until you deploy.

## 3. Configure environment variables

Copy `.env.example` to `.env` and fill it in. Locally, `docker-compose`
reads `.env` automatically. On Render/Koyeb, set the same variables in
their dashboards instead of committing a `.env` file.

`WEBAPP_URL` must be the final HTTPS URL of your deployment — the bot uses
it both for the mini app's "Open" button and to register the Telegram
webhook on startup, so redeploy once after you know the URL if you didn't
have it yet.

## 4. Run locally

```bash
pip install -r requirements.txt
python app.py
```

Or with Docker (also starts a local MongoDB container):

```bash
docker compose up --build
```

Without `WEBAPP_URL` set to a real HTTPS address, the bot won't receive
updates (Telegram webhooks require HTTPS) — for local bot testing, use a
tunnel like `ngrok http 8000` and set `WEBAPP_URL` to the tunnel URL.

## 5. Deploy on Render

1. Push this repo to GitHub.
2. Render Dashboard → **New → Blueprint** → connect the repo. It reads
   `render.yaml` and creates the service automatically.
3. Fill in `BOT_TOKEN`, `LOG_CHANNEL_ID`, `ADMIN_IDS`, `MONGODB_URL` in the
   dashboard (marked `sync: false` in the blueprint, so Render prompts for
   them).
4. Once deployed, update `WEBAPP_URL` to the real `.onrender.com` address
   and redeploy so the webhook registers correctly.

## 6. Deploy on Koyeb

Koyeb doesn't auto-read a repo config file the way Render does — use the
included `Dockerfile`:

1. Push this repo to GitHub.
2. Koyeb Control Panel → **Create Web Service → GitHub** → select the repo.
3. Builder: **Dockerfile**. Port: **8000**.
4. Add the same environment variables as above (including `MONGODB_URL`).
5. Deploy, then set `WEBAPP_URL` to the `.koyeb.app` URL and redeploy.

See `koyeb.yaml` for the equivalent CLI command.

## Notes

- `plugins/` holds the metadata source (`anilist.py`) behind a shared
  interface (`base.py`) — add another source by implementing the same
  `search` / `get_details` methods and registering it in
  `plugins/__init__.py`. MyAnimeList (via the Jikan API) was tried and
  removed — too unreliable in practice.
- The bot keeps `/addpost` and `/delpost` conversation state in memory —
  run the web process with a **single worker** (already set in `Dockerfile`
  and `render.yaml`); multiple workers would each have their own copy and
  break the multi-step flows.
- Join links are stored as plain URLs you provide via `/addpost` follow-up
  editing or the in-app editor — this project doesn't source, scrape, or
  curate content itself.
