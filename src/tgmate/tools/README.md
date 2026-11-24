# tools

The tools themselves, independent of any front end. Each tool is a class in
its own module whose operations are static or class methods; front ends call
them and present the result.

## Errors ([errors.py](errors.py))
- `ToolError` means the user's input can't be processed. Its message is
  written for the user and shown as is, so front ends don't rephrase it.
- Any other exception is a bug or an environment problem, not the user's
  fault.

## Sandbox ([sandbox.py](sandbox.py), [worker.py](worker.py))
Operations that parse untrusted files run in a separate worker process
(`python -I -m tgmate.tools.worker`), so a crash, hang or memory blow-up in
native code fails one conversion instead of the caller. The tool's public
method calls `sandbox.run(operation, inputs, options, outputs)`; the worker
looks the operation up in `worker.OPERATIONS` and runs the tool's in-process
implementation (the `_`-prefixed method).
- **Process:** an empty environment (no token or settings), `-I` (no
  `PYTHON*` variables, user site-packages or current directory on the import
  path) and its own process group, killed with everything it started once
  the operation ends or fails.
- **Limits:** wall-clock time (`sandbox.TIMEOUT_SECONDS` unless the call
  passes `timeout=`, as downloads do); in the worker, CPU time a little over
  that timeout and the operation's `worker.Limits`: address space (Linux
  only: macOS refuses it), file size and open files. By default the file
  size limit is 0 (no write can make a file grow); an operation that writes
  files (LibreOffice, yt-dlp) raises it and works in the caller's
  `sandbox.run(..., workdir=…)` directory, which the caller creates and
  removes, so it's cleaned up even when the worker is killed and the caller
  can keep what's left there. The YouTube operation's address-space limit is
  nominal (64 GB): Deno's V8 crashes below that, so in Docker the container's
  memory limit bounds it. At most `sandbox.MAX_OUTPUT_BYTES` of results are
  read back.
- **Not covered:** the worker runs as the caller's user, so code that
  exploits a parser could still truncate or delete that user's files (the
  bot's database, in the Docker image) and open network connections. Closing
  that needs OS-level confinement (a separate user, seccomp or Landlock).
- **Protocol:** inputs and results are length-prefixed blobs over the pipes,
  with the operation and its options as a JSON header; nothing is pickled.
  Library output on stdout is moved to stderr, so it can't corrupt results.
- **Errors:** the worker's `ToolError` is re-raised in the caller with the
  same message, and running out of memory becomes one too. A timeout or
  oversized result is a `ToolError` saying so. Anything else (a crash, a bug,
  malformed output) is logged with the end of the worker's stderr and
  reported as "The conversion failed unexpectedly."

