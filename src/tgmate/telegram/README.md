# telegram

The Telegram bot (aiogram 3): who may use it ([access.py](access.py)), what
it does for them ([tools.py](tools.py), with files in [files.py](files.py)),
startup ([setup.py](setup.py)) and wiring ([app.py](app.py)). Run with `python -m tgmate.telegram`; settings
come from [config.py](../config.py).

The bot works in private chats only. Added to a group or channel, it leaves
right away; messages from groups are ignored.

## Access ([access.py](access.py))
The owner (`OWNER_USER_ID`) can always use the bot. Everyone else needs the
owner's approval; `require_access` guards every tool handler and button.

| Who writes | What happens |
| --- | --- |
| Someone new | Stored as `pending`; the owner gets a DM with Approve / Reject; the user hears that access was requested. |
| `pending` user | The owner is asked again at most once a day (`APPROVAL_REQUEST_INTERVAL_SECONDS`); otherwise the user hears they're waiting, at most once an hour (`ACCESS_NOTICE_INTERVAL_SECONDS`). |
| `rejected` user | "This bot is private.", at most once an hour; the owner isn't asked again. Only the owner can approve them, from `/users`. |
| `revoked` user | Back to `pending`, and the owner is asked again. |
| `approved` user | The message reaches the tools. |

- Every message refreshes the user's stored name and username.
- Tool buttons pressed by someone who isn't approved only get an alert
  (waiting, private, or "send me a message" for unknown and revoked users).
  Nothing is stored or changed and the owner isn't asked; only a message does
  that.
- Owner actions: Approve (the user gets a DM saying so), Reject, Revoke
  (neither tells the user). Pressed in the request DM or in `/users`, which
  lists pending, approved and rejected users with the matching buttons.
  Revoked users aren't listed: they ask again by writing.
- The owner must `/start` the bot once so it can DM them; startup logs a
  warning while it can't.

## Tools ([tools.py](tools.py))
Send something, then pick what to do with it:

| Message | Buttons |
| --- | --- |
| Text or a caption with a link | One per link tool (`LINK_ACTIONS`): QR code |
| A photo, or a document with an `image/*` type | One per image tool (`FILE_ACTIONS`): PDF |
| A document with the `application/pdf` type | One per PDF tool: JPG images |
| A Word, ODT or RTF document (`DOCUMENT_TYPES`) | One per document tool: PDF |
| An album of photos or images | PDF, of the whole album |
| Anything else | None; a pointer to `/help` |

A photo or album with a link in its caption gets both kinds of buttons.

- The link is the message's first `url` or `text_link` entity, as Telegram
  marked it up. Buttons carry only the tool name: the handler reads the link
  or file back from the user's message, which the button's message replies
  to. If that message is gone, the user is asked to send it again.
- **Albums** arrive as one message per file. The first one waits until none
  has arrived for `ALBUM_WAIT_SECONDS`, then replies once for the whole
  album, in the order it was sent. The prompt can reply to only one message,
  so the album's files are kept in memory (`Albums`) under a random token
  that its buttons carry, for `ALBUM_TTL_SECONDS` and only for that chat.
  After a restart the user is asked to send the album again. An album with
  anything but images is refused: other files go one at a time.
- **Sizes:** files over `DOWNLOAD_LIMIT` (20 MB, the hosted Bot API's limit)
  are refused before any button is offered, and again when one is pressed.
  Results with a file over `UPLOAD_LIMIT` (50 MB, per file) are refused
  instead of sent.
- **Results** reply to the user's message, with Telegram showing "sending a
  file…" meanwhile:
  - QR codes as photos captioned with the encoded address (cut to Telegram's
    1024-character limit);
  - images → one PDF on A4 pages, named after the first image's file (photos
    have none: `images.pdf`);
  - PDF → its pages as JPEG files at the tool's default resolution, named
    like the CLI's (`report-1.jpg`, …, zero-padded from 10 pages:
    `report-01.jpg`): one file, an album of up to
    `ALBUM_LIMIT` (10), or a ZIP (`report.zip`) for more. Names keep only the
    sent file's base name, so a crafted name can't put folders into the ZIP.
  - a Word, ODT or RTF document → its PDF, named after the document;
  - A tool's refusal (`ToolError`) is sent as the reply instead.
- Tools run in a worker thread so the bot keeps answering meanwhile; the PDF
  tools' work itself happens in a sandboxed process with a timeout
  ([tools](../tools/README.md#sandbox)).

| Command | Who | Does |
| --- | --- | --- |
| `/start`, `/help` | everyone approved | What the bot can do (the owner also sees `/users`) |
| `/qr <link>` | everyone approved | QR code for the link |
| `/users` | owner | Lists users with Approve / Reject / Revoke buttons. Approved users get "You are not authorized to use this command."; anyone not approved only goes through the access flow above, so outsiders learn nothing about the commands |

Command menus are set at startup ([setup.py](setup.py)): the owner's includes
`/users`.
