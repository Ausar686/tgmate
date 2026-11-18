import io
import pathlib

import pypdfium2 as pdfium
import pytest
from PIL import Image

from tests.images import (
    close_to,
    make_image,
    pdf_embedded_images,
    pdf_page_image,
    pdf_pages,
    stripe_image,
)
from tgmate.tools.errors import ToolError
from tgmate.tools.pdf import PAPER_SIZES, PDF, PageSize

ENCRYPTED = (pathlib.Path(__file__).parent.parent / "fixtures" / "encrypted.pdf").read_bytes()
RED, BLUE, GREEN, WHITE = (255, 0, 0), (0, 0, 255), (0, 128, 0), (255, 255, 255)


def encode(image: Image.Image, fmt: str = "PNG", **options: object) -> bytes:
    output = io.BytesIO()
    image.save(output, fmt, **options)
    return output.getvalue()


# --- images → PDF ---


def test_one_page_per_image_in_order() -> None:
    pdf = PDF.from_images([make_image(color="red"), make_image("JPEG", color="blue"), make_image(color="green")])

    assert len(pdf_pages(pdf)) == 3
    colors = [pdf_page_image(pdf, index).getpixel((297, 420)) for index in range(3)]
    assert [close_to(c, e) for c, e in zip(colors, [RED, BLUE, GREEN], strict=True)] == [True, True, True]


def test_jpeg_is_embedded_unchanged() -> None:
    jpeg = make_image("JPEG", size=(300, 200), color="blue")

    [(data, filters)] = pdf_embedded_images(PDF.from_images([jpeg]))

    assert (data, filters) == (jpeg, ["DCTDecode"])


def test_png_is_embedded_losslessly() -> None:
    png = encode(stripe_image((90, 30)))

    pdf = PDF.from_images([png], PageSize.IMAGE)

    [(_, filters)] = pdf_embedded_images(pdf)
    assert filters == ["FlateDecode"]
    page = pdf_page_image(pdf, scale=96 / 72)
    assert page.size == (90, 30)
    assert page.getpixel((10, 15)) == BLUE and page.getpixel((80, 15)) == RED


