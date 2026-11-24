"""Tools for approved users: offer the actions that fit what they sent, and run the one they pick."""

import asyncio
import html

from aiogram import Bot, F, Router
from aiogram.enums import MessageEntityType
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from tgmate.config import Settings
from tgmate.telegram.access import require_access, source_notice
from tgmate.telegram.files import (
    FILE_ACTIONS,
    MB,
    TOOL_KINDS,
    Albums,
    Attachment,
    FileAction,
    Kind,
    Limits,
    attachment,
    check_downloadable,
    send_document_pdf,
    send_docx,
    send_jpegs,
    send_pdf,
)
from tgmate.tools.errors import ToolError
from tgmate.tools.qr import QRCode

# Telegram's limit for a photo caption, counted after HTML parsing (`&amp;` is one character), so the plain text
# is cut before escaping, which also keeps the cut out of escape sequences.
CAPTION_LIMIT = 1024

HELP = (
    "Send me something and pick what to do with it:\n"
    "• a link → <b>QR code</b>: an image that opens the link when scanned\n"
    "• photos or images, one or an album → <b>PDF</b>: one page per image\n"
    "• a PDF → <b>JPG images</b>: one per page, as a ZIP above 10 pages\n"
    "• a PDF → <b>DOCX</b>: an editable Word document\n"
    "• a Word (DOCX, DOC), ODT or RTF document → <b>PDF</b>\n"
    "I take files up to {limit} MB.\n\n"
    "Or use a command:\n"
    "/qr &lt;link&gt; — QR code for a link"
)
OWNER_HELP = "\n/users — approve or revoke users"
NOTHING_TO_DO = (
    "I don't know what to do with this yet. Send me a link, an image, a PDF or a document, "
    "or /help to see what I can do."
)
PROMPT = "What should I do with this?"
SOURCE_GONE = "I can't see the original message anymore; send it again."
ALBUM_GONE = "I no longer have this album; send it again."
ALBUM_NOT_IMAGES = "I can only turn an album of images into a PDF; send PDFs and other files one at a time."
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
    router.message.register(offer_album_actions, F.media_group_id)
    router.message.register(offer_actions)
    router.callback_query.register(run_link_action, LinkAction.filter())
    router.callback_query.register(run_file_action, FileAction.filter())
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


async def show_help(message: Message, settings: Settings, limits: Limits) -> None:
    owner = message.from_user is not None and message.from_user.id == settings.owner_user_id
    text = HELP.format(limit=limits.download // MB) + (OWNER_HELP if owner else "")
    await message.answer(f"{text}\n\n{source_notice(settings.source_url)}")


async def not_authorized(message: Message) -> None:
    await message.reply(NOT_AUTHORIZED)


def _buttons(message: Message, files: list[Attachment], album: str = "") -> list[InlineKeyboardButton]:
    """Buttons for the tools that take these files, then for the link tools if the message has a link."""
    buttons = [
        InlineKeyboardButton(text=text, callback_data=FileAction(tool=tool, album=album).pack())
        for text, tool in (FILE_ACTIONS[files[0].kind] if files else [])
    ]
    if first_link(message) is not None:
        buttons += [
            InlineKeyboardButton(text=text, callback_data=LinkAction(tool=tool).pack()) for text, tool in LINK_ACTIONS
        ]
    return buttons


async def offer_actions(message: Message, limits: Limits) -> None:
    # The prompt replies to the user's message, so the button handlers read the link or file back from it.
    file = attachment(message)
    files = [file] if file is not None else []
    try:
        check_downloadable(files, limits)
    except ToolError as exc:
        await message.reply(html.escape(str(exc)))
        return
    buttons = _buttons(message, files)
    if not buttons:
        await message.reply(NOTHING_TO_DO)
        return
    await message.reply(PROMPT, reply_markup=InlineKeyboardMarkup(inline_keyboard=[buttons]))


async def offer_album_actions(message: Message, albums: Albums, limits: Limits) -> None:
    album = await albums.collect(message)
    if album is None:
        return
    first = album[0]
    files = [attachment(album_message) for album_message in album]
    if any(file is None or file.kind is not Kind.IMAGE for file in files):
        await first.reply(ALBUM_NOT_IMAGES)
        return
    try:
        check_downloadable(files, limits)
    except ToolError as exc:
        await first.reply(html.escape(str(exc)))
        return
    # The prompt can reply to only one of the album's messages, so the buttons carry a token for all its files.
    token = albums.keep(message.chat.id, files)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[_buttons(first, files, token)])
    await first.reply(f"What should I do with these {len(files)} images?", reply_markup=keyboard)


async def run_file_action(
    query: CallbackQuery, callback_data: FileAction, albums: Albums, limits: Limits, bot: Bot
) -> None:
    kind = TOOL_KINDS.get(callback_data.tool)
    if kind is None:
        await query.answer()
        return
    gone = ALBUM_GONE if callback_data.album else SOURCE_GONE
    prompt = query.message
    # Results reply to the user's message, so without it (an old prompt, or one Telegram no longer shows) nothing runs.
    source = prompt.reply_to_message if isinstance(prompt, Message) else None
    if source is None:
        await query.answer(gone, show_alert=True)
        return
    if callback_data.album:
        files = albums.get(source.chat.id, callback_data.album)
    else:
        file = attachment(source)
        files = [file] if file is not None else None
    if not files or any(file.kind is not kind for file in files):
        await query.answer(gone, show_alert=True)
        return
    await query.answer()
    match callback_data.tool:
        case "pdf":
            await send_pdf(bot, source, files, limits)
        case "jpg":
            await send_jpegs(bot, source, files[0], limits)
        case "doc-pdf":
            await send_document_pdf(bot, source, files[0], limits)
        case "docx":
            await send_docx(bot, source, files[0], limits)


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