## Office documents ([office.py](office.py))
`Office.to_pdf(document) -> bytes`: a DOCX, DOC, ODT or RTF document as a
PDF, converted by LibreOffice (`soffice`, found on `PATH` or in the macOS
app), which runs inside the [sandbox](#sandbox) worker.
- **Format** is read from the content (OLE2 signature for DOC, `{\rtf` for
  RTF, the ZIP's parts for DOCX and ODT), never from the name, and
  LibreOffice is told to open the file only as that format. Anything else is
  refused before LibreOffice starts. DOCX and ODT are ZIP archives, refused
  above `MAX_ARCHIVE_ENTRIES` parts or `MAX_UNPACKED_BYTES` unpacked.
- **Isolation:** every conversion gets a fresh LibreOffice profile and home
  in the job's directory, and nothing from the user reaches the command line
  (the file is saved as `document.<format>`). By default LibreOffice fetches
  images a document links to on the web and embeds linked local files, so
  the profile blocks untrusted links; it also points the proxy at a closed
  port and disables macros and active content.
- **Refused** with `ToolError`: other formats, archives over the limits, a
  document LibreOffice can't open, and LibreOffice not being installed.
- **Not covered:** fonts a document uses but the system lacks are replaced
  (the Docker image has Word's metric-compatible fonts and DejaVu, not CJK
  fonts), so layouts can differ from Word's.

## YouTube ([youtube.py](youtube.py))
`YouTube.download(url, MediaFormat.MP3 | MP4, directory, *, max_height=720,
max_bytes=2000 MB) -> Media`: one video, downloaded by yt-dlp into the
caller's `directory` (as `<video id>.mp3` or `.mp4`) inside the
[sandbox](#sandbox), with a 30-minute timeout. `Media` has the file's path,
the video's title, uploader and duration, its width and height (MP4 only),
and `file_name`: the title made safe as a file name, which front ends save or
send the file under.
- **Links:** only youtube.com (`www`, `m`, `music`) and youtu.be links to a
  single video (`watch?v=`, `shorts/`, `live/`, `embed/`), checked by host and
  an 11-character ID; the download uses the canonical `watch?v=<id>` address,
  so playlist and timestamp parameters are dropped. yt-dlp may use only its
  YouTube extractor (never the generic one, which fetches whatever a page
  points at), loads no plugins, keeps no cache, and names files after the ID,
  so nothing from the page reaches a path.
- **MP3:** the best audio, converted by ffmpeg at 192 kbps, with title and
  artist tags. **MP4:** the best video up to `max_height` on its shorter side
  (so vertical videos aren't penalised; the smallest above it when nothing is
  that small), preferring H.264 and AAC, which every player handles, merged
  with the best audio.
- **Refused** with `ToolError`, before downloading where possible: anything
  but a single video, live streams and premieres, videos over
  `MAX_DURATION_SECONDS` (3 hours) or of unknown length, estimated or actual
  sizes over `max_bytes`, a height outside 144–2160, what YouTube refuses
  (its message, without yt-dlp's prefixes), and ffmpeg not being installed.
  A 403 from YouTube's stream servers, which happens now and then, gets one
  more attempt from scratch.
- **Dependencies:** yt-dlp is frozen at its pinned release, with its
  `default` extra (the `yt-dlp-ejs` challenge solver and friends) and its
  `deno` extra (Deno from PyPI, which runs YouTube's challenge JavaScript
  without file, network or environment permissions). ffmpeg and ffprobe come
  from the system (`PATH`); Docker installs Debian's.
- **Live check:** `TGMATE_NETWORK_TESTS=1 pytest tests/tools/test_youtube_live.py`
  downloads a real video; run it after updating yt-dlp.

## QR code ([qr.py](qr.py))
`QRCode.from_url(url, fmt=PNG, scale=10) -> bytes` returns the image.
- **Address:** surrounding whitespace is stripped and `https://` is added
  when there's no `://`. It must then be an `http` or `https` address with a
  host. Refused with `ToolError`: other schemes, spaces or control
  characters, an invalid port, a username or password
  (`https://bank.example@evil.example` really opens `evil.example`), and
  addresses too long for a QR code (about 2,300 bytes).
- **Encoding:** a regular QR code (never a Micro QR), error correction level
  M or higher when it fits at no extra size, with the 4-module quiet zone the
  QR spec requires.
- **Image:** `ImageFormat.PNG` (1-bit) or `ImageFormat.SVG`. `scale` is pixels
  per module (SVG units for SVG), from 1 to `QRCode.MAX_SCALE`.

## PDF ([pdf.py](pdf.py))
PDFium (via pypdfium2) builds and renders PDFs; Pillow reads images;
pdf2docx rebuilds PDFs as Word documents. All work on bytes in memory, so
nothing touches the disk. Every public method
runs in the [sandbox](#sandbox).

`PDF.from_images(images, page_size=A4) -> bytes`: one page per image, in
order.
- **Inputs:** JPEG, PNG, WebP, GIF, BMP and TIFF (multi-frame files use their
  first frame), at most `MAX_IMAGES` images of at most `MAX_IMAGE_PIXELS`
  each. The size is checked before decoding, so decompression bombs are
  refused cheaply. Every image is fully decoded once, so a damaged or
  truncated file is refused instead of producing a broken page. Errors name
  the file's position ("File 2 …").
- **Quality:** an RGB or grayscale JPEG without EXIF rotation is embedded
  byte for byte, with no re-compression. Other JPEGs are turned upright
  (EXIF orientation, which PDF viewers ignore) and re-encoded at quality 95.
  Other formats are embedded losslessly (Flate). Transparency is laid over
  white.
- **Layout:** `PageSize.A4` and `PageSize.LETTER` fit each image on the paper,
  centred and as large as possible, turning the page to landscape for a
  landscape image. `PageSize.IMAGE` makes each page the image's own size at
  its stated DPI (96 when it states none, or something implausible).

`PDF.to_jpegs(pdf, dpi=150) -> list[bytes]`: one JPEG per page, in order.
- `dpi` from `MIN_DPI` to `MAX_DPI`. A page that would render above
  `MAX_RENDER_PIXELS` is rendered smaller, keeping its proportions. Each JPEG
  records the resolution it was rendered at, so it prints at the page's size.
- Refused: more than `MAX_PAGES` pages, password-protected PDFs, and anything
  PDFium can't open (which includes PDFs without pages).

`PDF.page_count(pdf) -> int`: how many images `to_jpegs` would return, without
rendering, and refusing the same PDFs; lets a caller check its outputs first.

`PDF.to_docx(pdf) -> bytes`: the PDF as an editable Word document, rebuilt
by pdf2docx (on PyMuPDF): text with its fonts and paragraphs, tables, and
images, including scanned pages as pictures (there's no OCR). It refuses the
same PDFs as `to_jpegs`, checked with PDFium first. pdf2docx is imported only
inside the worker: it configures logging on import and loads OpenCV.

`PDF.jpeg_names(stem, count) -> list[str]`: the file names front ends give
the pages, `<stem>-1.jpg` onwards, zero-padded to sort in page order.
