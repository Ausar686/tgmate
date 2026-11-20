"""Builders for minimal office documents and text PDFs, and reading text back from PDFs and Word documents."""

import collections.abc as cabc
import io
import zipfile

import docx as python_docx
import pymupdf
import pypdfium2 as pdfium

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
IMAGE_RELATIONSHIP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def docx(text: str, *, linked_images: cabc.Sequence[str] = ()) -> bytes:
    """A Word document with one paragraph of `text`, then an image linked (not embedded) from each URL."""
    images = "".join(_linked_docx_image(f"rIdImage{index}", index) for index in range(len(linked_images)))
    relationships = "".join(
        f'<Relationship Id="rIdImage{index}" Type="{IMAGE_RELATIONSHIP}" Target="{url}" TargetMode="External"/>'
        for index, url in enumerate(linked_images)
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="word/document.xml"/></Relationships>',
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{relationships}</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document {W} {R}><w:body>'
            f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>{images}</w:body></w:document>",
        )
    return output.getvalue()


def _linked_docx_image(relationship: str, index: int) -> str:
    """A 1-inch picture whose image is linked through `relationship`."""
    return (
        "<w:p><w:r><w:drawing>"
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:extent cx="914400" cy="914400"/><wp:docPr id="{index + 1}" name="image{index}"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:nvPicPr><pic:cNvPr id="{index + 1}" name="image{index}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:link="{relationship}"/></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm>'
        '<a:prstGeom prst="rect"/></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline>'
        "</w:drawing></w:r></w:p>"
    )


def odt(text: str, *, linked_images: cabc.Sequence[str] = ()) -> bytes:
    """An OpenDocument text with one paragraph of `text`, then an image linked from each URL."""
    images = "".join(
        f'<text:p><draw:frame svg:width="2.5cm" svg:height="2.5cm" text:anchor-type="as-char">'
        f'<draw:image xlink:href="{url}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>'
        "</draw:frame></text:p>"
        for url in linked_images
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        # The mimetype comes first and uncompressed, as OpenDocument requires.
        archive.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text")
        archive.writestr(
            "META-INF/manifest.xml",
            '<?xml version="1.0"?><manifest:manifest '
            'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
            '<manifest:file-entry manifest:full-path="/" '
            'manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry '
            'manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>',
        )
        archive.writestr(
            "content.xml",
            '<?xml version="1.0"?><office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
            'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
            'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" office:version="1.2"><office:body><office:text>'
            f"<text:p>{text}</text:p>{images}</office:text></office:body></office:document-content>",
        )
    return output.getvalue()


def rtf(text: str) -> bytes:
    return b"{\\rtf1\\ansi " + text.encode("ascii") + b"\\par}"


def pdf_text(pdf: bytes) -> str:
    """All the text on the PDF's pages."""
    document = pdfium.PdfDocument(pdf)
    try:
        return "\n".join(document[index].get_textpage().get_text_range() for index in range(len(document)))
    finally:
        document.close()


def text_pdf(pages: cabc.Sequence[str]) -> bytes:
    """A PDF with one line of real text (not an image of it) per page."""
    document = pymupdf.open()
    try:
        for text in pages:
            document.new_page().insert_text((72, 72), text, fontsize=14)
        return document.tobytes()
    finally:
        document.close()


def docx_paragraphs(data: bytes) -> list[str]:
    """The text of a Word document's non-empty paragraphs, in order."""
    return [paragraph.text for paragraph in python_docx.Document(io.BytesIO(data)).paragraphs if paragraph.text]
