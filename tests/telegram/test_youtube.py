import asyncio
import html
import pathlib
import threading
import typing as t

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, SendAudio, SendMessage, SendVideo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.telegram.conftest import seed_user
from tests.telegram.fake_api import FakeTelegram
from tests.telegram.updates import USER, callback_update, link_update, message_data, url_entity
from tgmate.storage.models import UserStatus
from tgmate.telegram.files import MB, Limits
from tgmate.telegram.tools import LinkAction
from tgmate.telegram.youtube import BUSY, SEND_TIMEOUT_SECONDS, WORKING, Downloads
from tgmate.tools.errors import ToolError
from tgmate.tools.youtube import Media, MediaFormat, YouTube

LINK = "https://youtu.be/jNQXAC9IVRw"
TITLE = "Me at the <zoo>"


@pytest.fixture(autouse=True)
async def approved(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    await seed_user(sessionmaker, USER, UserStatus.APPROVED)


class FakeYouTube:
    """Stands in for `YouTube.download` (tested with the tool): records each call and leaves the file it would."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, MediaFormat, int]] = []
        self.paths: list[pathlib.Path] = []
        self.error: ToolError | None = None
        # Set, a download waits for it, so a test can press another button meanwhile.
        self.release: threading.Event | None = None
        self.started = threading.Event()

    def download(self, url: str, media_format: MediaFormat, directory: pathlib.Path, *, max_bytes: int) -> Media:
        self.calls.append((url, media_format, max_bytes))
        self.started.set()
        if self.release is not None:
            self.release.wait(timeout=5)
        if self.error is not None:
            raise self.error
        path = directory / f"jNQXAC9IVRw.{media_format}"
        path.write_bytes(f"the {media_format}".encode())
        self.paths.append(path)
        if media_format is MediaFormat.MP3:
            return Media(path, TITLE, "jawed", 19)
        return Media(path, TITLE, "jawed", 19, 320, 240)


@pytest.fixture
def youtube(monkeypatch: pytest.MonkeyPatch) -> FakeYouTube:
    fake = FakeYouTube()
    monkeypatch.setattr(YouTube, "download", staticmethod(fake.download))
    return fake


def youtube_message(message_id: int = 100) -> dict[str, t.Any]:
    text = f"look {LINK}"
    return message_data(text, message_id=message_id, entities=[url_entity(text, LINK)])


async def press(dispatcher: Dispatcher, bot: Bot, tool: str, update_id: int = 1) -> None:
    await dispatcher.feed_update(
        bot, callback_update(LinkAction(tool=tool).pack(), replying_to=youtube_message(), update_id=update_id)
    )


# --- offering ---


@pytest.mark.parametrize(
    ("link", "buttons"),
    [
        (LINK, [("QR code", "qr"), ("MP3", "mp3"), ("MP4", "mp4")]),
        ("https://www.youtube.com/shorts/jNQXAC9IVRw", [("QR code", "qr"), ("MP3", "mp3"), ("MP4", "mp4")]),
        # Not a single video: a channel, and another site.
        ("https://www.youtube.com/@jawed", [("QR code", "qr")]),
        ("https://example.com/watch?v=jNQXAC9IVRw", [("QR code", "qr")]),
    ],
)
async def test_youtube_video_links_are_offered_mp3_and_mp4(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, link: str, buttons: list[tuple[str, str]]
) -> None:
    await dispatcher.feed_update(bot, link_update(f"look {link}", link))

    [prompt] = telegram.calls(SendMessage)
    offered = [(b.text, LinkAction.unpack(b.callback_data).tool) for b in prompt.reply_markup.inline_keyboard[0]]
    assert offered == buttons


# --- downloading and sending ---


async def test_mp3_is_sent_as_audio_replying_to_the_link(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, youtube: FakeYouTube
) -> None:
    await press(dispatcher, bot, "mp3")

    assert youtube.calls == [(LINK, MediaFormat.MP3, 50 * MB)]
    [audio] = telegram.calls(SendAudio)
    assert (audio.title, audio.performer, audio.duration) == (TITLE, "jawed", 19)
    assert audio.reply_parameters.message_id == 100
    assert telegram.uploads == [("Me at the zoo.mp3", b"the mp3")]
    assert telegram.timeouts[telegram.requests.index(audio)] == SEND_TIMEOUT_SECONDS


async def test_mp4_is_sent_as_a_streamable_video_with_its_frame_and_title(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, youtube: FakeYouTube
) -> None:
    await press(dispatcher, bot, "mp4")

    [video] = telegram.calls(SendVideo)
    assert (video.width, video.height, video.duration, video.supports_streaming) == (320, 240, 19, True)
    assert video.caption == "Me at the &lt;zoo&gt;"
    assert video.reply_parameters.message_id == 100
    assert telegram.uploads == [("Me at the zoo.mp4", b"the mp4")]
    assert telegram.timeouts[telegram.requests.index(video)] == SEND_TIMEOUT_SECONDS


async def test_the_bots_own_server_lets_it_send_larger_files(
    dispatcher: Dispatcher, bot: Bot, youtube: FakeYouTube
) -> None:
    dispatcher["limits"] = Limits(download=20 * MB, upload=2000 * MB)

    await press(dispatcher, bot, "mp4")

    assert youtube.calls == [(LINK, MediaFormat.MP4, 2000 * MB)]


async def test_a_status_shows_while_downloading_and_the_files_are_removed_after(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, youtube: FakeYouTube
) -> None:
    await press(dispatcher, bot, "mp3")

    [status] = telegram.calls(SendMessage)
    assert (status.text, status.reply_parameters.message_id) == (WORKING, 100)
    [deleted] = telegram.calls(DeleteMessage)
    assert deleted.chat_id == USER
    [path] = youtube.paths
    assert not path.parent.exists()


async def test_a_refusal_is_the_reply_and_nothing_is_sent(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, youtube: FakeYouTube
) -> None:
    youtube.error = ToolError("YouTube refused: Private <video>")

    await press(dispatcher, bot, "mp4")

    assert telegram.sent_texts(USER) == [WORKING, "YouTube refused: Private &lt;video&gt;"]
    assert telegram.calls(SendVideo) == []
    assert len(telegram.calls(DeleteMessage)) == 1


async def test_a_status_the_user_already_deleted_doesnt_matter(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, youtube: FakeYouTube
) -> None:
    telegram.errors[DeleteMessage] = TelegramBadRequest(DeleteMessage(chat_id=USER, message_id=1), "not found")

    await press(dispatcher, bot, "mp3")

    assert len(telegram.calls(SendAudio)) == 1
    assert telegram.sent_texts(USER) == [WORKING]


async def test_one_download_at_a_time_per_user(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, youtube: FakeYouTube
) -> None:
    youtube.release = threading.Event()
    first = asyncio.create_task(press(dispatcher, bot, "mp4"))
    await asyncio.to_thread(youtube.started.wait, 5)

    await press(dispatcher, bot, "mp3", update_id=2)
    youtube.release.set()
    await first

    assert html.escape(BUSY) in telegram.sent_texts(USER)
    assert [call[1] for call in youtube.calls] == [MediaFormat.MP4]
    assert len(telegram.calls(SendVideo)) == 1

    # Once it's done, the next one goes.
    await press(dispatcher, bot, "mp3", update_id=3)
    assert len(telegram.calls(SendAudio)) == 1


async def test_downloads_beyond_the_slots_wait_for_one() -> None:
    downloads = Downloads(slots=1)
    order: list[str] = []
    first_in = asyncio.Event()
    release = asyncio.Event()

    async def download(user_id: int, name: str) -> None:
        with downloads.for_user(user_id):
            async with downloads.slots:
                order.append(f"{name} starts")
                first_in.set()
                await release.wait()
                order.append(f"{name} ends")

    first = asyncio.create_task(download(1, "first"))
    await first_in.wait()
    second = asyncio.create_task(download(2, "second"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)

    assert order == ["first starts", "first ends", "second starts", "second ends"]
