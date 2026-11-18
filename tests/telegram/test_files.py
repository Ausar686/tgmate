import asyncio
import io
import typing as t
import zipfile

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, SendDocument, SendMediaGroup, SendMessage
from aiogram.types import InlineKeyboardMarkup
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.images import close_to, make_image, pdf_page_image, pdf_pages
from tests.telegram.conftest import seed_user
from tests.telegram.fake_api import FakeTelegram
from tests.telegram.updates import USER, callback_update, document, message_data, photo, update, url_entity
from tgmate.storage.models import UserStatus
from tgmate.telegram import files
from tgmate.telegram.files import Albums, FileAction
from tgmate.telegram.tools import ALBUM_GONE, ALBUM_NOT_IMAGES, NOTHING_TO_DO, PROMPT, SOURCE_GONE, LinkAction
from tgmate.tools.pdf import PDF

RED, BLUE, GREEN = (255, 0, 0), (0, 0, 255), (0, 128, 0)
PDF_TYPE = "application/pdf"


@pytest.fixture(autouse=True)
async def approved(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    await seed_user(sessionmaker, USER, UserStatus.APPROVED)


def a_pdf(pages: int) -> bytes:
    return PDF.from_images([make_image(color="red")] * pages)


def buttons(markup: InlineKeyboardMarkup) -> list[tuple[str, str]]:
    """Each button's text and packed callback data, minus any album token."""
    pressed = []
    for button in markup.inline_keyboard[0]:
        data = button.callback_data
        if data.startswith("file:"):
            data = FileAction.unpack(data).model_copy(update={"album": ""}).pack()
        pressed.append((button.text, data))
    return pressed


def photo_message(telegram: FakeTelegram, data: bytes, file_id: str = "img", **kwargs: t.Any) -> dict[str, t.Any]:
    telegram.files[file_id] = data
    return message_data(photo=photo(file_id, len(data)), **kwargs)


def document_message(
    telegram: FakeTelegram, data: bytes, mime_type: str | None, file_name: str | None = None, **kwargs: t.Any
) -> dict[str, t.Any]:
    telegram.files["doc"] = data
    return message_data(document=document("doc", len(data), mime_type, file_name), **kwargs)


async def press(dispatcher: Dispatcher, bot: Bot, tool: str, source: dict[str, t.Any] | None) -> None:
    await dispatcher.feed_update(bot, callback_update(FileAction(tool=tool).pack(), replying_to=source))


def sent_document(telegram: FakeTelegram) -> tuple[str, bytes]:
    [sent] = telegram.calls(SendDocument)
    assert sent.reply_parameters.message_id == 100
    return sent.document.filename, sent.document.data


# --- offering ---


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("photo", [("PDF", "file:pdf:")]), ("image", [("PDF", "file:pdf:")]), ("pdf", [("JPG images", "file:jpg:")])],
)
async def test_files_get_a_reply_offering_their_tools(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, kind: str, expected: list[tuple[str, str]]
) -> None:
    message = {
        "photo": lambda: photo_message(telegram, make_image("JPEG")),
        "image": lambda: document_message(telegram, make_image(), "image/png", "scan.png"),
        "pdf": lambda: document_message(telegram, a_pdf(1), PDF_TYPE, "report.pdf"),
    }[kind]()

    await dispatcher.feed_update(bot, update(**message))

    [prompt] = telegram.calls(SendMessage)
    assert (prompt.text, prompt.reply_parameters.message_id) == (PROMPT, 100)
    assert buttons(prompt.reply_markup) == expected


