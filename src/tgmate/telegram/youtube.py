"""YouTube links: download the video as MP3 or MP4 and reply with it as audio or video."""

import asyncio
import collections.abc as cabc
import contextlib
import html
import logging
import os
import pathlib
import shutil
import stat
import tempfile

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import AiogramError, TelegramAPIError
from aiogram.types import FSInputFile, Message, ReplyParameters
from aiogram.utils.chat_action import ChatActionSender

from tgmate.telegram.files import Limits, caption
from tgmate.tools.errors import ToolError
from tgmate.tools.youtube import Media, MediaFormat, YouTube

log = logging.getLogger(__name__)

# yt-dlp, Deno and ffmpeg take a few hundred MB per download; more downloads than this wait for a slot.
DOWNLOAD_SLOTS = 2
# A local Bot API server answers only once it has passed the whole file on to Telegram.
SEND_TIMEOUT_SECONDS = 30 * 60
WORKING = "Downloading… long videos can take a few minutes."
BUSY = "I'm still downloading your previous video; send this one again when it's done."
SEND_FAILED = "Telegram didn't take the file; try again later."
UNAVAILABLE = "I can't download anything right now; try again later."
# Each download's directory goes here, and only the bot uses it, so whatever is here at startup was left by a download
# that a shutdown interrupted: the sandbox's thread can't be cancelled, and outlives the handler's cleanup.
JOBS_DIR = pathlib.Path(tempfile.gettempdir()) / "tgmate-youtube"


def clear_jobs() -> None:
    """Remove what interrupted downloads left; run at startup, before any download."""
    shutil.rmtree(JOBS_DIR, ignore_errors=True)
    jobs_dir()
    return None


def jobs_dir() -> pathlib.Path:
    """`JOBS_DIR`, made again if something removed it (such as a cleaner of old temporary files).

    Refused with `PermissionError` unless it's a directory of the bot's own that only it can use: in a shared temporary
    directory, another user could have put theirs, or a symlink, there first.
    """
    with contextlib.suppress(FileExistsError):
        JOBS_DIR.mkdir(mode=0o700)
    info = JOBS_DIR.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError(f"{JOBS_DIR} isn't a directory only the bot can use")
    return JOBS_DIR


def is_youtube_video(link: str) -> bool:
    try:
        YouTube.video_id(link)
    except ToolError:
        return False
    return True


class Downloads:
    """Bounds YouTube downloads: one at a time per user, and `slots` at once in all."""

    def __init__(self, slots: int = DOWNLOAD_SLOTS) -> None:
        self.slots = asyncio.Semaphore(slots)
        self._users: set[int] = set()

    @contextlib.contextmanager
    def for_user(self, user_id: int) -> cabc.Iterator[None]:
        """Mark the user's download as going; refuses with `ToolError` while another one of theirs is."""
        if user_id in self._users:
            raise ToolError(BUSY)
        self._users.add(user_id)
        try:
            yield
        finally:
            self._users.discard(user_id)


async def send_media(
    bot: Bot, source: Message, link: str, media_format: MediaFormat, limits: Limits, downloads: Downloads
) -> None:
    """Reply to `source` with the video at `link` as MP3 audio or MP4 video, or with why it can't be downloaded."""
    try:
        # Private chats only, so the chat is the user.
        with downloads.for_user(source.chat.id):
            status = await _reply(bot, source, WORKING)
            try:
                await _download_and_send(bot, source, link, media_format, limits, downloads)
            finally:
                # Only tidiness: the user may have deleted the chat or the message already.
                with contextlib.suppress(TelegramAPIError):
                    await bot.delete_message(source.chat.id, status.message_id)
    except ToolError as exc:
        await _reply(bot, source, html.escape(str(exc)))
    return None


async def _reply(bot: Bot, source: Message, text: str) -> Message:
    # Downloads take minutes, so the user may have deleted their message by now.
    reply = ReplyParameters(message_id=source.message_id, allow_sending_without_reply=True)
    return await bot.send_message(source.chat.id, text, reply_parameters=reply)


async def _download_and_send(
    bot: Bot, source: Message, link: str, media_format: MediaFormat, limits: Limits, downloads: Downloads
) -> None:
    action = ChatAction.UPLOAD_VIDEO if media_format is MediaFormat.MP4 else ChatAction.UPLOAD_DOCUMENT
    async with downloads.slots, ChatActionSender(bot=bot, chat_id=source.chat.id, action=action):
        try:
            jobs = jobs_dir()
        except OSError as exc:
            log.error("can't download into %s: %s", JOBS_DIR, exc)
            raise ToolError(UNAVAILABLE) from exc
        with tempfile.TemporaryDirectory(dir=jobs) as directory:
            media = await asyncio.to_thread(
                YouTube.download, link, media_format, pathlib.Path(directory), max_bytes=limits.upload
            )
            try:
                await _send(bot, source, media, media_format)
            except AiogramError as exc:
                # Such as the upload timing out, the file being over what Telegram takes after all, or an answer that
                # isn't the Bot API's JSON.
                log.warning("could not send %s to chat %d: %s", media.file_name, source.chat.id, exc)
                raise ToolError(SEND_FAILED) from exc
    return None


async def _send(bot: Bot, source: Message, media: Media, media_format: MediaFormat) -> None:
    file = FSInputFile(media.path, media.file_name)
    reply = ReplyParameters(message_id=source.message_id, allow_sending_without_reply=True)
    if media_format is MediaFormat.MP3:
        await bot.send_audio(
            source.chat.id,
            file,
            title=media.title,
            performer=media.uploader,
            duration=media.duration,
            reply_parameters=reply,
            request_timeout=SEND_TIMEOUT_SECONDS,
        )
    else:
        await bot.send_video(
            source.chat.id,
            file,
            duration=media.duration,
            width=media.width,
            height=media.height,
            caption=caption(media.title),
            supports_streaming=True,
            reply_parameters=reply,
            request_timeout=SEND_TIMEOUT_SECONDS,
        )
    return None
