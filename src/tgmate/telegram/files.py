"""Files users send: which tools fit them, collecting albums, and replying with the converted files."""

import asyncio
import collections.abc as cabc
import dataclasses
import enum
import html
import io
import pathlib
import secrets
import time
import typing as t
import zipfile

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, InputMediaDocument, Message
from aiogram.utils.chat_action import ChatActionSender

from tgmate.config import Settings
from tgmate.tools.errors import ToolError
from tgmate.tools.office import Office
from tgmate.tools.pdf import PDF

MB = 1024 * 1024
# Telegram's most files in one album; more pages than this are sent as a ZIP.
ALBUM_LIMIT = 10
# Telegram's limit for a caption, counted after HTML parsing (`&amp;` is one character), so the plain text is cut
# before escaping, which also keeps the cut out of escape sequences.
CAPTION_LIMIT = 1024
# Telegram delivers an album as one message per file; it's complete once none has arrived for this long.
ALBUM_WAIT_SECONDS = 1.0
# How long an album's buttons keep working. Albums are kept in memory, so a restart forgets them too.
ALBUM_TTL_SECONDS = 24 * 60 * 60


class Kind(enum.StrEnum):
    IMAGE = "image"
    PDF = "pdf"
    DOCUMENT = "document"


# The types Telegram clients give Word, OpenDocument text and RTF files; the tool checks the content itself.
DOCUMENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.oasis.opendocument.text",
    "application/rtf",
    "text/rtf",
}


@dataclasses.dataclass(frozen=True)
class Limits:
    """The largest file, in bytes, the bot takes from users and the largest it sends them."""

    download: int
    upload: int

    @classmethod
    def of(cls, settings: Settings) -> t.Self:
        return cls(settings.download_limit_mb * MB, settings.upload_limit_mb * MB)


@dataclasses.dataclass(frozen=True)
class Attachment:
    kind: Kind
    file_id: str
    size: int | None
    # Photos have no file name.
    name: str | None


class FileAction(CallbackData, prefix="file"):
    tool: str
    # Set for an album, whose files `Albums` keeps; a single file is read back from the message the prompt replies to.
    album: str = ""


# (button text, tool) for every action that takes a file of that kind; a new file tool adds its row here.
FILE_ACTIONS = {
    Kind.IMAGE: [("PDF", "pdf")],
    Kind.PDF: [("JPG images", "jpg"), ("DOCX", "docx")],
    Kind.DOCUMENT: [("PDF", "doc-pdf")],
}
TOOL_KINDS = {tool: kind for kind, actions in FILE_ACTIONS.items() for _, tool in actions}


def attachment(message: Message) -> Attachment | None:
    """The message's image (a photo at its largest size, or an image document), PDF or office document, if any."""
    if message.photo:
        largest = message.photo[-1]
        return Attachment(Kind.IMAGE, largest.file_id, largest.file_size, None)
    document = message.document
    if document is None or document.mime_type is None:
        return None
    if document.mime_type == "application/pdf":
        kind = Kind.PDF
    elif document.mime_type.startswith("image/"):
        kind = Kind.IMAGE
    elif document.mime_type in DOCUMENT_TYPES:
        kind = Kind.DOCUMENT
    else:
        return None
    return Attachment(kind, document.file_id, document.file_size, document.file_name)


def check_downloadable(files: list[Attachment], limits: Limits) -> None:
    """Refuse files over the download limit, before offering or trying to download them."""
    for number, file in enumerate(files, 1):
        if file.size is not None and file.size > limits.download:
            which = "The file" if len(files) == 1 else f"File {number}"
            limit = f"I can only take files up to {limits.download // MB} MB"
            raise ToolError(f"{which} is {file.size / MB:.1f} MB; {limit}.")


def check_sendable(size: int, limits: Limits) -> None:
    if size > limits.upload:
        raise ToolError(f"The result is {size / MB:.1f} MB; Telegram only lets me send up to {limits.upload // MB} MB.")


def caption(text: str) -> str:
    """`text` cut to Telegram's caption limit and escaped for HTML."""
    return html.escape(text if len(text) <= CAPTION_LIMIT else text[: CAPTION_LIMIT - 1] + "…")


def stem(name: str | None, default: str) -> str:
    """The file name without folders or extension, so a crafted name can't put a path into a ZIP entry."""
    # Windows paths split on both `/` and `\`.
    return pathlib.PureWindowsPath(name or "").stem or default


