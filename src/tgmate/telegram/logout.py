"""Logs the bot out of Telegram's hosted Bot API, to move it to its own: `python -m tgmate.telegram.logout`."""

import asyncio

from aiogram import Bot

from tgmate.config import Settings

DONE = (
    "Logged out of Telegram's hosted Bot API. Start the bot with TELEGRAM_API_URL set now; "
    "the hosted Bot API won't take it back for 10 minutes."
)


async def log_out(bot: Bot) -> None:
    """Without this, Telegram doesn't guarantee updates reach the bot's own server instead of the hosted one."""
    async with bot:
        await bot.log_out()
    return None


def main() -> None:
    # Always the hosted Bot API, whatever TELEGRAM_API_URL says: that's the server the bot is leaving.
    asyncio.run(log_out(Bot(Settings().telegram_bot_token.get_secret_value())))
    print(DONE)


if __name__ == "__main__":
    main()
