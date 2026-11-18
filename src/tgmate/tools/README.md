# tools

The tools themselves, independent of any front end. Each tool is a class in
its own module whose operations are static or class methods; front ends call
them and present the result.

## Errors ([errors.py](errors.py))
- `ToolError` means the user's input can't be processed. Its message is
  written for the user and shown as is, so front ends don't rephrase it.
- Any other exception is a bug or an environment problem, not the user's
  fault.

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