class Albums:
    """Collects an album's messages, which arrive one update each, then keeps its files for the album's buttons."""

    def __init__(self, wait: float = ALBUM_WAIT_SECONDS, ttl: float = ALBUM_TTL_SECONDS) -> None:
        self.wait = wait
        self.ttl = ttl
        self._arriving: dict[tuple[int, str | None], list[Message]] = {}
        self._kept: dict[tuple[int, str], tuple[float, list[Attachment]]] = {}

    async def collect(self, message: Message) -> list[Message] | None:
        """The whole album in order, to whichever of its messages came first; None to the rest."""
        key = (message.chat.id, message.media_group_id)
        arriving = self._arriving.get(key)
        if arriving is not None:
            arriving.append(message)
            return None
        arriving = self._arriving[key] = [message]
        seen = 0
        while seen != len(arriving):
            seen = len(arriving)
            await asyncio.sleep(self.wait)
        del self._arriving[key]
        return sorted(arriving, key=lambda album_message: album_message.message_id)

    def keep(self, chat_id: int, files: list[Attachment]) -> str:
        """Store the album's files and return the token its buttons carry."""
        now = time.monotonic()
        self._kept = {key: kept for key, kept in self._kept.items() if kept[0] > now}
        token = secrets.token_urlsafe(9)
        self._kept[(chat_id, token)] = (now + self.ttl, files)
        return token

    def get(self, chat_id: int, token: str) -> list[Attachment] | None:
        expires, files = self._kept.get((chat_id, token), (0.0, None))
        return files if expires > time.monotonic() else None


async def download(bot: Bot, file: Attachment) -> bytes:
    buffer = await bot.download(file.file_id)
    return buffer.read()


async def send_pdf(bot: Bot, source: Message, images: list[Attachment], limits: Limits) -> None:
    """Reply to `source` with one PDF of the images, or with why it can't be made."""
    async with ChatActionSender.upload_document(source.chat.id, bot):
        try:
            check_downloadable(images, limits)
            pdf = await asyncio.to_thread(PDF.from_images, [await download(bot, image) for image in images])
            check_sendable(len(pdf), limits)
        except ToolError as exc:
            await source.reply(html.escape(str(exc)))
            return
        await source.reply_document(BufferedInputFile(pdf, f"{stem(images[0].name, 'images')}.pdf"))


async def send_document_pdf(bot: Bot, source: Message, document: Attachment, limits: Limits) -> None:
    """Reply to `source` with the office document as a PDF, or with why it can't be converted."""
    await _send_converted(bot, source, document, limits, Office.to_pdf, "pdf")


async def send_docx(bot: Bot, source: Message, pdf: Attachment, limits: Limits) -> None:
    """Reply to `source` with the PDF as an editable Word document, or with why it can't be converted."""
    await _send_converted(bot, source, pdf, limits, PDF.to_docx, "docx")


async def _send_converted(
    bot: Bot,
    source: Message,
    file: Attachment,
    limits: Limits,
    convert: cabc.Callable[[bytes], bytes],
    extension: str,
) -> None:
    """Reply with `convert` of the file, named after it with `extension`, or with the tool's refusal."""
    async with ChatActionSender.upload_document(source.chat.id, bot):
        try:
            check_downloadable([file], limits)
            result = await asyncio.to_thread(convert, await download(bot, file))
            check_sendable(len(result), limits)
        except ToolError as exc:
            await source.reply(html.escape(str(exc)))
            return
        await source.reply_document(BufferedInputFile(result, f"{stem(file.name, 'document')}.{extension}"))


async def send_jpegs(bot: Bot, source: Message, pdf: Attachment, limits: Limits) -> None:
    """Reply to `source` with the PDF's pages as JPEG files (an album, or a ZIP of more), or with why not."""
    async with ChatActionSender.upload_document(source.chat.id, bot):
        try:
            check_downloadable([pdf], limits)
            pages = await asyncio.to_thread(PDF.to_jpegs, await download(bot, pdf))
            name = stem(pdf.name, "document")
            files = dict(zip(PDF.jpeg_names(name, len(pages)), pages, strict=True))
            archive = await asyncio.to_thread(zip_files, files) if len(files) > ALBUM_LIMIT else None
            # Telegram's limit is per file: the ZIP, or each page sent on its own or in an album.
            check_sendable(len(archive) if archive is not None else max(map(len, pages)), limits)
        except ToolError as exc:
            await source.reply(html.escape(str(exc)))
            return
        if archive is not None:
            await source.reply_document(BufferedInputFile(archive, f"{name}.zip"))
            return
        documents = [BufferedInputFile(data, filename) for filename, data in files.items()]
        if len(documents) == 1:
            await source.reply_document(documents[0])
        else:
            await source.reply_media_group([InputMediaDocument(media=document) for document in documents])


def zip_files(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    # Stored, not deflated: JPEGs are already compressed.
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
        for filename, data in files.items():
            archive.writestr(filename, data)
    return output.getvalue()
