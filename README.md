# Anime Index

A Telegram bot + Mini App for browsing, requesting, and moderating an anime
catalog. Flask serves both the JSON API and the mini app's HTML/CSS/JS; the
bot runs in the same process via a Telegram webhook.

## What's included

- **`/anidex`** (also `/start`) — welcome message with About / Help /
  Open Mini App buttons.
- **`/addpost <name>`** — admin-only. Prompts for a source (AniList /
  MyAnimeList), shows paginated search results, and on your pick, fetches
  full details and creates the catalog entry.
- **`/delpost <name>`** — admin-only. Deletes a matching post (or lets you
  choose which one, if several match).
- **Mini app** — Trending Now + Popular (live from AniList) under **All**;
  your own posted catalog, browsable A–Z, under **Available**.
- **Request Anime** — for any title without a join link yet. Notifies your
  log channel with Accept / Cancel buttons.
- **Join** — shown once a post has a link. Opens whatever URL you set for
  it.
- **Report an issue** — preset reasons + optional 50-character note, sent
  to your log channel.
- **Profile** — Telegram ID, registration status, role, access, verified
  via Telegram's WebApp `initData` signature.
- **Admin inline link editor** — edit a post's join link straight from the
  mini app (no need to re-run `/addpost`).

## 1. Create the bot

1. Message **[@BotFather](https://t.me/BotFather)** → `/newbot` → follow
   the prompts → copy the token it gives you (`BOT_TOKEN`).
2. Get your own Telegram numeric ID from **[@userinfobot](https://t.me/userinfobot)**
   — this goes in `ADMIN_IDS`.
3. Create a private channel for logs (requests/reports), add the bot as an
   admin, and grab the channel ID (starts with `-100...`) — you can get it
   by forwarding a message from the channel to **[@userinfobot](https://t.me/userinfobot)**.
   This is `LOG_CHANNEL_ID`.

## 2. Configure environment variables

Copy `.env.example` to `.env` and fill it in. Locally, `docker-compose`
reads `.env` automatically. On Render/Koyeb, set the same variables in
their dashboards instead of committing a `.env` file.

`WEBAPP_URL` must be the final HTTPS URL of your deployment — the bot uses
it both for the mini app's "Open" button and to register the Telegram
webhook on startup, so redeploy once after you know the URL if you didn't
have it yet.

## 3. Run locally

```bash
pip install -r requirements.txt
python app.py
```

Or with Docker:

```bash
docker compose up --build
```

Without `WEBAPP_URL` set to a real HTTPS address, the bot won't receive
updates (Telegram webhooks require HTTPS) — for local bot testing, use a
tunnel like `ngrok http 8000` and set `WEBAPP_URL` to the tunnel URL.

## 4. Deploy on Render

1. Push this repo to GitHub.
2. Render Dashboard → **New → Blueprint** → connect the repo. It reads
   `render.yaml` and creates the service automatically.
3. Fill in `BOT_TOKEN`, `LOG_CHANNEL_ID`, `ADMIN_IDS` in the dashboard
   (marked `sync: false` in the blueprint, so Render prompts for them).
4. Once deployed, update `WEBAPP_URL` to the real `.onrender.com` address
   and redeploy so the webhook registers correctly.

Render's free plan has an ephemeral filesystem — see the note in
`render.yaml` about attaching a persistent disk once you're past testing.

## 5. Deploy on Koyeb

Koyeb doesn't auto-read a repo config file the way Render does — use the
included `Dockerfile`:

1. Push this repo to GitHub.
2. Koyeb Control Panel → **Create Web Service → GitHub** → select the repo.
3. Builder: **Dockerfile**. Port: **8000**.
4. Add the same environment variables as above.
5. Deploy, then set `WEBAPP_URL` to the `.koyeb.app` URL and redeploy.

See `koyeb.yaml` for the equivalent CLI command.

## Notes

- `plugins/` holds the two metadata sources (`anilist.py`, `myanimelist.py`)
  behind a shared interface (`base.py`) — add another source by
  implementing the same `search` / `get_details` methods and registering
  it in `plugins/__init__.py`.
- The bot keeps `/addpost` and `/delpost` conversation state in memory —
  run the web process with a **single worker** (already set in `Dockerfile`
  and `render.yaml`); multiple workers would each have their own copy and
  break the multi-step flows.
- Join links are stored as plain URLs you provide via `/addpost` follow-up
  editing or the in-app editor — this project doesn't source, scrape, or
  curate content itself.
