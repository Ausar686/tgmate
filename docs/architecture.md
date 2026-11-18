# Architecture

Product-level decisions that span modules. Module contracts live in each
module's `README.md`; this file links to them rather than restating them.

## Goal
Everyday file and media tools, usable from a terminal and from a Telegram
bot, with the same behavior in both.

## Tools
| Tool | What it does | Status |
| --- | --- | --- |
| QR code | Web address → PNG or SVG QR code | CLI and Telegram ([tools](../src/tgmate/tools/README.md)) |
| Images → PDF | One or more images → one PDF | CLI ([tools](../src/tgmate/tools/README.md)); Telegram next |
| PDF → JPG | One JPG per page | CLI ([tools](../src/tgmate/tools/README.md)); Telegram next |
| DOC(X) → PDF | Office document → PDF | Planned |
| PDF → DOCX | PDF → editable Word document | Planned |
| YouTube → MP3 / MP4 | Download audio or video | Planned |

## Decisions
- **Tools vs front ends:** each tool is a class in `tgmate.tools` whose
  operations are static or class methods. Front ends (CLI, Telegram, future
  ones) only parse input, call the tool and present the result, so a tool
  behaves the same everywhere. Tools report bad input with `ToolError`, whose
  message is shown to the user as is.
- **CLI:** Typer, one subcommand per tool (`tgmate <tool>`). Command list:
  [cli](../src/tgmate/cli/README.md).
- **Telegram access:** private chats only; the bot leaves any group or
  channel it's added to. Users need the owner's approval (`OWNER_USER_ID`),
  requested by DM the first time they write, like memedexer's chat approval.
  Because only approved users can use it, the risks of the YouTube tools
  (terms of service, blocked server IPs) are accepted. Details:
  [telegram](../src/tgmate/telegram/README.md).
- **Telegram interaction:** the user sends something (a link, a file), the bot
  replies with buttons for the tools that fit it, and the result replies to
  the user's message. Commands (`/qr <link>`) are a shortcut. QR codes are
  sent as photos.
- **Storage:** SQLite via SQLAlchemy async, migrated with Alembic at startup,
  like memedexer; it holds only users and their access status
  ([storage](../src/tgmate/storage/README.md)).
- **Telegram file limits:** the bot starts on Telegram's hosted Bot API
  (receives up to 20 MB, sends up to 50 MB) and refuses larger files with a
  clear message. The YouTube PR moves it to a self-hosted Bot API server
  (receives files of any size, sends up to 2 GB).
- **PDF → JPG in Telegram:** up to 10 pages are sent as an album; more pages
  are sent as one ZIP.
- **yt-dlp:** pinned and frozen; updated to the latest release only on
  request, after a breakage, and checked against the failing link.
- **License:** MIT for now. The PR that adds PDF → DOCX moves the project to
  AGPL-3.0-or-later (its library, PyMuPDF, is AGPL); the bot will then link
  to its source code, as the AGPL requires for network use.
