import pathlib

import pytest
from typer.testing import CliRunner

from tests.terminal import plain
from tgmate.cli.app import app
from tgmate.tools.errors import ToolError
from tgmate.tools.office import Office

runner = CliRunner()


@pytest.fixture(autouse=True)
def converted(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Fakes LibreOffice (tested with the tool): records each document and returns a stand-in PDF."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "report.docx").write_bytes(b"the document")
    documents: list[bytes] = []

    def to_pdf(data: bytes) -> bytes:
        documents.append(data)
        return b"%PDF-converted"

    monkeypatch.setattr(Office, "to_pdf", staticmethod(to_pdf))
    return documents


def test_doc_to_pdf_writes_the_pdf_named_after_the_document_in_the_current_folder(
    tmp_path: pathlib.Path, converted: list[bytes]
) -> None:
    result = runner.invoke(app, ["doc-to-pdf", "docs/report.docx"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "report.pdf"
    assert (tmp_path / "report.pdf").read_bytes() == b"%PDF-converted"
    assert converted == [b"the document"]


def test_doc_to_pdf_takes_an_output(tmp_path: pathlib.Path) -> None:
    result = runner.invoke(app, ["doc-to-pdf", "docs/report.docx", "-o", "out.pdf"])

    assert result.exit_code == 0
    assert (tmp_path / "out.pdf").read_bytes() == b"%PDF-converted"


def test_doc_to_pdf_keeps_an_existing_pdf_without_force_and_converts_nothing(
    tmp_path: pathlib.Path, converted: list[bytes]
) -> None:
    (tmp_path / "report.pdf").write_bytes(b"keep")

    result = runner.invoke(app, ["doc-to-pdf", "docs/report.docx"])

    assert result.exit_code == 2
    assert "--force" in plain(result.stderr)
    assert (tmp_path / "report.pdf").read_bytes() == b"keep"
    assert converted == []


def test_doc_to_pdf_overwrites_with_force(tmp_path: pathlib.Path) -> None:
    (tmp_path / "report.pdf").write_bytes(b"old")

    result = runner.invoke(app, ["doc-to-pdf", "docs/report.docx", "-f"])

    assert result.exit_code == 0
    assert (tmp_path / "report.pdf").read_bytes() == b"%PDF-converted"


def test_doc_to_pdf_reports_a_refusal(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    def refuse(data: bytes) -> bytes:
        raise ToolError("LibreOffice isn't installed here, so I can't convert documents.")

    monkeypatch.setattr(Office, "to_pdf", staticmethod(refuse))

    result = runner.invoke(app, ["doc-to-pdf", "docs/report.docx"])

    assert result.exit_code == 1
    assert result.stderr.strip() == "Error: LibreOffice isn't installed here, so I can't convert documents."
    assert not (tmp_path / "report.pdf").exists()
