"""Helpers for reading back the images tools produce."""

import io

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
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


def make_image(
    fmt: str = "PNG",
    size: tuple[int, int] = (40, 20),
    color: str | tuple[int, ...] = "red",
    mode: str = "RGB",
    orientation: int | None = None,
    dpi: int | None = None,
) -> bytes:
    """An encoded image of one colour; `orientation` sets the EXIF rotation tag."""
    image = Image.new(mode, size, color)
    options: dict = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        options["exif"] = exif
    if dpi is not None:
        options["dpi"] = (dpi, dpi)
    output = io.BytesIO()
    image.save(output, fmt, **options)
    return output.getvalue()


def stripe_image(size: tuple[int, int] = (60, 30)) -> Image.Image:
    """Red with a blue left third, so rotations and placement are visible."""
    image = Image.new("RGB", size, "red")
    image.paste("blue", (0, 0, size[0] // 3, size[1]))
    return image


def pdf_pages(pdf: bytes) -> list[tuple[float, float]]:
    """Page sizes in points."""
    document = pdfium.PdfDocument(pdf)
    try:
        return [document[index].get_size() for index in range(len(document))]
    finally:
        document.close()


def pdf_page_image(pdf: bytes, index: int = 0, scale: float = 1) -> Image.Image:
    """A page rendered to an RGB image."""
    document = pdfium.PdfDocument(pdf)
    try:
        return document[index].render(scale=scale).to_pil().convert("RGB")
    finally:
        document.close()


def pdf_embedded_images(pdf: bytes, index: int = 0) -> list[tuple[bytes, list[str]]]:
    """Raw stream data and filters of the images on a page."""
    document = pdfium.PdfDocument(pdf)
    try:
        objects = document[index].get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE])
        return [(bytes(obj.get_data(decode_simple=False)), obj.get_filters()) for obj in objects]
    finally:
        document.close()


def close_to(actual: tuple[int, ...], expected: tuple[int, ...], tolerance: int = 12) -> bool:
    """Colours equal within JPEG's rounding."""
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected, strict=True))
