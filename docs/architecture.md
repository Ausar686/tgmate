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
| Images → PDF | One or more images → one PDF | CLI and Telegram ([tools](../src/tgmate/tools/README.md)) |
| PDF → JPG | One JPG per page | CLI and Telegram ([tools](../src/tgmate/tools/README.md)) |
| DOC(X) → PDF | Word, ODT or RTF document → PDF | CLI and Telegram ([tools](../src/tgmate/tools/README.md)) |
| PDF → DOCX | PDF → editable Word document | CLI and Telegram ([tools](../src/tgmate/tools/README.md)) |
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
- **PDF → JPG in Telegram:** up to 10 pages are sent as an album of JPEG
  files (documents, not photos, which Telegram would shrink and recompress);
  more pages are sent as one ZIP.
- **Images → PDF in Telegram:** one image, or one album (up to 10, Telegram's
  album limit), becomes one PDF on A4 pages. Albums are remembered in memory
  only, so their buttons stop working after a day or a restart.
- **Sandboxing:** tool operations that parse untrusted files in Python's
  process (PDFium and Pillow for the PDF tools) run in a separate worker
  process with a timeout, resource limits and no environment, so a crash,
  hang or decompression bomb fails one conversion instead of the bot, and a
  compromised parser can't read the bot's token or make any file grow (it
  runs as the bot's user, so it could still truncate or delete the bot's
  files; see the tools README for what isn't covered). Tools keep
  their synchronous API, so the CLI and the bot get the same protection
  ([tools](../src/tgmate/tools/README.md#sandbox)).
- **Documents → PDF:** LibreOffice (headless Writer, from Debian's
  packages) converts DOCX, DOC, ODT and RTF; it's the only free converter
  with good Word fidelity. It runs inside the sandbox worker with a fresh
  profile per job that blocks linked web and local content, and it roughly
  more than doubles the Docker image (387 → about 920 MB). Outside Docker it must be
  installed separately; the tool says so when it's missing.
- **yt-dlp:** pinned and frozen; updated to the latest release only on
  request, after a breakage, and checked against the failing link.
- **License:** AGPL-3.0-or-later, since PDF → DOCX uses PyMuPDF (AGPL).
  As the AGPL requires for network use, the bot offers its source code
  (`SOURCE_URL`, this repository by default) in `/help` and in its first reply
  to anyone who asks for access.
- **PDF → DOCX:** pdf2docx on PyMuPDF 1.27, pinned below 2.x: PyMuPDF 2
  depends on onnxruntime and AI layout packages, which the project doesn't
  want without a need, while 1.27 has no dependencies. pdf2docx brings
  OpenCV (classic image processing, not AI) and numpy, about 240 MB in all
  (the Docker image grows to about 1.3 GB).
  It parses untrusted PDFs in Python, so it runs in the sandbox worker.
