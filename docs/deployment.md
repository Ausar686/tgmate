# Deployment

tgmate's Telegram bot runs as a single container with a SQLite database on a
Docker volume, optionally next to its own Bot API server for large files. The
images are built locally from [.docker/](../.docker) and run with
[docker-compose.yaml](../docker-compose.yaml).

## 1. Create the bot
1. In [@BotFather](https://t.me/BotFather): `/newbot`, keep the token.
   Optionally `/setjoingroups` → your bot → **Disable**: the bot works in
   private chats only and leaves any group it's added to anyway.
2. From the account that will own the bot, open the bot and send `/start`.
   Telegram doesn't let bots DM someone first, and access requests arrive by
   DM.
3. Find that account's numeric user id (e.g. via
   [@userinfobot](https://t.me/userinfobot)).

## 2. Configure
```bash
cp .env.example .env
```
Fill in `TELEGRAM_BOT_TOKEN` and `OWNER_USER_ID`. Every other variable falls
back to its default when left empty; the defaults and meanings live in
[config.py](../src/tgmate/config.py). Compose pins `DATABASE_URL` to the
volume, so the value in `.env` is ignored there. If you deploy a modified
version, set `SOURCE_URL` to where its source is published: the AGPL requires
offering it to the bot's users, and the bot links to it. `BOT_MEMORY_LIMIT`
(default `2g`) caps the container's memory, which bounds conversions and
downloads together; raise it if several large jobs run at once.

## 3. Run
```bash
docker compose build --pull
docker compose up -d
docker compose logs -f bot
```
`--pull` fetches the newest base images, so the build picks up their
security fixes, which also re-runs the image's own `apt-get upgrade`.
On startup the bot migrates the database, registers its command menus, and
starts polling. It logs a warning if it can't reach the owner (step 1.2).

Updating to a newer version is the same `build --pull` and `up -d` after
`git pull`; migrations run automatically on start. Rebuild the same way from
time to time even without code changes, to pick up base image security
fixes.

## 4. Use
People write to the bot; the owner gets a DM with **Approve** / **Reject**
for each new user and manages everyone with `/users`. Approved users send a
link and pick a tool, or use a command; see
[the bot's README](../src/tgmate/telegram/README.md).

## Own Bot API server
Telegram's hosted Bot API lets bots receive files up to 20 MB and send up to
50 MB, too little for most YouTube videos. The bot's own server, in local
mode, takes both up to 2000 MB. It's the `bot-api` compose service, which
runs only with the `bot-api` profile and is reachable only by the bot.
1. At [my.telegram.org](https://my.telegram.org) → **API development
   tools**, create an application and note its `api_id` and `api_hash`.
2. In `.env`:
   ```bash
   COMPOSE_PROFILES=bot-api
   TELEGRAM_API_ID=<api_id>
   TELEGRAM_API_HASH=<api_hash>
   TELEGRAM_API_URL=http://bot-api:8081
   ```
   Optionally raise `DOWNLOAD_LIMIT_MB` (up to 2000) for larger files from
   users, with `BOT_MEMORY_LIMIT` to match: they're converted in memory.
3. Stop the bot if it's running, log it out of the hosted Bot API (or
   Telegram may keep delivering its updates there), and start both
   services. Once logged out, the bot can't use the hosted Bot API again
   for 10 minutes.
   ```bash
   docker compose build --pull
   docker compose stop bot
   docker compose run --rm --no-deps bot python -m tgmate.telegram.logout
   docker compose up -d
   ```
To go back to the hosted Bot API, empty `COMPOSE_PROFILES` and
`TELEGRAM_API_URL`, then `docker compose up -d --remove-orphans`. The
server's session and the files it fetched live on the `bot-api` volume;
TDLib deletes old files on its own.

## Operations
- **Restarts:** the service restarts unless stopped. A fatal error, such as
  an invalid token, exits the process so Docker restarts it, backing off
  between restarts; check `docker compose logs bot`.
- **Stopping:** `docker compose stop` sends SIGTERM; the bot finishes polling
  and exits within the 30 s `stop_grace_period`.
- **Logs** are capped at 3 × 10 MB by the json-file driver.
- **Backup:** the whole state is one SQLite file on the `data` volume. Use
  SQLite's online backup so a running bot doesn't produce a torn copy:
  ```bash
  docker compose exec bot python -c "import sqlite3; sqlite3.connect('/data/tgmate.db').backup(sqlite3.connect('/data/backup.db'))"
  docker compose cp bot:/data/backup.db ./tgmate-backup.db
  ```
- **Image:** Debian slim with the app in its own venv, no pip, running as an
  unprivileged `tgmate` user. CI builds it, migrates a fresh database inside
  it, and fails on fixable high or critical vulnerabilities (Trivy). The Bot
  API server's image is aiogram's build of Telegram's server, pinned by
  digest and run as the same unprivileged user; CI builds, starts and scans
  it too.

## Troubleshooting
- **YouTube downloads fail with "Sign in to confirm you're not a bot"** or
  similar: YouTube blocks some server IP ranges. The bot can't work around
  that; try another network or ask for a yt-dlp update (it's frozen, see
  [architecture](architecture.md)).
- **Telegram calls fail with `Request timeout error`** while `curl` on the
  host reaches `api.telegram.org`: the host's VPN or firewall doesn't pass
  bridged container traffic. The service uses Docker's default bridge
  network; if the host can't route it, add `network_mode: host` to the `bot`
  service (memedexer needs this on its host).
- **Build fails with `DNS: transient error` or apt can't reach its
  repositories** while pulling the base images works: build steps run on
  Docker's bridge too, and may get Docker's fallback DNS (Google), which some
  networks block. Build on the host network, then start without `--build`:
  ```bash
  docker build --network host --pull -f .docker/Dockerfile -t tgmate:latest .
  docker compose up -d
  ```
  A permanent fix is a resolver the containers can reach, e.g.
  `"dns": ["<your router or upstream DNS>"]` in `/etc/docker/daemon.json`,
  then restart Docker.
