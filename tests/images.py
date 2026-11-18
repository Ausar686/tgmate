"""Helpers for reading back the images tools produce."""

import io

import zxingcpp
from PIL import Image


def decode_qr(png: bytes) -> str:
    """Return the text of the only QR code in a PNG image."""
    with Image.open(io.BytesIO(png)) as image:
        codes = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode)
    assert len(codes) == 1
    return codes[0].text


def png_size(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as image:
        return image.size
