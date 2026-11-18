"""PDF tools: images into one PDF, and PDF pages into JPEG images."""

import collections.abc as cabc
import enum
import io
import math

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image, ImageOps, UnidentifiedImageError

from tgmate.tools.errors import ToolError

POINTS_PER_INCH = 72
EXIF_ORIENTATION = 0x0112


class PageSize(enum.StrEnum):
    A4 = "a4"
    LETTER = "letter"
    # Each page takes its image's own size.
    IMAGE = "image"


# Portrait width × height in points; a landscape image gets the page turned.
PAPER_SIZES = {PageSize.A4: (595.28, 841.89), PageSize.LETTER: (612.0, 792.0)}


class PDF:
    """Builds a PDF from images and renders a PDF's pages as JPEG images."""

    MAX_IMAGES = 100
    # Checked before decoding, so a small file that unpacks into a huge image (a decompression bomb) is refused.
    MAX_IMAGE_PIXELS = 50_000_000
    IMAGE_FORMATS = {"JPEG": "JPEG", "PNG": "PNG", "WEBP": "WebP", "GIF": "GIF", "BMP": "BMP", "TIFF": "TIFF"}
    # Used for `PageSize.IMAGE` when an image doesn't say its resolution, or says something implausible.
    DEFAULT_IMAGE_DPI = 96
    PLAUSIBLE_IMAGE_DPI = (36, 2400)
    REENCODED_JPEG_QUALITY = 95

    MAX_PAGES = 100
    DEFAULT_DPI = 150
    MIN_DPI = 36
    MAX_DPI = 600
    # A page whose size would render above this at the requested DPI is rendered smaller instead.
    MAX_RENDER_PIXELS = 25_000_000
    JPEG_QUALITY = 90

    @classmethod
    def from_images(cls, images: cabc.Sequence[bytes], page_size: PageSize = PageSize.A4) -> bytes:
        """Return a PDF with one page per image, in order, each fitted and centred on its page."""
        if not images:
            raise ToolError("Give at least one image.")
        if len(images) > cls.MAX_IMAGES:
            raise ToolError(f"At most {cls.MAX_IMAGES} images fit in one PDF.")
        document = pdfium.PdfDocument.new()
        try:
            for number, data in enumerate(images, 1):
                cls._add_image_page(document, data, number, page_size)
            output = io.BytesIO()
            document.save(output)
        finally:
            document.close()
        return output.getvalue()

    @classmethod
    def to_jpegs(cls, data: bytes, dpi: int = DEFAULT_DPI) -> list[bytes]:
        """Return one JPEG per page of the PDF, in order, rendered at `dpi`."""
        if not cls.MIN_DPI <= dpi <= cls.MAX_DPI:
            raise ToolError(f"DPI must be between {cls.MIN_DPI} and {cls.MAX_DPI}.")
        document = cls._open_pdf(data)
        try:
            return [cls._render_page(document[index], dpi) for index in range(len(document))]
        finally:
            document.close()

    @classmethod
    def page_count(cls, data: bytes) -> int:
        """The number of pages `to_jpegs` would return, without rendering; refuses the same PDFs."""
        document = cls._open_pdf(data)
        try:
            return len(document)
        finally:
            document.close()

    @staticmethod
    def jpeg_names(stem: str, count: int) -> list[str]:
        """File names for `count` pages: `<stem>-1.jpg`, …, zero-padded so they sort in page order."""
        digits = len(str(count))
        return [f"{stem}-{number:0{digits}d}.jpg" for number in range(1, count + 1)]

    @classmethod
    def _open_pdf(cls, data: bytes) -> pdfium.PdfDocument:
        """The loaded PDF, after checking it isn't encrypted or too long; refuses anything else with `ToolError`."""
        try:
            # PDFium also refuses a PDF without pages, so every document that loads has some.
            document = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            if getattr(exc, "err_code", None) == pdfium_raw.FPDF_ERR_PASSWORD:
                raise ToolError("The PDF is password-protected; remove the password first.") from exc
            raise ToolError("This isn't a PDF I can read.") from exc
        if len(document) > cls.MAX_PAGES:
            pages = len(document)
            document.close()
            raise ToolError(f"The PDF has {pages} pages; the limit is {cls.MAX_PAGES}.")
        return document

    @classmethod
    def _add_image_page(cls, document: pdfium.PdfDocument, data: bytes, number: int, page_size: PageSize) -> None:
        with cls._open_image(data, number) as image:
            pdf_image = pdfium.PdfImage.new(document)
            if cls._is_plain_jpeg(image):
                # Embedded as is: no re-compression, so photos keep their exact quality.
                pdf_image.load_jpeg(io.BytesIO(data), inline=True)
                size = image.size
            else:
                upright = cls._flatten(ImageOps.exif_transpose(image))
                if image.format == "JPEG":
                    reencoded = io.BytesIO()
                    upright.save(reencoded, "JPEG", quality=cls.REENCODED_JPEG_QUALITY)
                    reencoded.seek(0)
                    pdf_image.load_jpeg(reencoded, inline=True)
                else:
                    pdf_image.set_bitmap(pdfium.PdfBitmap.from_pil(upright))
                size = upright.size
            page_width, page_height, x, y, width, height = cls._layout(size, cls._image_dpi(image), page_size)
        page = document.new_page(page_width, page_height)
        pdf_image.set_matrix(pdfium.PdfMatrix().scale(width, height).translate(x, y))
        page.insert_obj(pdf_image)
        page.gen_content()
        page.close()

    @classmethod
    def _open_image(cls, data: bytes, number: int) -> Image.Image:
        """The decoded image, after checking its format and size; refuses anything else with `ToolError`."""
        limit = f"the limit is {cls.MAX_IMAGE_PIXELS // 1_000_000} megapixels"
        try:
            image = Image.open(io.BytesIO(data))
        except Image.DecompressionBombError as exc:
            # Pillow's own, higher limit, hit before ours can look at the size.
            raise ToolError(f"Image {number} is too large; {limit}.") from exc
        except UnidentifiedImageError as exc:
            raise ToolError(f"File {number} isn't an image I can read.") from exc
        if image.format not in cls.IMAGE_FORMATS:
            image.close()
            supported = ", ".join(cls.IMAGE_FORMATS.values())
            raise ToolError(f"File {number} is a {image.format} image; supported formats: {supported}.")
        if image.width * image.height > cls.MAX_IMAGE_PIXELS:
            image.close()
            raise ToolError(f"Image {number} is too large ({image.width}×{image.height} pixels); {limit}.")
        try:
            image.load()
        except OSError as exc:
            image.close()
            raise ToolError(f"Image {number} is damaged or incomplete.") from exc
        return image

    @staticmethod
    def _is_plain_jpeg(image: Image.Image) -> bool:
        """A JPEG a PDF can show unchanged: RGB or grayscale, and not rotated by EXIF (which PDFs ignore)."""
        orientation = image.getexif().get(EXIF_ORIENTATION, 1)
        return image.format == "JPEG" and image.mode in ("RGB", "L") and orientation == 1

    @staticmethod
    def _flatten(image: Image.Image) -> Image.Image:
        """RGB or grayscale, with any transparency laid over white as a viewer would show it."""
        if image.mode in ("RGB", "L"):
            return image
        if image.mode == "1":
            return image.convert("L")
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background

    @classmethod
    def _image_dpi(cls, image: Image.Image) -> float:
        dpi = image.info.get("dpi", (0, 0))[0]
        low, high = cls.PLAUSIBLE_IMAGE_DPI
        return dpi if low <= dpi <= high else cls.DEFAULT_IMAGE_DPI

    @staticmethod
    def _layout(
        size: tuple[int, int], dpi: float, page_size: PageSize
    ) -> tuple[float, float, float, float, float, float]:
        """Page width and height, then the image's x, y, width and height on it, all in points."""
        image_width, image_height = (pixels * POINTS_PER_INCH / dpi for pixels in size)
        if page_size is PageSize.IMAGE:
            return image_width, image_height, 0, 0, image_width, image_height
        page_width, page_height = PAPER_SIZES[page_size]
        if image_width > image_height:
            page_width, page_height = page_height, page_width
        scale = min(page_width / image_width, page_height / image_height)
        width, height = image_width * scale, image_height * scale
        return page_width, page_height, (page_width - width) / 2, (page_height - height) / 2, width, height

    @classmethod
    def _render_page(cls, page: pdfium.PdfPage, dpi: int) -> bytes:
        width, height = page.get_size()
        scale = dpi / POINTS_PER_INCH

        def rendered_pixels(scale: float) -> int:
            # PDFium rounds each side up to whole pixels.
            return math.ceil(width * scale) * math.ceil(height * scale)

        if rendered_pixels(scale) > cls.MAX_RENDER_PIXELS:
            scale = (cls.MAX_RENDER_PIXELS / (width * height)) ** 0.5
            while rendered_pixels(scale) > cls.MAX_RENDER_PIXELS:
                scale *= 0.99
        try:
            image = page.render(scale=scale).to_pil().convert("RGB")
        finally:
            page.close()
        output = io.BytesIO()
        # Records the rendered resolution, so the image prints at the page's size.
        # At least 1: a page large enough to be scaled below 0.5 dpi would otherwise record an invalid 0.
        rendered_dpi = max(1, round(scale * POINTS_PER_INCH))
        image.save(output, "JPEG", quality=cls.JPEG_QUALITY, optimize=True, dpi=(rendered_dpi, rendered_dpi))
        return output.getvalue()
