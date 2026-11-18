import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import AnswerCallbackQuery, EditMessageText, LeaveChat, SendMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import OWNER
from tests.telegram.conftest import seed_user, user_status
from tests.telegram.fake_api import FakeTelegram
from tests.telegram.updates import USER, callback_update, command_update, member_update, update
from tgmate.storage.models import User, UserStatus
from tgmate.telegram.access import APPROVED, DENIED, REQUESTED, WAITING, UserAction
from tgmate.telegram.tools import HELP, OWNER_HELP, LinkAction


def forbidden(method: type) -> TelegramForbiddenError:
    return TelegramForbiddenError(method(chat_id=1, text="x"), "Forbidden: bot was blocked by the user")


async def press(dispatcher: Dispatcher, bot: Bot, action: str, user_id: int = USER, *, by: int = OWNER) -> None:
    await dispatcher.feed_update(bot, callback_update(UserAction(action=action, user_id=user_id).pack(), user_id=by))


async def test_unknown_user_is_registered_and_the_owner_is_asked(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await dispatcher.feed_update(bot, command_update("/start", full_name=("Al <ice>", "B"), username="al"))

    async with sessionmaker() as session:
        user = await session.get(User, USER)
    assert (user.status, user.full_name, user.username) == (UserStatus.PENDING, "Al <ice> B", "al")
    request, reply = telegram.calls(SendMessage)
    assert request.chat_id == OWNER
    assert "<b>Al &lt;ice&gt; B</b> @al (<code>5</code>)" in request.text
    buttons = [UserAction.unpack(b.callback_data) for b in request.reply_markup.inline_keyboard[0]]
    assert [(b.action, b.user_id) for b in buttons] == [("approve", USER), ("reject", USER)]
    assert (reply.chat_id, reply.text) == (USER, REQUESTED)


async def test_pending_user_asks_the_owner_once_and_hears_why_once_an_hour(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    for update_id in (1, 2, 3):
        await dispatcher.feed_update(bot, update("hello?", update_id=update_id))

    assert len(telegram.sent_texts(OWNER)) == 1
    assert telegram.sent_texts(USER) == [REQUESTED, WAITING]


async def test_request_is_still_acknowledged_when_the_owner_cannot_be_reached(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, caplog: pytest.LogCaptureFixture
) -> None:
    telegram.errors[SendMessage] = [forbidden(SendMessage)]

    await dispatcher.feed_update(bot, update("hi"))

    assert telegram.sent_texts(USER) == [REQUESTED]
    assert "telegram call failed" in caplog.text


async def test_owner_approves_and_the_user_is_told(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(sessionmaker, USER, UserStatus.PENDING)

    await press(dispatcher, bot, "approve")

    assert await user_status(sessionmaker, USER) is UserStatus.APPROVED
    assert telegram.sent_texts(USER) == [APPROVED]
    [answer] = telegram.calls(AnswerCallbackQuery)
    assert answer.text == "User approved."
    [edit] = telegram.calls(EditMessageText)
    assert edit.text == "<b>Alice</b> @alice (<code>5</code>): approved."


async def test_approval_is_kept_when_the_user_cannot_be_told(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(sessionmaker, USER, UserStatus.PENDING)
    telegram.errors[SendMessage] = [forbidden(SendMessage)]

    await press(dispatcher, bot, "approve")

    assert await user_status(sessionmaker, USER) is UserStatus.APPROVED
    [edit] = telegram.calls(EditMessageText)
    assert "Couldn't tell them" in edit.text


@pytest.mark.parametrize(("action", "status"), [("reject", UserStatus.REJECTED), ("revoke", UserStatus.REVOKED)])
async def test_owner_rejects_or_revokes_without_messaging_the_user(
    dispatcher: Dispatcher,
    bot: Bot,
    telegram: FakeTelegram,
    sessionmaker: async_sessionmaker[AsyncSession],
    action: str,
    status: UserStatus,
) -> None:
    await seed_user(sessionmaker, USER, UserStatus.APPROVED)

    await press(dispatcher, bot, action)

    assert await user_status(sessionmaker, USER) is status
    assert telegram.sent_texts(USER) == []


async def test_only_the_owner_can_decide(
    dispatcher: Dispatcher, bot: Bot, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(sessionmaker, USER, UserStatus.PENDING)
    await seed_user(sessionmaker, 7, UserStatus.APPROVED, full_name="Mallory")

    await press(dispatcher, bot, "approve", by=7)

    assert await user_status(sessionmaker, USER) is UserStatus.PENDING


@pytest.mark.parametrize(
    ("action", "user_id", "alert"), [("ban", USER, "Unknown action."), ("approve", 99, "Unknown user.")]
)
async def test_unknown_action_or_user_is_reported(
    dispatcher: Dispatcher,
    bot: Bot,
    telegram: FakeTelegram,
    sessionmaker: async_sessionmaker[AsyncSession],
    action: str,
    user_id: int,
    alert: str,
) -> None:
    await seed_user(sessionmaker, USER, UserStatus.PENDING)

    await press(dispatcher, bot, action, user_id)

    [answer] = telegram.calls(AnswerCallbackQuery)
    assert (answer.text, answer.show_alert) == (alert, True)
    assert await user_status(sessionmaker, USER) is UserStatus.PENDING


async def test_rejected_user_is_turned_away_without_asking_the_owner(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(sessionmaker, USER, UserStatus.REJECTED)

    await dispatcher.feed_update(bot, update("let me in"))

    assert telegram.sent_texts(OWNER) == []
    assert telegram.sent_texts(USER) == [DENIED]
    assert await user_status(sessionmaker, USER) is UserStatus.REJECTED


async def test_revoked_user_who_writes_asks_again(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(sessionmaker, USER, UserStatus.REVOKED)

    await dispatcher.feed_update(bot, update("hi again"))

    assert await user_status(sessionmaker, USER) is UserStatus.PENDING
    assert len(telegram.sent_texts(OWNER)) == 1
    assert telegram.sent_texts(USER) == [REQUESTED]


async def test_approved_user_gets_help_and_their_names_are_refreshed(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(sessionmaker, USER, UserStatus.APPROVED)

    await dispatcher.feed_update(bot, command_update("/start", full_name=("Alicia", None), username=None))

    assert telegram.sent_texts(USER) == [HELP]
    async with sessionmaker() as session:
        user = await session.get(User, USER)
    assert (user.full_name, user.username, user.status) == ("Alicia", None, UserStatus.APPROVED)


async def test_owner_is_always_allowed_and_never_stored(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await dispatcher.feed_update(bot, command_update("/help", user_id=OWNER))

    assert telegram.sent_texts(OWNER) == [HELP + OWNER_HELP]
    assert await user_status(sessionmaker, OWNER) is None


@pytest.mark.parametrize(("status", "alert"), [(UserStatus.PENDING, WAITING), (UserStatus.REJECTED, DENIED)])
async def test_tool_buttons_refuse_users_who_are_not_approved(
    dispatcher: Dispatcher,
    bot: Bot,
    telegram: FakeTelegram,
    sessionmaker: async_sessionmaker[AsyncSession],
    status: UserStatus,
    alert: str,
) -> None:
    await seed_user(sessionmaker, USER, status)

    await dispatcher.feed_update(bot, callback_update(LinkAction(tool="qr").pack()))

    [answer] = telegram.calls(AnswerCallbackQuery)
    assert (answer.text, answer.show_alert) == (alert, True)
    assert telegram.sent_texts(OWNER) == []


async def test_users_lists_everyone_but_revoked_with_their_buttons(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(sessionmaker, 2, UserStatus.APPROVED, full_name="Bob", username=None)
    await seed_user(sessionmaker, 3, UserStatus.PENDING, full_name="Cat")
    await seed_user(sessionmaker, 4, UserStatus.REJECTED, full_name="Dan")
    await seed_user(sessionmaker, 5, UserStatus.REVOKED, full_name="Eve")

    await dispatcher.feed_update(bot, command_update("/users", user_id=OWNER))

    [listing] = telegram.calls(SendMessage)
    assert listing.text.splitlines() == [
        "⏳ <b>Cat</b> @alice (<code>3</code>)",
        "✅ <b>Bob</b> (<code>2</code>)",
        "🚫 <b>Dan</b> @alice (<code>4</code>)",
    ]
    rows = listing.reply_markup.inline_keyboard
    buttons = [(b.text, UserAction.unpack(b.callback_data)) for row in rows for b in row]
    assert [(text, action.user_id) for text, action in buttons] == [
        ("Approve Cat", 3),
        ("Reject Cat", 3),
        ("Revoke Bob", 2),
        ("Approve Dan", 4),
    ]


async def test_users_with_nobody_to_list(dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram) -> None:
    await dispatcher.feed_update(bot, command_update("/users", user_id=OWNER))

    assert telegram.sent_texts(OWNER) == ["No pending, approved or rejected users."]


async def test_users_command_from_anyone_else_is_an_ordinary_message(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await dispatcher.feed_update(bot, command_update("/users"))

    assert telegram.sent_texts(USER) == [REQUESTED]


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
async def test_bot_leaves_groups_and_channels_it_is_added_to(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, chat_type: str
) -> None:
    await dispatcher.feed_update(bot, member_update(chat_type=chat_type))

    [leave] = telegram.calls(LeaveChat)
    assert leave.chat_id == -100


async def test_messages_in_groups_are_ignored(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await seed_user(sessionmaker, USER, UserStatus.APPROVED)

    await dispatcher.feed_update(bot, command_update("/help", chat_id=-100, chat_type="group"))

    assert telegram.requests == []
