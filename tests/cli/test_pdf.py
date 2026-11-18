import pathlib

import pytest
from typer.testing import CliRunner

from tests.images import make_image, pdf_pages
from tests.terminal import plain
from tgmate.cli.app import app
from tgmate.tools.pdf import PAPER_SIZES, PageSize

runner = CliRunner()


@pytest.fixture(autouse=True)
def in_tmp_path(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.jpg").write_bytes(make_image("JPEG", size=(40, 20)))
    (tmp_path / "b.png").write_bytes(make_image("PNG", size=(20, 40)))


def test_images_to_pdf_names_the_pdf_after_the_first_image(tmp_path: pathlib.Path) -> None:
    result = runner.invoke(app, ["images-to-pdf", "a.jpg", "b.png"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "a.pdf"
    a4 = PAPER_SIZES[PageSize.A4]
    assert pdf_pages((tmp_path / "a.pdf").read_bytes()) == [pytest.approx(a4[::-1]), pytest.approx(a4)]


def test_images_to_pdf_takes_an_output_and_a_page_size(tmp_path: pathlib.Path) -> None:
    result = runner.invoke(app, ["images-to-pdf", "b.png", "-o", "scan.pdf", "--page-size", "LETTER"])

    assert result.exit_code == 0
    assert pdf_pages((tmp_path / "scan.pdf").read_bytes()) == [pytest.approx(PAPER_SIZES[PageSize.LETTER])]


def test_images_to_pdf_keeps_an_existing_pdf_without_force(tmp_path: pathlib.Path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"keep")

    result = runner.invoke(app, ["images-to-pdf", "a.jpg"])

    assert result.exit_code == 2
    assert "--force" in plain(result.stderr)
    assert (tmp_path / "a.pdf").read_bytes() == b"keep"


def test_images_to_pdf_reports_a_file_that_is_not_an_image(tmp_path: pathlib.Path) -> None:
    (tmp_path / "notes.txt").write_text("hello")

    result = runner.invoke(app, ["images-to-pdf", "a.jpg", "notes.txt"])

    assert result.exit_code == 1
    assert result.stderr == "Error: File 2 isn't an image I can read.\n"
    assert not (tmp_path / "a.pdf").exists()


def test_images_to_pdf_needs_existing_files() -> None:
    result = runner.invoke(app, ["images-to-pdf", "missing.png"])

    assert result.exit_code == 2
    assert "does not exist" in plain(result.stderr)


def test_pdf_to_jpg_writes_numbered_pages_into_the_output_dir(tmp_path: pathlib.Path) -> None:
    runner.invoke(app, ["images-to-pdf", "a.jpg", "b.png", "-o", "doc.pdf"])

    result = runner.invoke(app, ["pdf-to-jpg", "doc.pdf", "-o", "pages/new", "--dpi", "72"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["pages/new/doc-1.jpg", "pages/new/doc-2.jpg"]
    assert (tmp_path / "pages/new/doc-1.jpg").read_bytes()[:3] == b"\xff\xd8\xff"


def test_pdf_to_jpg_pads_page_numbers_to_sort_in_order(tmp_path: pathlib.Path) -> None:
    runner.invoke(app, ["images-to-pdf", *["a.jpg"] * 10, "-o", "doc.pdf"])

    result = runner.invoke(app, ["pdf-to-jpg", "doc.pdf", "--dpi", "36"])

    assert result.exit_code == 0
    assert result.stdout.splitlines()[:2] == ["doc-01.jpg", "doc-02.jpg"]
    assert result.stdout.splitlines()[-1] == "doc-10.jpg"


def test_pdf_to_jpg_writes_nothing_if_any_page_file_exists(tmp_path: pathlib.Path) -> None:
    runner.invoke(app, ["images-to-pdf", "a.jpg", "b.png", "-o", "doc.pdf"])
    (tmp_path / "doc-2.jpg").write_bytes(b"keep")

    result = runner.invoke(app, ["pdf-to-jpg", "doc.pdf"])

    assert result.exit_code == 2
    assert "--output-dir" in plain(result.stderr)
    assert not (tmp_path / "doc-1.jpg").exists()
    assert (tmp_path / "doc-2.jpg").read_bytes() == b"keep"


def test_pdf_to_jpg_force_overwrites(tmp_path: pathlib.Path) -> None:
    runner.invoke(app, ["images-to-pdf", "a.jpg", "-o", "doc.pdf"])
    (tmp_path / "doc-1.jpg").write_bytes(b"old")

    result = runner.invoke(app, ["pdf-to-jpg", "doc.pdf", "-f"])

    assert result.exit_code == 0
    assert (tmp_path / "doc-1.jpg").read_bytes()[:3] == b"\xff\xd8\xff"


def test_pdf_to_jpg_reports_a_file_that_is_not_a_pdf() -> None:
    result = runner.invoke(app, ["pdf-to-jpg", "a.jpg"])

    assert result.exit_code == 1
    assert result.stderr == "Error: This isn't a PDF I can read.\n"


def test_pdf_to_jpg_dpi_out_of_range_is_a_usage_error() -> None:
    result = runner.invoke(app, ["pdf-to-jpg", "a.jpg", "--dpi", "10"])

    assert result.exit_code == 2


def test_a_page_file_appearing_after_the_check_names_the_output_dir(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner.invoke(app, ["images-to-pdf", "a.jpg", "-o", "doc.pdf"])
    monkeypatch.setattr("tgmate.cli.pdf.refuse_existing", lambda *args, **kwargs: None)
    (tmp_path / "doc-1.jpg").write_bytes(b"raced")

    result = runner.invoke(app, ["pdf-to-jpg", "doc.pdf"])

    assert result.exit_code == 2
    assert "--output-dir" in plain(result.stderr)
    assert (tmp_path / "doc-1.jpg").read_bytes() == b"raced"
