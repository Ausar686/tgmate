import html

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, SendMessage, SendPhoto
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.images import decode_qr
from tests.telegram.conftest import seed_user
from tests.telegram.fake_api import FakeTelegram
from tests.telegram.updates import (
    USER,
    callback_update,
    command_update,
    link_update,
    message_data,
    update,
    url_entity,
)
from tgmate.storage.models import UserStatus
from tgmate.telegram.tools import CAPTION_LIMIT, NOTHING_TO_DO, SOURCE_GONE, LinkAction


@pytest.fixture(autouse=True)
async def approved(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    await seed_user(sessionmaker, USER, UserStatus.APPROVED)


def sent_qr(telegram: FakeTelegram) -> tuple[str, str, int]:
    """The decoded link, caption and replied-to message id of the only photo sent."""
    [photo] = telegram.calls(SendPhoto)
    return decode_qr(photo.photo.data), photo.caption, photo.reply_parameters.message_id


async def test_link_gets_a_reply_offering_the_link_tools(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    # Cyrillic before the link checks that entity offsets are read in UTF-16 units.
    await dispatcher.feed_update(bot, link_update("Глянь 👀 https://example.com/путь", "https://example.com/путь"))

    [prompt] = telegram.calls(SendMessage)
    assert prompt.reply_parameters.message_id == 100
    buttons = [(b.text, LinkAction.unpack(b.callback_data).tool) for b in prompt.reply_markup.inline_keyboard[0]]
    assert buttons == [("QR code", "qr")]


async def test_qr_button_replies_to_the_original_message_with_its_link(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    text = "Глянь 👀 example.com/путь?a=1&b=2"
    source = message_data(text, message_id=55, entities=[url_entity(text, "example.com/путь?a=1&b=2")])

    await dispatcher.feed_update(bot, callback_update(LinkAction(tool="qr").pack(), replying_to=source))

    assert sent_qr(telegram) == ("https://example.com/путь?a=1&b=2", "https://example.com/путь?a=1&amp;b=2", 55)
    [answer] = telegram.calls(AnswerCallbackQuery)
    assert answer.text is None


async def test_text_link_uses_its_hidden_address(dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram) -> None:
    source = message_data("docs", entities=[{"type": "text_link", "offset": 0, "length": 4, "url": "https://docs.example"}])

    await dispatcher.feed_update(bot, callback_update(LinkAction(tool="qr").pack(), replying_to=source))

    assert sent_qr(telegram)[0] == "https://docs.example"


async def test_button_whose_original_message_is_gone_asks_for_the_link_again(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await dispatcher.feed_update(bot, callback_update(LinkAction(tool="qr").pack()))

    [answer] = telegram.calls(AnswerCallbackQuery)
    assert (answer.text, answer.show_alert) == (SOURCE_GONE, True)
    assert telegram.calls(SendPhoto) == []


async def test_message_without_a_link_gets_pointed_to_help(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await dispatcher.feed_update(bot, update("just some words"))

    assert telegram.sent_texts(USER) == [NOTHING_TO_DO]


async def test_qr_command_sends_the_code_for_its_argument(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await dispatcher.feed_update(bot, command_update("/qr example.com"))

    assert sent_qr(telegram) == ("https://example.com", "https://example.com", 100)


async def test_qr_command_without_a_link_shows_usage(dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram) -> None:
    await dispatcher.feed_update(bot, command_update("/qr"))

    [usage] = telegram.sent_texts(USER)
    assert usage.startswith("Usage: /qr")


async def test_qr_command_reports_why_a_link_is_refused(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await dispatcher.feed_update(bot, command_update("/qr https://a@b.example/<x>"))

    assert telegram.sent_texts(USER) == ["The address must not contain a username or password."]
    assert telegram.calls(SendPhoto) == []


async def test_long_link_caption_is_cut_to_telegram_limit(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    link = "https://example.com/" + "a" * 1500

    await dispatcher.feed_update(bot, command_update(f"/qr {link}"))

    decoded, caption, _ = sent_qr(telegram)
    assert decoded == link
    assert len(caption) == CAPTION_LIMIT
    assert caption.endswith("…") and link.startswith(caption[:-1])



async def test_caption_limit_counts_escaped_characters_once(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    # Telegram counts a caption after HTML parsing, so `&amp;` is one character and must never be cut in half.
    link = "https://example.com/?" + "a=1&" * 400

    await dispatcher.feed_update(bot, command_update(f"/qr {link}"))

    decoded, caption, _ = sent_qr(telegram)
    assert decoded == link
    assert len(caption) > CAPTION_LIMIT
    assert html.escape(html.unescape(caption)) == caption
    shown = html.unescape(caption)
    assert len(shown) == CAPTION_LIMIT
    assert shown.endswith("…") and link.startswith(shown[:-1])

async def test_button_for_a_tool_that_no_longer_exists_does_nothing(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    source = message_data("https://example.com", entities=[url_entity("https://example.com", "https://example.com")])

    await dispatcher.feed_update(bot, callback_update(LinkAction(tool="retired").pack(), replying_to=source))

    assert len(telegram.calls(AnswerCallbackQuery)) == 1
    assert telegram.calls(SendPhoto) == []
    assert telegram.calls(SendMessage) == []