async def test_photo_with_a_link_offers_both_its_tools(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    caption = "see https://example.com"
    telegram.files["img"] = make_image("JPEG")
    entities = [url_entity(caption, "https://example.com")]

    await dispatcher.feed_update(
        bot, update(photo=photo("img", 500), caption=caption, caption_entities=entities)
    )

    [prompt] = telegram.calls(SendMessage)
    assert buttons(prompt.reply_markup) == [("PDF", "file:pdf:"), ("QR code", LinkAction(tool="qr").pack())]


@pytest.mark.parametrize("mime_type", ["application/zip", None])
async def test_other_documents_get_pointed_to_help(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, mime_type: str | None
) -> None:
    await dispatcher.feed_update(bot, update(document=document("doc", 10, mime_type, "a.zip")))

    assert telegram.sent_texts(USER) == [NOTHING_TO_DO]


async def test_file_over_the_download_limit_is_refused_before_offering(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    size = files.DOWNLOAD_LIMIT + files.MB // 2

    await dispatcher.feed_update(bot, update(document=document("doc", size, PDF_TYPE, "big.pdf")))

    assert telegram.sent_texts(USER) == ["The file is 20.5 MB; I can only take files up to 20 MB."]


# --- images → PDF ---


async def test_pdf_button_replies_with_a_pdf_of_the_photo(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await press(dispatcher, bot, "pdf", photo_message(telegram, make_image("JPEG", color="blue")))

    filename, pdf = sent_document(telegram)
    assert filename == "images.pdf"
    assert len(pdf_pages(pdf)) == 1
    assert close_to(pdf_page_image(pdf).getpixel((297, 420)), BLUE)
    [answer] = telegram.calls(AnswerCallbackQuery)
    assert answer.text is None


async def test_pdf_of_an_image_document_takes_its_name(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await press(dispatcher, bot, "pdf", document_message(telegram, make_image(), "image/png", "scan.png"))

    assert sent_document(telegram)[0] == "scan.pdf"


async def test_image_the_tool_refuses_gets_its_reason(dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram) -> None:
    await press(dispatcher, bot, "pdf", document_message(telegram, b"not really", "image/png", "fake.png"))

    assert telegram.sent_texts(USER) == ["File 1 isn&#x27;t an image I can read."]
    assert telegram.calls(SendDocument) == []


async def test_result_over_the_upload_limit_is_refused(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(files, "UPLOAD_LIMIT", 100)

    await press(dispatcher, bot, "pdf", photo_message(telegram, make_image("JPEG")))

    [reply] = telegram.sent_texts(USER)
    assert reply.startswith("The result is 0.0 MB; Telegram only lets me send up to 0 MB.")
    assert telegram.calls(SendDocument) == []


# --- PDF → JPEG ---


def jpeg_colors(images: list[bytes]) -> list[tuple[int, ...]]:
    colors = []
    for data in images:
        with Image.open(io.BytesIO(data)) as image:
            assert image.format == "JPEG"
            colors.append(image.getpixel((image.width // 2, image.height // 2)))
    return colors


async def test_one_page_pdf_comes_back_as_one_jpeg(dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram) -> None:
    await press(dispatcher, bot, "jpg", document_message(telegram, a_pdf(1), PDF_TYPE, "report.pdf"))

    filename, jpeg = sent_document(telegram)
    assert filename == "report-1.jpg"
    assert close_to(jpeg_colors([jpeg])[0], RED)


async def test_pages_come_back_as_an_album_of_jpeg_files_in_order(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    pdf = PDF.from_images([make_image(color="red"), make_image(color="blue"), make_image(color="green")])

    await press(dispatcher, bot, "jpg", document_message(telegram, pdf, PDF_TYPE, "report.pdf"))

    [album] = telegram.calls(SendMediaGroup)
    assert album.reply_parameters.message_id == 100
    assert [item.type for item in album.media] == ["document"] * 3
    assert [item.media.filename for item in album.media] == ["report-1.jpg", "report-2.jpg", "report-3.jpg"]
    colors = jpeg_colors([item.media.data for item in album.media])
    assert [close_to(c, e) for c, e in zip(colors, [RED, BLUE, GREEN], strict=True)] == [True] * 3


async def test_more_pages_than_an_album_holds_come_back_as_a_zip(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await press(dispatcher, bot, "jpg", document_message(telegram, a_pdf(11), PDF_TYPE, "report.pdf"))

    filename, data = sent_document(telegram)
    assert filename == "report.zip"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert names == [f"report-{number:02d}.jpg" for number in range(1, 12)]
        assert len(jpeg_colors([archive.read(name) for name in names])) == 11
    assert telegram.calls(SendMediaGroup) == []


@pytest.mark.parametrize("file_name", ["..\\..\\evil.pdf", "../../evil.pdf", "C:evil.pdf"])
async def test_crafted_file_names_cannot_put_folders_into_the_zip(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, file_name: str
) -> None:
    await press(dispatcher, bot, "jpg", document_message(telegram, a_pdf(11), PDF_TYPE, file_name))

    filename, data = sent_document(telegram)
    assert filename == "evil.zip"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist()[0] == "evil-01.jpg"


async def test_pdf_without_a_name_is_called_document(dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram) -> None:
    await press(dispatcher, bot, "jpg", document_message(telegram, a_pdf(1), PDF_TYPE))

    assert sent_document(telegram)[0] == "document-1.jpg"


async def test_pdf_the_tool_refuses_gets_its_reason(dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram) -> None:
    await press(dispatcher, bot, "jpg", document_message(telegram, b"just text", PDF_TYPE, "fake.pdf"))

    assert telegram.sent_texts(USER) == ["This isn&#x27;t a PDF I can read."]


async def test_file_grown_past_the_limit_is_refused_when_pressed(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = document_message(telegram, a_pdf(1), PDF_TYPE, "report.pdf")
    monkeypatch.setattr(files, "DOWNLOAD_LIMIT", 10)

    await press(dispatcher, bot, "jpg", source)

    [reply] = telegram.sent_texts(USER)
    assert reply.startswith("The file is ")
    assert telegram.calls(SendDocument) == []


# --- buttons whose file is gone or doesn't fit ---


async def test_button_whose_file_message_is_gone_asks_to_send_it_again(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await press(dispatcher, bot, "pdf", None)

    [answer] = telegram.calls(AnswerCallbackQuery)
    assert (answer.text, answer.show_alert) == (SOURCE_GONE, True)


async def test_button_for_the_wrong_kind_of_file_does_nothing_but_alert(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await press(dispatcher, bot, "jpg", photo_message(telegram, make_image("JPEG")))

    [answer] = telegram.calls(AnswerCallbackQuery)
    assert answer.text == SOURCE_GONE
    assert telegram.calls(SendDocument) == []


async def test_button_for_a_file_tool_that_no_longer_exists_does_nothing(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram
) -> None:
    await press(dispatcher, bot, "retired", photo_message(telegram, make_image("JPEG")))

    [answer] = telegram.calls(AnswerCallbackQuery)
    assert answer.text is None
    assert telegram.calls(SendDocument) == telegram.calls(SendMessage) == []


# --- albums ---


@pytest.fixture
def albums(dispatcher: Dispatcher) -> Albums:
    # Long enough for every message of an album fed at once to arrive, short enough to keep tests fast.
    dispatcher["albums"] = Albums(wait=0.2)
    return dispatcher["albums"]


async def feed_album(dispatcher: Dispatcher, bot: Bot, messages: list[dict[str, t.Any]]) -> None:
    updates = [update(update_id=index, **message) for index, message in enumerate(messages, 1)]
    # Telegram delivers an album as separate updates, which the bot handles concurrently.
    await asyncio.gather(*(dispatcher.feed_update(bot, album_update) for album_update in updates))


def album_photos(telegram: FakeTelegram, colors: list[str], group: str = "g1") -> list[dict[str, t.Any]]:
    # Listed out of order: the album keeps the order the messages were sent in.
    return [
        photo_message(
            telegram, make_image("JPEG", color=color), f"{group}-{index}", message_id=200 + index, media_group_id=group
        )
        for index, color in reversed(list(enumerate(colors)))
    ]


async def test_album_gets_one_prompt_replying_to_its_first_message(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, albums: Albums
) -> None:
    await feed_album(dispatcher, bot, album_photos(telegram, ["red", "blue", "green"]))

    [prompt] = telegram.calls(SendMessage)
    assert prompt.text == "What should I do with these 3 images?"
    assert prompt.reply_parameters.message_id == 200
    assert buttons(prompt.reply_markup) == [("PDF", "file:pdf:")]


async def test_album_pdf_button_makes_one_pdf_of_all_its_images_in_order(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, albums: Albums
) -> None:
    messages = album_photos(telegram, ["red", "blue", "green"])
    await feed_album(dispatcher, bot, messages)
    [prompt] = telegram.calls(SendMessage)
    [[button]] = prompt.reply_markup.inline_keyboard
    first = next(message for message in messages if message["message_id"] == 200)

    await dispatcher.feed_update(bot, callback_update(button.callback_data, replying_to=first))

    [sent] = telegram.calls(SendDocument)
    assert sent.reply_parameters.message_id == 200
    pdf = sent.document.data
    colors = [pdf_page_image(pdf, index).getpixel((297, 420)) for index in range(3)]
    assert [close_to(c, e) for c, e in zip(colors, [RED, BLUE, GREEN], strict=True)] == [True] * 3


async def test_album_caption_link_is_offered_too(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, albums: Albums
) -> None:
    messages = album_photos(telegram, ["red", "blue"])
    first = next(message for message in messages if message["message_id"] == 200)
    first.update(caption="https://example.com", caption_entities=[url_entity("https://example.com", "https://example.com")])

    await feed_album(dispatcher, bot, messages)

    [prompt] = telegram.calls(SendMessage)
    assert buttons(prompt.reply_markup) == [("PDF", "file:pdf:"), ("QR code", LinkAction(tool="qr").pack())]


async def test_album_with_other_files_is_refused(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, albums: Albums
) -> None:
    messages = [
        message_data(document=document("a", 10, PDF_TYPE, "a.pdf"), message_id=300, media_group_id="g2"),
        message_data(document=document("b", 10, "image/png", "b.png"), message_id=301, media_group_id="g2"),
    ]

    await feed_album(dispatcher, bot, messages)

    assert telegram.sent_texts(USER) == [ALBUM_NOT_IMAGES]


async def test_album_with_a_file_over_the_download_limit_names_it(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, albums: Albums
) -> None:
    messages = [
        message_data(photo=photo("a", 10), message_id=300, media_group_id="g3"),
        message_data(photo=photo("b", files.DOWNLOAD_LIMIT + 1), message_id=301, media_group_id="g3"),
    ]

    await feed_album(dispatcher, bot, messages)

    [reply] = telegram.sent_texts(USER)
    assert reply.startswith("File 2 is 20.0 MB;")


async def test_albums_from_different_chats_or_groups_stay_apart(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, albums: Albums
) -> None:
    messages = album_photos(telegram, ["red", "blue"], "g4") + album_photos(telegram, ["green", "red", "blue"], "g5")

    await feed_album(dispatcher, bot, messages)

    assert sorted(prompt.text for prompt in telegram.calls(SendMessage)) == [
        "What should I do with these 2 images?",
        "What should I do with these 3 images?",
    ]


@pytest.mark.parametrize("token", ["unknown", "expired"])
async def test_album_button_the_bot_no_longer_remembers_asks_to_send_it_again(
    dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram, albums: Albums, token: str
) -> None:
    if token == "expired":
        albums.ttl = 0
        token = albums.keep(USER, [files.Attachment(files.Kind.IMAGE, "img", 10, None)])
    first = photo_message(telegram, make_image("JPEG"), message_id=200, media_group_id="g6")

    await dispatcher.feed_update(bot, callback_update(FileAction(tool="pdf", album=token).pack(), replying_to=first))

    [answer] = telegram.calls(AnswerCallbackQuery)
    assert (answer.text, answer.show_alert) == (ALBUM_GONE, True)


async def test_album_button_only_works_in_the_chat_it_was_offered_in(albums: Albums) -> None:
    token = albums.keep(USER, [files.Attachment(files.Kind.IMAGE, "img", 10, None)])

    assert albums.get(USER + 1, token) is None
    assert albums.get(USER, token) is not None
