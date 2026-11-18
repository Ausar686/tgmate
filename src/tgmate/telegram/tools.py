"""Tools for approved users: offer the actions that fit what they sent, and run the one they pick."""

import asyncio
import html

from aiogram import F, Router
from aiogram.enums import MessageEntityType
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tgmate.config import Settings
from tgmate.telegram.access import require_access
from tgmate.tools.errors import ToolError
from tgmate.tools.qr import QRCode

# Telegram's limit for a photo caption, counted after HTML parsing (`&amp;` is one character), so the plain text
# is cut before escaping, which also keeps the cut out of escape sequences.
CAPTION_LIMIT = 1024

HELP = (
    "Send me a link and pick what to do with it:\n"
    "• <b>QR code</b>: an image that opens the link when scanned\n\n"
    "Or use a command:\n"
    "/qr &lt;link&gt; — QR code for a link"
)
OWNER_HELP = "\n/users — approve or revoke users"
NOTHING_TO_DO = "I don't know what to do with this yet. Send me a link, or /help to see what I can do."
SOURCE_GONE = "I can't see the original message anymore; send the link again."
NOT_AUTHORIZED = "You are not authorized to use this command."


class LinkAction(CallbackData, prefix="link"):
    tool: str


# (button text, tool) for every action that takes a link; a new link tool adds its row here.
LINK_ACTIONS = [("QR code", "qr")]


def build_tools_router() -> Router:
    router = Router(name="tools")
    router.message.filter(F.chat.type == "private")
    router.message.middleware(require_access)
    router.callback_query.middleware(require_access)
    router.message.register(show_help, Command("start", "help"))
    router.message.register(qr_command, Command("qr"))
    # The owner's /users is handled by the access router first; here it only meets approved users.
    router.message.register(not_authorized, Command("users"))
    router.message.register(offer_link_actions, has_link)
    router.message.register(nothing_to_do)
    router.callback_query.register(run_link_action, LinkAction.filter())
    return router


def first_link(message: Message) -> str | None:
    """The first web link in the message's text or caption, as Telegram marked it up."""
    text = message.text or message.caption or ""
    for entity in message.entities or message.caption_entities or []:
        if entity.type == MessageEntityType.URL:
            return entity.extract_from(text)
        if entity.type == MessageEntityType.TEXT_LINK and entity.url:
            return entity.url
    return None


def has_link(message: Message) -> dict[str, str] | bool:
    link = first_link(message)
    return {"link": link} if link else False


async def show_help(message: Message, settings: Settings) -> None:
    owner = message.from_user is not None and message.from_user.id == settings.owner_user_id
    await message.answer(HELP + (OWNER_HELP if owner else ""))


async def nothing_to_do(message: Message) -> None:
    await message.reply(NOTHING_TO_DO)


async def not_authorized(message: Message) -> None:
    await message.reply(NOT_AUTHORIZED)


def _link_actions_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    for text, tool in LINK_ACTIONS:
        keyboard.button(text=text, callback_data=LinkAction(tool=tool))
    return keyboard.as_markup()


async def offer_link_actions(message: Message, link: str) -> None:
    # The prompt replies to the user's message, so the button handler reads the link back from it.
    await message.reply("What should I do with this link?", reply_markup=_link_actions_keyboard())


async def run_link_action(query: CallbackQuery, callback_data: LinkAction) -> None:
    prompt = query.message
    source = prompt.reply_to_message if isinstance(prompt, Message) else None
    link = first_link(source) if source is not None else None
    if link is None:
        await query.answer(SOURCE_GONE, show_alert=True)
        return
    await query.answer()
    match callback_data.tool:
        case "qr":
            await send_qr(source, link)


async def qr_command(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.reply("Usage: /qr &lt;link&gt;, e.g. <code>/qr example.com</code>")
        return
    await send_qr(message, command.args)


async def send_qr(message: Message, link: str) -> None:
    """Reply to `message` with a QR code for `link`, or with why it can't be made."""
    try:
        url = QRCode.normalize_url(link)
        png = await asyncio.to_thread(QRCode.from_url, url)
    except ToolError as exc:
        await message.reply(html.escape(str(exc)))
        return
    caption = url if len(url) <= CAPTION_LIMIT else url[: CAPTION_LIMIT - 1] + "…"
    await message.reply_photo(BufferedInputFile(png, "qr.png"), caption=html.escape(caption))