@pytest.mark.parametrize(("size", "page"), [((30, 60), (595.28, 841.89)), ((60, 30), (841.89, 595.28))])
def test_a4_page_turns_with_the_image_and_fits_it_centred(size: tuple[int, int], page: tuple[float, float]) -> None:
    pdf = PDF.from_images([make_image(size=size, color="red")])

    assert pdf_pages(pdf) == [pytest.approx(page)]
    rendered = pdf_page_image(pdf)
    # A 1:2 image on a 1:√2 page fills the long side and leaves white bands on the short one.
    short_side_edge = (5, rendered.height // 2) if size[0] < size[1] else (rendered.width // 2, 5)
    assert rendered.getpixel(short_side_edge) == WHITE
    assert rendered.getpixel((rendered.width // 2, rendered.height // 2)) == RED


def test_letter_page_size() -> None:
    assert pdf_pages(PDF.from_images([make_image(size=(30, 60))], PageSize.LETTER)) == [
        pytest.approx(PAPER_SIZES[PageSize.LETTER])
    ]


@pytest.mark.parametrize(("dpi", "expected"), [(144, (30.0, 15.0)), (None, (45.0, 22.5)), (5, (45.0, 22.5))])
def test_image_page_size_follows_the_image_resolution(dpi: int | None, expected: tuple[float, float]) -> None:
    pdf = PDF.from_images([make_image(size=(60, 30), dpi=dpi)], PageSize.IMAGE)

    # PNG stores resolution in pixels per metre, so 144 dpi comes back as 143.99.
    assert pdf_pages(pdf) == [pytest.approx(expected, rel=1e-3)]


def test_exif_rotated_jpeg_is_turned_upright() -> None:
    # Stored landscape with the blue third on the left; orientation 6 means "rotate 90° clockwise to view".
    jpeg = encode(stripe_image((60, 30)), "JPEG", quality=95, exif=_orientation(6), dpi=(96, 96))

    pdf = PDF.from_images([jpeg], PageSize.IMAGE)

    assert pdf_pages(pdf) == [pytest.approx((22.5, 45.0))]
    page = pdf_page_image(pdf, scale=96 / 72)
    assert close_to(page.getpixel((15, 5)), BLUE) and close_to(page.getpixel((15, 55)), RED)


def test_transparency_is_laid_over_white() -> None:
    png = make_image("PNG", mode="RGBA", color=(0, 0, 255, 128))

    rendered = pdf_page_image(PDF.from_images([png]))

    assert close_to(rendered.getpixel((297, 420)), (127, 127, 255), tolerance=2)


@pytest.mark.parametrize("fmt", ["WEBP", "GIF", "BMP", "TIFF"])
def test_other_supported_formats(fmt: str) -> None:
    image = make_image(fmt, mode="P" if fmt == "GIF" else "RGB", color=1 if fmt == "GIF" else "green")

    assert len(pdf_pages(PDF.from_images([image]))) == 1


@pytest.mark.parametrize("mode", ["CMYK", "1", "LA", "P"])
def test_unusual_colour_modes_are_converted(mode: str) -> None:
    fmt = "JPEG" if mode == "CMYK" else "PNG"
    image = make_image(fmt, mode=mode, color=0)

    assert len(pdf_pages(PDF.from_images([image]))) == 1


def test_no_images_is_refused() -> None:
    with pytest.raises(ToolError, match="at least one image"):
        PDF.from_images([])


def test_too_many_images_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PDF, "MAX_IMAGES", 2)

    with pytest.raises(ToolError, match="At most 2 images"):
        PDF.from_images([make_image()] * 3)


def test_non_image_is_refused_with_its_position() -> None:
    with pytest.raises(ToolError, match="File 2 isn't an image"):
        PDF.from_images([make_image(), b"%PDF-1.7 not an image"])


def test_unsupported_image_format_is_refused() -> None:
    with pytest.raises(ToolError, match="File 1 is a ICO image; supported formats: JPEG, PNG, WebP"):
        PDF.from_images([make_image("ICO", size=(16, 16))])


def test_huge_image_is_refused_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PDF, "MAX_IMAGE_PIXELS", 799)

    with pytest.raises(ToolError, match=r"Image 1 is too large \(40×20 pixels\)"):
        PDF.from_images([make_image(size=(40, 20))])


def test_truncated_image_is_refused() -> None:
    jpeg = make_image("JPEG", size=(200, 200))

    with pytest.raises(ToolError, match="Image 1 is damaged"):
        PDF.from_images([jpeg[: len(jpeg) // 2]])


# --- PDF → JPEG ---


def test_each_page_becomes_a_jpeg_in_order() -> None:
    pdf = PDF.from_images([make_image(color="red"), make_image(color="blue")])

    pages = PDF.to_jpegs(pdf)

    assert len(pages) == 2
    images = [Image.open(io.BytesIO(page)) for page in pages]
    assert {image.format for image in images} == {"JPEG"}
    centres = [image.getpixel((image.width // 2, image.height // 2)) for image in images]
    assert close_to(centres[0], RED) and close_to(centres[1], BLUE)


# PDFium rounds each side up: A4 is 595.28 × 841.89 points.
@pytest.mark.parametrize(("dpi", "size"), [(72, (596, 842)), (150, (1241, 1754))])
def test_pages_render_at_the_requested_dpi(dpi: int, size: tuple[int, int]) -> None:
    [page] = PDF.to_jpegs(PDF.from_images([make_image(size=(30, 60))]), dpi=dpi)

    assert Image.open(io.BytesIO(page)).size == size



def test_pages_record_their_resolution_so_a_round_trip_keeps_the_page_size() -> None:
    pdf = PDF.from_images([make_image(size=(30, 60))])

    pages = PDF.to_jpegs(pdf, dpi=150)

    assert Image.open(io.BytesIO(pages[0])).info["dpi"] == pytest.approx((150, 150))
    # Rounding the rendered size up to whole pixels adds at most one pixel (0.48 pt at 150 dpi).
    assert pdf_pages(PDF.from_images(pages, PageSize.IMAGE)) == [pytest.approx(pdf_pages(pdf)[0], abs=0.5)]

def test_huge_page_is_rendered_smaller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PDF, "MAX_RENDER_PIXELS", 100_000)

    [page] = PDF.to_jpegs(PDF.from_images([make_image(size=(30, 60))]), dpi=150)

    width, height = Image.open(io.BytesIO(page)).size
    assert width * height <= 100_000
    assert height / width == pytest.approx(841.89 / 595.28, rel=0.01)


@pytest.mark.parametrize("dpi", [PDF.MIN_DPI - 1, PDF.MAX_DPI + 1])
def test_dpi_out_of_range_is_refused(dpi: int) -> None:
    with pytest.raises(ToolError, match="DPI must be between"):
        PDF.to_jpegs(PDF.from_images([make_image()]), dpi=dpi)


def test_too_many_pages_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = PDF.from_images([make_image()] * 3)
    monkeypatch.setattr(PDF, "MAX_PAGES", 2)

    with pytest.raises(ToolError, match="3 pages; the limit is 2"):
        PDF.to_jpegs(pdf)


def test_password_protected_pdf_is_refused() -> None:
    with pytest.raises(ToolError, match="password-protected"):
        PDF.to_jpegs(ENCRYPTED)


@pytest.mark.parametrize("data", [b"", b"just text", make_image()])
def test_non_pdf_is_refused(data: bytes) -> None:
    with pytest.raises(ToolError, match="isn't a PDF I can read"):
        PDF.to_jpegs(data)


def _orientation(value: int) -> Image.Exif:
    exif = Image.Exif()
    exif[0x0112] = value
    return exif


def test_pdf_without_pages_is_refused_as_unreadable() -> None:
    document = pdfium.PdfDocument.new()
    output = io.BytesIO()
    document.save(output)
    document.close()

    with pytest.raises(ToolError, match="isn't a PDF I can read"):
        PDF.to_jpegs(output.getvalue())
