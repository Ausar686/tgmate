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
- **Limits:** `sandbox.TIMEOUT_SECONDS` of wall-clock time; in the worker,
  `worker.MEMORY_LIMIT_BYTES` of address space (Linux only: macOS refuses
  it), CPU time a little over the timeout, a file size limit of 0 (no write
  can make a file grow) and few open files. At most `sandbox.MAX_OUTPUT_BYTES`
  of results are read back.
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
PDFium (via pypdfium2) builds and renders PDFs; Pillow reads images. Both
work on bytes in memory, so nothing touches the disk. Every public method
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

`PDF.jpeg_names(stem, count) -> list[str]`: the file names front ends give
the pages, `<stem>-1.jpg` onwards, zero-padded to sort in page order.
