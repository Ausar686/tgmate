"""Builders for the Telegram updates the bot receives."""

import typing as t

from aiogram.types import Update

from tests.conftest import OWNER

USER = 5
BOT = {"id": 42, "is_bot": True, "first_name": "tgmate"}


def utf16_length(text: str) -> int:
    """Telegram measures entity offsets and lengths in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def url_entity(text: str, link: str) -> dict[str, t.Any]:
    """A `url` entity covering `link` inside `text`, as Telegram's clients mark links up."""
    start = text.index(link)
    return {"type": "url", "offset": utf16_length(text[:start]), "length": utf16_length(link)}


def message_data(
    text: str | None = None,
    *,
    user_id: int = USER,
    chat_id: int | None = None,
    chat_type: str = "private",
    message_id: int = 100,
    entities: list[dict[str, t.Any]] | None = None,
    full_name: tuple[str, str | None] = ("Alice", None),
    username: str | None = "alice",
    **extra: t.Any,
) -> dict[str, t.Any]:
    first_name, last_name = full_name
    sender = {"id": user_id, "is_bot": False, "first_name": first_name}
    if last_name:
        sender["last_name"] = last_name
    if username:
        sender["username"] = username
    data: dict[str, t.Any] = {
        "message_id": message_id,
        "date": 1_760_000_000,
        "chat": {"id": user_id if chat_id is None else chat_id, "type": chat_type},
        "from": sender,
        **extra,
    }
    if text is not None:
        data["text"] = text
    if entities:
        data["entities"] = entities
    return data


def update(text: str | None = None, *, update_id: int = 1, **kwargs: t.Any) -> Update:
    return Update.model_validate({"update_id": update_id, "message": message_data(text, **kwargs)})


def photo(file_id: str, size: int, width: int = 40, height: int = 20) -> list[dict[str, t.Any]]:
    """A photo's sizes as Telegram sends them, smallest first; only the largest has `file_id`."""
    thumbnail = {"file_id": f"{file_id}-thumb", "file_unique_id": "t", "width": 4, "height": 2, "file_size": 100}
    largest = {"file_id": file_id, "file_unique_id": "p", "width": width, "height": height, "file_size": size}
    return [thumbnail, largest]


def document(file_id: str, size: int, mime_type: str | None, file_name: str | None = None) -> dict[str, t.Any]:
    data: dict[str, t.Any] = {"file_id": file_id, "file_unique_id": "d", "file_size": size}
    if mime_type is not None:
        data["mime_type"] = mime_type
    if file_name is not None:
        data["file_name"] = file_name
    return data


def link_update(text: str, link: str, **kwargs: t.Any) -> Update:
    """A message whose `link` Telegram marked up as a URL."""
    return update(text, entities=[url_entity(text, link)], **kwargs)


def command_update(command: str, *, user_id: int = USER, **kwargs: t.Any) -> Update:
    name = command.split()[0]
    entities = [{"type": "bot_command", "offset": 0, "length": utf16_length(name)}]
    return update(command, user_id=user_id, entities=entities, **kwargs)


def callback_update(
    data: str, *, user_id: int = USER, replying_to: dict[str, t.Any] | None = None, update_id: int = 1
) -> Update:
    """A button press on a bot message, which replies to `replying_to` (a `message_data` dict) when given."""
    prompt: dict[str, t.Any] = {
        "message_id": 77,
        "date": 0,
        "chat": {"id": user_id, "type": "private"},
        "from": BOT,
        "text": "prompt",
    }
    if replying_to is not None:
        prompt["reply_to_message"] = replying_to
    return Update.model_validate(
        {
            "update_id": update_id,
            "callback_query": {
                "id": "cb1",
                "from": {"id": user_id, "is_bot": False, "first_name": "Owner" if user_id == OWNER else "Alice"},
                "chat_instance": "ci",
                "data": data,
                "message": prompt,
            },
        }
    )


def member_update(*, chat_type: str = "group", old: str = "left", new: str = "member", chat_id: int = -100) -> Update:
    chat: dict[str, t.Any] = {"id": chat_id, "type": chat_type}
    if chat_type != "private":
        chat["title"] = "some group"
    return Update.model_validate(
        {
            "update_id": 1,
            "my_chat_member": {
                "chat": chat,
                "from": {"id": USER, "is_bot": False, "first_name": "Alice"},
                "date": 0,
                "old_chat_member": {"status": old, "user": BOT},
                "new_chat_member": {"status": new, "user": BOT},
            },
        }
    )
