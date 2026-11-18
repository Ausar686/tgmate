import pytest

from tests.images import decode_qr, png_size
from tgmate.tools.errors import ToolError
from tgmate.tools.qr import ImageFormat, QRCode


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com/path?q=1&lang=en#section",
        "https://пример.рф/страница",
        "https://localhost:8080/",
    ],
)
def test_png_decodes_to_the_url(url):
    assert decode_qr(QRCode.from_url(url)) == url


def test_url_without_scheme_gets_https():
    assert decode_qr(QRCode.from_url("example.com/docs")) == "https://example.com/docs"


def test_surrounding_whitespace_is_ignored():
    assert decode_qr(QRCode.from_url("  https://example.com\n")) == "https://example.com"


def test_svg_output_is_an_svg_document():
    svg = QRCode.from_url("https://example.com", ImageFormat.SVG).decode()

    assert svg.startswith("<?xml")
    assert "<svg" in svg


def test_scale_multiplies_the_image_size():
    width, height = png_size(QRCode.from_url("https://example.com", scale=1))

    assert width == height
    assert png_size(QRCode.from_url("https://example.com", scale=7)) == (width * 7, height * 7)


@pytest.mark.parametrize("scale", [0, -1, QRCode.MAX_SCALE + 1])
def test_scale_out_of_range_is_rejected(scale):
    with pytest.raises(ToolError, match="Scale"):
        QRCode.from_url("https://example.com", scale=scale)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("", "http and https"),
        ("ftp://example.com/file", "http and https"),
        ("javascript://alert(1)", "http and https"),
        ("https://", "http and https"),
        ("https://exa mple.com", "spaces"),
        ("https://example.com/\x00", "control characters"),
        ("https://example.com:99999/", "port"),
        ("https://bank.example@evil.example/", "username"),
        ("https://user:secret@example.com/", "username"),
        ("mailto:someone@example.com", "username"),
    ],
)
def test_non_web_addresses_are_rejected(url, message):
    with pytest.raises(ToolError, match=message):
        QRCode.normalize_url(url)


def test_address_too_long_for_a_qr_code_is_rejected():
    with pytest.raises(ToolError, match="too long"):
        QRCode.from_url("https://example.com/" + "a" * 3000)
