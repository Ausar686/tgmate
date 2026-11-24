FROM aiogram/telegram-bot-api:10.5@sha256:0ed088d2ffcc1dbca294813d6949799747c64294aaff931437b8d18e671f4c20

# Runs as the bot's user (uid 10001, see Dockerfile) instead of switching to its own: TDLib writes downloaded files
# readable by their owner only, and the bot reads them straight from the shared volume.
RUN apk upgrade --no-cache \
    && chown 10001:10001 /var/lib/telegram-bot-api /tmp/telegram-bot-api
USER 10001:10001

# The API ID and hash come from TELEGRAM_API_ID and TELEGRAM_API_HASH, which the server reads itself.
ENTRYPOINT ["telegram-bot-api", "--local", "--dir=/var/lib/telegram-bot-api", "--temp-dir=/tmp/telegram-bot-api", "--http-port=8081"]
