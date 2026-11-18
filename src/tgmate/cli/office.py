"""`tgmate doc-to-pdf`."""

import pathlib
import typing as t

import typer

from tgmate.cli.files import refuse_existing, write_output
from tgmate.tools.office import Office


def doc_to_pdf(
    document: t.Annotated[
        pathlib.Path, typer.Argument(exists=True, dir_okay=False, help="Document to convert: DOCX, DOC, ODT or RTF.")
    ],
    output: t.Annotated[
        pathlib.Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="PDF to write [default: the document's name, .pdf]."),
    ] = None,
    force: t.Annotated[bool, typer.Option("--force", "-f", help="Overwrite the output file.")] = False,
) -> None:
    """Convert a Word, OpenDocument text or RTF document to PDF with LibreOffice."""
    target = output or document.with_suffix(".pdf").relative_to(document.parent)
    # Before converting, which starts LibreOffice and can take a while.
    refuse_existing([target], force=force)
    write_output(target, Office.to_pdf(document.read_bytes()), force=force)
