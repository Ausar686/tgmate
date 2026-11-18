import collections.abc as cabc
import http.server
import io
import os
import pathlib
import re
import shutil
import threading
import zipfile

import pytest
from PIL import Image

from tests.documents import docx, odt, pdf_text, rtf
from tests.images import pdf_page_image
from tgmate.tools import office
from tgmate.tools.errors import ToolError
from tgmate.tools.office import UNSUPPORTED, Office

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"
RED = (255, 0, 0)

# LibreOffice is a system package, not a Python dependency: without it these tests are skipped, except in CI, which
# installs it and must not skip them silently.
requires_libreoffice = pytest.mark.skipif(
    shutil.which("soffice") is None and not office.MACOS_SOFFICE.exists() and "CI" not in os.environ,
    reason="LibreOffice isn't installed",
)


@pytest.fixture
def no_libreoffice_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    """For documents refused before LibreOffice would run, so the test runs where it isn't installed too."""
    monkeypatch.setattr(Office, "soffice", staticmethod(lambda: "/nonexistent/soffice"))


@requires_libreoffice
@pytest.mark.parametrize(
    ("document", "text"),
    [
        (docx("Hello from a DOCX"), "Hello from a DOCX"),
        (odt("Hello from an ODT"), "Hello from an ODT"),
        (rtf("Hello from an RTF"), "Hello from an RTF"),
        ((FIXTURES / "hello.doc").read_bytes(), "Hello from a DOC"),
    ],
    ids=["docx", "odt", "rtf", "doc"],
)
def test_each_format_becomes_a_pdf_with_its_text(document: bytes, text: str) -> None:
    pdf = Office.to_pdf(document)

    assert pdf.startswith(b"%PDF-")
    assert text in pdf_text(pdf)


@requires_libreoffice
@pytest.mark.real_sandbox
def test_conversion_runs_within_the_workers_limits() -> None:
    assert "Hello" in pdf_text(Office.to_pdf(docx("Hello")))


class Recorder(http.server.BaseHTTPRequestHandler):
    requests: list[str] = []

    def do_GET(self) -> None:
        self.requests.append(self.path)
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture
def web_server() -> cabc.Iterator[tuple[str, list[str]]]:
    """A local web server's address, and the paths requested from it."""
    server = http.server.HTTPServer(("127.0.0.1", 0), Recorder)
    requests: list[str] = []
    Recorder.requests = requests
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()


@requires_libreoffice
@pytest.mark.parametrize("build", [docx, odt], ids=["docx", "odt"])
def test_linked_web_and_local_images_are_not_loaded(
    build: cabc.Callable[..., bytes], web_server: tuple[str, list[str]], tmp_path: pathlib.Path
) -> None:
    # Without blocking, LibreOffice requests the web image and draws the local one (solid red) into the PDF.
    address, requests = web_server
    local = tmp_path / "secret.png"
    Image.new("RGB", (100, 100), "red").save(local)

    pdf = Office.to_pdf(build("Linked", linked_images=[f"{address}/image.png", local.as_uri()]))

    assert requests == []
    page = pdf_page_image(pdf, scale=0.5)
    assert RED not in {color for _, color in page.getcolors(page.width * page.height)}


@requires_libreoffice
def test_a_damaged_document_is_refused() -> None:
    damaged = (FIXTURES / "hello.doc").read_bytes()[:600]

    with pytest.raises(ToolError, match="^LibreOffice couldn't open this DOC document; it may be damaged.$"):
        Office.to_pdf(damaged)


def zip_with(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return output.getvalue()


@pytest.mark.parametrize(
    "data",
    [
        b"just some text",
        b"%PDF-1.7",
        zip_with({"xl/workbook.xml": b"<workbook/>"}),
        zip_with({"mimetype": b"application/vnd.oasis.opendocument.spreadsheet"}),
        b"PK\x03\x04 not really a zip",
    ],
    ids=["text", "pdf", "spreadsheet", "opendocument spreadsheet", "broken zip"],
)
def test_other_files_are_refused_before_libreoffice_runs(no_libreoffice_needed: None, data: bytes) -> None:
    with pytest.raises(ToolError, match=f"^{re.escape(UNSUPPORTED)}$"):
        Office.to_pdf(data)


def test_archive_with_too_many_parts_is_refused(no_libreoffice_needed: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Office, "MAX_ARCHIVE_ENTRIES", 3)

    with pytest.raises(ToolError, match="more than 3 parts"):
        Office.to_pdf(docx("Hello"))


def test_archive_that_unpacks_too_large_is_refused(
    no_libreoffice_needed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Office, "MAX_UNPACKED_BYTES", 1024 * 1024)

    with pytest.raises(ToolError, match="unpacks to more than 1 MB"):
        Office.to_pdf(zip_with({"word/document.xml": b" " * (1024 * 1024 + 1)}))


def test_missing_libreoffice_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(office, "MACOS_SOFFICE", tmp_path / "missing")

    with pytest.raises(ToolError, match="LibreOffice isn't installed"):
        Office.to_pdf(docx("Hello"))
