import collections.abc as cabc
import itertools
import pathlib
import typing as t

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.client.telegram import PRODUCTION, TelegramAPIServer
from aiogram.methods import (
    GetChat,
    GetFile,
    GetMe,
    SendAudio,
    SendDocument,
    SendMediaGroup,
    SendMessage,
    SendPhoto,
    SendVideo,
    TelegramMethod,
)
from aiogram.types import ChatFullInfo, File, FSInputFile, Message, User


class FakeTelegram(BaseSession):
    """Bot API stand-in: records every call and answers with realistic objects instead of hitting the network."""

    def __init__(self, api: TelegramAPIServer = PRODUCTION, local_files: pathlib.Path | None = None) -> None:
        super().__init__(api=api)
        # A local-mode server keeps the files it fetched here and answers GetFile with their path.
        self.local_files = local_files
        self.requests: list[TelegramMethod] = []
        # Each request's own timeout, if it set one, in the order of `requests`.
        self.timeouts: list[int | None] = []
        # Files sent from disk, read when sent: the bot removes them right after.
        self.uploads: list[tuple[str | None, bytes]] = []
        # A list of errors is consumed one per call, so a call can fail N times and then succeed.
        self.errors: dict[type[TelegramMethod], Exception | list[Exception]] = {}
        # Downloadable files by file id.
        self.files: dict[str, bytes] = {}
        self._message_ids = itertools.count(1000)

    def calls(self, method: type[TelegramMethod]) -> list[t.Any]:
        return [request for request in self.requests if isinstance(request, method)]

    def sent_texts(self, chat_id: int | None = None) -> list[str]:
        return [m.text for m in self.calls(SendMessage) if chat_id is None or m.chat_id == chat_id]

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> t.Any:
        self.requests.append(method)
        self.timeouts.append(timeout)
        error = self.errors.get(type(method))
        if isinstance(error, list):
            error = error.pop(0) if error else None
        if error is not None:
            raise error
        if isinstance(method, SendMessage):
            return Message.model_validate(
                {
                    "message_id": next(self._message_ids),
                    "date": 0,
                    "chat": {"id": method.chat_id, "type": "private"},
                    "text": method.text,
                }
            )
        if isinstance(method, SendPhoto):
            message_id = next(self._message_ids)
            return Message.model_validate(
                {
                    "message_id": message_id,
                    "date": 0,
                    "chat": {"id": method.chat_id, "type": "private"},
                    "caption": method.caption,
                    "photo": [{"file_id": f"photo-{message_id}", "file_unique_id": "p", "width": 330, "height": 330}],
                }
            )
        if isinstance(method, SendDocument):
            return self._document_message(method.chat_id, method.document.filename)
        if isinstance(method, SendAudio | SendVideo):
            media = method.audio if isinstance(method, SendAudio) else method.video
            assert isinstance(media, FSInputFile)
            self.uploads.append((media.filename, pathlib.Path(media.path).read_bytes()))
            return self._document_message(method.chat_id, media.filename)
        if isinstance(method, SendMediaGroup):
            return [self._document_message(method.chat_id, item.media.filename) for item in method.media]
        if isinstance(method, GetFile):
            data = self.files[method.file_id]
            file_path = method.file_id
            if self.local_files is not None:
                path = self.local_files / method.file_id
                path.write_bytes(data)
                file_path = str(path)
            return File(file_id=method.file_id, file_unique_id="u", file_size=len(data), file_path=file_path)
        if isinstance(method, GetMe):
            return User(id=42, is_bot=True, first_name="tgmate", username="tgmate_bot")
        if isinstance(method, GetChat):
            return ChatFullInfo.model_construct(id=method.chat_id, type="private")
        return True

    def _document_message(self, chat_id: int | str, filename: str | None) -> Message:
        message_id = next(self._message_ids)
        return Message.model_validate(
            {
                "message_id": message_id,
                "date": 0,
                "chat": {"id": chat_id, "type": "private"},
                "document": {"file_id": f"document-{message_id}", "file_unique_id": "d", "file_name": filename},
            }
        )

    async def stream_content(self, url: str, *args: t.Any, **kwargs: t.Any) -> cabc.AsyncGenerator[bytes]:
        # A local-mode server serves no downloads: the bot must read the file from disk.
        assert self.local_files is None, url
        # The file path GetFile returned (the file id) ends the download URL.
        yield self.files[url.rsplit("/", 1)[1]]

    async def close(self) -> None:
        return None
