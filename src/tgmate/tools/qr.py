"""QR codes for web addresses."""

import enum
import io
import urllib.parse

import segno

from tgmate.tools.errors import ToolError


class ImageFormat(enum.StrEnum):
    PNG = "png"
    SVG = "svg"


class QRCode:
    """Renders a web address as a QR code image."""

    SCHEMES = frozenset({"http", "https"})
    DEFAULT_SCALE = 10
    MAX_SCALE = 40
    # The quiet zone the QR spec requires around the code, in modules.
    BORDER = 4

    @classmethod
    def from_url(cls, url: str, fmt: ImageFormat = ImageFormat.PNG, scale: int = DEFAULT_SCALE) -> bytes:
        """Return the image of a QR code that opens `url`."""
        if not 1 <= scale <= cls.MAX_SCALE:
            raise ToolError(f"Scale must be between 1 and {cls.MAX_SCALE}.")
        try:
            code = segno.make_qr(cls.normalize_url(url), error="m")
        except segno.DataOverflowError as exc:
            raise ToolError("The address is too long to fit in a QR code.") from exc
        buffer = io.BytesIO()
        code.save(buffer, kind=fmt.value, scale=scale, border=cls.BORDER)
        return buffer.getvalue()

    @classmethod
    def normalize_url(cls, url: str) -> str:
        """Return `url` as an http(s) address, assuming `https://` when it has no scheme."""
        url = url.strip()
        if "://" not in url:
            url = f"https://{url}"
        if any(char.isspace() or not char.isprintable() for char in url):
            raise ToolError("The address must not contain spaces or control characters.")
        parts = urllib.parse.urlsplit(url)
        try:
            _ = parts.port  # Parsed lazily: reading it is what rejects a non-numeric or out-of-range port.
        except ValueError as exc:
            raise ToolError("The address has an invalid port.") from exc
        if parts.scheme.lower() not in cls.SCHEMES or not parts.hostname:
            raise ToolError("Only http and https web addresses are supported.")
        # `https://bank.example@evil.example` opens evil.example; refuse addresses that hide their host this way.
        if parts.username is not None:
            raise ToolError("The address must not contain a username or password.")
        return url
