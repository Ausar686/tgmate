# Deployment

tgmate's Telegram bot runs as a single container with a SQLite database on a
Docker volume. The image is built locally from
[.docker/Dockerfile](../.docker/Dockerfile) and run with
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
volume, so the value in `.env` is ignored there.

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
  it, and fails on fixable high or critical vulnerabilities (Trivy).

## Troubleshooting
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
